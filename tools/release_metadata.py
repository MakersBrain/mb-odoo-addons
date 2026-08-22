#!/usr/bin/env python3
"""Compose release metadata for one qualified runtime/extension platform pair."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "contracts" / "mb_control_v1.json"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
DIGEST_REF = re.compile(r"^[^\s@]+@(sha256:[0-9a-f]{64})$")


def canonical_digest(value):
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(rendered).hexdigest()}"


def read_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def checked_digest(value, name):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ValueError(f"{name} is not a sha256 digest")
    return value


def checked_ref(value, name):
    match = DIGEST_REF.fullmatch(value or "")
    if not match:
        raise ValueError(f"{name} is not a digest-pinned OCI reference")
    return match.group(1)


def bridge_contract():
    raw = CONTRACT.read_bytes()
    contract = json.loads(raw)
    return {
        "name": contract["contract"],
        "version": contract["version"],
        "prefix": contract["prefix"],
        "endpoint_count": contract["endpoint_count"],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "provider_addons": contract["provider_addons"],
    }


def selected_runtime(runtime, qualified):
    checked_ref(runtime["official_source_ref"], "runtime source")
    checked_ref(runtime["deployment_ref"], "runtime deployment reference")
    checked_digest(runtime["subject_digest"], "runtime subject")
    platform = next(
        (
            item
            for item in runtime["platforms"]
            if item["platform"] == qualified["platform"]
            and item["manifest_digest"] == qualified["manifest_digest"]
        ),
        None,
    )
    if not platform or platform["config_digest"] != qualified["config_digest"]:
        raise ValueError("payload qualification does not exactly match the runtime descriptor")
    expected = {
        "official_source_ref": runtime["official_source_ref"],
        "deployment_ref": runtime["deployment_ref"],
        "subject_digest": runtime["subject_digest"],
        "subject_kind": runtime["subject_kind"],
        "manifest_digest": platform["manifest_digest"],
        "config_digest": platform["config_digest"],
        "platform": platform["platform"],
    }
    if expected != qualified:
        raise ValueError("qualified_odoo_runtime is not the selected complete runtime identity")
    return platform


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension-ref", required=True)
    parser.add_argument(
        "--extension-subject-kind", choices=("image_index", "image_manifest"), required=True
    )
    parser.add_argument("--extension-manifest-digest", required=True)
    parser.add_argument("--extension-config-digest", required=True)
    parser.add_argument("--payload-manifest", required=True)
    parser.add_argument("--runtime-descriptor", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--qualification-result", choices=("passed",), default="passed")
    parser.add_argument("--output")
    args = parser.parse_args()

    try:
        subject_digest = checked_ref(args.extension_ref, "extension reference")
        extension_manifest_digest = checked_digest(
            args.extension_manifest_digest, "extension platform manifest"
        )
        extension_config_digest = checked_digest(
            args.extension_config_digest, "extension configuration"
        )
        payload = read_json(args.payload_manifest)
        runtime = read_json(args.runtime_descriptor)
        evidence = read_json(args.evidence)
        required_evidence = {"signature_bundle", "sbom", "vulnerability_report"}
        if set(evidence) != required_evidence:
            raise ValueError(f"extension evidence keys must be exactly {sorted(required_evidence)}")
        selected_runtime(runtime, payload["qualified_odoo_runtime"])
        checked_digest(payload["payload_digest"], "payload tree")
        for name, item in evidence.items():
            if not isinstance(item, dict):
                raise ValueError(f"evidence {name} is not an object")
            subject = checked_ref(item["reference"], f"evidence {name} reference")
            checked_digest(item["subject_digest"], f"evidence {name} subject digest")
            checked_digest(item["sha256_digest"], f"evidence {name} content digest")
            if subject != item["subject_digest"]:
                raise ValueError(f"evidence {name} reference/subject mismatch")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    bridge = bridge_contract()
    extension_platform = {
        "platform": payload["platform"],
        "manifest_digest": extension_manifest_digest,
        "config_digest": extension_config_digest,
        "payload_digest": payload["payload_digest"],
        "python_implementation": payload["python"]["implementation"],
        "python_abi": payload["python"]["abi"],
        "python_platform": f"linux_{payload['platform']['architecture'].replace('amd64', 'x86_64').replace('arm64', 'aarch64')}",
        "lock_file_digest": f"sha256:{payload['lock_sha256']}",
        "dependency_inventory_digest": f"sha256:{payload['dependency_inventory_sha256']}",
        "qualified_odoo_runtime": payload["qualified_odoo_runtime"],
        "signature": evidence["signature_bundle"],
        "sbom": evidence["sbom"],
        "vulnerability_report": evidence["vulnerability_report"],
    }
    pair_input = {
        "runtime": payload["qualified_odoo_runtime"],
        "extension": {
            "subject_digest": subject_digest,
            "manifest_digest": extension_manifest_digest,
            "config_digest": extension_config_digest,
        },
        "payload_digest": payload["payload_digest"],
        "bridge_contract_digest": f"sha256:{bridge['sha256']}",
        "addon_versions": payload["addon_versions"],
        "qualification_result": args.qualification_result,
    }
    metadata = {
        "schema": "makersbrain.odoo.extension-release.v2",
        "source": {
            "repository": os.environ.get("GITHUB_REPOSITORY", "MakersBrain/mb-odoo-addons"),
            "commit": payload["source_commit"],
            "ref": os.environ.get("GITHUB_REF", ""),
        },
        "odoo_runtime": runtime,
        "extension_bundle": {
            "oci_ref": args.extension_ref,
            "subject_digest": subject_digest,
            "subject_kind": args.extension_subject_kind,
            "platforms": [extension_platform],
        },
        "payload_tree_digest": payload["payload_digest"],
        "lock_file_digest": f"sha256:{payload['lock_sha256']}",
        "dependency_inventory_digest": f"sha256:{payload['dependency_inventory_sha256']}",
        "locked_dependencies": payload["locked_dependencies"],
        "addon_count": len(payload["addon_versions"]),
        "addons": payload["addon_versions"],
        "bridge_contract": bridge,
        "bridge_contract_digest": f"sha256:{bridge['sha256']}",
        "evidence_object_digest": canonical_digest(evidence),
        "pair_qualifications": [
            {
                "platform": payload["platform"],
                "odoo_manifest_digest": payload["qualified_odoo_runtime"]["manifest_digest"],
                "extension_manifest_digest": extension_manifest_digest,
                "payload_digest": payload["payload_digest"],
                "qualification_digest": canonical_digest(pair_input),
                "qualification_result": args.qualification_result,
            }
        ],
    }
    rendered = json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = pathlib.Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
