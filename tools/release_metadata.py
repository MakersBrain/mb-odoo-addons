#!/usr/bin/env python3
"""Emit the release metadata that accompanies a published Odoo image.

    python3 tools/release_metadata.py --image ghcr.io/makersbrain/mb-odoo@sha256:...

This is the record `mb-infra` reads when it composes a platform release, and the
only place the control plane can learn which add-on versions are actually inside
a given image digest. It is deliberately small: evidence that is large (SBOM,
vulnerability report) travels as separate release artifacts and is referenced by
digest from the composed release record, not inlined here.

Everything is derived from the checkout, so the metadata cannot describe a tree
other than the one that was built.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ADDONS = ROOT / "addons"
DOCKERFILE = ROOT / "deploy" / "Odoo.Dockerfile"
CONTRACT = ROOT / "contracts" / "mb_control_v1.json"

DIGEST_REF = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")


def manifest_of(addon: pathlib.Path) -> dict | None:
    path = addon / "__manifest__.py"
    if not path.is_file():
        return None
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            try:
                data = ast.literal_eval(node)
            except (ValueError, SyntaxError, TypeError):
                continue
            if isinstance(data, dict) and "version" in data:
                return data
    return None


def installed_addons() -> dict[str, str]:
    """Every addon the image copies into /mnt/mb-addons."""
    versions: dict[str, str] = {}
    for addon in sorted(ADDONS.iterdir()):
        if not addon.is_dir():
            continue
        manifest = manifest_of(addon)
        if manifest:
            versions[addon.name] = manifest["version"]
    return versions


def odoo_base() -> dict[str, str]:
    """The pinned base image, read from the Dockerfile rather than assumed."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    match = re.search(r"^FROM\s+(odoo:(\d+)@sha256:[0-9a-f]{64})", text, re.M)
    if not match:
        raise SystemExit(
            f"{DOCKERFILE.relative_to(ROOT)} has no digest-pinned `FROM odoo:<major>@sha256:...`"
        )
    return {"image": match.group(1), "major_version": match.group(2)}


def oca_pin() -> dict[str, str] | None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    match = re.search(r"server-auth\.git.*?checkout\s+([0-9a-f]{40})", text, re.S)
    if not match:
        return None
    return {"repository": "OCA/server-auth", "commit": match.group(1), "addon": "auth_oidc"}


def bridge_contract() -> dict:
    if not CONTRACT.is_file():
        raise SystemExit(
            f"{CONTRACT.relative_to(ROOT)} is missing. "
            "Run `python3 tools/bridge_contract.py --write`."
        )
    raw = CONTRACT.read_bytes()
    contract = json.loads(raw)
    return {
        "name": contract["contract"],
        "version": contract["version"],
        "prefix": contract["prefix"],
        "endpoint_count": contract["endpoint_count"],
        # The digest binds the composed release record to an exact contract
        # file, so the control plane can prove which surface it was tested for.
        "sha256": hashlib.sha256(raw).hexdigest(),
        "provider_addons": contract["provider_addons"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="digest-pinned image reference")
    parser.add_argument("--output", help="write here instead of stdout")
    args = parser.parse_args()

    if not DIGEST_REF.match(args.image):
        print(
            f"--image must be digest pinned, got {args.image!r}. "
            "A tag is not an immutable deployment input.",
            file=sys.stderr,
        )
        return 1

    addons = installed_addons()
    if not addons:
        print("no addons found; refusing to publish metadata for an empty image", file=sys.stderr)
        return 1

    metadata = {
        "schema": "makersbrain.odoo.release.v1",
        "image": args.image,
        "source": {
            "repository": os.environ.get("GITHUB_REPOSITORY", "MakersBrain/mb-odoo-addons"),
            "commit": os.environ.get("GITHUB_SHA", ""),
            "ref": os.environ.get("GITHUB_REF", ""),
            "ci_run": (
                f"{os.environ.get('GITHUB_SERVER_URL', '')}/"
                f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/"
                f"{os.environ.get('GITHUB_RUN_ID', '')}"
                if os.environ.get("GITHUB_RUN_ID")
                else ""
            ),
        },
        "odoo": odoo_base(),
        "oca_dependency": oca_pin(),
        "bridge_contract": bridge_contract(),
        "addon_count": len(addons),
        "addons": addons,
    }

    rendered = json.dumps(metadata, indent=2) + "\n"
    if args.output:
        output = pathlib.Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.output} ({len(addons)} addons)")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
