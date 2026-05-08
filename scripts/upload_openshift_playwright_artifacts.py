#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import mimetypes
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def load_env_dir(path: str) -> None:
    directory = Path(path)
    if not directory.is_dir():
        return
    for item in directory.iterdir():
        if item.is_file() and item.name not in os.environ:
            os.environ[item.name] = item.read_text().strip()


def required_env(name: str) -> str:
    value = env(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def s3_region() -> str:
    return env("BUCKET_REGION") or "us-east-1"


def s3_base_url() -> str:
    scheme = env("BUCKET_SCHEME", "https")
    host = required_env("BUCKET_HOST")
    port = env("BUCKET_PORT")
    authority = f"{host}:{port}" if port and port not in {"80", "443"} else host
    return f"{scheme}://{authority}/{required_env('BUCKET_NAME')}"


def urlopen(request: urllib.request.Request, timeout: int = 60):
    if urllib.parse.urlparse(request.full_url).scheme == "https" and env("BUCKET_TLS_VERIFY", "true").lower() in {"0", "false", "no"}:
        return urllib.request.urlopen(request, timeout=timeout, context=ssl._create_unverified_context())
    return urllib.request.urlopen(request, timeout=timeout)


def signing_key(secret_key: str, date_stamp: str, region: str) -> bytes:
    key = ("AWS4" + secret_key).encode("utf-8")
    for value in (date_stamp, region, "s3", "aws4_request"):
        key = hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()
    return key


def s3_request(method: str, key: str, body: bytes = b"", query: str = "", content_type: str = "application/octet-stream") -> bytes:
    access_key = required_env("AWS_ACCESS_KEY_ID")
    secret_key = required_env("AWS_SECRET_ACCESS_KEY")
    region = s3_region()
    now = dt.datetime.utcnow()
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    parsed = urllib.parse.urlparse(s3_base_url())
    encoded_key = "/".join(urllib.parse.quote(part, safe="") for part in key.split("/"))
    canonical_uri = f"{parsed.path.rstrip('/')}/{encoded_key}"
    url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, canonical_uri, "", query, ""))
    payload_hash = hashlib.sha256(body).hexdigest()
    canonical_headers = (
        f"host:{parsed.netloc}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join([method, canonical_uri, query, canonical_headers, signed_headers, payload_hash])
    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, credential_scope, hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()]
    )
    signature = hmac.new(signing_key(secret_key, date_stamp, region), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        url,
        data=body if method in {"PUT", "POST"} else None,
        method=method,
        headers={
            "Authorization": (
                "AWS4-HMAC-SHA256 "
                f"Credential={access_key}/{credential_scope}, "
                f"SignedHeaders={signed_headers}, "
                f"Signature={signature}"
            ),
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
            "Content-Type": content_type,
        },
    )
    with urlopen(request, timeout=60) as response:
        return response.read()


def safe_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    return [path for path in root.rglob("*") if path.is_file()]


def read_json_or_default(key: str, default: object) -> object:
    try:
        return json.loads(s3_request("GET", key).decode("utf-8"))
    except Exception:
        return default


def status_from_counts(passed: int, failed: int, skipped: int, errors: int) -> str:
    if failed or errors:
        return "failed"
    if passed > 0:
        return "passed_with_skips" if skipped else "passed"
    return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload OpenShift Playwright quality artifacts to S3/ObjectBucket.")
    parser.add_argument("--report-dir", default="playwright-report")
    parser.add_argument("--results-dir", default="test-results")
    parser.add_argument("--metrics-file", default="/tmp/ai-tutor-frontend-quality-metrics.prom")
    parser.add_argument("--secret-dir", default=env("ARTIFACT_SECRET_DIR", "/var/run/ai-tutor-artifacts-secret"))
    parser.add_argument("--config-dir", default=env("ARTIFACT_CONFIG_DIR", "/var/run/ai-tutor-artifacts-config"))
    parser.add_argument("--history-limit", type=int, default=int(env("ARTIFACT_HISTORY_LIMIT", "20")))
    args = parser.parse_args()

    load_env_dir(args.config_dir)
    load_env_dir(args.secret_dir)

    environment = env("QUALITY_ENVIRONMENT", "openshift-dev")
    env_slug = env("QUALITY_ENVIRONMENT_SLUG", "dev")
    repository = env("QUALITY_REPOSITORY", "NAGA-open-webui")
    branch = env("QUALITY_BRANCH", "rs/ai-tutor-tests")
    run_id = env("QUALITY_RUN_ID") or env("OPENSHIFT_BUILD_NAME") or str(int(time.time()))
    commit_sha = env("QUALITY_COMMIT_SHA", "openshift-build")
    prefix = env("ARTIFACT_PREFIX", f"openshift/frontend/{env_slug}")
    run_prefix = f"{prefix}/runs/{run_id}"

    metrics = Path(args.metrics_file).read_text() if Path(args.metrics_file).exists() else ""
    counts = {}
    for status in ("passed", "failed", "skipped", "error", "total"):
        marker = f'ai_tutor_quality_checks_total{{source="playwright_ui",status="{status}"}}'
        for line in metrics.splitlines():
            if marker in line:
                counts[status] = int(float(line.rsplit(" ", 1)[-1]))
                break
        counts.setdefault(status, 0)

    uploaded = 0
    for root_name in (args.report_dir, args.results_dir):
        root = Path(root_name)
        for path in safe_files(root):
            rel = path.relative_to(root).as_posix() if root.is_dir() else path.name
            key = f"{run_prefix}/{root.name}/{rel}"
            s3_request("PUT", key, path.read_bytes(), content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            uploaded += 1

    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report_path = f"/artifact/{run_prefix}/playwright-report/index.html"
    metadata = {
        "repository": repository,
        "environment": environment,
        "branch": branch,
        "run_id": run_id,
        "commit_sha": commit_sha,
        "created_at": created_at,
        "status": status_from_counts(counts["passed"], counts["failed"], counts["skipped"], counts["error"]),
        "passed": counts["passed"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "error": counts["error"],
        "total": counts["total"],
        "report_path": report_path,
    }

    s3_request("PUT", f"{run_prefix}/metadata.json", json.dumps(metadata, indent=2).encode("utf-8"), content_type="application/json")
    s3_request("PUT", f"{prefix}/latest.json", json.dumps(metadata, indent=2).encode("utf-8"), content_type="application/json")
    index_key = f"{prefix}/index.json"
    index = read_json_or_default(index_key, [])
    if not isinstance(index, list):
        index = []
    index = [item for item in index if item.get("run_id") != run_id]
    index.insert(0, metadata)
    s3_request("PUT", index_key, json.dumps(index[: args.history_limit], indent=2).encode("utf-8"), content_type="application/json")
    print(f"Uploaded {uploaded} OpenShift Playwright artifact file(s) to {run_prefix}.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Skipping OpenShift Playwright artifact upload: {exc}")
