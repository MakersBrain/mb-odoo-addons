#!/usr/bin/env python3
"""Run non-mutating Sendcloud v3 account qualification.

The fixed-host client never prints credentials, response bodies, addresses, or
request headers. It deliberately has no shipment, label, return, or cancellation
operation; charged live qualification must be performed through the Odoo adapter
with the approval controls described in the runbook.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener


BASE_URL = "https://panel.sendcloud.sc"
MAX_RESPONSE = 2 * 1024 * 1024
REQUIRED_KEYS = ("SENDCLOUD_PUBLIC_KEY", "SENDCLOUD_PRIVATE_KEY")


class QualificationError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise QualificationError("qualification environment file is unavailable") from error
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key.startswith("SENDCLOUD_"):
            values[key] = value.strip().strip("'\"")
    if any(not values.get(key) for key in REQUIRED_KEYS):
        raise QualificationError("Sendcloud public/private keys are missing")
    return values


class Client:
    def __init__(self, public_key: str, private_key: str):
        encoded = base64.b64encode(f"{public_key}:{private_key}".encode()).decode()
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
            "User-Agent": "MakersBrain-Sendcloud-Qualification/1",
        }
        self.opener = build_opener(
            HTTPSHandler(context=ssl.create_default_context()), NoRedirect()
        )

    def request(self, method: str, path: str, payload: dict | None = None) -> dict | list:
        body = json.dumps(payload, separators=(",", ":")).encode() if payload else None
        request = Request(
            f"{BASE_URL}{path}", data=body, headers=self.headers, method=method
        )
        try:
            with self.opener.open(request, timeout=20) as response:
                declared = response.headers.get("Content-Length", "")
                if declared.isdigit() and int(declared) > MAX_RESPONSE:
                    raise QualificationError("Sendcloud response exceeded the size limit")
                raw = response.read(MAX_RESPONSE + 1)
        except HTTPError as error:
            raise QualificationError(f"Sendcloud rejected a read-only check (HTTP {error.code})") from error
        except URLError as error:
            raise QualificationError("Sendcloud is unavailable for qualification") from error
        if len(raw) > MAX_RESPONSE:
            raise QualificationError("Sendcloud response exceeded the size limit")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, ValueError) as error:
            raise QualificationError("Sendcloud returned invalid JSON") from error
        if not isinstance(value, (dict, list)):
            raise QualificationError("Sendcloud returned an unexpected response")
        return value


def rows(payload: dict | list) -> list[dict]:
    value = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(value, dict):
        value = value.get("results", [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def qualify(values: dict[str, str], client: Client) -> dict:
    metadata = client.request("GET", "/api/v3/user/auth/metadata")
    senders = rows(client.request("GET", "/api/v3/addresses/sender-addresses"))
    sender_ids = [str(item.get("id")) for item in senders if item.get("id") is not None]
    result: dict[str, object] = {
        "credentials_valid": True,
        "integration_metadata_available": bool(metadata),
        "sender_address_count": len(senders),
        "sender_address_ids": sender_ids,
        "mutations_performed": 0,
    }

    country = values.get("SENDCLOUD_QUALIFICATION_COUNTRY", "").upper()
    postal = values.get("SENDCLOUD_QUALIFICATION_POSTAL_CODE", "")
    city = values.get("SENDCLOUD_QUALIFICATION_CITY", "")
    if country and postal and city:
        query = urlencode({
            "country_code": country,
            "address_postal_code": postal,
            "address_city": city,
            "limit": 10,
        })
        result["service_point_count"] = len(
            rows(client.request("GET", f"/api/v3/service-points?{query}"))
        )
    else:
        result["service_points"] = "skipped_missing_qualification_destination"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file", type=Path, default=Path("sendcloud.env"),
        help="ignored env file containing Sendcloud keys and optional qualification destination",
    )
    args = parser.parse_args(argv)
    try:
        values = load_env(args.env_file)
        result = qualify(
            values, Client(values["SENDCLOUD_PUBLIC_KEY"], values["SENDCLOUD_PRIVATE_KEY"])
        )
    except QualificationError as error:
        print(f"Sendcloud qualification failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
