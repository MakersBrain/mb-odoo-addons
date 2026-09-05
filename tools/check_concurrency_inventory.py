#!/usr/bin/env python3
"""Verify that the focused concurrency tests remain in the full server suite."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = {
    "l10n_fr_micro_urssaf/tests/test_urssaf_declaration.py": ("TestUrssafConcurrency", 4),
    "mb_ceramics_firing/tests/test_firing_concurrency.py": ("TestFiringConcurrency", 2),
    "mb_ceramics_workflow/tests/test_board_content_concurrency.py": (
        "TestBoardContentConcurrency",
        4,
    ),
    "mb_commercial_operations_depot/tests/test_contract_concurrency.py": (
        "TestDepotContractConcurrency",
        3,
    ),
    "mb_commercial_operations_stock/tests/test_commercial_stock.py": (
        "TestCommercialStockConcurrency",
        1,
    ),
    "mb_control_bridge/tests/test_receipt_concurrency.py": (
        "TestOperationReceiptConcurrency",
        1,
    ),
    "mb_label/tests/test_label.py": ("TestLabelTemplateConcurrency", 3),
}
EXPECTED_TOTAL = 18


def decorator_tags(node: ast.ClassDef) -> set[str]:
    tags: set[str] = set()
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        function = decorator.func
        if not (isinstance(function, ast.Name) and function.id == "tagged"):
            continue
        tags.update(
            argument.value
            for argument in decorator.args
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        )
    return tags


def imported_modules(init_path: Path) -> set[str]:
    tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    imported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            imported.update(alias.name for alias in node.names)
    return imported


def main() -> int:
    errors: list[str] = []
    total = 0
    for relative, (class_name, expected_count) in INVENTORY.items():
        path = ROOT / "addons" / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        classes = [
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
        ]
        if len(classes) != 1:
            errors.append(f"{relative}: expected exactly one {class_name}")
            continue
        node = classes[0]
        tags = decorator_tags(node)
        if "post_install" not in tags or "-at_install" not in tags:
            errors.append(f"{relative}:{class_name}: must be tagged post_install and -at_install")
        methods = [
            child.name
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and child.name.startswith("test_")
        ]
        if len(methods) != expected_count:
            errors.append(
                f"{relative}:{class_name}: discovered {len(methods)} tests, expected {expected_count}"
            )
        total += len(methods)

        module_name = path.stem
        if module_name not in imported_modules(path.parent / "__init__.py"):
            errors.append(f"{relative}: tests/__init__.py does not import {module_name}")

    if total != EXPECTED_TOTAL:
        errors.append(f"concurrency inventory contains {total} tests, expected {EXPECTED_TOTAL}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OK: {EXPECTED_TOTAL} concurrency tests across {len(INVENTORY)} invariant groups")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
