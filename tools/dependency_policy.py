#!/usr/bin/env python3
"""Validate addon imports and build the admitted offline Python payload."""

from __future__ import annotations

import argparse
import ast
import importlib
import importlib.metadata
import json
import pathlib
import platform
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
ADDONS = ROOT / "addons"
DEPENDENCIES = ROOT / "dependencies"
LOCK = DEPENDENCIES / "python-requirements.lock"
INVENTORY = DEPENDENCIES / "inventory.json"
WHEELHOUSE = DEPENDENCIES / "wheelhouse"
LOCK_ENTRY = re.compile(r"^[A-Za-z0-9_.-]+==[^\s;]+(?:\s+--hash=sha256:[0-9a-f]{64})+$")
FORBIDDEN_FILES = {"sitecustomize.py", "usercustomize.py"}
XML_ID_ATTRIBUTES = {"action", "groups", "parent", "ref", "t-call", "t-inherit"}
EVAL_REF = re.compile(r"\bref\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)\.")


def addon_manifests():
    for path in sorted(ADDONS.glob("*/__manifest__.py")):
        yield path, ast.literal_eval(path.read_text(encoding="utf-8"))


def absolute_imports():
    found = set()
    for path in ADDONS.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".", 1)[0])
    return found


def xml_module_references(addon_dir, known_modules):
    """Return known modules whose XML IDs/templates are used by an add-on."""
    found = set()
    for path in addon_dir.rglob("*.xml"):
        root = ET.parse(path).getroot()
        for element in root.iter():
            for attribute, value in element.attrib.items():
                if attribute in XML_ID_ATTRIBUTES:
                    for token in value.split(","):
                        module, separator, _identifier = token.strip().lstrip("!").partition(".")
                        if separator and module in known_modules:
                            found.add(module)
                found.update(
                    module for module in EVAL_REF.findall(value) if module in known_modules
                )
    return found


def check_direct_xml_dependencies(manifests):
    known_modules = set(manifests)
    for manifest in manifests.values():
        known_modules.update(manifest.get("depends", []))
    violations = []
    for addon, manifest in manifests.items():
        allowed = {addon, "base", *manifest.get("depends", [])}
        missing = xml_module_references(ADDONS / addon, known_modules) - allowed
        if missing:
            violations.append(f"{addon}: {sorted(missing)}")
    if violations:
        raise ValueError(
            "XML references modules absent from direct depends: " + "; ".join(violations)
        )


def locked_packages():
    packages = []
    for raw in LOCK.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not LOCK_ENTRY.fullmatch(line):
            raise ValueError(f"unhashed or unpinned lock entry: {line}")
        packages.append(line.split("==", 1)[0].lower().replace("_", "-"))
    return packages


def check(runtime=False):
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    extension = inventory["extension_packages"]
    collisions = {
        item["import"]
        for item in extension
        if item["import"] in sys.stdlib_module_names
        or item["import"] == "odoo"
        or item["import"] in inventory["runtime_imports"]
    }
    if collisions:
        raise ValueError(f"extension top-level namespace collision: {sorted(collisions)}")
    locked = locked_packages()
    declared_extension = sorted(
        item["distribution"].lower().replace("_", "-") for item in extension
    )
    if locked != declared_extension:
        raise ValueError("extension package inventory does not exactly match the lock")

    manifests = {path.parent.name: manifest for path, manifest in addon_manifests()}
    declared_manifest_imports = set()
    for manifest in manifests.values():
        declared_manifest_imports.update(
            manifest.get("external_dependencies", {}).get("python", [])
        )
    providers = set(inventory["runtime_imports"])
    providers.update(item["import"] for item in extension)
    missing_declarations = declared_manifest_imports - providers
    if missing_declarations:
        raise ValueError(
            f"manifest dependencies absent from inventory: {sorted(missing_declarations)}"
        )

    local = {path.name for path in ADDONS.iterdir() if path.is_dir()}
    allowed = set(sys.stdlib_module_names) | local | {"odoo"}
    undeclared = absolute_imports() - allowed - providers
    if undeclared:
        raise ValueError(f"undeclared top-level imports: {sorted(undeclared)}")

    check_direct_xml_dependencies(manifests)

    for path in WHEELHOUSE.iterdir():
        if path.name == ".gitkeep":
            continue
        if not path.is_file() or path.suffix != ".whl":
            raise ValueError(f"unexpected wheelhouse entry: {path.name}")

    if runtime:
        implementation = sys.implementation.name
        abi = f"cp{sys.version_info.major}{sys.version_info.minor}"
        expected = inventory["python"]
        if implementation != expected["implementation"] or abi != expected["abi"]:
            raise ValueError(f"runtime Python mismatch: {implementation}/{abi}")
        architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(
            platform.machine(), platform.machine()
        )
        if f"linux/{architecture}" not in expected["platforms"]:
            raise ValueError(f"runtime target platform linux/{architecture} is not admitted")
        for module, item in inventory["runtime_imports"].items():
            importlib.import_module(module)
            actual = importlib.metadata.version(item["distribution"])
            if actual != item["version"]:
                raise ValueError(
                    f"{item['distribution']} version {actual} != admitted {item['version']}"
                )
    return inventory


def build(target):
    inventory = check(runtime=True)
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--require-hashes",
            "--no-compile",
            "--no-deps",
            "--find-links",
            str(WHEELHOUSE),
            "--target",
            str(target),
            "-r",
            str(LOCK),
        ],
        check=True,
    )
    for path in target.rglob("*"):
        if path.name in FORBIDDEN_FILES or path.suffix == ".pth":
            raise ValueError(f"forbidden Python payload file: {path.relative_to(target)}")
        if path.is_symlink():
            raise ValueError(f"Python payload link is forbidden: {path.relative_to(target)}")
    scripts = target / "bin"
    if scripts.exists() and any(scripts.iterdir()):
        raise ValueError("extension dependencies must not install console scripts")
    for library in target.rglob("*.so"):
        result = subprocess.run(["ldd", str(library)], capture_output=True, check=False, text=True)
        if result.returncode or "not found" in result.stdout + result.stderr:
            raise ValueError(f"native dependency closure failed: {library.relative_to(target)}")
    expected = {
        item["distribution"].lower().replace("_", "-") for item in inventory["extension_packages"]
    }
    installed = {
        path.name.rsplit("-", 1)[0].lower().replace("_", "-") for path in target.glob("*.dist-info")
    }
    if installed != expected:
        raise ValueError(f"installed dependency inventory mismatch: {sorted(installed)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--build", type=pathlib.Path)
    args = parser.parse_args()
    if args.build:
        build(args.build)
    else:
        check(runtime=args.runtime)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
