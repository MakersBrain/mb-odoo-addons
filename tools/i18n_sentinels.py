#!/usr/bin/env python3
"""Bilingual runtime sentinels.

A catalogue that parses is not a catalogue that renders. These sentinels pick a
few owned UI strings per addon — a menu, a field label, an error message — and
assert that Odoo actually returns the French for a `fr_FR` user and the English
source for an `en_US` one, against a real database with the addons installed.

    # refresh docs/i18n/sentinels.json from the committed catalogues
    uv run --no-project --with polib python tools/i18n_sentinels.py --generate

    # assert them against a database
    uv run --no-project --with polib python tools/i18n_sentinels.py --check DB

Sentinels target interface chrome the addons own. They never assert translated
record data: product names, partner names and customer content are business
records that may legitimately be English, French, or neither.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    import polib
except ImportError:  # pragma: no cover
    sys.exit(
        "polib is missing. Run this through uv:\n"
        "  uv run --no-project --with polib python tools/i18n_sentinels.py --generate"
    )

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "docs" / "i18n" / "sentinels.json"
CONTAINER_DEFAULT = "makersbrain-odoo-web"

# How many sentinels to keep per addon. Enough to cover more than one surface,
# few enough that the manifest stays reviewable by hand.
PER_MODULE = 3


def occurrences(entry) -> list[str]:
    joined = []
    for reference, line in entry.occurrences:
        joined.append(f"{reference}:{line}" if line else reference)
    return joined


def classify(entry) -> tuple[str, str] | None:
    """Return (surface, locator) for an entry worth using as a sentinel."""
    for occurrence in occurrences(entry):
        if occurrence.startswith("model:ir.ui.menu,name:"):
            return ("menu", occurrence.split(":", 2)[2].rstrip(":0"))
        if occurrence.startswith("model:ir.actions.act_window,name:"):
            return ("action", occurrence.split(":", 2)[2].rstrip(":0"))
        if occurrence.startswith("model:ir.model.fields,field_description:"):
            return ("field", occurrence.split(":", 2)[2].rstrip(":0"))
    comment = entry.comment or ""
    if "odoo-python" in comment:
        return ("python", "")
    if "odoo-javascript" in comment:
        return ("javascript", "")
    return None


def inherited_terms() -> set[str]:
    """Strings that came from upstream Odoo, not from this repository."""
    reference = REPO / "docs" / "i18n" / "odoo_fr_reference.json"
    if not reference.exists():
        return set()
    return set(json.loads(reference.read_text(encoding="utf-8")))


def worth_asserting(entry, surface: str, inherited: set[str]) -> bool:
    if not entry.msgstr.strip() or entry.msgid_plural:
        return False
    if entry.msgstr.strip() == entry.msgid.strip():
        return False
    if len(entry.msgid) < 6 or len(entry.msgid) > 120:
        return False
    if "<" in entry.msgid or "%" in entry.msgid or "{" in entry.msgid:
        return False
    # A sentinel must test a string this repository owns. "Company" and
    # "Activities" arrive on every model that inherits mail; asserting them
    # would prove that upstream Odoo is translated, which is not in question.
    if entry.msgid in inherited:
        return False
    return True


def generate() -> int:
    sentinels = []
    inherited = inherited_terms()
    for module_dir in sorted((REPO / "addons").iterdir()):
        po_path = module_dir / "i18n" / "fr.po"
        if not po_path.exists():
            continue
        chosen: dict[str, dict] = {}
        for entry in polib.pofile(str(po_path)):
            if entry.obsolete:
                continue
            classified = classify(entry)
            if not classified:
                continue
            surface, locator = classified
            if not worth_asserting(entry, surface, inherited):
                continue
            # One per surface first, so a module with fifty fields and one error
            # message does not end up with three field sentinels.
            if surface in chosen:
                continue
            chosen[surface] = {
                "module": module_dir.name,
                "surface": surface,
                "locator": locator,
                "msgid": entry.msgid,
                "fr": entry.msgstr,
            }
            if len(chosen) >= PER_MODULE:
                break
        sentinels.extend(chosen.values())

    MANIFEST.write_text(json.dumps(sentinels, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    modules = len({s["module"] for s in sentinels})
    print(f"{len(sentinels)} sentinels across {modules} addon(s) -> {MANIFEST.relative_to(REPO)}")
    return 0


# Runs inside `odoo shell`, where `env` is injected. Kept as a string because
# that is the only interface `odoo shell` offers.
CHECK_SCRIPT = r'''
import json, sys
from odoo.tools.translate import code_translations

sentinels = json.loads(SENTINELS_JSON)
failures = []

for item in sentinels:
    module, surface, locator = item["module"], item["surface"], item["locator"]
    source, expected = item["msgid"], item["fr"]

    if surface in ("python", "javascript"):
        if surface == "python":
            catalogue = code_translations.get_python_translations(module, "fr_FR")
        else:
            catalogue = code_translations.get_web_translations(module, "fr_FR")
            catalogue = {m["id"]: m["string"] for m in catalogue.get("messages", [])}
        actual = catalogue.get(source)
    else:
        record = env.ref(locator, raise_if_not_found=False)
        if record is None:
            failures.append(f"{module}: {locator} does not exist")
            continue
        field = {"menu": "name", "action": "name", "field": "field_description"}[surface]
        actual = record.with_context(lang="fr_FR")[field]
        english = record.with_context(lang="en_US")[field]
        if english != source:
            failures.append(
                f"{module}: {locator} English is {english!r}, catalogue source is {source!r}"
            )

    if actual is None:
        failures.append(f"{module}: no French for {source!r} ({surface})")
    elif actual != expected:
        failures.append(f"{module}: {source!r} rendered {actual!r}, expected {expected!r}")

for failure in failures:
    print("SENTINEL FAIL " + failure)
print(f"SENTINEL SUMMARY {len(sentinels) - len(failures)}/{len(sentinels)} passed")
'''


def check(database: str, container: str) -> int:
    if not MANIFEST.exists():
        print(f"{MANIFEST.relative_to(REPO)} does not exist; run --generate first", file=sys.stderr)
        return 1
    sentinels = json.loads(MANIFEST.read_text(encoding="utf-8"))
    script = f"SENTINELS_JSON = {json.dumps(json.dumps(sentinels, ensure_ascii=False))}\n" + CHECK_SCRIPT

    result = subprocess.run(
        [
            "docker", "exec", "-i", container,
            "odoo", "shell", "-c", "/etc/odoo/odoo.conf", "-d", database,
            "--no-http", "--log-level=warn",
        ],
        input=script,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    failures = [line for line in output.splitlines() if line.startswith("SENTINEL FAIL")]
    summary = [line for line in output.splitlines() if line.startswith("SENTINEL SUMMARY")]

    for failure in failures:
        print(failure)
    if summary:
        print(summary[-1])
    else:
        print(output[-4000:], file=sys.stderr)
        print("the shell produced no summary; see the output above", file=sys.stderr)
        return 1
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--generate", action="store_true", help="rebuild the manifest from the catalogues")
    parser.add_argument("--check", metavar="DB", help="assert the manifest against a database")
    parser.add_argument("--container", default=CONTAINER_DEFAULT, help="Odoo container name")
    args = parser.parse_args()

    if args.generate:
        return generate()
    if args.check:
        return check(args.check, args.container)
    parser.error("choose --generate or --check DB")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
