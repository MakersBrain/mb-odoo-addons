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
* **QWeb output uses `t-out`.** Odoo 19 keeps `t-esc` as a deprecated alias;
  rejecting it here prevents new server and OWL templates from reintroducing
  the warning after the repository-wide migration.
* **Production JavaScript has no `console.log`.** Protocol data and customer
  identifiers must go through an explicit, redacting debug boundary.
* **Privileged integration services are private.** A bridge/capture method that
  calls `sudo`, installs modules, or exports personal data must not silently
  become reachable through generic ORM RPC.
* **Company-owned models have complete record-rule coverage.** ACLs are
  additive and record rules are default-allow, so every ACL-bearing group must
  be covered by a global or applicable company rule.
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

SENSITIVE_SERVICE_ADDONS = {
    "mb_control_bridge",
    "mb_email_bridge",
    "mb_inventory_capture",
    "mb_invoice_capture",
}
SENSITIVE_METHOD_CALLS = {
    "button_immediate_install",
    "button_install",
    "export_personal_data",
    "sudo",
}
# Intentional UI action: the transient migration wizard performs its own group
# check before its narrowly-scoped read and is meant to remain button-callable.
PUBLIC_SERVICE_METHOD_ALLOWLIST = {
    ("mb_inventory_capture", "stock_migration.py", "action_analyze"),
}

ACCESS_HEADER = [
    "id",
    "name",
    "model_id:id",
    "group_id:id",
    "perm_read",
    "perm_write",
    "perm_create",
    "perm_unlink",
]

# Core Odoo 19 Community addons this repository depends on, plus the OCA modules
# vendored by tools/vendor-oca.sh. Not the full core list — only what is
# actually depended on, so an unexpected new dependency is worth a look rather
# than waved through.
KNOWN_EXTERNAL = {
    "account",
    "account_edi_ubl_cii",
    "account_payment",
    "auth_oauth",
    "base",
    "l10n_fr_account",
    "fleet",
    "hr_expense",
    "hr_timesheet",
    "maintenance",
    "mail",
    "mrp",
    "mrp_account",
    "payment",
    "point_of_sale",
    "product",
    "product_expiry",
    "project",
    "project_hr_expense",
    "project_mrp",
    "project_purchase",
    "project_stock_account",
    "purchase",
    "purchase_stock",
    "resource",
    "sale_management",
    "sale_project",
    "sale_timesheet",
    "stock_account",
    "sale",
    "sale_stock",
    "stock",
    "uom",
    "web",
    "website_sale_stock",
    "website_sale_collect",
    "delivery",
    "website_sale",
    "stock_delivery",
    "delivery_mondialrelay",
    "website_sale_mondialrelay",
    # OCA, vendored and optional.
    "sale_order_global_stock_route",
    "stock_restrict_lot",
    "stock_picking_filter_lot",
    "stock_inventory",
    "stock_picking_report_valued",
    "sale_invoice_frequency",
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
            fail(
                addon,
                f"manifest {key!r} is {type(manifest[key]).__name__}, expected {kind.__name__}",
            )

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
                if not (addon_dir / spec[len(prefix) :]).is_file():
                    fail(addon, f"asset {spec} in bundle {bundle} does not exist")


def check_xml(addon_dir: Path) -> None:
    for xml_path in sorted(addon_dir.rglob("*.xml")):
        try:
            tree = ET.parse(xml_path)
        except ET.ParseError as exc:
            fail(addon_dir.name, f"{xml_path.relative_to(addon_dir)} is not well-formed: {exc}")
            continue
        if any("t-esc" in element.attrib for element in tree.iter()):
            fail(
                addon_dir.name,
                f"{xml_path.relative_to(addon_dir)} uses deprecated t-esc; use t-out",
            )


def check_javascript(addon_dir: Path) -> None:
    source = addon_dir / "static" / "src"
    if not source.is_dir():
        return
    for path in sorted(source.rglob("*.js")):
        if "console.log(" in path.read_text(encoding="utf-8"):
            fail(
                addon_dir.name,
                f"{path.relative_to(addon_dir)} uses console.log in production code",
            )


def check_sensitive_service_methods(addon_dir: Path) -> None:
    if addon_dir.name not in SENSITIVE_SERVICE_ADDONS:
        return
    for path in sorted((addon_dir / "models").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        methods = (
            node
            for class_node in tree.body
            if isinstance(class_node, ast.ClassDef)
            for node in class_node.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        for node in methods:
            if (
                node.name.startswith("_")
                or (
                    addon_dir.name,
                    path.name,
                    node.name,
                )
                in PUBLIC_SERVICE_METHOD_ALLOWLIST
            ):
                continue
            sensitive = any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in SENSITIVE_METHOD_CALLS
                for child in ast.walk(node)
            )
            if not sensitive:
                continue
            private = any(
                isinstance(decorator, ast.Attribute)
                and isinstance(decorator.value, ast.Name)
                and decorator.value.id == "api"
                and decorator.attr == "private"
                for decorator in node.decorator_list
            )
            if not private:
                fail(
                    addon_dir.name,
                    f"{path.relative_to(addon_dir)}:{node.lineno} privileged public method "
                    f"{node.name} lacks @api.private",
                )


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
            fail(
                addon_dir.name,
                f"ir.model.access.csv line {number} has {len(row)} columns, expected {len(ACCESS_HEADER)}",
            )


def _local_company_models(addon_dir: Path) -> set[str]:
    """Return concrete local model names that declare their own company_id."""
    result: set[str] = set()
    models_dir = addon_dir / "models"
    if not models_dir.is_dir():
        return result
    for path in sorted(models_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            if any(
                isinstance(base, ast.Attribute) and base.attr == "TransientModel"
                for base in class_node.bases
            ):
                continue
            model_name = None
            owns_company = False
            for node in class_node.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    if target.id == "_name" and isinstance(value, ast.Constant):
                        if isinstance(value.value, str):
                            model_name = value.value
                    elif target.id == "company_id" and isinstance(value, ast.Call):
                        function = value.func
                        owns_company = (
                            isinstance(function, ast.Attribute)
                            and isinstance(function.value, ast.Name)
                            and function.value.id == "fields"
                            and function.attr == "Many2one"
                        )
            if model_name and owns_company:
                result.add(model_name)
    return result


def _model_name_from_ref(reference: str, candidates: set[str] | None = None) -> str | None:
    external_id = reference.rsplit(".", 1)[-1]
    if not external_id.startswith("model_"):
        return None
    for model_name in candidates or ():
        if external_id == f"model_{model_name.replace('.', '_')}":
            return model_name
    return external_id.removeprefix("model_").replace("_", ".")


def _domain_has_company_boundary(expression: str) -> bool:
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except (SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Tuple, ast.List)) or len(node.elts) != 3:
            continue
        field, operator, value = node.elts
        if not (
            isinstance(field, ast.Constant)
            and field.value == "company_id"
            and isinstance(operator, ast.Constant)
        ):
            continue
        if (
            operator.value == "in" and isinstance(value, ast.Name) and value.id == "company_ids"
        ) or (operator.value == "=" and isinstance(value, ast.Name) and value.id == "company_id"):
            return True
    return False


def _qualify_xml_id(addon: str, reference: str) -> str:
    return reference if "." in reference else f"{addon}.{reference}"


def _rule_groups(field: ET.Element | None, addon: str) -> set[str]:
    if field is None:
        return set()
    groups = set()
    if reference := field.get("ref"):
        groups.add(_qualify_xml_id(addon, reference))
    expression = field.get("eval", "")
    try:
        tree = ast.parse(expression, mode="eval") if expression else None
    except SyntaxError:
        return groups
    if tree:
        for command in (node for node in ast.walk(tree) if isinstance(node, ast.Tuple)):
            if not command.elts or not isinstance(command.elts[0], ast.Constant):
                continue
            operation = command.elts[0].value
            value_nodes = command.elts[1:2] if operation == 4 else command.elts[2:3]
            if operation not in {4, 6}:
                continue
            for value_node in value_nodes:
                for node in ast.walk(value_node):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "ref"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                    ):
                        groups.add(_qualify_xml_id(addon, node.args[0].value))
    return groups


def _group_implications(manifests: dict[str, dict]) -> dict[str, set[str]]:
    implications: dict[str, set[str]] = {}
    for addon, manifest in manifests.items():
        addon_dir = ADDONS / addon
        for relative_path in [*manifest.get("data", []), *manifest.get("demo", [])]:
            path = addon_dir / relative_path
            if path.suffix != ".xml" or not path.is_file():
                continue
            root = ET.parse(path).getroot()
            for record in root.iter("record"):
                record_id = record.get("id")
                if record.get("model") != "res.groups" or not record_id:
                    continue
                group = _qualify_xml_id(addon, record_id)
                implied_field = next(
                    (
                        field
                        for field in record.findall("field")
                        if field.get("name") == "implied_ids"
                    ),
                    None,
                )
                implications.setdefault(group, set()).update(_rule_groups(implied_field, addon))
    return implications


def _implied_group_closure(group: str, implications: dict[str, set[str]]) -> set[str]:
    result = {group}
    pending = [group]
    while pending:
        current = pending.pop()
        for implied in implications.get(current, set()) - result:
            result.add(implied)
            pending.append(implied)
    return result


def _field_enabled(field: ET.Element | None) -> bool:
    if field is None:
        return True
    value = (field.get("eval") or field.text or "").strip().lower()
    return value not in {"0", "false"}


def check_company_rule_completeness(
    addon_dir: Path,
    manifest: dict,
    implications: dict[str, set[str]] | None = None,
) -> None:
    """Require company rules for every permission granted on local company models."""
    local_models = _local_company_models(addon_dir)
    if not local_models:
        return

    access_path = addon_dir / "security" / "ir.model.access.csv"
    if not access_path.is_file():
        return
    permissions = ACCESS_HEADER[4:]
    acl_grants: dict[str, dict[str, set[str]]] = {}
    with access_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            model_name = _model_name_from_ref(row.get("model_id:id", ""), local_models)
            if model_name not in local_models:
                continue
            group = row.get("group_id:id", "")
            granted = {
                permission.removeprefix("perm_")
                for permission in permissions
                if row.get(permission) == "1"
            }
            if granted:
                acl_grants.setdefault(model_name, {}).setdefault(group, set()).update(granted)

    rule_coverage: dict[str, dict[str, set[str]]] = {}
    global_coverage: dict[str, set[str]] = {}
    for relative_path in [*manifest.get("data", []), *manifest.get("demo", [])]:
        path = addon_dir / relative_path
        if path.suffix != ".xml" or not path.is_file():
            continue
        root = ET.parse(path).getroot()
        for record in root.iter("record"):
            if record.get("model") != "ir.rule":
                continue
            fields_by_name = {field.get("name"): field for field in record.findall("field")}
            model_field = fields_by_name.get("model_id")
            model_name = (
                _model_name_from_ref(model_field.get("ref", ""), local_models)
                if model_field is not None
                else None
            )
            domain_field = fields_by_name.get("domain_force")
            domain = (
                ""
                if domain_field is None
                else (domain_field.get("eval") or domain_field.text or "")
            )
            if model_name not in acl_grants or not _domain_has_company_boundary(domain):
                continue
            applies = {
                permission.removeprefix("perm_")
                for permission in permissions
                if _field_enabled(fields_by_name.get(permission))
            }
            groups = _rule_groups(fields_by_name.get("groups"), addon_dir.name)
            if groups:
                for group in groups:
                    rule_coverage.setdefault(model_name, {}).setdefault(group, set()).update(
                        applies
                    )
            else:
                global_coverage.setdefault(model_name, set()).update(applies)

    for model_name, acl_groups in sorted(acl_grants.items()):
        for group, granted in sorted(acl_groups.items()):
            applicable_groups = _implied_group_closure(group, implications or {})
            covered = set(global_coverage.get(model_name, set()))
            for applicable_group in applicable_groups:
                covered.update(rule_coverage.get(model_name, {}).get(applicable_group, set()))
            missing = sorted(granted - covered)
            if missing:
                label = group or "<all users>"
                fail(
                    addon_dir.name,
                    f"company-owned model {model_name} grants {', '.join(missing)} to "
                    f"{label} without an applicable company rule",
                )


def check_graph(manifests: dict[str, dict]) -> None:
    for addon, manifest in manifests.items():
        for dep in manifest.get("depends", []):
            if dep not in manifests and dep not in KNOWN_EXTERNAL:
                fail(
                    addon,
                    f"depends on {dep!r}, which is neither in this repository "
                    f"nor on the known-external list in tools/check_addons.py",
                )

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


def check_spec_versions(manifests: dict[str, dict]) -> None:
    """SPEC.md publishes a version table. Keep it honest.

    It drifted once already -- one row sat two minor versions behind its
    manifest -- and nothing noticed, because a stale documentation table
    breaks no test. Cheap to check, so check it.
    """
    spec = ADDONS.parent / "SPEC.md"
    if not spec.is_file():
        fail("SPEC.md", "is missing; addon version documentation cannot be verified")
        return
    published = dict(re.findall(r"`(\w+)` \| (\d[\d.]*)", spec.read_text(encoding="utf-8")))
    for addon, manifest in sorted(manifests.items()):
        version = manifest.get("version")
        if addon not in published:
            fail(addon, "is absent from the version table in SPEC.md")
        elif published[addon] != version:
            fail(
                addon,
                f"SPEC.md lists version {published[addon]}, but the manifest declares {version}",
            )
    for addon in sorted(set(published) - set(manifests)):
        fail(addon, "appears in the SPEC.md version table but has no manifest")


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
        check_javascript(addon_dir)
        check_sensitive_service_methods(addon_dir)
        check_access_csv(addon_dir)

    check_graph(manifests)
    implications = _group_implications(manifests)
    for addon, manifest in manifests.items():
        check_company_rule_completeness(ADDONS / addon, manifest, implications)
    check_spec_versions(manifests)

    if failures:
        for line in failures:
            print(f"FAIL  {line}", file=sys.stderr)
        print(f"\n{len(failures)} problem(s) in {len(addon_dirs)} addon(s)", file=sys.stderr)
        return 1

    print(
        f"OK  {len(addon_dirs)} addons: manifests, data paths, assets, XML, "
        f"access and company-rule coverage, dependency graph and SPEC.md versions"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
