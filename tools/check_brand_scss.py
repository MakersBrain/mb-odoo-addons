#!/usr/bin/env python3
"""Verify Odoo's checked-in token projection matches @makersbrain/ui exactly."""

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECTION = ROOT / "addons/mb_brand/static/src/scss/mb_tokens.scss"
PACKAGE = "@makersbrain/ui"


def resolve(subpath: str) -> pathlib.Path | None:
    script = f'process.stdout.write(require.resolve("{PACKAGE}/{subpath}"))'
    try:
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(
            f"cannot resolve {PACKAGE}/{subpath}; run `npm ci` in {ROOT}",
            file=sys.stderr,
        )
        return None
    return pathlib.Path(result.stdout)


def main() -> int:
    upstream = resolve("adapters/odoo.scss")
    if upstream is None:
        return 1

    expected = upstream.read_bytes()
    actual = PROJECTION.read_bytes()
    if actual != expected:
        package_json = resolve("package.json")
        version = (
            json.loads(package_json.read_text())["version"]
            if package_json is not None
            else "unknown"
        )
        print(
            f"{PROJECTION.relative_to(ROOT)} does not match "
            f"{PACKAGE}@{version}/adapters/odoo.scss.\n"
            "Copy the published projection into the addon before committing.",
            file=sys.stderr,
        )
        return 1

    package_json = resolve("package.json")
    version = (
        json.loads(package_json.read_text())["version"] if package_json is not None else "unknown"
    )
    print(f"Odoo token projection matches {PACKAGE}@{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
