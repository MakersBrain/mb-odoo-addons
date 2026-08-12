# Odoo 19 English/French Translation Plan

## Status

Draft for review. This document defines a parallel implementation plan; it does
not itself translate, import, deploy, or modify database translations.

## Objective

Make every installable custom addon in this repository production-ready in:

- English (`en_US`) as the canonical source language;
- French (`fr_FR`) through addon-local `i18n/fr.po` catalogs.

English must remain in source code, XML, QWeb, JavaScript, manifests, help text,
exceptions, reports, and emails. French prose must live in translation catalogs,
except for genuine legal names, brands, customer data, test fixtures, and
technical identifiers.

The work is complete only when both languages render correctly in the backend,
POS, OWL client actions, emails, and HTML/PDF reports—not merely when PO files
parse.

## Baseline

The repository contains 29 installable addon directories:

1. `l10n_fr_micro_enterprise`
2. `l10n_fr_micro_urssaf`
3. `mb_account_payment_sumup`
4. `mb_ai_bridge`
5. `mb_catalogue_sync`
6. `mb_ceramics_firing`
7. `mb_ceramics_workflow`
8. `mb_commercial_operations`
9. `mb_commercial_operations_depot`
10. `mb_commercial_operations_expense`
11. `mb_commercial_operations_fleet`
12. `mb_commercial_operations_mrp`
13. `mb_commercial_operations_pos`
14. `mb_commercial_operations_purchase`
15. `mb_commercial_operations_sale`
16. `mb_commercial_operations_stock`
17. `mb_commercial_operations_urssaf`
18. `mb_control_bridge`
19. `mb_dbfilter_gateway`
20. `mb_depot`
21. `mb_inventory_capture`
22. `mb_inventory_capture_catalogue`
23. `mb_invoice_capture`
24. `mb_kiln_bridge`
25. `mb_label`
26. `mb_label_pos`
27. `mb_payment_sumup`
28. `mb_pos_sumup`
29. `mb_workshop_base`

Current catalog state:

- `mb_depot` has an existing `i18n/fr.po`, but it is partial and must be merged,
  reviewed, and validated rather than overwritten.
- The other 28 addons have no French catalog.
- No addon currently has a committed POT source catalog.
- `fr_FR` is not currently activated in `odoo_test`.

English does not require an `en_US.po`: Odoo uses the source `msgid` as English.
An English catalog should be introduced only for an intentional dialect override,
not as a copy of every source string.

## Odoo 19 translation architecture

Use the installed Odoo 19 CLI as the extraction authority:

```text
odoo i18n loadlang
odoo i18n export
odoo i18n import
```

Do not maintain string inventories manually. Odoo extraction covers:

- static Python `_()` and `_lt()` calls;
- translated model descriptions, field labels/help, selections, constraints,
  and manifest metadata;
- installed XML/data records with external IDs and translatable fields;
- backend QWeb text and supported translated attributes;
- static JavaScript `_t()` calls below `static/src`;
- literal OWL/QWeb text and supported attributes below `static/src`.

It does not reliably cover:

- f-strings or dynamically assembled translation calls;
- JavaScript text not wrapped in `_t()`;
- XML files not loaded by the manifest;
- values written into fields that are not translatable;
- arbitrary component attributes unless they use Odoo's `.translate` convention;
- protocol tokens, IDs, domains, debug output, or customer-entered record data.

Every agent must first correct missing source markings within its owned addons,
then upgrade those modules in its scratch database, and only then export POT
files.

## Shared terminology

The coordinator creates `docs/i18n/fr_glossary.md` before translation begins.
Agents must follow it and propose changes through the coordinator rather than
silently choosing divergent terminology.

Initial required terms:

| English source | Preferred French | Notes |
|---|---|---|
| consignment / consignment sale | dépôt-vente | Use the French legal/business expression. |
| depot | dépôt / point de vente | Choose by operational context; do not use warehouse terminology blindly. |
| turnover | chiffre d’affaires | Never translate as profit or receipts. |
| customer receipts | encaissements clients | Distinguish from turnover excluding VAT. |
| commercial operation | opération commerciale | Shared planning model. |
| refill | réassort / réapprovisionnement | Glossary must choose one UI form consistently. |
| permanence shift | permanence | Store-attendance obligation. |
| break-even | seuil de rentabilité | Use consistently in reports and fields. |
| firing | cuisson | Ceramics process. |
| firing load | charge de cuisson | Physical kiln load, not accounting charge. |
| bisque | biscuit | Ceramics stage. |
| glazing | émaillage | Ceramics stage. |
| piece | pièce | Do not confuse with stock lot. |
| lot / serial number | lot / numéro de série | Follow native Inventory wording. |
| payment receipt | encaissement / paiement | Select using accounting context. |
| refund | remboursement | Use avoir only for the accounting document. |
| filing / declaration | déclaration | Especially URSSAF. |
| stock capture | capture de stock | Image-assisted inventory intake. |
| invoice capture | capture de facture | Document intake, not invoice creation. |

Keep `URSSAF`, `ACRE`, `CFP`, `CMA`, `SumUp`, `TollQuote`, `QR`, product names,
and official Article 293 B references unchanged where appropriate.

## Parallel ownership model

Each addon has exactly one translation owner. Agents may modify only their
assigned addon directories. They must not edit the shared glossary, QA scripts,
CI configuration, or another agent's catalog. The coordinator owns all shared
files and final integration.

### Agent A — Compliance and payments

Owned addons:

- `l10n_fr_micro_enterprise`
- `l10n_fr_micro_urssaf`
- `mb_payment_sumup`
- `mb_account_payment_sumup`
- `mb_pos_sumup`

Internal order:

1. Micro-enterprise and payment-provider foundations.
2. Invoice-payment and POS adapters.
3. URSSAF declarations and reports.

Review emphasis:

- French legal/accounting terminology and Article 293 B wording;
- ACRE, CFP, chamber, versement libératoire, filing, and payment status;
- refund/payment error parity;
- POS JavaScript `_t()` coverage;
- translated invoice and declaration reports.

### Agent B — Commercial Operations family

Owned addons:

- `mb_commercial_operations`
- `mb_commercial_operations_stock`
- `mb_commercial_operations_sale`
- `mb_commercial_operations_purchase`
- `mb_commercial_operations_pos`
- `mb_commercial_operations_mrp`
- `mb_commercial_operations_expense`
- `mb_commercial_operations_fleet`
- `mb_commercial_operations_depot`
- `mb_commercial_operations_urssaf`

Internal order:

1. Core planning and profitability.
2. Stock bridge.
3. Sale, Purchase, POS, MRP, Expense, and Fleet bridges.
4. Depot and URSSAF bridges.

Review emphasis:

- planning wizard, warnings, activities, state labels, and menus;
- VAT-exclusive sales versus VAT-inclusive customer receipts;
- cost, contribution, break-even, and actual-evidence terminology;
- refill/permanence comparison-window wording;
- planning, frozen-baseline, and outcome HTML/PDF reports;
- no French literals left in report source templates.

### Agent C — Workshop, ceramics, kilns, and labels

Owned addons:

- `mb_workshop_base`
- `mb_ceramics_firing`
- `mb_ceramics_workflow`
- `mb_kiln_bridge`
- `mb_label`
- `mb_label_pos`

Internal order:

1. Workshop base.
2. Ceramics firing and Label Studio.
3. Kiln bridge, ceramics workflow, and POS label integration.

Review emphasis:

- ceramics vocabulary and manufacturing terminology;
- firing programs, segments, kiln loads, losses, and workflow states;
- Label Studio has a large custom JavaScript surface with many current literal
  labels, notifications, errors, editor controls, and printer/device messages;
- wrap genuine JS UI strings with `_t()` before extraction;
- translate OWL/QWeb scanner controls such as flash/torch labels;
- never translate printer protocol commands, barcode payloads, diagnostic codes,
  or debug logs.

### Agent D — Platform, capture, catalogue, invoice intake, and depot

Owned addons:

- `mb_control_bridge`
- `mb_ai_bridge`
- `mb_catalogue_sync`
- `mb_depot`
- `mb_inventory_capture`
- `mb_inventory_capture_catalogue`
- `mb_invoice_capture`
- `mb_dbfilter_gateway`

Internal order:

1. Control bridge, AI bridge, catalogue sync, and depot.
2. Invoice capture and inventory capture.
3. Inventory-catalogue integration and DB-filter gateway.

Review emphasis:

- merge and preserve the existing `mb_depot/i18n/fr.po` translations;
- replace French source literals such as report headings with English source and
  keep their French rendition in `fr.po`;
- mark inventory-capture JavaScript and OWL/QWeb literals correctly;
- preserve API identifiers, AI provider values, database names, SKU values, and
  external catalogue fields;
- translate user-visible capture/provider failures without exposing raw payloads.

## Dependency waves

The four agents may work concurrently because their files do not overlap. Within
each batch, use two dependency waves:

### Wave 1 — foundations

- Agent A: micro-enterprise and payment provider.
- Agent B: commercial core and stock.
- Agent C: workshop base, ceramics firing, and Label Studio.
- Agent D: control/AI bridges, catalogue sync, and depot.

### Wave 2 — leaves and cross-domain adapters

- Agent A: account/POS payment adapters and URSSAF.
- Agent B: commercial optional bridges.
- Agent C: workflow, kiln bridge, and label POS.
- Agent D: capture addons, invoice intake, catalogue bridge, and DB filter.

Cross-batch integration is deferred until all owner branches are ready:

- `l10n_fr_micro_urssaf` depends on `mb_depot` terminology.
- `mb_commercial_operations_depot` depends on `mb_depot`.
- `mb_commercial_operations_urssaf` depends on both commercial and URSSAF work.
- `mb_inventory_capture` depends on `mb_workshop_base`.
- label/POS and payment/POS assets must be tested together in final POS bundles.

Agents must not wait for another batch merely to extract their own strings.
Cross-batch terminology and integrated UI validation belong to the coordinator.

## Coordinator preparation

Before addon agents edit files, the coordinator performs these shared tasks:

1. Freeze the English source-string baseline for the translation window.
2. Create and approve `docs/i18n/fr_glossary.md`.
3. Add `tools/check_i18n.py` and its dependency using the repository's normal
   dependency mechanism.
4. Add CI commands for PO syntax, catalog completeness, addon validation, and
   bilingual runtime tests.
5. Publish an exact-key allowlist for legitimate identical English/French terms.
6. Assign unique scratch database and filestore names to every agent.
7. Record the module list and expected POT digest at the start of integration.

The coordinator must not regenerate an agent's catalogs while that agent is
working.

## Per-agent implementation workflow

### 1. Inspect source strings

For every owned addon:

- find hard-coded English/French UI prose in Python, XML, JavaScript, OWL/QWeb,
  manifests, reports, and email templates;
- distinguish UI strings from technical identifiers and record data;
- replace dynamic/f-string translations with one static English msgid and named
  placeholders;
- import `_t` from `@web/core/l10n/translation` for JavaScript UI text;
- use `t-translation="off"` for literal protocol/data regions that must not be
  extracted;
- ensure translated XML files are declared in the manifest and records have
  stable XML IDs;
- correct misspelled or ambiguous English before translation.

### 2. Create an isolated Odoo database

Each agent uses a unique name such as:

```text
mb_i18n_compliance_<suffix>
mb_i18n_commercial_<suffix>
mb_i18n_workshop_<suffix>
mb_i18n_platform_<suffix>
```

Never share `mb_scratch`, another agent's database, or a filestore. Load French
before installing/upgrading the owned modules so the real install path imports
the catalogs:

```bash
docker exec odoo-poc-web \
  odoo i18n loadlang -c /etc/odoo/odoo.conf \
  -d "$AGENT_DB" -l fr_FR
```

### 3. Upgrade before extracting

Database-backed XML/model terms must match the current source:

```bash
docker exec odoo-poc-web \
  odoo module upgrade -c /etc/odoo/odoo.conf \
  -d "$AGENT_DB" MODULE_A MODULE_B
```

If the module command is unsuitable for the local deployment, use the tested
server form with `-u` and `--stop-after-init`. Do not extract from a stale or
partially installed database.

### 4. Export source templates

Place module names before `-l`, because Odoo 19's `-l` accepts multiple values:

```bash
docker exec odoo-poc-web \
  odoo i18n export -c /etc/odoo/odoo.conf \
  -d "$AGENT_DB" MODULE_A MODULE_B -l pot
```

This writes addon-local `i18n/<module>.pot` files through the mounted addon path.
Commit one POT per addon so source-catalog drift is reviewable.

### 5. Merge, never destructively overwrite

For an existing catalog:

```bash
msgmerge --update --backup=none \
  addons/MODULE/i18n/fr.po \
  addons/MODULE/i18n/MODULE.pot
```

For a new catalog, initialize it from the POT with a valid French header, then
translate it. Do not directly export `-l fr_FR` over a curated PO unless the
database was first seeded with that exact PO; Odoo export reflects database
translations and can discard work absent from the database.

Required header values include:

```text
Project-Id-Version: Odoo Server 19.0
Language: fr
Content-Type: text/plain; charset=UTF-8
Plural-Forms: nplurals=2; plural=(n > 1);
```

### 6. Translate completely

For every active POT entry:

- provide a non-empty French translation;
- preserve the exact meaning and UI tone;
- preserve named/positional placeholders, percent escapes, newlines, and markup;
- provide both plural forms;
- remove fuzzy status after review;
- do not translate code samples, protocol commands, XML IDs, URLs, or variable
  names inside technical documentation;
- keep report text legally and financially precise.

### 7. Import deterministically

```bash
docker exec odoo-poc-web \
  odoo i18n import -c /etc/odoo/odoo.conf \
  -d "$AGENT_DB" -l fr_FR -w \
  /mnt/makersbrain-addons/MODULE/i18n/fr.po
```

Restart the long-running Odoo process before browser testing Python/JS
translations because code and web translation bundles are cached.

### 8. Validate and hand off

Each agent runs its static gates, focused addon tests, module install/upgrade,
POT comparison, relevant asset compilation, and bilingual smoke tests. The
handoff must include:

- owned modules and changed files;
- extraction commands and database name;
- translated/total entry counts per addon;
- explicit allowlisted identical entries;
- hard-coded strings intentionally excluded and why;
- test and asset results;
- unresolved terminology questions.

An agent must not claim completion based only on `msgfmt` success.

## Static translation gates

Add `tools/check_i18n.py` as the repository authority. It must fail on:

- missing `i18n/<module>.pot` or `i18n/fr.po` for an installable custom addon;
- invalid UTF-8 or missing/incorrect French headers;
- fuzzy, obsolete, duplicate, or conflicting active entries;
- missing or empty singular translations;
- missing plural indices 0 or 1;
- active POT entries absent from the PO;
- stale PO entries, except a temporary reviewed exact-key allowlist;
- alphabetic `msgstr == msgid` unless the exact key is allowlisted;
- changed printf placeholders, including named keys, flags, types, and `%%`;
- changed brace/template placeholders;
- changed required newline/control-token structure;
- unbalanced or incompatible HTML/XML fragments;
- removed or added protected tags/attributes;
- introduced scripts, event-handler attributes, or unsafe URL schemes.

Also run gettext validation:

```bash
msgfmt --check-header --check-format \
  -o /dev/null addons/MODULE/i18n/fr.po
```

The custom checker remains mandatory because Odoo-exported entries are not
always tagged with the format flags `msgfmt` needs to validate placeholders.

Use a targeted source scanner rather than rejecting every string literal. It
should flag likely user-facing:

- Python exceptions, notifications, and action labels not wrapped in `_()`;
- JavaScript dialogs, notifications, buttons, and errors not wrapped in `_t()`;
- English or French prose in runtime views/QWeb/JS that extraction misses.

Tests, fixtures, comments, protocol tokens, debug logs, and approved brand/legal
terms use reviewed allowlists. A probabilistic language classifier must not be a
blocking CI signal.

## POT freshness gate

For each installed addon, export a fresh POT from the exact reviewed source and
database metadata, then compare keys by context, msgid, and plural msgid against
the committed catalogs.

Use per-module exports. Do not use one combined repository POT: identical msgids
would lose deterministic ownership and create unnecessary merge conflicts.

The gate must prove:

- committed POT equals current extractable source;
- every active POT key exists in `fr.po`;
- every required translation is non-empty;
- no removed source key remains active without a reviewed exception.

## Runtime and integration validation

After the four batches are merged, the coordinator creates one clean integration
database with `fr_FR` loaded before installing all 29 addons.

### Server validation

1. Install all addons on a fresh database.
2. Upgrade all addons on that database.
3. Run all repository Odoo tests.
4. Run `tools/check_addons.py`, Ruff, `git diff --check`, `msgfmt`, and
   `tools/check_i18n.py`.
5. Re-export all 29 POT files and assert zero catalog drift.
6. Import every `fr.po` with overwrite and rerun module upgrades.
7. Repeat relevant migration tests from a pre-translation database.

### Frontend validation

Compile/load the actual Odoo 19 bundles and run the repository's WebSuite/Hoot
tests. Browser smoke tests must cover both an `en_US` user and a `fr_FR` user:

- backend app roots and main menus;
- Commercial Operations planning wizard and reports;
- depot sale entry and stock views;
- Label Studio editor, device selection, and printing UI;
- inventory and invoice capture client actions;
- kiln/ceramics workflow screens;
- a POS session containing SumUp and label/scanner extensions.

Fail on:

- console/page errors;
- missing JavaScript modules or OWL templates;
- untranslated owned sentinel strings in French;
- French owned sentinel strings in English;
- stale language bundles after switching users/languages.

Do not use a global “no English words” assertion: product names, brands, partner
data, and customer content may legitimately be English.

### Report validation matrix

Render both QWeb HTML and PDF under English and French users/partners for:

- micro-enterprise invoices and Article 293 B text;
- SumUp invoice/payment QR content;
- URSSAF declaration/reporting;
- depot delivery/statement documents;
- commercial planning, frozen baseline, and outcome packs;
- any invoice/report inheritance combinations installed together.

Assert reviewed English/French sentinel pairs in HTML. For PDFs, assert a valid,
non-empty `%PDF` result and extract selected text when the environment supports
it. Never assert translated record data that originates from customers/products.

### Sentinel manifest

Maintain a small shared test manifest containing, per addon:

- source msgid;
- expected French translation;
- view/action/report locator;
- test user language;
- whether the string belongs to backend, POS, client action, email, or report.

Sentinels should target owned UI chrome—menus, actions, buttons, headings,
warnings, and errors—not arbitrary database values.

## Versioning and commits

- Bump each affected addon version once after its translation/source-marking work
  is complete, following the repository's Odoo 19 version policy.
- Keep each agent's commits restricted to its owned addons.
- Prefer one reviewed commit per functional batch, or smaller commits when source
  marking and catalog generation need separate review.
- The coordinator commits shared glossary/tooling/CI changes separately.
- Do not combine unrelated implementation changes with translation commits.
- Do not deploy agent branches individually; deploy only the integrated result.

## Deployment

After all gates pass:

1. Back up the target database.
2. Activate `fr_FR` using the native Odoo 19 language command.
3. Upgrade all 29 custom addons so translation metadata and web bundles refresh.
4. Explicitly import curated `fr.po` files with overwrite if deterministic DB
   replacement is required.
5. Restart Odoo and invalidate/rebuild frontend assets as required.
6. Verify one English and one French user in the deployed database.
7. Render the report matrix in both languages.
8. Record module versions, catalog digests, deployment time, and rollback backup.

Do not translate existing customer/product/partner values automatically. Those
are business records, not addon UI catalogs, and require a separate data policy.

## Definition of done

The repository is English/French ready when:

- all 29 installable custom addons have current POT and complete `fr.po` files;
- English source prose is reviewed, clear, and contains no accidental French UI
  literals;
- all genuine Python/JS/QWeb UI strings are extractable;
- French catalogs contain no missing, empty, fuzzy, unsafe, stale, or unapproved
  identical entries;
- placeholders, plurals, markup, and report layouts pass automated checks;
- all addons install and upgrade together with French loaded first;
- backend, POS, custom client actions, emails, and reports pass bilingual runtime
  acceptance;
- Odoo tests, asset builds, static checks, and catalog freshness gates pass;
- `odoo_test` is backed up, upgraded, healthy, and verified by English and French
  users;
- the four agent batches and the coordinator report no unresolved terminology or
  ownership conflicts.
