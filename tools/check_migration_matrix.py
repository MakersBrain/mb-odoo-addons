"""Validate that the documented migration matrix matches candidate source."""

import ast
import json
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "docs" / "migration-matrix.json"
PHASE_FILENAMES = {
    "pre": "pre-migrate.py",
    "post": "post-migrate.py",
    "end": "end-migrate.py",
}


class MatrixEntry(TypedDict):
    module: str
    installed_version: str
    target_version: str
    directory: str
    phase: str
    postcondition: str


def version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def main() -> None:
    entries: list[MatrixEntry] = json.loads(MATRIX_PATH.read_text())
    if not entries:
        raise SystemExit("migration matrix must not be empty")
    errors: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in entries:
        key = (entry["module"], entry["directory"], entry["phase"])
        if key in seen:
            errors.append(f"duplicate matrix entry: {key}")
        seen.add(key)
        manifest_path = ROOT / "addons" / entry["module"] / "__manifest__.py"
        manifest = ast.literal_eval(manifest_path.read_text())
        if manifest["version"] != entry["target_version"]:
            errors.append(
                f"{entry['module']}: manifest {manifest['version']} != matrix target "
                f"{entry['target_version']}"
            )
        if version_tuple(entry["installed_version"]) >= version_tuple(entry["target_version"]):
            errors.append(f"{entry['module']}: installed version must precede target")
        phase_file = PHASE_FILENAMES.get(entry["phase"])
        if not phase_file:
            errors.append(f"{entry['module']}: unsupported phase {entry['phase']}")
            continue
        migration_path = manifest_path.parent / "migrations" / entry["directory"] / phase_file
        if not migration_path.is_file():
            errors.append(f"missing migration: {migration_path.relative_to(ROOT)}")
        if not entry.get("postcondition", "").strip():
            errors.append(f"{entry['module']}: postcondition is required")
    if errors:
        raise SystemExit("\n".join(errors))
    module_count = len({entry["module"] for entry in entries})
    print(f"OK  migration matrix: {len(entries)} phases across {module_count} addons")


if __name__ == "__main__":
    main()
