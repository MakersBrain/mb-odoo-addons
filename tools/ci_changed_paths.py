#!/usr/bin/env python3
"""Classify changed paths into conservative CI lanes.

Paths are read from stdin, one per line.  The output is suitable for appending
directly to ``GITHUB_OUTPUT`` and is deliberately fail-open for unknown files in
areas that can affect an Odoo runtime.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import PurePosixPath

LANES = ("server", "upgrade", "frontend", "i18n", "lifecycle")
FULL_EVENTS = {"workflow_dispatch"}
FULL_FILES = {
    "Makefile",
    "docker-compose.yml",
    "pyproject.toml",
    "tools/ci_changed_paths.py",
    "tools/test_ci_changed_paths.py",
}
FULL_PREFIXES = (".github/workflows/", "config/", "dependencies/", "deploy/", "fixtures/")


def _all_lanes() -> set[str]:
    return set(LANES)


def _classify_addon(path: PurePosixPath) -> set[str]:
    parts = path.parts
    if len(parts) < 3:
        return _all_lanes()

    relative = parts[2:]
    name = relative[-1]
    suffix = path.suffix.lower()
    area = relative[0]

    if name == "__manifest__.py":
        return _all_lanes()
    if area == "migrations":
        return _all_lanes()
    if area == "i18n" and suffix in {".po", ".pot"}:
        return {"i18n"}
    if area == "static":
        lanes = {"frontend"}
        if suffix in {".js", ".ts", ".xml"}:
            lanes.add("i18n")
        return lanes

    if suffix == ".py":
        lanes = {"server", "i18n"}
        if area in {"models", "security", "data"} or len(relative) == 1:
            lanes.update({"upgrade", "lifecycle"})
        return lanes

    if suffix == ".xml":
        lanes = {"server", "frontend", "i18n"}
        if area in {"data", "demo", "security"}:
            lanes.update({"upgrade", "lifecycle"})
        return lanes

    if suffix == ".csv":
        lanes = {"server"}
        if area in {"data", "demo", "security"}:
            lanes.update({"upgrade", "lifecycle", "i18n"})
        return lanes

    # Add-on-local documentation is still allowed to alter manifests or generated
    # metadata indirectly, so an unrecognised add-on path is intentionally full.
    return _all_lanes()


def _classify_tool(path: str) -> set[str]:
    name = PurePosixPath(path).name.lower()
    if name in {"ci_changed_paths.py", "test_ci_changed_paths.py"}:
        return _all_lanes()
    if "uninstall" in name:
        return {"lifecycle"}
    if "migration" in name or "upgrade" in name:
        return {"server", "upgrade", "lifecycle"}
    if "asset" in name or "hoot" in name or "brand" in name:
        return {"frontend"}
    if "i18n" in name or name.startswith("check_po"):
        return {"i18n"}
    if name in {
        "check_addons.py",
        "ci_extension.sh",
        "dependency_policy.py",
        "extension_manifest.py",
        "extension_manifest.sh",
    }:
        return _all_lanes()
    return _all_lanes()


def classify(
    paths: Iterable[str], *, event: str, ref: str = "", uncertain: bool = False
) -> dict[str, bool]:
    """Return full/server/upgrade/frontend/i18n/lifecycle decisions."""

    cleaned = [path.strip().replace("\\", "/") for path in paths if path.strip()]
    force_full = uncertain or event in FULL_EVENTS or (event == "push" and ref == "refs/heads/main")
    if event not in {"pull_request", "push", *FULL_EVENTS}:
        force_full = True
    if event == "pull_request" and not cleaned:
        force_full = True

    selected: set[str] = set()
    for raw_path in cleaned:
        path = PurePosixPath(raw_path)
        normalized = path.as_posix()
        if normalized == "FORCE_ALL":
            force_full = True
            continue
        if normalized in FULL_FILES or normalized.startswith(FULL_PREFIXES):
            force_full = True
        elif normalized.startswith("addons/"):
            addon_lanes = _classify_addon(path)
            selected.update(addon_lanes)
            if (
                addon_lanes == _all_lanes()
                and path.name != "__manifest__.py"
                and "migrations" not in path.parts
            ):
                force_full = True
        elif normalized.startswith("tools/"):
            tool_lanes = _classify_tool(normalized)
            selected.update(tool_lanes)
            if tool_lanes == _all_lanes():
                force_full = True
        elif normalized.startswith("docs/migration-matrix."):
            selected.add("upgrade")
        elif normalized in {"package.json", "package-lock.json"}:
            selected.add("frontend")
        elif normalized.startswith("scripts/") and path.suffix == ".py":
            selected.update({"server", "i18n"})

    if force_full:
        selected = _all_lanes()
    return {"full": force_full, **{lane: lane in selected for lane in LANES}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--ref", default="")
    parser.add_argument("--uncertain", action="store_true")
    args = parser.parse_args()

    result = classify(
        sys.stdin,
        event=args.event,
        ref=args.ref,
        uncertain=args.uncertain,
    )
    for name, enabled in result.items():
        print(f"{name}={'true' if enabled else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
