# Translation workflow

English is the source language and lives in the code. French lives in
`addons/<module>/i18n/fr.po`. `addons/<module>/i18n/<module>.pot` is the
extracted English source catalogue and is committed so source-string drift is
reviewable.

Shared files are maintained centrally so terminology and exceptions remain
consistent across addons:

| File | Purpose |
|---|---|
| `docs/i18n/fr_glossary.md` | The one approved French term per English term. |
| `docs/i18n/odoo_fr_reference.json` | Official Odoo French for inherited boilerplate. |
| `docs/i18n/i18n_allowlist.json` | Reviewed identical-translation and stale-entry exceptions. |
| `tools/check_i18n.py` | The gate. |
| `tools/i18n_seed_po.py` | POT into fr.po, non-destructively. |
| `tools/i18n.sh` | Scratch database, install, upgrade, export, import. |
| `tools/i18n_sentinels.py` | Picks owned UI strings per addon and asserts they render in French. |
| `tools/i18n_reports.py` | Renders every report as HTML and PDF in both languages. |
| `tools/i18n_integration.sh` | The end-to-end run over all addons at once. |
| `docs/i18n/sentinels.json` | The generated sentinel manifest. |

## The loop

Work one addon at a time, in dependency order.

### 1. Fix the source first

Extraction only sees what is marked. Before exporting anything:

- wrap user-facing Python text in `_()` (`from odoo import _`), and module-level
  text in `_lt()`;
- wrap user-facing JavaScript text in `_t()`
  (`import { _t } from "@web/core/l10n/translation";`);
- replace f-strings and concatenation in translated text with a single static
  msgid and named placeholders: `_("Cannot ship %(product)s.", product=name)`,
  never `_(f"Cannot ship {name}.")`;
- move French prose out of source into the catalogue: the source string becomes
  English, the French becomes its `msgstr`;
- mark protocol and data regions in QWeb with `t-translation="off"`;
- make sure every translated XML file is listed in the manifest and every record
  has a stable XML ID;
- fix misspelled or ambiguous English before it is translated.

Never mark: protocol commands, printer opcodes, barcode payloads, log messages,
diagnostic codes, XML IDs, domains, field technical names, API endpoints, JSON
keys, SKU values, provider identifiers, file paths, URLs, or test fixtures.

### 2. Build the scratch database

Use a dedicated disposable database for the modules being translated:

```bash
tools/i18n.sh setup "$WORK_DB" MODULE_A MODULE_B
```

That creates the database, loads `fr_FR` *before* the addons are installed — so
the install path imports the catalogues the way a deployment does — and installs
the modules.

### 3. Upgrade, then export

Database-backed view and model terms must match the current source, so upgrade
before every export:

```bash
tools/i18n.sh refresh "$WORK_DB" MODULE_A MODULE_B   # upgrade + export POT
```

This writes `addons/<module>/i18n/<module>.pot`.

### 4. Merge the POT into the catalogue

```bash
uv run --no-project --with polib python tools/i18n_seed_po.py MODULE_A MODULE_B
```

Existing translations are kept, inherited Odoo boilerplate is prefilled from the
reference, entries the POT no longer has are dropped, and everything else is left
empty for you.

### 5. Translate every entry

Follow `fr_glossary.md`. Preserve placeholders, plural forms, newlines, and
markup exactly. No fuzzy entries survive review. Do not translate code samples,
protocol commands, XML IDs, URLs, or variable names inside technical text.

### 6. Check

```bash
uv run --no-project --with polib python tools/check_i18n.py --all --module MODULE_A
```

`--all` runs both the catalogue gate and the source scanner. A finding the
scanner reports that is genuinely not user-facing is a signal to look again, not
to suppress. When it really is a false positive — a barcode symbology name, a
device model, a table of protocol constants — record it in
`docs/i18n/i18n_allowlist.json`:

- `identical`: msgids whose French is legitimately the same as the English;
- `stale`: catalogue entries kept although the POT no longer has them;
- `source.texts`: exact literals the scanner should stop flagging;
- `source.files`: path prefixes that hold data rather than interface.

Every exception needs review and a narrow, documented match.

### 7. Import and verify at runtime

```bash
tools/i18n.sh import "$WORK_DB" MODULE_A MODULE_B
tools/i18n.sh upgrade "$WORK_DB" MODULE_A MODULE_B
```

Python and web translation bundles are cached, so restart the Odoo process
before browser-testing. Verify at least one backend view, one report, and — where
the addon has them — one POS screen and one client action in both languages.

### 8. Bump the version

Bump the addon's `version` in `__manifest__.py` once its translation work is
complete, following the repository's Odoo 19 version policy.

## Integration

For repository-wide verification, run one clean database with all addons
installed together:

```bash
tools/i18n_integration.sh
```

That drops and rebuilds `mb_i18n_integration`, loads `fr_FR` before installing
anything, installs and upgrades all addons, re-exports every POT and fails on any
drift, imports every `fr.po` with overwrite, runs the repository test suite, and
asserts the sentinels. Regenerate the sentinel manifest first when catalogues
have changed:

```bash
uv run --no-project --with polib python tools/i18n_sentinels.py --generate
```

A sentinel is one owned UI string per surface per addon — a menu, an action, a
field label, a Python error, a JavaScript message — checked in both directions:
French for a `fr_FR` context, and the catalogue's English source for `en_US`.
There is deliberately no "no English words anywhere" assertion: product names,
brands, and partner data may legitimately be English.

The report matrix renders every `ir.actions.report` this repository declares, as
HTML and as PDF, under both languages, and asserts catalogue-to-render
correspondence: a `msgid` from the addon's `fr.po` that appears in the English
render must appear as its `msgstr` in the French one, and must not survive
untranslated. A report whose model has no record in a demo-less database cannot
render a body; the tool creates a small synthetic record where a recipe exists in
its `PROBES` table, rolls it back, and names the reports it could not assert
rather than counting them as passes.

### What these gates do not cover

Worth knowing before trusting a green run:

- The Hoot browser suite. It needs an image with Chromium, which the `odoo:19`
  image is not, so the JavaScript catalogues are proven by extraction and by
  Python-side rendering, not by a browser.
- A live POS session with the SumUp and label extensions loaded together.
- Reports whose model has no record are asserted only as far as "renders and
  produces a valid PDF in both languages"; the integration summary names each
  body that could not be checked against its catalogue.
- Deployment to any shared environment, which remains a separate, authorised
  operation.
