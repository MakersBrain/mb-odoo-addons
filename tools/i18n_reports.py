#!/usr/bin/env python3
"""Render every custom report under an English and a French user.

The catalogue gates prove a report's text is translated in the database. They do
not prove the report still renders once it is, which is a different failure: a
French string that breaks a QWeb attribute, a translated template that no longer
parses, a PDF that comes back empty.

    uv run --no-project --with polib python tools/i18n_reports.py DB

For every report this asserts that the HTML renders and the PDF starts with
%PDF, in both languages. Where the report has a document to render, it also
asserts catalogue-to-render correspondence: every `msgid` from the addon's own
`fr.po` that appears in the English render must appear as its `msgstr` in the
French one. That is the property that matters — not that the two renders differ,
but that they differ in exactly the way the catalogue says they should.

A report whose model has no record cannot be rendered with content. Rather than
assert nothing and call it a pass, this prints what it could not check and says
so in the summary.

Record data is never asserted: product, partner and customer content may
legitimately be English in a French report.
"""

from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
from pathlib import Path

try:
    import polib
except ImportError:  # pragma: no cover
    sys.exit(
        "polib is missing. Run this through uv:\n"
        "  uv run --no-project --with polib python tools/i18n_reports.py DB"
    )

REPO = Path(__file__).resolve().parent.parent
CONTAINER_DEFAULT = "mb-odoo-web"

# Minimal records for models that have none in a demo-less database, so the
# document body renders and the catalogue assertion has something to bite on.
# Deliberately small: this is a rendering probe, not a fixture library, and
# everything it creates is rolled back.
PROBES = {
    "mb.commercial.operation": [
        ("res.partner", "partner_id", {"name": "i18n render probe"}),
        (None, None, {"name": "i18n render probe",
                      "planned_start": "2026-01-05", "planned_end": "2026-01-06"}),
    ],
}

SCRIPT_TEMPLATE = r'''
import re

CATALOGUES = json.loads(r"""__CATALOGUES__""")
PROBES = json.loads(r"""__PROBES__""")

reports = env["ir.actions.report"].sudo().search([])
own = []
for report in reports:
    data = env["ir.model.data"].sudo().search(
        [("model", "=", "ir.actions.report"), ("res_id", "=", report.id)], limit=1)
    if data and (data.module.startswith("mb_") or data.module.startswith("l10n_fr_micro")):
        own.append((data.module, f"{data.module}.{data.name}", report))

TAGS = re.compile(r"<[^>]+>")


def probe_records(model_name):
    """Create the smallest record that makes the document body render."""
    recipe = PROBES.get(model_name)
    if not recipe:
        return None
    values = {}
    for helper_model, field, helper_values in recipe:
        if helper_model:
            values[field] = env[helper_model].sudo().create(helper_values).id
        else:
            values.update(helper_values)
    return env[model_name].sudo().create(values)


failures, skipped = [], []
asserted_pairs = 0
reports_asserted = 0

for module, xmlid, report in own:
    model = env[report.model] if report.model in env else None
    records = model.sudo().search([], limit=1) if model is not None else None
    probed = False
    if (records is None or not records) and model is not None:
        try:
            records = probe_records(report.model)
            probed = records is not None
        except Exception as exc:
            skipped.append(f"{xmlid}: could not build a probe record ({type(exc).__name__})")
            records = None
    docids = records.ids if records else []

    rendered = {}
    for lang in ("en_US", "fr_FR"):
        try:
            body, _ = report.with_context(lang=lang).sudo()._render_qweb_html(
                report.report_name, docids)
            rendered[lang] = body.decode() if isinstance(body, bytes) else str(body)
        except Exception as exc:
            failures.append(f"{xmlid} html {lang}: {type(exc).__name__}: {exc}")

        try:
            pdf, _ = report.with_context(lang=lang).sudo()._render_qweb_pdf(
                report.report_name, docids)
            if not pdf.startswith(b"%PDF"):
                failures.append(f"{xmlid} pdf {lang}: not a PDF")
            elif len(pdf) < 1000:
                failures.append(f"{xmlid} pdf {lang}: {len(pdf)} bytes, suspiciously empty")
        except Exception as exc:
            failures.append(f"{xmlid} pdf {lang}: {type(exc).__name__}: {exc}")

    if not docids:
        skipped.append(f"{xmlid}: {report.model} has no record, body not rendered")
    elif "en_US" in rendered and "fr_FR" in rendered:
        english, french = rendered["en_US"], rendered["fr_FR"]
        catalogue = CATALOGUES.get(module, {})
        checked_here = 0
        for msgid, msgstr in catalogue.items():
            if len(msgid) < 15 or msgid == msgstr:
                continue
            if msgid in english:
                if msgstr not in french:
                    failures.append(
                        f"{xmlid}: {msgid[:45]!r} is in the English render but its French "
                        f"{msgstr[:45]!r} is not in the French one")
                else:
                    checked_here += 1
                if msgid in french:
                    failures.append(
                        f"{xmlid}: English {msgid[:45]!r} survives untranslated in the "
                        f"French render")
        asserted_pairs += checked_here
        if checked_here:
            reports_asserted += 1
        else:
            skipped.append(f"{xmlid}: rendered, but no catalogue term appears in the body")
        if probed:
            print(f"REPORT PROBE {xmlid}: rendered with a synthetic {report.model}")

env.cr.rollback()

for entry in skipped:
    print("REPORT SKIP " + entry)
for failure in failures:
    print("REPORT FAIL " + failure)
print(
    f"REPORT SUMMARY {len(own)} reports rendered as HTML and PDF in both languages; "
    f"{reports_asserted} with catalogue assertions covering {asserted_pairs} term(s); "
    f"{len(skipped)} not assertable; {len(failures)} failures"
)
'''


def catalogues() -> dict[str, dict[str, str]]:
    """msgid to French, per addon, for the terms a report could contain."""
    result: dict[str, dict[str, str]] = {}
    for path in sorted(glob.glob(str(REPO / "addons" / "*" / "i18n" / "fr.po"))):
        module = Path(path).parent.parent.name
        entries = {}
        for entry in polib.pofile(path):
            if entry.obsolete or not entry.msgstr.strip() or entry.msgid_plural:
                continue
            # Only view terms can appear in a rendered report.
            if any("ir.ui.view" in reference for reference, _ in entry.occurrences):
                entries[entry.msgid] = entry.msgstr
        if entries:
            result[module] = entries
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("database")
    parser.add_argument("--container", default=CONTAINER_DEFAULT)
    args = parser.parse_args()

    script = "import json\n" + (
        SCRIPT_TEMPLATE
        .replace("__CATALOGUES__", json.dumps(catalogues()).replace('"""', '\\"\\"\\"'))
        .replace("__PROBES__", json.dumps(PROBES))
    )

    result = subprocess.run(
        [
            "docker", "exec", "-i", args.container,
            "odoo", "shell", "-c", "/etc/odoo/odoo.conf", "-d", args.database,
            "--no-http", "--log-level=error",
        ],
        input=script,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    interesting = [
        line for line in output.splitlines()
        if line.startswith(("REPORT FAIL", "REPORT SUMMARY", "REPORT SKIP", "REPORT PROBE"))
    ]
    if not interesting:
        print(output[-4000:], file=sys.stderr)
        print("the shell produced no summary; see the output above", file=sys.stderr)
        return 1
    for line in interesting:
        print(line)
    return 1 if any(line.startswith("REPORT FAIL") for line in interesting) else 0


if __name__ == "__main__":
    raise SystemExit(main())
