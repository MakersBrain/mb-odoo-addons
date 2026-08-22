"""Pure parsers for artifacts emitted by the catalogue-ceramics scraper.

This module deliberately imports no Odoo model API. Parsing produces normalized
plain dictionaries; the batch model decides whether and how to persist them.
"""

import csv
import gzip
import hashlib
import io
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_RECORDS = 10_000
MAX_RAW_RECORD_CHARS = 65_536
CATALOGUE_V2 = "ceramics.catalogue_item.v2"
CSV_REQUIRED = {
    "product_name",
    "price",
    "currency",
    "stock_quantity",
    "product_url",
}


class AdapterError(ValueError):
    """A bounded, user-displayable artifact error."""


@dataclass(frozen=True)
class ParsedArtifact:
    adapter_key: str
    rows: tuple[dict[str, Any], ...]
    source_key: str | None
    currency: str | None
    fetched_at_min: datetime | None
    fetched_at_max: datetime | None


def _bounded_source(data: bytes) -> bytes:
    if not data:
        raise AdapterError("The uploaded catalogue artifact is empty.")
    if len(data) > MAX_SOURCE_BYTES:
        raise AdapterError("The uploaded catalogue artifact exceeds 20 MB.")
    return data


def _decompress(data: bytes) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            decoded = stream.read(MAX_DECOMPRESSED_BYTES + 1)
    except (gzip.BadGzipFile, EOFError, OSError) as error:
        raise AdapterError("The gzip catalogue artifact is malformed.") from error
    if len(decoded) > MAX_DECOMPRESSED_BYTES:
        raise AdapterError("The decompressed catalogue artifact exceeds 100 MB.")
    return decoded


def _text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise AdapterError("Catalogue artifacts must be UTF-8 encoded.") from error


def _decimal(value: Any, field: str, *, allow_blank: bool = True) -> float | None:
    if value in (None, "") and allow_blank:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise AdapterError(f"{field} must be a number.") from error
    if not math.isfinite(parsed):
        raise AdapterError(f"{field} must be a finite number.")
    if parsed < 0:
        raise AdapterError(f"{field} cannot be negative.")
    return parsed


def _integer(value: Any, field: str, *, allow_blank: bool = True) -> int | None:
    if value in (None, "") and allow_blank:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise AdapterError(f"{field} must be a whole number.") from error
    if parsed < 0:
        raise AdapterError(f"{field} cannot be negative.")
    return parsed


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError as error:
        raise AdapterError("fetched_at must be an ISO-8601 timestamp.") from error


def _raw(record: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True)
    if len(encoded) > MAX_RAW_RECORD_CHARS:
        raise AdapterError("A catalogue record exceeds the retained evidence limit.")
    return record


def _category(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [part.strip() for part in text.split(" > ") if part.strip()]


def _normalize_v2(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("format") != CATALOGUE_V2:
        raise AdapterError("The NDJSON contains an unknown catalogue record version.")
    raw_variant = (record.get("raw") or {}).get("variant") or {}
    stock_tracked = raw_variant.get("isTrackingEnabled")
    if stock_tracked is None:
        stock_tracked = record.get("stock_quantity") is not None
    external_id = str(record.get("external_id") or "").strip()
    if not external_id:
        raise AdapterError("A v2 catalogue record has no external_id.")
    name = str(record.get("name") or record.get("product_name") or "").strip()
    if not name:
        raise AdapterError("A catalogue record has no product name.")
    return {
        "external_id": external_id,
        "parent_external_id": record.get("parent_external_id"),
        "identity_is_fallback": False,
        "name": name,
        "variant_title": record.get("variant_title"),
        "description": record.get("description"),
        "category_path": _category(record.get("category_path")),
        "price": _decimal(record.get("price"), "price", allow_blank=False),
        "currency": str(record.get("currency") or "").upper() or None,
        "vat_status": record.get("vat_status"),
        "stock_quantity": _integer(record.get("stock_quantity"), "stock_quantity"),
        "stock_is_tracked": bool(stock_tracked),
        "availability": record.get("availability"),
        "product_url": record.get("product_url"),
        "image_url": record.get("image_url"),
        "fetched_at": _timestamp(record.get("fetched_at")),
        "raw_record": _raw(record),
    }


def _normalize_csv(record: dict[str, Any], source_key: str) -> dict[str, Any]:
    name = str(record.get("product_name") or "").strip()
    if not name:
        raise AdapterError("A CSV row has no product_name.")
    product_url = str(record.get("product_url") or "").strip()
    variant_title = str(record.get("variant_title") or "").strip() or None
    exact = str(record.get("external_id") or "").strip()
    fallback_material = "\0".join((source_key, product_url, variant_title or ""))
    external_id = (
        exact or "fallback:" + hashlib.sha256(fallback_material.encode("utf-8")).hexdigest()
    )
    stock_value = record.get("stock_quantity")
    return {
        "external_id": external_id,
        "parent_external_id": record.get("parent_external_id") or None,
        "identity_is_fallback": not bool(exact),
        "name": name,
        "variant_title": variant_title,
        "description": record.get("description") or None,
        "category_path": _category(record.get("category_path")),
        "price": _decimal(record.get("price"), "price", allow_blank=False),
        "currency": str(record.get("currency") or "").upper() or None,
        "vat_status": record.get("vat_status") or None,
        "stock_quantity": _integer(stock_value, "stock_quantity"),
        "stock_is_tracked": stock_value not in (None, ""),
        "availability": record.get("availability") or None,
        "product_url": product_url or None,
        "image_url": record.get("image_url") or None,
        "fetched_at": _timestamp(record.get("fetched_at")),
        "raw_record": _raw(record),
    }


def detect(data: bytes, filename: str = "") -> str:
    data = _bounded_source(data)
    decoded = _decompress(data) if data.startswith(b"\x1f\x8b") else data
    text = _text(decoded)
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    claims = []
    if first.startswith("{"):
        claims.append("catalogue_v2")
    try:
        header = set(next(csv.reader(io.StringIO(text))))
    except StopIteration:
        header = set()
    if CSV_REQUIRED.issubset(header):
        claims.append("catalogue_csv")
    if len(claims) != 1:
        if not claims:
            raise AdapterError("No supported catalogue adapter recognizes this file.")
        raise AdapterError("More than one catalogue adapter recognizes this file.")
    if filename.lower().endswith(".gz") and claims[0] != "catalogue_v2":
        raise AdapterError("Only catalogue v2 NDJSON may be gzip-compressed.")
    return claims[0]


def parse(
    data: bytes, filename: str, source_key: str, adapter_key: str | None = None
) -> ParsedArtifact:
    data = _bounded_source(data)
    selected = adapter_key or detect(data, filename)
    decoded = _decompress(data) if data.startswith(b"\x1f\x8b") else data
    text = _text(decoded)
    rows: list[dict[str, Any]] = []
    source_keys: set[str] = set()
    if selected == "catalogue_v2":
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            if len(rows) >= MAX_RECORDS:
                raise AdapterError("The catalogue artifact exceeds 10,000 records.")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise AdapterError(f"NDJSON line {number} is not valid JSON.") from error
            if not isinstance(record, dict):
                raise AdapterError(f"NDJSON line {number} is not an object.")
            record_source = str(record.get("source") or "").strip()
            if not record_source:
                raise AdapterError(f"NDJSON line {number} has no scraper source.")
            source_keys.add(record_source)
            rows.append(_normalize_v2(record))
    elif selected == "catalogue_csv":
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or not CSV_REQUIRED.issubset(reader.fieldnames):
            raise AdapterError("The scraper CSV does not contain the required columns.")
        for number, record in enumerate(reader, start=2):
            if len(rows) >= MAX_RECORDS:
                raise AdapterError("The catalogue artifact exceeds 10,000 records.")
            try:
                rows.append(_normalize_csv(record, source_key))
            except AdapterError as error:
                raise AdapterError(f"CSV line {number}: {error}") from error
        source_keys.add(source_key)
    else:
        raise AdapterError(f"Unsupported catalogue adapter: {selected}.")
    if not rows:
        raise AdapterError("The catalogue artifact contains no product records.")
    source_keys.discard("")
    if len(source_keys) > 1:
        raise AdapterError("The catalogue artifact mixes more than one source.")
    artifact_source = next(iter(source_keys), None)
    if artifact_source and source_key and artifact_source != source_key:
        raise AdapterError(
            f"The artifact source {artifact_source!r} does not match the selected shop."
        )
    external_ids = [row["external_id"] for row in rows]
    if len(external_ids) != len(set(external_ids)):
        raise AdapterError("The catalogue artifact contains duplicate external IDs.")
    currencies = {row["currency"] for row in rows if row["currency"]}
    if len(currencies) > 1:
        raise AdapterError("The catalogue artifact mixes currencies.")
    fetched = sorted(row["fetched_at"] for row in rows if row["fetched_at"])
    return ParsedArtifact(
        adapter_key=selected,
        rows=tuple(rows),
        source_key=artifact_source,
        currency=next(iter(currencies), None),
        fetched_at_min=fetched[0] if fetched else None,
        fetched_at_max=fetched[-1] if fetched else None,
    )
