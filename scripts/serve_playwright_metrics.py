#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PLAYWRIGHT_GROUP_LABELS = {
    "ui_live": "Live user workflows",
    "ui_mocked": "Controlled UI workflows",
}


def quote_label(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def metric_line(name: str, value: float | int, labels: dict[str, str] | None = None) -> str:
    if labels:
        encoded = ",".join(f"{key}={quote_label(val)}" for key, val in sorted(labels.items()))
        return f"{name}{{{encoded}}} {value}"
    return f"{name} {value}"


def empty_metrics() -> list[str]:
    lines = [
        metric_line("ai_tutor_quality_source_available", 0, {"source": "playwright_ui"}),
        metric_line("ai_tutor_quality_source_ok", 0, {"source": "playwright_ui"}),
        metric_line("ai_tutor_quality_source_duration_seconds", 0, {"source": "playwright_ui"}),
    ]
    for status in ("passed", "failed", "skipped", "error", "total"):
        lines.append(metric_line("ai_tutor_quality_checks_total", 0, {"source": "playwright_ui", "status": status}))
    return lines


def parse_playwright_report(report_path: Path) -> list[str]:
    lines = [
        "# HELP ai_tutor_quality_source_available Whether a quality signal is available.",
        "# TYPE ai_tutor_quality_source_available gauge",
        "# HELP ai_tutor_quality_source_ok Whether the latest quality signal is passing cleanly.",
        "# TYPE ai_tutor_quality_source_ok gauge",
        "# HELP ai_tutor_quality_source_duration_seconds Total duration of the latest quality signal.",
        "# TYPE ai_tutor_quality_source_duration_seconds gauge",
        "# HELP ai_tutor_quality_source_last_run_timestamp_seconds Last run time for a quality signal.",
        "# TYPE ai_tutor_quality_source_last_run_timestamp_seconds gauge",
        "# HELP ai_tutor_quality_checks_total Count of checks by quality source and status.",
        "# TYPE ai_tutor_quality_checks_total gauge",
        "# HELP ai_tutor_quality_group_checks_total Count of checks by quality source, group, and status.",
        "# TYPE ai_tutor_quality_group_checks_total gauge",
        "# HELP ai_tutor_quality_check_duration_seconds Duration of an individual quality check.",
        "# TYPE ai_tutor_quality_check_duration_seconds gauge",
        "# HELP ai_tutor_playwright_results_available Whether the Playwright report is available.",
        "# TYPE ai_tutor_playwright_results_available gauge",
        "# HELP ai_tutor_playwright_run_timestamp_seconds Last modification time of the Playwright report.",
        "# TYPE ai_tutor_playwright_run_timestamp_seconds gauge",
        "# HELP ai_tutor_playwright_tests_total Playwright test counts grouped by status.",
        "# TYPE ai_tutor_playwright_tests_total gauge",
        "# HELP ai_tutor_playwright_workflow_duration_seconds Duration of each Playwright workflow result.",
        "# TYPE ai_tutor_playwright_workflow_duration_seconds gauge",
    ]

    if not report_path.exists():
        return lines + empty_metrics()

    text = report_path.read_text(errors="ignore")
    match = re.search(r'<template id="playwrightReportBase64">data:application/zip;base64,(.*?)</template>', text, re.S)
    if not match:
        return lines + empty_metrics()

    raw = base64.b64decode(match.group(1))
    archive = zipfile.ZipFile(io.BytesIO(raw))
    report = json.loads(archive.read("report.json"))

    passed = failed = skipped = errors = tests = 0
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    duration_seconds = round(float(report.get("duration", 0)) / 1000, 3)

    for file_entry in report.get("files", []):
        file_name = file_entry.get("fileName", "")
        for test in file_entry.get("tests", []):
            tests += 1
            outcome = test.get("outcome", "")
            if test.get("ok") and outcome == "expected":
                status = "passed"
                passed += 1
            elif outcome == "skipped":
                status = "skipped"
                skipped += 1
            else:
                status = "failed"
                failed += 1

            workflow_group = "ui_live" if "live.spec" in file_name else "ui_mocked"
            display_group = PLAYWRIGHT_GROUP_LABELS[workflow_group]
            project = test.get("projectName", "unknown")
            workflow = test.get("title", "")
            duration = round(float(test.get("duration", 0)) / 1000, 3)
            groups[display_group][status] += 1

            labels = {
                "source": "playwright_ui",
                "group": display_group,
                "service": project,
                "classname": file_name,
                "name": workflow,
                "status": status,
            }
            lines.append(metric_line("ai_tutor_quality_check_duration_seconds", duration, labels))
            lines.append(
                metric_line(
                    "ai_tutor_playwright_workflow_duration_seconds",
                    duration,
                    {"group": display_group, "project": project, "workflow": workflow, "status": status},
                )
            )

    ok = failed == 0 and errors == 0 and tests > 0
    timestamp = report_path.stat().st_mtime
    lines.extend(
        [
            metric_line("ai_tutor_quality_source_available", 1, {"source": "playwright_ui"}),
            metric_line("ai_tutor_quality_source_ok", 1 if ok else 0, {"source": "playwright_ui"}),
            metric_line("ai_tutor_quality_source_duration_seconds", duration_seconds, {"source": "playwright_ui"}),
            metric_line("ai_tutor_quality_source_last_run_timestamp_seconds", timestamp, {"source": "playwright_ui"}),
            metric_line("ai_tutor_playwright_results_available", 1),
            metric_line("ai_tutor_playwright_run_timestamp_seconds", timestamp),
        ]
    )

    for status, value in {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "error": errors,
        "total": tests,
    }.items():
        lines.append(metric_line("ai_tutor_quality_checks_total", value, {"source": "playwright_ui", "status": status}))

    for group, counts in sorted(groups.items()):
        lines.append(metric_line("ai_tutor_quality_group_checks_total", sum(counts.values()), {"source": "playwright_ui", "group": group, "status": "total"}))
        for status, value in sorted(counts.items()):
            lines.append(metric_line("ai_tutor_quality_group_checks_total", value, {"source": "playwright_ui", "group": group, "status": status}))

    for status, value in {"passed": passed, "failed": failed, "skipped": skipped, "total": tests}.items():
        lines.append(metric_line("ai_tutor_playwright_tests_total", value, {"status": status}))

    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve Playwright metrics for Prometheus/Grafana.")
    parser.add_argument("--report", default="playwright-report/index.html", help="Path to the Playwright HTML report.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", default=9109, type=int, help="Port to bind.")
    args = parser.parse_args()

    report_path = Path(args.report).resolve()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/metrics":
                payload = ("\n".join(parse_playwright_report(report_path)) + "\n").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if self.path in {"/", "/healthz"}:
                payload = b"ok\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving Playwright metrics on http://{args.host}:{args.port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
