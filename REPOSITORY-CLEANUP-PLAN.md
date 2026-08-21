# Repository Cleanup Plan

Status: completed 21 August 2026

Target: the current Odoo 19 codebase and its current data model. Historical
installations, superseded file formats, renamed APIs, and pre-current-schema
databases are not supported by this cleanup.

## Goal

Leave one direct implementation of the current product:

- no runtime branches for legacy records, fields, routes, payloads, or contexts;
- no migration hooks for schemas that predate the current addon versions;
- no import/export support for superseded formats;
- no tests or translations whose only purpose is removed compatibility behavior;
- no completed implementation plans kept as project documentation; and
- no documentation that promises, explains, or instructs use of removed paths.

The cleanup must preserve current business concepts whose names happen to use
words such as *migration*, *alias*, *compatible*, or *obsolete*. In particular,
ceramic glaze migration tests, inventory stock-migration analysis, durable QR
aliases, carrier/service compatibility, and gettext obsolete-entry validation
are current features rather than backward-compatibility machinery.

## 1. Establish the supported baseline

1. Treat a fresh Odoo 19 installation of the current manifests as the only
   supported installation path.
2. Record the pre-cleanup static-check and fresh-install test results.
3. Inventory compatibility code by reference graph, not by keyword alone:
   implementation, callers, views, security, tests, data, translations, and
   documentation must be considered as one removal unit.
4. Do not preserve old database rows or old external callers by adding a new
   shim. If removing a compatibility field or selection value exposes dead code,
   remove that code as well.

## 2. Remove historical migration machinery

Delete every addon `migrations/<version>/` hook. These scripts exist only to
upgrade older schemas and contradict the fresh-current-schema baseline.

After removal:

- remove imports, comments, tests, and documentation that refer to those hooks;
- keep current constraints/defaults in normal models or data files when they
  are required by a fresh install; and
- verify that no manifest or operational command assumes historical upgrades.

Known migration-hook owners are `l10n_fr_micro_urssaf`,
`mb_ceramics_firing`, `mb_commercial_operations`, `mb_control_bridge`,
`mb_depot`, `mb_invoice_capture`, and `mb_workshop_base`.

## 3. Remove runtime compatibility paths

### Ceramics workflow

- Remove the `finishing` legacy workflow kind and every branch that accepts it.
- Remove the legacy finishing-session model/UI/action/menu if it exists only to
  complete pre-bisque workflow records.
- Remove tests, access rules, translations, and documentation for that path.
- Keep the current throwing, bisque, glazing, firing, board, loss, and genealogy
  workflows intact.

### Commercial planning and profitability

- Remove scalar-field and operation-owned-cost fallbacks now superseded by
  scenario-owned cost lines and unit-based scenario lines.
- Remove legacy cost reconciliation warnings, legacy mix-share evaluation,
  delegated legacy actions, and the `Legacy Migration` source option.
- Remove superseded fields only after all current forms, reports, templates,
  computes, and bridges have been changed to use the canonical scenario model.
- Replace tests that seed legacy shapes with tests of the one current shape;
  delete tests whose only assertion is backward compatibility.

### Label editor and POS

- Remove version-3/legacy label JSON import and export conversion. Import and
  export must accept only the current document schema.
- Remove the legacy converter module, UI branches, converter tests, and its
  translation entries.
- Remove compatibility parsing or messaging for historical QR encodings while
  preserving exact durable QR aliases minted by the current label system and
  native Odoo barcode fall-through.

### Webshop carrier runtime

- Remove the compatibility pickup controller route and keep the current native
  Odoo route only.
- Require the current per-operation provider safety contract; remove the
  provider-wide legacy fallback.
- Remove old cron-context keys and accept only the Odoo 19 context contract.
- Update provider implementations and tests together so missing current
  declarations fail directly rather than silently inheriting old behavior.

### One-off operational residue

- Remove `scripts/import_ateliera_r2_images.py` and any documentation or command
  references whose only purpose is restoring the retired Ateliera R2 dataset.
- Audit setup, import, demo, benchmark, and POC scripts for already-consumed
  transition work; remove only those with no current reproducible development,
  qualification, or operations role.

## 4. Remove implemented plans and stale compatibility documentation

Classify every root Markdown document against the current source and manifests:

1. Delete a plan/design/report when all of its deliverables are implemented or
   superseded. Confirmed first-pass candidates include:
   `COMMERCIAL-OPERATIONS-PLANNING-REPORT-PLAN.md`,
   `IDENTITY-SPINE-DESIGN.md`, and
   `makersbrain-webshop-carrier-sendcloud-plan.md`.
2. For a mixed document, retain only genuinely unimplemented work as a shorter,
   current plan; remove implementation diaries, completed phases, migration
   instructions, dated capability inventories, and backward-compatibility
   requirements. First-pass mixed candidates include
   `CRAFT-PLATFORM-PLAN.md`, `PRODUCT-PHOTO-INVENTORY-CAPTURE-PLAN.md`,
   `makersbrain-webshop-carrier-plan.md`, and
   `makersbrain-webshop-domain-email-plan.md`.
3. Keep a plan that is wholly unimplemented, but remove any stale premise or
   compatibility promise. Draft candidates include
   `DEPOT-MARKET-PROFITABILITY-PLAN.md` and
   `ODOO-I18N-EN-FR-TRANSLATION-PLAN.md`; their status must be checked against
   current addons before retention.
4. Delete completed research/sample reports when they are no longer a live
   acceptance artifact or operational reference.
5. Repair every remaining Markdown link after deletions. `SPEC.md` should be the
   canonical description of implemented behavior; addon READMEs should contain
   only current setup and operating instructions.

No plan is deleted solely because a similarly named addon exists. Its stated
deliverables must be traced to current models, views, security, tests, tooling,
and deployment configuration first.

## 5. Remove residue and simplify the current implementation

1. Run repository-wide reference searches after each removal unit.
2. Delete now-unused fields, methods, imports, XML records, ACLs, fixtures,
   translation messages, and test helpers.
3. Collapse conditionals that only distinguished current data from legacy data.
4. Regenerate or mechanically prune POT/PO catalogues so removed source strings
   do not remain active or obsolete.
5. Update addon versions only when required by this repository's current release
   policy; do not add migrations for the removals.

## 6. Verification gates

Run the fastest checks after each removal unit and the complete gates at the end:

1. `git diff --check`
2. `make check`
3. focused JavaScript tests for edited frontend addons
4. focused fresh-database Odoo tests for each edited addon family
5. `make test` for all custom addons on a fresh disposable database
6. a fresh install smoke test followed by searches proving there are no live
   legacy/backward-compatibility markers or references to deleted files

Keyword searches are an audit aid, not the acceptance criterion: remaining
matches must be reviewed and identified as current business semantics or generic
format/tool behavior.

## 7. Execution order

1. Capture baseline checks and finish the plan/document classification.
2. Remove migration hooks and one-off historical scripts.
3. Remove isolated carrier and label compatibility paths.
4. Remove ceramics legacy finishing end to end.
5. Remove commercial-planning compatibility fields and calculations end to end.
6. Delete completed plans and reduce mixed plans to unimplemented work.
7. Prune translations and repair cross-document references.
8. Run the full verification gates and review the final diff for accidental
   removal of current domain behavior.

## Definition of done

The cleanup is complete when a fresh Odoo 19 database installs and passes the
full suite using only the canonical current models and formats; no runtime path,
test, migration hook, translation, or documentation remains solely for older
versions or historical data; every retained plan describes only work that is
not implemented; and every remaining compatibility-related search match has a
documented current-purpose justification.

## Execution result

- Removed all addon migration hooks and compatibility-only setup/import code.
- Removed the ceramics finishing path, commercial scalar/fallback planning,
  historical label file conversion, QR payload interpretation, carrier route and
  provider-contract shims, and their tests, views, security, and translations.
- Deleted completed root plans and reduced the three mixed plans to open work.
- Replaced the historical repository snapshot with the current 41-addon
  specification and removed dangling plan references and implementation diaries.
- Regenerated affected POT/PO catalogues; all 41 French catalogues are complete.
- Verified `make check`, JavaScript syntax checks, and a fresh-database
  `make test`: 634 tests, 0 failures, 0 errors.
