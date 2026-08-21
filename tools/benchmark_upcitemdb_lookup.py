#!/usr/bin/env python3
"""Ground-truth-blind UPCitemDB product-lookup evaluation.

The free endpoint permits two identifiers per lookup request and expects a
sustainable request rate. Expected product data is used only after retrieval to
score the normalized response; it is never sent to UPCitemDB.
"""

import argparse
import json
import re
import sqlite3
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ENDPOINT = "https://api.upcitemdb.com/prod/trial/lookup"
MAX_BATCH_SIZE = 2
MAX_RESPONSE_BYTES = 1024 * 1024
TRIAL_MINIMUM_INTERVAL = 10.0
CACHE_SCHEMA_VERSION = 2
DEFAULT_POSITIVE_TTL_SECONDS = 30 * 24 * 60 * 60
DEFAULT_NEGATIVE_TTL_SECONDS = 24 * 60 * 60


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


class LookupCache:
    """Bounded normalized-result cache; raw provider responses are never stored."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=5)
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = FULL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS product_lookup_cache (
                provider TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                normalized_gtin TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('found', 'not_found')),
                candidate_json TEXT,
                cached_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                PRIMARY KEY (provider, schema_version, normalized_gtin),
                CHECK (
                    (status = 'found' AND candidate_json IS NOT NULL)
                    OR (status = 'not_found' AND candidate_json IS NULL)
                )
            )
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def get(self, barcode: str, now: int | None = None) -> dict | None:
        current_time = int(time.time()) if now is None else now
        normalized = comparison_gtin(barcode)
        row = self.connection.execute(
            """
            SELECT status, candidate_json, cached_at, expires_at
              FROM product_lookup_cache
             WHERE provider = ? AND schema_version = ? AND normalized_gtin = ?
               AND expires_at > ?
            """,
            ("upcitemdb", CACHE_SCHEMA_VERSION, normalized, current_time),
        ).fetchone()
        if row is None:
            return None
        status, candidate_json, cached_at, expires_at = row
        candidate = json.loads(candidate_json) if candidate_json else None
        if candidate is not None and comparison_gtin(candidate["identifier"]) != normalized:
            raise RuntimeError("cached candidate identifier does not match its cache key")
        return {
            "status": status,
            "candidate": candidate,
            "cached_at": cached_at,
            "expires_at": expires_at,
        }

    def put(
        self,
        barcode: str,
        candidate: dict | None,
        ttl_seconds: int,
        now: int | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("cache TTL must be positive")
        current_time = int(time.time()) if now is None else now
        normalized = comparison_gtin(barcode)
        if candidate is not None and comparison_gtin(candidate["identifier"]) != normalized:
            raise ValueError("candidate identifier does not match its cache key")
        status = "found" if candidate is not None else "not_found"
        candidate_json = (
            json.dumps(candidate, separators=(",", ":"), sort_keys=True) if candidate else None
        )
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO product_lookup_cache (
                    provider, schema_version, normalized_gtin, status,
                    candidate_json, cached_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (provider, schema_version, normalized_gtin) DO UPDATE SET
                    status = excluded.status,
                    candidate_json = excluded.candidate_json,
                    cached_at = excluded.cached_at,
                    expires_at = excluded.expires_at
                """,
                (
                    "upcitemdb",
                    CACHE_SCHEMA_VERSION,
                    normalized,
                    status,
                    candidate_json,
                    current_time,
                    current_time + ttl_seconds,
                ),
            )


def compact(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKC", value).casefold()
        if character.isalnum()
    )


def digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def gs1_check_digit_valid(value: str) -> bool:
    number = digits(value)
    if len(number) not in {8, 12, 13, 14}:
        return False
    payload, check = number[:-1], int(number[-1])
    total = sum(
        int(character) * (3 if offset % 2 == 0 else 1)
        for offset, character in enumerate(reversed(payload))
    )
    return (10 - total % 10) % 10 == check


def comparison_gtin(value: str) -> str:
    number = digits(value)
    if not gs1_check_digit_valid(number):
        raise ValueError("identifier has an invalid GS1 check digit")
    return number.zfill(14)


def chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def lookup_batch(barcodes: list[str]) -> tuple[list[dict], dict]:
    if not 1 <= len(barcodes) <= MAX_BATCH_SIZE:
        raise ValueError("UPCitemDB trial batches must contain one or two identifiers")
    query = urllib.parse.urlencode({"upc": ",".join(barcodes)})
    request = urllib.request.Request(
        f"{ENDPOINT}?{query}",
        headers={"Accept": "application/json", "User-Agent": "mb-inventory-benchmark/1.0"},
    )
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
    )
    try:
        with opener.open(request, timeout=30) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            rate_limit = {
                key: response.headers.get(key)
                for key in (
                    "X-RateLimit-Limit",
                    "X-RateLimit-Remaining",
                    "X-RateLimit-Reset",
                    "Retry-After",
                )
                if response.headers.get(key) is not None
            }
    except urllib.error.HTTPError as error:
        if error.code == 429:
            raise RuntimeError("UPCitemDB rate limit reached; retry after its reset window") from None
        raise RuntimeError(f"UPCitemDB returned HTTP {error.code}") from None
    if len(payload) > MAX_RESPONSE_BYTES:
        raise RuntimeError("UPCitemDB response exceeded the 1 MB bound")
    envelope = json.loads(payload)
    if envelope.get("code") != "OK" or not isinstance(envelope.get("items"), list):
        raise RuntimeError("UPCitemDB returned an invalid response")
    return envelope["items"], rate_limit


def item_identifiers(item: dict) -> list[str]:
    values = []
    for field in ("upc", "ean", "gtin"):
        raw = item.get(field)
        if raw:
            try:
                values.append(comparison_gtin(str(raw)))
            except ValueError:
                continue
    return list(dict.fromkeys(values))


def normalize_item(item: dict, requested_barcode: str, retrieved_at: str) -> dict:
    requested = comparison_gtin(requested_barcode)
    if requested not in item_identifiers(item):
        raise ValueError("provider item does not contain the requested GTIN")
    return {
        "identifier": requested_barcode,
        "identifier_type": f"GTIN-{len(digits(requested_barcode))}",
        "brand": str(item.get("brand") or "").strip(),
        "manufacturer_sku": str(item.get("model") or "").strip(),
        "name": str(item.get("title") or "").strip(),
        "pack": str(item.get("size") or item.get("weight") or "").strip(),
        "category": str(item.get("category") or "").strip(),
        # UPCitemDB's ``elid`` is an eBay listing ID, not a stable provider
        # product ID. The canonical GTIN is the only safe cache/source key.
        "source_record_id": requested,
        "provider": "upcitemdb",
        "retrieved_at": retrieved_at,
    }


def candidate_matches(candidate: dict, expected: dict) -> dict:
    expected_terms = [compact(term) for term in re.split(r"\s+", expected["product"]) if term]
    candidate_text = compact(
        " ".join(
            str(candidate[field])
            for field in ("brand", "manufacturer_sku", "name", "pack")
        )
    )
    return {
        "exact_identifier": comparison_gtin(candidate["identifier"])
        == comparison_gtin(expected["barcode"]),
        "complete_expected_terms": all(term in candidate_text for term in expected_terms),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("expected", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--positive-ttl-days", type=int, default=DEFAULT_POSITIVE_TTL_SECONDS // 86400
    )
    parser.add_argument(
        "--negative-ttl-hours", type=int, default=DEFAULT_NEGATIVE_TTL_SECONDS // 3600
    )
    parser.add_argument(
        "--minimum-interval",
        type=float,
        default=TRIAL_MINIMUM_INTERVAL,
        help="seconds between free-tier requests; values below 10 are rejected",
    )
    args = parser.parse_args()
    if args.minimum_interval < TRIAL_MINIMUM_INTERVAL:
        raise SystemExit("UPCitemDB trial requests must be spaced by at least 10 seconds")
    if args.positive_ttl_days <= 0 or args.negative_ttl_hours <= 0:
        raise SystemExit("cache TTLs must be positive")

    expected = json.loads(args.expected.read_text())
    by_barcode = {
        details["barcode"]: (filename, details)
        for filename, details in expected.items()
        if details.get("barcode")
    }
    for barcode in by_barcode:
        if not gs1_check_digit_valid(barcode):
            raise SystemExit(f"invalid expected barcode: {barcode}")

    report = {
        "provider": "upcitemdb",
        "endpoint_tier": "trial",
        "images": {},
        "requests": [],
        "cache": {"hits": 0, "misses": 0, "schema_version": CACHE_SCHEMA_VERSION},
    }
    cache = LookupCache(args.cache)
    misses = []
    try:
        for barcode, (filename, wanted) in by_barcode.items():
            cached = None if args.refresh else cache.get(barcode)
            if cached is None:
                misses.append(barcode)
                report["cache"]["misses"] += 1
                continue
            report["cache"]["hits"] += 1
            candidate = cached["candidate"]
            report["images"][filename] = {
                "barcode": barcode,
                "candidate": candidate,
                "cache_status": "hit",
                "matches": candidate_matches(candidate, wanted) if candidate else None,
            }

        batches = chunks(misses, MAX_BATCH_SIZE)
        for batch_index, batch in enumerate(batches):
            if batch_index:
                time.sleep(args.minimum_interval)
            started = time.monotonic()
            items, rate_limit = lookup_batch(batch)
            report["requests"].append(
                {
                    "identifier_count": len(batch),
                    "elapsed_seconds": round(time.monotonic() - started, 2),
                    "rate_limit": rate_limit,
                }
            )
            items_by_identifier = {
                identifier: item for item in items for identifier in item_identifiers(item)
            }
            retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat()
            for barcode in batch:
                filename, wanted = by_barcode[barcode]
                item = items_by_identifier.get(comparison_gtin(barcode))
                candidate = normalize_item(item, barcode, retrieved_at) if item else None
                ttl = (
                    args.positive_ttl_days * 86400
                    if candidate
                    else args.negative_ttl_hours * 3600
                )
                cache.put(barcode, candidate, ttl)
                report["images"][filename] = {
                    "barcode": barcode,
                    "candidate": candidate,
                    "cache_status": "miss",
                    "matches": candidate_matches(candidate, wanted) if candidate else None,
                }
            print(f"queried {len(batch)} identifier(s)", file=sys.stderr)
    finally:
        cache.close()

    report["summary"] = {
        "exact_identifier": {
            "matched": sum(
                bool((item.get("matches") or {}).get("exact_identifier"))
                for item in report["images"].values()
            ),
            "expected": len(by_barcode),
        },
        "complete_expected_terms": {
            "matched": sum(
                bool((item.get("matches") or {}).get("complete_expected_terms"))
                for item in report["images"].values()
            ),
            "expected": len(by_barcode),
        },
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
