#!/usr/bin/env python3
"""Benchmark sanitized private inventory photos with Azure prebuilt-read.

Only aggregate match decisions, token counts, timings, and sanitized digests are
written. Source images and provider response bodies stay in memory. Every
terminal Azure analyze result is deleted before the next sample is submitted.
"""

import argparse
import hashlib
import json
import os
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from evaluate_inventory_capture import EXPECTED, sanitize

API_VERSION = "2024-11-30"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_POLLS = 120


def compact(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKC", value).casefold()
        if character.isalnum()
    )


def request(
    url: str,
    key: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    mimetype: str | None = None,
) -> tuple[int, dict, bytes]:
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "User-Agent": "mb-inventory-benchmark/1",
    }
    if mimetype:
        headers["Content-Type"] = mimetype
    call = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(
            call, timeout=90, context=ssl.create_default_context()
        ) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise RuntimeError("Azure response exceeded the 8 MB bound")
            return response.status, dict(response.headers.items()), payload
    except urllib.error.HTTPError as error:
        # Provider bodies can contain extracted label text, so do not echo them.
        raise RuntimeError(f"Azure returned HTTP {error.code}") from None


def analyze(endpoint: str, key: str, image: bytes, mimetype: str) -> tuple[dict, bool]:
    base = endpoint.rstrip("/")
    query = urllib.parse.urlencode({"_overload": "analyzeDocument", "api-version": API_VERSION})
    submit_url = f"{base}/documentintelligence/documentModels/prebuilt-read:analyze?{query}"
    status, headers, _ = request(submit_url, key, method="POST", body=image, mimetype=mimetype)
    if status not in {200, 202}:
        raise RuntimeError(f"unexpected Azure submit status {status}")
    operation_url = headers.get("Operation-Location") or headers.get("operation-location")
    if not operation_url:
        raise RuntimeError("Azure omitted Operation-Location")
    expected_origin = urllib.parse.urlsplit(base)[:2]
    if urllib.parse.urlsplit(operation_url)[:2] != expected_origin:
        raise RuntimeError("Azure returned a cross-origin operation URL")

    terminal = False
    try:
        for _ in range(MAX_POLLS):
            time.sleep(2)
            _, _, payload = request(operation_url, key)
            operation = json.loads(payload)
            state = operation.get("status")
            if state in {"notStarted", "running"}:
                continue
            terminal = True
            if state != "succeeded" or not isinstance(operation.get("analyzeResult"), dict):
                raise RuntimeError(f"Azure analysis ended in state {state!r}")
            return operation["analyzeResult"], delete_result(operation_url, key)
        raise RuntimeError("Azure analysis exceeded the polling limit")
    finally:
        if terminal:
            # The successful return already deleted it. This second call is
            # intentionally idempotent and also covers terminal failure states.
            delete_result(operation_url, key)


def delete_result(operation_url: str, key: str) -> bool:
    try:
        status, _, _ = request(operation_url, key, method="DELETE")
        return status in {200, 202, 204}
    except RuntimeError as error:
        if "HTTP 404" in str(error):
            return True
        raise


def result_text(result: dict) -> tuple[str, int]:
    content = result.get("content")
    words = []
    for page in result.get("pages") or []:
        for word in page.get("words") or []:
            if isinstance(word.get("content"), str):
                words.append(word["content"])
    if not isinstance(content, str):
        content = " ".join(words)
    return content, len(words)


def evaluate(content: str, expected: dict) -> dict:
    haystack = compact(content)
    decisions: dict[str, Any] = {}
    for field in ("barcode", "lot"):
        wanted = expected.get(field)
        decisions[field] = None if wanted is None else compact(str(wanted)) in haystack
    product = expected.get("product")
    product_terms = [compact(term) for term in str(product or "").split()]
    decisions["product"] = (
        None if product is None else all(term and term in haystack for term in product_terms)
    )
    decisions["alternates"] = {
        alternate: compact(alternate) in haystack for alternate in expected.get("alternates", [])
    }
    return decisions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    endpoint = os.environ.get("AZURE_DOCUMENT_ENDPOINT", "").strip()
    key = os.environ.get("AZURE_DOCUMENT_KEY", "").strip()
    parsed = urllib.parse.urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".cognitiveservices.azure.com")
    ):
        raise SystemExit(
            "AZURE_DOCUMENT_ENDPOINT must be an Azure Cognitive Services HTTPS endpoint"
        )
    if not key:
        raise SystemExit("AZURE_DOCUMENT_KEY is required")

    expected = json.loads(EXPECTED.read_text())
    report: dict[str, Any] = {
        "provider": "azure-document-intelligence",
        "model": "prebuilt-read",
        "api_version": API_VERSION,
        "images": {},
    }
    with zipfile.ZipFile(args.zip_path) as archive:
        members = {
            PurePosixPath(info.filename).name: info
            for info in archive.infolist()
            if not info.is_dir()
            and PurePosixPath(info.filename).suffix.lower() in {".jpg", ".jpeg", ".png"}
        }
        for filename in sorted(expected):
            if filename not in members:
                raise RuntimeError(f"sample ZIP is missing {filename}")
            source = archive.read(members[filename])
            sanitized, width, height, mimetype = sanitize(source)
            started = time.monotonic()
            result, deleted = analyze(endpoint, key, sanitized, mimetype)
            content, word_count = result_text(result)
            report["images"][filename] = {
                "sanitized_sha256": hashlib.sha256(sanitized).hexdigest(),
                "width": width,
                "height": height,
                "word_count": word_count,
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "result_deleted": deleted,
                "matches": evaluate(content, expected[filename]),
            }
            print(f"tested {filename}", file=sys.stderr)

    fields = ("barcode", "lot", "product")
    report["summary"] = {
        field: {
            "matched": sum(image["matches"][field] is True for image in report["images"].values()),
            "expected": sum(
                image["matches"][field] is not None for image in report["images"].values()
            ),
        }
        for field in fields
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
