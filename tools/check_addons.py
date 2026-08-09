#!/usr/bin/env python3
"""Static checks an Odoo install would only fail on much later, or not at all.

Everything here runs without a database, without Odoo importable and in well
under a second, which is the point: an addon that is going to fail should fail
in the lint lane and not eight minutes into a container build.

Checks, and why each one exists:

* **Manifest parses as a literal.** Odoo reads `__manifest__.py` with
  `ast.literal_eval`, so a manifest that runs code is not a manifest. Catching
  this here gives a file and a line instead of an import error.
* **Required keys and their types.** A missing `license` is an unlicensed
  module; a `depends` that is a string rather than a list installs one
  character at a time.
* **`version` is present and Odoo-shaped.** `19.0.x.y.z`. Odoo compares
  versions as strings when deciding whether to run a migration, so an addon
  without one never migrates, silently.
* **Every path in `data` and `assets` exists.** Odoo raises on a missing data
  file at install; a missing asset path merely produces a bundle that is
  quietly short of a file, which is worse.
* **Declared dependencies resolve.** Either to another addon in this repository
  or to a name on the known-core list. A typo here surfaces at install as
  "module not found" with no indication of who asked for it.
* **XML parses.** Odoo will tell you this too, after standing up a database.
* **`ir.model.access.csv` has the right header and a group or an explicit
  blank.** A rule with no group applies to every user, which is occasionally
  intended and usually not, so it has to be written as an empty column rather
  than a short row.
* **The dependency graph is acyclic.** Odoo detects this; it does so with a
  recursion error.

Exit status is 1 if anything failed, so it drops straight into CI or a
pre-commit hook.
"""

from __future__ import annotations

import ast
import csv
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ADDONS = Path(__file__).resolve().parent.parent / "addons"

REQUIRED_KEYS = {
    "name": str,
    "version": str,
    "license": str,
    "depends": list,
}

VERSION_RE = re.compile(r"^19\.0\.\d+\.\d+\.\d+$")

ACCESS_HEADER = [
    "id", "name", "model_id:id", "group_id:id",
    "perm_read", "perm_write", "perm_create", "perm_unlink",
]

# Core Odoo 19 Community addons this repository depends on, plus the OCA modules
# vendored by tools/vendor-oca.sh. Not the full core list — only what is
# actually depended on, so an unexpected new dependency is worth a look rather
# than waved through.
KNOWN_EXTERNAL = {
    "account", "account_edi_ubl_cii", "account_payment", "base", "l10n_fr_account",
    "maintenance", "mail", "mrp", "payment", "point_of_sale", "product", "purchase",
    "purchase_stock",
    "sale", "sale_stock", "stock", "uom", "web",
    # OCA, vendored and optional.
    "sale_order_global_stock_route", "stock_restrict_lot", "stock_picking_filter_lot",
    "stock_inventory", "stock_picking_report_valued", "sale_invoice_frequency",
}

failures: list[str] = []


def fail(addon: str, message: str) -> None:
    failures.append(f"{addon}: {message}")


def check_manifest(path: Path) -> dict | None:
    addon = path.parent.name
    try:
        manifest = ast.literal_eval(path.read_text())
    except (ValueError, SyntaxError) as exc:
        fail(addon, f"__manifest__.py is not a literal dict: {exc}")
        return None
    if not isinstance(manifest, dict):
        fail(addon, "__manifest__.py does not evaluate to a dict")
        return None

    for key, kind in REQUIRED_KEYS.items():
        if key not in manifest:
            fail(addon, f"manifest has no {key!r}")
        elif not isinstance(manifest[key], kind):
            fail(addon, f"manifest {key!r} is {type(manifest[key]).__name__}, expected {kind.__name__}")

    version = manifest.get("version")
    if isinstance(version, str) and not VERSION_RE.match(version):
        fail(addon, f"version {version!r} is not 19.0.x.y.z")

    return manifest


def check_declared_paths(addon_dir: Path, manifest: dict) -> None:
    addon = addon_dir.name
    for rel in manifest.get("data", []) + manifest.get("demo", []):
        if not (addon_dir / rel).is_file():
            fail(addon, f"data file {rel} does not exist")

    for bundle, entries in (manifest.get("assets") or {}).items():
        for entry in entries:
            # An entry may be a bare path or an ('after', path, path) tuple.
            paths = [entry] if isinstance(entry, str) else list(entry)[1:]
            for spec in paths:
                if not isinstance(spec, str) or "*" in spec:
                    continue  # globs are Odoo's to resolve
                prefix = f"{addon}/"
                if not spec.startswith(prefix):
                    continue  # another addon's file; its own check covers it
                if not (addon_dir / spec[len(prefix):]).is_file():
                    fail(addon, f"asset {spec} in bundle {bundle} does not exist")


def check_xml(addon_dir: Path) -> None:
    for xml_path in sorted(addon_dir.rglob("*.xml")):
        try:
            ET.parse(xml_path)
        except ET.ParseError as exc:
            fail(addon_dir.name, f"{xml_path.relative_to(addon_dir)} is not well-formed: {exc}")


def check_access_csv(addon_dir: Path) -> None:
    path = addon_dir / "security" / "ir.model.access.csv"
    if not path.is_file():
        return
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        fail(addon_dir.name, "ir.model.access.csv is empty")
        return
    if rows[0] != ACCESS_HEADER:
        fail(addon_dir.name, f"ir.model.access.csv header is {rows[0]}, expected {ACCESS_HEADER}")
        return
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(ACCESS_HEADER):
            fail(addon_dir.name,
                 f"ir.model.access.csv line {number} has {len(row)} columns, expected {len(ACCESS_HEADER)}")


def check_graph(manifests: dict[str, dict]) -> None:
    for addon, manifest in manifests.items():
        for dep in manifest.get("depends", []):
            if dep not in manifests and dep not in KNOWN_EXTERNAL:
                fail(addon, f"depends on {dep!r}, which is neither in this repository "
                            f"nor on the known-external list in tools/check_addons.py")

    # Depth-first cycle detection. Odoo finds these too, by exhausting the stack.
    state: dict[str, int] = {}

    def visit(addon: str, trail: list[str]) -> None:
        if state.get(addon) == 2:
            return
        if state.get(addon) == 1:
            fail(addon, f"dependency cycle: {' -> '.join([*trail, addon])}")
            return
        state[addon] = 1
        for dep in manifests.get(addon, {}).get("depends", []):
            if dep in manifests:
                visit(dep, [*trail, addon])
        state[addon] = 2

    for addon in manifests:
        visit(addon, [])


def main() -> int:
    if not ADDONS.is_dir():
        print(f"no addons directory at {ADDONS}", file=sys.stderr)
        return 1

    manifests: dict[str, dict] = {}
    addon_dirs = sorted(p for p in ADDONS.iterdir() if (p / "__manifest__.py").is_file())

    for addon_dir in addon_dirs:
        manifest = check_manifest(addon_dir / "__manifest__.py")
        if manifest is None:
            continue
        manifests[addon_dir.name] = manifest
        check_declared_paths(addon_dir, manifest)
        check_xml(addon_dir)
        check_access_csv(addon_dir)

    check_graph(manifests)

    if failures:
        for line in failures:
            print(f"FAIL  {line}", file=sys.stderr)
        print(f"\n{len(failures)} problem(s) in {len(addon_dirs)} addon(s)", file=sys.stderr)
        return 1

    print(f"OK  {len(addon_dirs)} addons: manifests, data paths, assets, XML, "
          f"access rules and dependency graph")
    return 0


if __name__ == "__main__":
    sys.exit(main())
