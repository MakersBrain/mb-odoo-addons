#!/usr/bin/env python3
"""Merge `i18n/<module>.pot` into `i18n/fr.po` without losing existing work.

This is the `msgmerge` step of the workflow, plus one thing msgmerge cannot do:
entries whose msgid already has an official Odoo French rendering — the mail,
activity, and ORM boilerplate that every custom model inherits — are prefilled
from `docs/i18n/odoo_fr_reference.json` so the same field label does not get a
different French word in each addon.

    uv run --no-project --with polib python tools/i18n_seed_po.py mb_depot

Existing translations always win over the reference, and nothing already
translated is ever overwritten or dropped. Entries the POT no longer contains
are removed, so run this only against a POT exported from the current source.

Options:
    --no-prefill   only merge; leave every new entry empty
    --report       print how many entries are still untranslated and exit
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import polib
except ImportError:  # pragma: no cover
    sys.exit(
        "polib is missing. Run this through uv:\n"
        "  uv run --no-project --with polib python tools/i18n_seed_po.py MODULE"
    )

REPO = Path(__file__).resolve().parent.parent
REFERENCE = REPO / "docs" / "i18n" / "odoo_fr_reference.json"

HEADER = """Project-Id-Version: Odoo Server 19.0
Report-Msgid-Bugs-To:
Last-Translator:
Language-Team: French
Language: fr
MIME-Version: 1.0
Content-Type: text/plain; charset=UTF-8
Content-Transfer-Encoding: 8bit
Plural-Forms: nplurals=2; plural=(n > 1);
"""


def key(entry) -> tuple[str, str, str]:
    return (entry.msgctxt or "", entry.msgid, entry.msgid_plural or "")


def seed(module: str, prefill: bool, report_only: bool) -> int:
    i18n = REPO / "addons" / module / "i18n"
    pot_path = i18n / f"{module}.pot"
    po_path = i18n / "fr.po"

    if not pot_path.exists():
        print(f"{module}: no {pot_path.relative_to(REPO)} — export the POT first", file=sys.stderr)
        return 1

    pot = polib.pofile(str(pot_path))
    existing: dict[tuple[str, str, str], Any] = {}
    if po_path.exists():
        for entry in polib.pofile(str(po_path)):
            if not entry.obsolete:
                existing[key(entry)] = entry

    reference = {}
    if prefill and REFERENCE.exists():
        reference = json.loads(REFERENCE.read_text(encoding="utf-8"))

    catalogue = polib.POFile()
    catalogue.header = (
        "Translation of Odoo Server.\n"
        "This file contains the translation of the following modules:\n"
        f"\t* {module}\n"
    )
    catalogue.metadata = dict(
        line.split(": ", 1)
        for line in HEADER.strip().splitlines()
        if ": " in line or line.endswith(": ")
    )
    # Preserve the two headers whose value is legitimately empty.
    catalogue.metadata.setdefault("Report-Msgid-Bugs-To", "")
    catalogue.metadata.setdefault("Last-Translator", "")

    kept = filled = empty = 0
    for source in pot:
        if source.obsolete:
            continue
        entry = polib.POEntry(
            msgid=source.msgid,
            msgid_plural=source.msgid_plural,
            msgctxt=source.msgctxt,
            occurrences=source.occurrences,
            comment=source.comment,
            tcomment=source.tcomment,
            flags=[f for f in source.flags if f != "fuzzy"],
        )
        previous = existing.get(key(source))
        translated = False

        if source.msgid_plural:
            values = {0: "", 1: ""}
            if previous is not None:
                for index in (0, 1):
                    values[index] = previous.msgstr_plural.get(index, "")
            entry.msgstr_plural = values
            translated = all(values[i].strip() for i in (0, 1))
        else:
            value = previous.msgstr if previous is not None else ""
            if not value.strip() and prefill:
                value = reference.get(source.msgid, "")
            entry.msgstr = value
            translated = bool(value.strip())

        if previous is not None and translated:
            kept += 1
        elif translated:
            filled += 1
        else:
            empty += 1
        catalogue.append(entry)

    if report_only:
        print(f"{module}: {kept + filled} translated, {empty} untranslated, {len(catalogue)} total")
        return 0

    dropped = sorted(k[1] for k in set(existing) - {key(e) for e in catalogue})
    po_path.parent.mkdir(parents=True, exist_ok=True)
    catalogue.save(str(po_path))

    print(
        f"{module}: {len(catalogue)} entries "
        f"({kept} kept, {filled} prefilled from Odoo, {empty} to translate)"
    )
    if dropped:
        print(f"  dropped {len(dropped)} entry(ies) no longer in the POT:")
        for msgid in dropped[:10]:
            print(f"    {msgid[:70]}")
        if len(dropped) > 10:
            print(f"    ... and {len(dropped) - 10} more")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("modules", nargs="+", metavar="MODULE")
    parser.add_argument("--no-prefill", action="store_true", help="leave every new entry empty")
    parser.add_argument("--report", action="store_true", help="report counts without writing")
    args = parser.parse_args()

    status = 0
    for module in args.modules:
        status |= seed(module, prefill=not args.no_prefill, report_only=args.report)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
