#!/usr/bin/env python3
"""Fail closed unless every CI lane selected by the classifier succeeded."""

from __future__ import annotations

import os
from collections.abc import Mapping

LANES = {
    "server": ("SERVER_SELECTED", "SERVER_RESULT"),
    "upgrade": ("UPGRADE_SELECTED", "UPGRADE_RESULT"),
    "uninstall": ("LIFECYCLE_SELECTED", "UNINSTALL_RESULT"),
    "frontend": ("FRONTEND_SELECTED", "FRONTEND_RESULT"),
    "i18n": ("I18N_SELECTED", "I18N_RESULT"),
}


def validate(changes_result: str, static_result: str, values: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    if changes_result != "success":
        errors.append(f"changed-path classification finished as {changes_result or 'missing'}")
    if static_result != "success":
        errors.append(f"static checks finished as {static_result or 'missing'}")

    for lane, (selected_key, result_key) in LANES.items():
        selected = values.get(selected_key, "")
        result = values.get(result_key, "")
        if selected == "true":
            if result != "success":
                errors.append(f"{lane} was selected but finished as {result or 'missing'}")
        elif selected == "false":
            if result not in {"skipped", "success"}:
                errors.append(f"{lane} was not selected but finished as {result or 'missing'}")
        else:
            errors.append(f"{lane} has invalid classifier output {selected or 'missing'}")
    return errors


def main() -> int:
    errors = validate(os.getenv("CHANGES_RESULT", ""), os.getenv("STATIC_RESULT", ""), os.environ)
    if errors:
        for error in errors:
            print(f"::error::{error}")
        return 1
    print("All selected CI lanes succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
