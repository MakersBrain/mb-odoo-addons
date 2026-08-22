#!/usr/bin/env python3
"""Build and verify the immutable extension payload manifest."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import pathlib
import stat

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIGEST_PREFIX = "sha256:"


def require_digest(value, name):
    if not value.startswith(DIGEST_PREFIX) or len(value) != 71:
        raise ValueError(f"{name} must be a sha256 OCI digest")
    int(value.removeprefix(DIGEST_PREFIX), 16)
    return value


def addon_versions(addons):
    versions = {}
    for manifest_path in sorted(addons.glob("*/__manifest__.py")):
        manifest = ast.literal_eval(manifest_path.read_text(encoding="utf-8"))
        versions[manifest_path.parent.name] = manifest["version"]
    if not versions:
        raise ValueError("extension contains no addons")
    return versions


def tree_inventory(roots):
    entries = []
    for logical_root, root in roots:
        for path in sorted(root.rglob("*")):
            relative = pathlib.PurePosixPath(logical_root, path.relative_to(root).as_posix())
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not (
                stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)
            ):
                raise ValueError(f"unsupported payload entry: {relative}")
            if stat.S_ISDIR(metadata.st_mode):
                continue
            entries.append(
                {
                    "path": str(relative),
                    "size": metadata.st_size,
                    "mode": stat.S_IMODE(metadata.st_mode),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return entries, f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=pathlib.Path, required=True)
    parser.add_argument("--runtime-source-ref", required=True)
    parser.add_argument("--runtime-deployment-ref", required=True)
    parser.add_argument("--runtime-subject-digest", required=True)
    parser.add_argument(
        "--runtime-subject-kind", choices=("image_index", "image_manifest"), required=True
    )
    parser.add_argument("--runtime-manifest-digest", required=True)
    parser.add_argument("--runtime-config-digest", required=True)
    parser.add_argument("--os", default="linux")
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--variant", default="")
    parser.add_argument("--source-commit", default="")
    args = parser.parse_args()

    addons = args.payload / "addons"
    python = args.payload / "python"
    entries, payload_digest = tree_inventory((("addons", addons), ("python", python)))
    lock = ROOT / "dependencies" / "python-requirements.lock"
    dependency_inventory = ROOT / "dependencies" / "inventory.json"
    bridge = ROOT / "contracts" / "mb_control_v1.json"
    locked = json.loads(dependency_inventory.read_text(encoding="utf-8"))["extension_packages"]
    platform = {"os": args.os, "architecture": args.architecture}
    if args.variant:
        platform["variant"] = args.variant
    manifest = {
        "schema": "makersbrain.odoo.extension-payload.v1",
        "payload_digest": payload_digest,
        "source_commit": args.source_commit,
        "platform": platform,
        "python": {"implementation": "cpython", "abi": "cp312"},
        "qualified_odoo_runtime": {
            "official_source_ref": args.runtime_source_ref,
            "deployment_ref": args.runtime_deployment_ref,
            "subject_digest": require_digest(args.runtime_subject_digest, "runtime subject"),
            "subject_kind": args.runtime_subject_kind,
            "manifest_digest": require_digest(args.runtime_manifest_digest, "runtime manifest"),
            "config_digest": require_digest(args.runtime_config_digest, "runtime configuration"),
            "platform": platform,
        },
        "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "dependency_inventory_sha256": hashlib.sha256(
            dependency_inventory.read_bytes()
        ).hexdigest(),
        "locked_dependencies": [
            {"name": item["distribution"], "version": item["version"]} for item in locked
        ],
        "bridge_contract_sha256": hashlib.sha256(bridge.read_bytes()).hexdigest(),
        "addon_versions": addon_versions(addons),
        "files": entries,
    }
    output = args.payload / "manifest.json"
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(payload_digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
