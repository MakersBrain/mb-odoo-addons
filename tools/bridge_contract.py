#!/usr/bin/env python3
"""Generate and check the /mb_control/v1 provider contract.

    python3 tools/bridge_contract.py            # print the contract
    python3 tools/bridge_contract.py --write    # write contracts/mb_control_v1.json
    python3 tools/bridge_contract.py --check    # fail if the committed file drifts

This repository is the *provider* of the `/mb_control/v1` bridge: every endpoint
under that prefix is served by an addon here, and `MakersBrain/mb-control-plane`
is its only client. Once the two live in separate repositories, nothing stops a
route being renamed, losing `auth="public"`, or gaining a method without the
client noticing, so the route table is extracted from the source and committed
as a contract that CI diffs on every change.

The extraction is static: the module is parsed with `ast`, never imported, so
this runs without Odoo installed and cannot execute addon code.

What this file is and is not
----------------------------
It is the authoritative *surface*: which paths exist, which methods they accept,
how they authenticate and whether they keep a session. Changing any of those is
a contract change and shows up as a diff here.

It is not yet the full contract of migration plan section 4.2: request and
response schemas, idempotency-key semantics, payload size bounds and error-body
shapes are not derivable from the route decorator and still have to be written
by hand. Adding them is the remaining work for 4.2; the surface is the part that
can be generated and therefore the part that should never drift silently.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ADDONS = ROOT / "addons"
CONTRACT = ROOT / "contracts" / "mb_control_v1.json"
PREFIX = "/mb_control/v1"


def literal(node: ast.AST):
    """Best-effort constant folding; returns None for anything dynamic."""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def route_decorators(tree: ast.Module):
    """Yield (function_name, decorator_call) for every @http.route/@route."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            name = (
                func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name)
                else None
            )
            if name == "route":
                yield node.name, decorator


def endpoints_in(path: pathlib.Path, addon: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for handler, decorator in route_decorators(tree):
        routes = literal(decorator.args[0]) if decorator.args else None
        if routes is None:
            for keyword in decorator.keywords:
                if keyword.arg == "route":
                    routes = literal(keyword.value)
        if isinstance(routes, str):
            routes = [routes]
        if not routes:
            continue

        options = {
            keyword.arg: literal(keyword.value)
            for keyword in decorator.keywords
            if keyword.arg
        }
        for route in routes:
            if not isinstance(route, str) or not route.startswith(PREFIX):
                continue
            methods = options.get("methods") or ["POST"]
            yield {
                "path": route,
                "methods": sorted(methods),
                "auth": options.get("auth", "user"),
                "type": options.get("type", "http"),
                "csrf": bool(options.get("csrf", True)),
                "save_session": bool(options.get("save_session", True)),
                "addon": addon,
                "handler": f"{path.relative_to(ROOT)}::{handler}",
            }


def addon_version(addon: str) -> str | None:
    manifest = ADDONS / addon / "__manifest__.py"
    if not manifest.is_file():
        return None
    tree = ast.parse(manifest.read_text(encoding="utf-8"), filename=str(manifest))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            data = literal(node)
            if isinstance(data, dict) and "version" in data:
                return data["version"]
    return None


def build() -> dict:
    endpoints: list[dict] = []
    for controller in sorted(ADDONS.glob("*/controllers/*.py")):
        addon = controller.relative_to(ADDONS).parts[0]
        endpoints.extend(endpoints_in(controller, addon))

    endpoints.sort(key=lambda e: (e["path"], e["methods"]))

    duplicates = sorted(
        {
            e["path"]
            for e in endpoints
            if sum(1 for other in endpoints if other["path"] == e["path"]) > 1
        }
    )

    providers = sorted({e["addon"] for e in endpoints})
    return {
        "contract": "mb_control",
        "version": "v1",
        "prefix": PREFIX,
        "description": (
            "Private control-plane bridge served by this repository's addons. "
            "Surface only: request and response schemas are not yet part of "
            "this contract. See tools/bridge_contract.py."
        ),
        "provider_addons": {addon: addon_version(addon) for addon in providers},
        "duplicate_paths": duplicates,
        "endpoint_count": len(endpoints),
        "endpoints": endpoints,
    }


def render(contract: dict) -> str:
    return json.dumps(contract, indent=2, sort_keys=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="write the contract file")
    group.add_argument("--check", action="store_true", help="fail if it drifts")
    args = parser.parse_args()

    contract = build()

    if not contract["endpoints"]:
        print("no /mb_control/v1 routes found; the extractor is broken", file=sys.stderr)
        return 1
    if contract["duplicate_paths"]:
        print(
            "the same bridge path is declared more than once: "
            f"{contract['duplicate_paths']}",
            file=sys.stderr,
        )
        return 1

    rendered = render(contract)

    if args.write:
        CONTRACT.parent.mkdir(parents=True, exist_ok=True)
        CONTRACT.write_text(rendered, encoding="utf-8")
        print(f"wrote {CONTRACT.relative_to(ROOT)} ({contract['endpoint_count']} endpoints)")
        return 0

    if args.check:
        if not CONTRACT.is_file():
            print(
                f"{CONTRACT.relative_to(ROOT)} is missing. "
                "Run `python3 tools/bridge_contract.py --write`.",
                file=sys.stderr,
            )
            return 1
        committed = CONTRACT.read_text(encoding="utf-8")
        if committed != rendered:
            print(
                f"{CONTRACT.relative_to(ROOT)} is out of date. The bridge surface "
                "changed.\n\nThis is a contract change: mb-control-plane is the "
                "client of every path below. Follow the compatibility-first "
                "sequence in the migration plan -- ship the backward-compatible "
                "provider change first, or add a new versioned endpoint and "
                "retire the old one after the supported window.\n\n"
                "Then run `python3 tools/bridge_contract.py --write`.",
                file=sys.stderr,
            )
            import difflib

            diff = difflib.unified_diff(
                committed.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                fromfile="committed",
                tofile="generated",
            )
            sys.stderr.writelines(diff)
            return 1
        print(f"bridge contract is current ({contract['endpoint_count']} endpoints)")
        return 0

    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
