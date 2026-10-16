#!/usr/bin/env python3
"""Verify the approved Portkey multimodal embedding wire contract.

The canary deliberately does not read application state or accept model and
dimension overrides. Credentials are supplied only through the environment,
and neither provider response bodies nor embedding values are printed.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests


MODEL_NAME = "@vertexai/gemini-embedding-2"
DIMENSIONS = 1536
API_KEY_ENV = "PORTKEY_CANARY_API_KEY"
BASE_URL_ENV = "PORTKEY_CANARY_BASE_URL"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"


class CanaryFailure(Exception):
    """A safe operational failure that may be printed without provider data."""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Probe Portkey with one text, one PNG, and one JPEG embedding "
            "request using the fixed Phase 6 model contract."
        )
    )
    parser.add_argument("--png", required=True, type=Path, help="Valid PNG sample")
    parser.add_argument("--jpeg", required=True, type=Path, help="Valid JPEG sample")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=120.0,
        help="Per-request timeout from 1 to 300 seconds (default: 120)",
    )
    return parser.parse_args()


def _load_image(path: Path, *, mime_type: str) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise CanaryFailure(
            f"The {mime_type} canary input could not be opened ({type(error).__name__})."
        ) from None

    if size <= 0:
        raise CanaryFailure(f"The {mime_type} canary input is empty.")
    if size > MAX_IMAGE_BYTES:
        raise CanaryFailure(
            f"The {mime_type} canary input exceeds {MAX_IMAGE_BYTES} bytes."
        )

    try:
        image = path.read_bytes()
    except OSError as error:
        raise CanaryFailure(
            f"The {mime_type} canary input could not be read ({type(error).__name__})."
        ) from None

    expected_signature = PNG_SIGNATURE if mime_type == "image/png" else JPEG_SIGNATURE
    if not image.startswith(expected_signature):
        raise CanaryFailure(f"The {mime_type} canary input has an invalid signature.")
    return image


def _resolve_endpoint() -> tuple[str, str]:
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    base_url = os.environ.get(BASE_URL_ENV, "").strip()
    if not api_key:
        raise CanaryFailure(f"{API_KEY_ENV} is required.")
    if not base_url:
        raise CanaryFailure(f"{BASE_URL_ENV} is required.")

    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise CanaryFailure(f"{BASE_URL_ENV} must be an absolute HTTPS URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CanaryFailure(
            f"{BASE_URL_ENV} must not contain credentials, a query, or a fragment."
        )
    return f"{base_url.rstrip('/')}/embeddings", api_key


def _read_response(response: requests.Response, *, label: str) -> dict[str, Any]:
    if response.status_code != 200:
        raise CanaryFailure(f"The {label} request failed with HTTP {response.status_code}.")

    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > MAX_RESPONSE_BYTES:
                raise CanaryFailure(f"The {label} response exceeded the safety limit.")
        except ValueError:
            raise CanaryFailure(
                f"The {label} response had an invalid Content-Length header."
            ) from None

    body = bytearray()
    for chunk in response.iter_content(chunk_size=64 * 1024):
        body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            raise CanaryFailure(f"The {label} response exceeded the safety limit.")

    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CanaryFailure(f"The {label} response was not valid JSON.") from None
    if not isinstance(decoded, dict):
        raise CanaryFailure(f"The {label} response was not a JSON object.")
    return decoded


def _extract_vectors(
    response: dict[str, Any],
    *,
    modality: str,
) -> list[Any]:
    data = response.get("data")
    if isinstance(data, list):
        vectors = [
            item.get("embedding")
            for item in data
            if isinstance(item, dict) and item.get("embedding") is not None
        ]
        if vectors:
            return vectors

    predictions = response.get("predictions")
    if isinstance(predictions, list):
        field = "imageEmbedding" if modality == "image" else "textEmbedding"
        vectors = [
            item.get(field)
            for item in predictions
            if isinstance(item, dict) and item.get(field) is not None
        ]
        if vectors:
            return vectors

    raise CanaryFailure(
        f"The {modality} response did not match a supported embedding shape."
    )


def _validate_vector(response: dict[str, Any], *, label: str, modality: str) -> None:
    vectors = _extract_vectors(response, modality=modality)
    if len(vectors) != 1:
        raise CanaryFailure(f"The {label} response did not contain exactly one vector.")

    vector = vectors[0]
    if not isinstance(vector, list) or len(vector) != DIMENSIONS:
        raise CanaryFailure(
            f"The {label} response was not exactly {DIMENSIONS} dimensions."
        )
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in vector
    ):
        raise CanaryFailure(f"The {label} vector contained a non-finite numeric value.")


def _post_canary(
    endpoint: str,
    api_key: str,
    payload: dict[str, Any],
    *,
    label: str,
    modality: str,
    timeout_seconds: float,
) -> None:
    try:
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout_seconds,
            allow_redirects=False,
            stream=True,
        )
    except requests.RequestException as error:
        raise CanaryFailure(
            f"The {label} request failed before a response ({type(error).__name__})."
        ) from None

    try:
        decoded = _read_response(response, label=label)
    finally:
        response.close()

    _validate_vector(decoded, label=label, modality=modality)
    print(f"PASS {label}: one finite {DIMENSIONS}-dimension vector")


def main() -> int:
    args = _parse_args()
    if not 1 <= args.timeout_seconds <= 300:
        print("FAIL --timeout-seconds must be between 1 and 300.", file=sys.stderr)
        return 2

    try:
        endpoint, api_key = _resolve_endpoint()
        png = _load_image(args.png, mime_type="image/png")
        jpeg = _load_image(args.jpeg, mime_type="image/jpeg")

        common = {
            "model": MODEL_NAME,
            "dimensions": DIMENSIONS,
            "encoding_format": "float",
        }
        _post_canary(
            endpoint,
            api_key,
            {**common, "input": ["Phase 6 multimodal embedding canary."]},
            label="text",
            modality="text",
            timeout_seconds=args.timeout_seconds,
        )
        for label, mime_type, image in (
            ("PNG", "image/png", png),
            ("JPEG", "image/jpeg", jpeg),
        ):
            _post_canary(
                endpoint,
                api_key,
                {
                    **common,
                    "input": [
                        {
                            "text": "",
                            "image": {
                                "base64": base64.b64encode(image).decode("ascii"),
                                "mimeType": mime_type,
                            },
                        }
                    ],
                },
                label=label,
                modality="image",
                timeout_seconds=args.timeout_seconds,
            )
    except CanaryFailure as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(
            f"FAIL The canary stopped unexpectedly ({type(error).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(
        f"PASS contract: model={MODEL_NAME} dimensions={DIMENSIONS} modalities=text,image"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
