#!/usr/bin/env python3
"""Independently parse every catalogue and check its header.

    python3 tools/check_po_parse.py

This is the second opinion on the translation catalogues. `check_i18n.py` is the
strict one -- it knows about Odoo's exporter, the sentinels and the placeholders
gettext cannot see, because Odoo does not emit the `#, python-format` flags
gettext would need. This file deliberately knows none of that. It parses each
catalogue with a different implementation and checks the header is well formed,
so a file that our own parser happens to accept because of a shared assumption
still has to satisfy something that does not share it.

Odoo's exporter omits the flags gettext relies on for placeholder validation,
so `check_i18n.py` owns that check while this independent polib pass validates
catalogue syntax and headers.
"""

from __future__ import annotations

import pathlib
import sys

try:
    import polib
except ImportError:  # pragma: no cover - the lane installs it
    print("polib is missing. Run: pip install polib", file=sys.stderr)
    raise SystemExit(1) from None

ROOT = pathlib.Path(__file__).resolve().parent.parent
ADDONS = ROOT / "addons"

# A catalogue with no Content-Type cannot state its charset, and one without a
# plural rule makes every plural lookup in Odoo fall back to the singular.
REQUIRED_HEADERS = ("Content-Type", "Plural-Forms")


def catalogues() -> list[pathlib.Path]:
    return sorted([*ADDONS.glob("*/i18n/*.po"), *ADDONS.glob("*/i18n/*.pot")])


def check(path: pathlib.Path) -> list[str]:
    relative = path.relative_to(ROOT)
    try:
        catalogue = polib.pofile(str(path))
    except OSError as error:
        return [f"{relative}: cannot be parsed: {error}"]
    except Exception as error:  # polib raises bare ValueError/SyntaxError variants
        return [f"{relative}: cannot be parsed: {error}"]

    # Header checks apply to translations only, matching what msgfmt was asked
    # to do here before: `--check-header` ran over addons/*/i18n/fr.po and never
    # over the templates. Extending it to .pot would fail the build on
    # mb_dbfilter_gateway's empty template -- a module with no translatable
    # strings -- which is a pre-existing condition and not this lane's business
    # to start enforcing by accident.
    if path.suffix != ".po":
        return []

    problems = []
    metadata = catalogue.metadata or {}
    for header in REQUIRED_HEADERS:
        if header not in metadata:
            problems.append(f"{relative}: header is missing {header}")

    charset = metadata.get("Content-Type", "")
    if charset and "charset=" not in charset:
        problems.append(f"{relative}: Content-Type does not state a charset: {charset!r}")

    return problems


def main() -> int:
    files = catalogues()
    if not files:
        print("no catalogues found; the glob is wrong", file=sys.stderr)
        return 1

    problems: list[str] = []
    for path in files:
        problems.extend(check(path))

    if problems:
        print(f"{len(problems)} catalogue problem(s):\n", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    translations = sum(1 for f in files if f.suffix == ".po")
    print(
        f"{len(files)} catalogues parse; "
        f"{translations} translation(s) carry a well-formed header"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
