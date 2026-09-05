# Odoo 19 Add-ons Remediation Plan

Status: implemented; all automated REL-01 gates passed on 2026-09-05
Prepared: 2026-09-04
Scope: all 41 add-ons in this repository
Execution model: three parallel specialist agents plus one integration owner

Implementation and validation evidence is recorded in
`docs/odoo-addons-remediation-evidence.md`. Physical scanner, camera, and printer
smoke testing remains a deployment-site check because those devices are not
available in the automated test environment.

## 1. Objective and completion criteria

This plan resolves every issue found in the Odoo design-pattern, format, idiom,
security, transaction, concurrency, data, frontend, and CI review. Work is
complete only when:

1. control-plane operations cannot be invoked through generic model RPC;
2. a failed HTTP request cannot commit a partial business operation;
3. every company-owned record is isolated for every group that has an ACL;
4. database invariants remain true under concurrent transactions;
5. install, upgrade, uninstall, assets, server tests, and browser tests pass;
6. module upgrades preserve user-authored data and provision seed data according to
   an explicitly approved company-scope policy;
7. deprecated or non-idiomatic code identified by the review is removed; and
8. each fix has a regression test that fails against the current implementation.

The last full baseline was healthy at the server level: all 41 add-ons installed
on a fresh database and 656 server tests completed with zero failures or errors.
Static validation of repository-owned Python, manifests, XML parsing, dependency
graph, translations, the control-bridge contract, and the brand-token projection
also passed. Asset pre-generation nevertheless exposed the `mb_brand` Sass import
failure. Preserve those results as the comparison baseline; they do not close the
security, concurrency, browser, or upgrade gaps below.

## 2. Multi-agent operating model

| Role | Primary ownership | May review, but must not edit |
|---|---|---|
| Agent S — Security and Transactions | SEC-01, TXN-01, TXN-02, MC-01, MC-02 | frontend and formatting files |
| Agent D — Data Integrity and Migrations | MIG-01, CON-01 through CON-06, DATA-01 through DATA-04, PERF-01, ORM-01, DEP-01 | controllers and JS/SCSS |
| Agent F — Frontend and CI | ASSET-01, CI-01, OWL-01, QWEB-01, LOG-01, UX-01, FMT-01 | backend security and migrations |
| Integration owner | architecture decisions, shared test helpers, CI, merge order, release evidence | none |

Each agent works on a separate branch or worktree and opens small PRs in the
sequence in section 5. No two active PRs should change the same manifest, model,
security XML, or workflow file. If ownership must cross a boundary, the agent
hands a patch or exact requirement to the owning agent instead of editing the
file. The integration owner rebases each PR onto the latest accepted predecessor,
runs the relevant narrow tests, then runs the full gates at phase boundaries.

Every PR must contain:

- the issue IDs it closes;
- a failing-before/passing-after regression test;
- upgrade or data-migration notes when schema or XML data changes;
- a rollback statement;
- screenshots or browser-test output for visible UI work; and
- no unrelated formatting or generated-catalogue churn.

## 3. Dependency map

```text
BASE-01
  |-- MIG-01 --> MC-02/CON-02..CON-06/DATA-02..DATA-04/PERF-01
  |-- SEC-01 --> TXN-01 --> TXN-02
  |-- MC-01  --> MC-02
  |-- CON-01 --> CON-02/03/04/05/06
  |-- DATA-01 --> DATA-02 --> DATA-03
  |-- ASSET-01 --> CI-01 --> OWL-01/QWEB-01/LOG-01
  `-- DEP-01 --> ORM-01/PERF-01/UX-01/FMT-01

All tracks --> REL-01 full install/upgrade/uninstall/concurrency/browser gate
```

The reproducible migration harness and label data-clobber fix land immediately after
the baseline. Security and atomicity follow before broader business changes.
Formatting is deliberately last so it does not obscure semantic review or create
avoidable merge conflicts.

## 4. Work packages

### BASE-01 — Freeze and reproduce the baseline

Owner: integration owner
Priority: prerequisite

Actions:

1. Record the commit SHA, Odoo image digest, PostgreSQL version, Python dependency
   lock state, and the exact list of 41 discovered manifests.
2. Run `make check` against repository-owned source. Ensure local-only directories
   such as `.agents/` and `.claude/` cannot make a source-format gate fail; change
   the formatter scope or documented invocation only if CI has the same problem.
3. Run `make test` on an empty allowlisted disposable database and archive the
   server-test summary.
4. Capture the current asset compilation failure with the bundle name and full
   Sass traceback. Do not accept the existing warning as a passing result.
5. Create reusable test users: one ordinary internal user, one accounting user
   without commercial-operations membership, and users restricted to company A,
   company B, or both.
6. Add a test-data naming convention and a helper for opening independent database
   cursors so concurrency tests synchronize with barriers rather than timing sleeps.

Acceptance:

- baseline commands and results are attached to the first PR;
- a fresh database definitely runs the tests rather than silently reusing installed
  modules; and
- concurrency helpers prove that two transactions overlap before either commits.

Rollback: documentation and test helpers only; revert the PR.

### MIG-01 — Make upgrade, uninstall, and concurrency testing reproducible

Owner: Agent D with integration owner
Priority: prerequisite for every schema or migration-bearing package
Files: `Makefile`, `.github/workflows/ci.yml`, migration test tooling, affected
manifests, and versioned migration directories

Actions:

1. Create a version matrix listing every affected add-on's installed version, target
   version, migration directory, migration phase, and expected postcondition. A
   manifest version bump is mandatory whenever a new migration must run.
2. Add `make upgrade-test` and a matching CI lane. Build a database with the pinned
   predecessor commit/image, install the predecessor add-ons, create fixtures that
   exercise each migration, switch to the candidate checkout/image, then run `-u` on
   the changed modules.
3. Assert observable migration effects rather than relying only on a green Odoo exit.
   Run the same upgrade a second time and prove it is idempotent and creates no
   duplicate seed, index, constraint, external ID, or relation.
4. Add matching `make uninstall-test` and `make concurrency-test` entry points. The
   concurrency lane must use independent registry cursors/connections, deterministic
   barriers, a fresh database, explicit test tags, and a bounded timeout.
5. Use the repository's Odoo migration filename convention (`pre-migrate.py`,
   `post-migrate.py`, or `end-migrate.py`) and directory named for the target manifest
   version. Add a smoke fixture proving the runner actually executed each phase.
6. Decide index installation before implementation. `CREATE INDEX CONCURRENTLY`
   cannot run inside Odoo's normal module-upgrade transaction; large online indexes
   require a separately rehearsed maintenance step. Otherwise create the index in the
   versioned migration transaction.
7. Archive the predecessor SHA/image digest, target SHA/image digest, commands,
   database fixture version, logs, and assertions as release evidence.

Acceptance:

- omitting a required manifest bump or migration file makes the upgrade lane fail;
- the predecessor fixture fails the relevant postcondition before upgrade and passes
  after it;
- a second upgrade is a no-op at the data/schema level;
- uninstall and concurrency targets run locally with the same commands as CI; and
- fresh-install tests remain separate and cannot substitute for upgrade tests.

Rollback: tooling-only changes can be reverted. Migration-bearing application changes
must follow the coordinated schema/application rollback rules in section 6.

### SEC-01 — Make controller service methods non-RPC

Owner: Agent S
Priority: critical
Files: `addons/mb_control_bridge/models/res_company.py`,
`addons/mb_control_bridge/models/res_users.py`,
`addons/mb_email_bridge/models/res_company.py`, and controller-facing service
models in `mb_invoice_capture` and `mb_inventory_capture`

Problem: authenticated controllers call public model methods that contain `sudo()`,
company configuration writes, user lifecycle operations, module installation, or
personal-data access. Public methods can also be reached through Odoo's generic RPC
surface unless explicitly marked private.

Actions:

1. Inventory every non-underscored model method in the four integration add-ons.
   Classify it as an intentional user-facing RPC API, a button/action API, or a
   controller-internal service. Search inherited models as well as new models.
2. Mark controller-internal services with Odoo 19 `@api.private`. Where a rename is
   clearer, use an underscore-prefixed method and update all internal callers. Do
   not rely on the HTTP route's authentication to protect a separately exposed ORM
   method.
3. At minimum protect:
   - `res.company.mb_project_webshop_domain`, `mb_bootstrap_tenant`,
     `mb_enable_module_bundle`, `mb_restrict_module_bundle`, and
     `mb_apply_entitlement`;
   - `res.users.mb_reconcile_membership`, `mb_replay_erasure`, and
     `mb_export_personal_data`; and
   - `res.company.mb_webshop_smtp_status`, `mb_configure_webshop_smtp`, and
     `mb_reset_webshop_smtp`.
   Also protect invoice `ingest`, inventory `ingest_result`, operation-receipt
   `for_replay`/`record`, and capability-policy `restrict` when the inventory
   confirms they are controller-only services.
4. Review status/read helpers such as `mb_webshop_status` and
   `mb_expected_module_bundle`: private-mark any response that discloses tenant,
   module, identity, or infrastructure state. Document any method intentionally
   left callable and enforce its groups with `check_access`/`has_group` before sudo.
5. Keep privilege elevation as narrow as possible: validate payload, tenant,
   company, capability, and idempotency key before the first `sudo()`; sudo only the
   recordset or system model that requires it.
6. Add a static policy check that flags newly added public methods in bridge/capture
   service files when they call `sudo`, `button_install`, or sensitive exports and
   lack an allowlist annotation or `@api.private`.
7. Update the committed bridge contract if method names change, then run the
   contract drift check.

Tests and acceptance:

- an ordinary internal user calling each protected method through `execute_kw`
  receives the RPC/private-method denial and causes no write;
- module installation, entitlement changes, membership reconciliation, erasure,
  export, and SMTP configuration cannot be triggered by generic RPC;
- correctly authenticated HTTP controller contract tests still pass;
- invalid signatures, wrong tenant/company, expired requests, replayed keys, and
  missing capabilities fail before privileged work; and
- no public controller-only method remains without an explicit rationale.

Rollback: revert code and contract together. No schema change. Do not temporarily
restore public RPC access in production; roll back the calling controller and model
as one unit.

### TXN-01 — Make each HTTP mutation atomic

Owner: Agent S
Priority: high
Files: `addons/mb_control_bridge/controllers/main.py`,
`addons/mb_invoice_capture/controllers/main.py`,
`addons/mb_invoice_capture/models/invoice_capture.py`,
`addons/mb_inventory_capture/controllers/main.py`, and their receipt/idempotency
models

Problem: broad controller exception handlers turn exceptions into successful HTTP
responses. Odoo may then commit writes performed before a late failure. Invoice
capture can create the capture and attachment before bill processing fails;
inventory capture can create an attempt before candidate validation fails.

Actions:

1. Draw the transaction boundary for every mutating route, including authentication
   state, idempotency receipt, attachments, attempts, candidates, bills, stock data,
   and response recording.
2. Put the entire business mutation and its success receipt inside one
   `with request.env.cr.savepoint():` block. Catch expected exceptions only outside
   that block, after the context manager has rolled back to the savepoint.
3. Create failure receipts only after deciding whether they are meant to persist.
   If persisted, write them in a new, deliberately separate savepoint after the
   failed business savepoint has rolled back. Never leave a receipt claiming success
   when its business rows were reverted.
4. Narrow exception types. Let unexpected programming/database errors propagate so
   Odoo rolls back the request and monitoring sees a server error. Map only known
   validation, authorization, conflict, and idempotency failures to contract codes.
5. Apply the pattern consistently to all broad catches in the control bridge, not
   only the example blocks near lines 60, 238, and 289.
6. Ensure external side effects occur after durable local state where possible. For
   unavoidable remote calls, store an outbox/job before commit and make delivery
   idempotent; never hold a database savepoint open around a long network request.

Tests and acceptance:

- inject a failure after every material create/write step and assert zero partial
  capture, attachment, bill, attempt, candidate, entitlement, or success-receipt
  rows remain;
- retry the same operation key after a rolled-back attempt and obtain one complete
  result, not a duplicate or a false replay;
- send two synchronized requests with the same operation key and digest and assert
  exactly one business mutation, one canonical receipt, and compatible responses;
- send two synchronized requests with the same key but different digests and assert
  one success, one conflict, no duplicate mutation, and a usable cursor after the
  uniqueness conflict is handled outside its savepoint;
- known validation failures retain the documented HTTP response;
- an unexpected exception yields a 5xx and the request transaction rolls back; and
- success-path controller contract tests remain unchanged.

Rollback: code-only. Because this changes commit semantics, deploy it before any
consumer starts relying on new failure-receipt behavior.

### TXN-02 — Remove ambient manual rollback from email configuration

Owner: Agent S
Priority: medium
Files: `addons/mb_email_bridge/controllers/main.py`

Actions:

1. Replace `request.env.cr.rollback()` near line 47 with the savepoint/catch-outside
   structure from TXN-01.
2. Confirm that authentication/audit work preceding the configuration call is
   either read-only or intentionally included in the savepoint.
3. Reuse the shared error mapper; do not manipulate the request cursor's ambient
   transaction from a controller.

Acceptance: a forced SMTP configuration failure reverts only the operation, leaves
no partial mail-server/company configuration, returns the expected contract error,
and does not erase unrelated framework state.

Dependency: TXN-01. Rollback: code-only revert.

### MC-01 — Close the commercial rent-period company leak

Owner: Agent S
Priority: high
Files: `addons/mb_commercial_operations_depot/security/ir.model.access.csv`,
`addons/mb_commercial_operations_depot/security/mb_commercial_operations_depot_security.xml`,
and security tests

Problem: `account.group_account_invoice` has read/write/create access to
`mb.commercial.rent.period`, but the company rule applies only to the commercial
operations group. Record rules are default-allow when no applicable rule exists.

Actions:

1. Make the company rule global by removing its `groups` field, unless a documented
   cross-company business case forbids that. Use
   `('company_id', 'in', company_ids)` and verify create/write company consistency.
   In the upgrade XML, explicitly clear the existing many-to-many `groups` value;
   merely deleting the field from source XML does not clear groups already stored in
   an installed database. Preserve the XML ID so the deployed rule is updated rather
   than duplicated.
2. Audit every ACL/rule pair in the module: for each group with any ACL permission,
   prove that at least one applicable company rule exists. Remember that group rules
   unify while global rules intersect.
3. Check related models reached through rent periods so a user cannot infer or
   mutate another company's contract, bill, partner, or scenario through relations.
4. Add a repository security checker that reports company-owned models having ACLs
   but no global or group-complete company rule.

Tests and acceptance:

- an accounting-only user in company A cannot search, read by known ID, write,
  unlink, or create a rent period for company B;
- a user allowed both companies sees both when both are active;
- commercial managers retain intended rights inside allowed companies; and
- `sudo()` is used only in test setup, never to make the asserted operation pass.

Rollback: security XML only, but rolling back reopens a data leak; treat as a
security rollback requiring explicit approval.

### MC-02 — Isolate webshop stock holds by company

Owner: Agent S with schema review by Agent D
Priority: medium
Files: `addons/mb_webshop/models/stock_hold.py`,
`addons/mb_webshop/security/ir.model.access.csv`, and the module security XML

Actions:

1. Add a stored, indexed, precomputed, required `company_id` related to
   `order_id.company_id`, enable `_check_company_auto`, and add `check_company=True`
   to compatible company relations. Do not force company checks onto legitimately
   shared products. Populate the field in a versioned migration before making it
   required.
2. Add a global record rule `('company_id', 'in', company_ids)` for stock holds.
3. Review cron/internal searches using `sudo()`: sudo may cross companies only for a
   documented system job, and subsequent order/move writes must retain the record's
   company context.
4. Add the model to the automated ACL/rule completeness check from MC-01.

Tests and acceptance: stock users in company A cannot discover company B holds by
search, direct known-ID read, or related navigation; expiry jobs still process all
intended companies safely; install and upgrade populate every existing hold. Because
the current stock-manager/system ACLs are read-only, test create/write company
consistency through the actual privileged internal service or a purpose-built test
group only where that operation is intended; do not cite an ACL denial as proof that
the record rule works.

Dependency: MC-01 checker; coordinate migration with Agent D. Rollback requires
retaining the populated column until the old code is restored, then dropping it only
in a later maintenance migration if desired.

### CON-01 — Establish the concurrency-control pattern

Owner: Agent D
Priority: high

Actions:

1. Use database unique/check constraints when PostgreSQL can express the invariant
   without privileged extensions. Use Odoo 19 `models.Constraint` or `models.Index`
   for supported declarations.
2. For range overlap or aggregate invariants that cannot be expressed portably,
   lock a stable parent row before re-reading and validating. Lock IDs in sorted
   order with `FOR UPDATE` to avoid deadlocks. The selected parents in this plan are
   company, kiln, warehouse, commercial operation, and `mrp.production`.
3. Never use a record being created as the only lock: two concurrent new rows do not
   conflict. Do not solve races with Python process locks or sleeps.
4. Translate constraint violations into the existing user-facing `ValidationError`
   and keep messages translatable.
5. Create a two-cursor test helper using a barrier/event so both transactions reach
   the critical section. Assert one succeeds and the other fails cleanly, then
   verify final database state.
6. Architecture decision: do not make `btree_gist` a dependency and do not install
   range exclusion constraints conditionally. Stable parent/key locking is the
   repository-wide enforcement mechanism for overlap rules. This keeps CI, staging,
   managed PostgreSQL, and production schemas identical. A future move to exclusion
   constraints requires a separate architecture decision and mandatory deployment
   prerequisite across every environment.

Acceptance: the pattern is documented in a test helper and used by CON-02 through
CON-06; tests are repeatable and contain no timing-based `sleep`.

### CON-02 — Serialize URSSAF declarations and dated rules

Owner: Agent D
Priority: high
Files: `addons/l10n_fr_micro_urssaf/models/urssaf_declaration.py` and
`addons/l10n_fr_micro_urssaf/models/urssaf_rule.py`

Actions:

1. Keep the existing exact company/period unique constraint, but serialize the
   broader overlapping-period check by locking the affected `res.company` row(s)
   in sorted order before re-running the overlap domain.
2. Apply the same pattern to rate, ACRE, and threshold effective-date windows near
   `urssaf_rule.py` lines 70–101, 142–164, and 192–206. Define the lock key from the
   complete business identity (company/global scope, levy/category, or rule type).
   If global rules have no company parent, lock a module-owned invariant-key row or
   use a transaction-scoped advisory lock with a stable model/key namespace. Acquire
   it before `super().create()`/`super().write()` and lock old and new keys in sorted
   order when applicability fields change.
3. Run a pre-migration query for existing overlaps and stop the upgrade with a
   report rather than choosing a winner silently.
4. Preserve inclusive date semantics: periods conflict when their closed date ranges
   share a date. Test consecutive periods using `previous.date_to + 1 day` as the
   valid non-overlapping boundary.

Tests: concurrent overlapping declarations; exact duplicates; adjacent non-overlap;
open-ended rule dates; concurrent rate/ACRE/threshold windows; multi-company
independence. Acceptance: at most one conflicting row commits and valid adjacent or
different-company rows both commit.

### CON-03 — Serialize kiln occupancy

Owner: Agent D
Priority: high
File: `addons/mb_ceramics_firing/models/mb_firing.py`

Actions: lock each affected kiln row in sorted order before the overlap check near
lines 191–227; re-read after acquiring the lock; run the logic from both create and
write, including kiln/date changes and batches. Preflight existing scheduled/firing
overlaps and report them. Do not add a range exclusion constraint in this package:
the current rule is asymmetric—it validates a firing entering `planned` against
draft/planned/firing/cooling records while still allowing draft-vs-draft overlap—and
a simple exclusion would silently make the rule stricter. If product later chooses
the stricter invariant, handle it in a separate migration and use PostgreSQL
`tsrange(..., '[)')`, matching Odoo's timestamp-without-time-zone storage, rather
than `tstzrange`.

Tests: two concurrent firings for one kiln and overlapping intervals allow only one;
different kilns and boundary-touching intervals follow the documented policy;
rescheduling cannot race creation.

### CON-04 — Serialize depot contract/rent periods

Owner: Agent D
Priority: high
File: `addons/mb_commercial_operations_depot/models/commercial_contract.py`

Actions: confirm the current business key, expected to be the affected
`stock.warehouse`, then lock that stable warehouse (and any additional company/depot
identity required by the domain) before validating contract overlap near lines
122–144 and any rent-period uniqueness tied to that contract.
Define whether touching end/start dates overlap, encode it once, and preflight old
data before upgrade. Preserve the current inclusive date-overlap semantics through
warehouse locking; do not add an environment-dependent exclusion constraint.

Tests: concurrent creates and date-changing writes; different companies/depots;
boundary dates; batch creates in reversed input order to check deadlock resistance.

### CON-05 — Enforce lot allocation uniqueness in PostgreSQL

Owner: Agent D
Priority: high
File: `addons/mb_commercial_operations_stock/models/commercial_operation.py`

Actions: replace the search-count check near lines 601–622 with
`UNIQUE(operation_id, lot_id)`, the current business key. PostgreSQL permits multiple
`NULL` lots, preserving untracked-product behavior. Do not add product or company to
the key unless requirements intentionally change. Preflight and report duplicate
groups; do not delete duplicates automatically.

Tests: concurrent duplicate allocation permits one row; distinct lots and permitted
null-lot lines still work; constraint errors use the domain message.

### CON-06 — Serialize board aggregate capacity

Owner: Agent D
Priority: high
File: `addons/mb_ceramics_workflow/models/mb_board_content.py`

Actions: lock the affected `mrp.production`, which is the aggregate and capacity
identity, before computing quantity near lines 52–86. Re-read all of that
production's board-content rows under the lock and apply the same path to create,
write, `action_remove`, `transfer_to`, moves, and unlink when it affects derived
state. Lock old and new productions in sorted order on moves.

Tests: concurrent additions on different boards for the same production serialize
and cannot exceed `production.product_qty`; simultaneous move/add remains within the
production total; different productions proceed independently.

Rollback for CON-02 through CON-06: check application/schema compatibility per
constraint. Old code may surface raw integrity errors or fail to populate new required
fields, so roll schema and application back as a coordinated unit unless compatibility
has been demonstrated. Never remove an enforcing constraint while race-prone code is
serving traffic.

### DATA-01 — Stop label upgrades from resetting the active version

Owner: Agent D
Priority: high
Files: `addons/mb_label/data/mb_label_data.xml`, `addons/mb_label/__manifest__.py`,
and label install/upgrade tests

Problem: the function outside `noupdate` unconditionally assigns
`template_wip_lot_30x20_v1` on every `-u`, overwriting a user's later current version.

Actions:

1. Remove the unconditional upgrade-time `<function>` write and place the WIP v1
   linkage inside the existing `noupdate="1"` installation block after the version
   record, matching the product seed.
2. Do not add a migration that guesses a missing current version: an upgrade cannot
   reconstruct a user's intended selection after a previous clobber. Produce an
   operator report for empty pointers and repair them only with an explicit decision.
3. Audit the product-label seed using the same rule and document the contract:
   version 1 and its initial pointer are created once; updates never change a user's
   selected current version.

Tests and acceptance: install links v1; saving v2 makes it current; module upgrade
keeps v2; repeated upgrades create no duplicate v1 and change no pointer; a database
with an ambiguous empty pointer is reported rather than silently rewritten; uninstall
leaves no orphan external IDs.

Rollback: do not restore the unsafe upgrade-time XML function. If a packaging problem
requires rollback, keep or forward-port the install-only linkage fix so future `-u`
runs cannot clobber a selected version. No data pointer should be rewritten during
rollback.

### DATA-02 — Make active default-label uniqueness complete and concurrent

Owner: Agent D
Priority: medium
File: `addons/mb_label/models/label_template.py`

Actions:

1. Add `active` to `@api.constrains("is_default", "company_id", "active")` so
   reactivation is validated.
2. Back the invariant with a partial unique index for one active default per company
   if Odoo's index declaration supports the target PostgreSQL expression. Otherwise
   lock the company row before the check and before `action_set_default` clears the
   previous default.
3. Make `action_set_default` one atomic, company-scoped operation and ensure archived
   defaults have the documented semantics.
4. Preflight duplicate active defaults and require an operator to choose the winner.
5. Lock the template row in `save_version()` before calculating `max(number) + 1`;
   retain the version-number database constraint and return a controlled conflict if
   simultaneous version saves cannot be serialized at the entry boundary.

Create the partial index only after the duplicate-default preflight is clean. Retain
the application-level company lock even with the index so `action_set_default()` is
atomic and returns a controlled domain message.

Tests: archive/reactivate, concurrent default creation, concurrent
`action_set_default`, separate companies, and upgrade with clean/dirty fixtures.

Dependency: DATA-01 because both change label templates.

### DATA-03 — Provision label seed templates per company

Owner: Agent D
Priority: medium
Files: `addons/mb_label/data/mb_label_data.xml`, a company extension or service,
hooks/migrations, and tests

Decision gate: confirm product intent. The model and rules are company-scoped, while
XML records without `company_id` receive only the installation company. The
recommended outcome is one independent seed template/version set per company.

Actions for the recommended outcome:

1. Add an immutable, indexed technical `seed_key` and enforce uniqueness with
   `company_id`. Replace single-company XML seeds with an idempotent
   `_ensure_label_seed_templates` service keyed by company and that seed key, not by
   translated name.
2. Call it from installation/post-init, an upgrade migration for every existing
   company, and company creation for new companies. Use `with_company(company)` and
   explicit `company_id`.
3. Do not make every seed default if a company already has an active default. Never
   overwrite documents or current versions edited by users.
4. Give generated records stable ownership/identification so uninstall and future
   upgrades can distinguish untouched seeds from user-modified copies.
5. Adopt the existing XML-backed templates for the installation company by assigning
   seed keys; do not duplicate them. External IDs cannot represent a dynamic record
   per arbitrary company, so do not use generated XML IDs as the per-company key.
   DATA-01 must land first. DATA-03 then adopts the installation-only XML records
   before retiring XML provisioning; removing a data file from the manifest must not
   be treated as deleting its existing XML-backed records.

Tests: two existing companies at upgrade, company created after install, rerun
idempotency, translated names, pre-existing custom default, and company rule
visibility. If product chooses installation-company-only instead, document that
choice in the manifest/readme and add a test proving it is deliberate.

Dependency: DATA-02.

### DATA-04 — Correct kiln connection count invalidation

Owner: Agent D
Priority: low/medium
File: `addons/mb_kiln_bridge/models/mb_kiln_connection.py`

Actions:

1. Decide whether the counts are stored UI counters or deliberately live queries.
2. For computed counters, add complete dotted `@api.depends` paths for created,
   reassigned, archived, and deleted related kilns/firings; add inverse relations if
   needed so Odoo can invalidate them reliably.
   `mb.kiln` currently lacks the firing inverse by `kiln_id`; introduce that relation
   before depending on `kiln_ids.firing_ids`. Do not reuse
   `mb.kiln.program.firing_ids`, whose inverse is `program_id`.
3. If a dependable relation cannot be expressed, expose explicit non-stored count
   methods/action domains and avoid a misleading stored compute.
4. Retain the existing batched `_read_group` implementation; do not regress to one
   `search_count` per connection.

Tests: create, reassign, archive, restore, and unlink related records immediately
update the displayed counts; multi-record reads have bounded query growth.

### PERF-01 — Index and narrow invoice supplier matching

Owner: Agent D
Priority: medium
File: `addons/mb_invoice_capture/models/invoice_capture.py`

Actions:

1. Measure current queries and rows loaded by `_match_supplier` around lines 525–560
   at representative partner cardinalities.
2. Add stored, indexed normalized keys for VAT, SIREN/SIRET, and name where standard
   indexed Odoo fields are insufficient. Define normalization centrally and
   recompute in a migration. Decide localization ownership explicitly: either declare
   the module owning `res.partner.siret` as a direct dependency or isolate SIRET
   normalization in an optional link add-on. Never declare `@api.depends("siret")`
   where that field may be absent.
3. Query exact strong identifiers first, restrict by allowed company/commercial
   partner and active state, use `limit=2` to detect ambiguity, then fall back through
   explicit ranked stages. The normalized-name fallback must also be indexed and
   bounded; it must not become another full-company scan.
4. Preserve ambiguity handling: never silently choose between equal candidates.
5. Avoid logging raw supplier identifiers or OCR payloads.

Tests and acceptance: exact VAT/SIRET/name fallback and ambiguity behavior remain
correct; query count is bounded and partners materialized do not grow linearly with
all active company contacts; migration recomputes existing partners idempotently.

### ORM-01 — Convert pure deletion vetoes to `@api.ondelete`

Owner: Agent D
Priority: low/medium
Files include `l10n_fr_micro_urssaf/models/urssaf_declaration.py`,
`mb_ceramics_firing/models/mb_firing.py`, `mb_label/models/label_print_job.py`,
`mb_label/models/label_alias.py`, `mb_label/models/label_template.py`, depot sale
report models, ceramics workflow session/allocation models, and `mrp_bom.py`
as well as any veto-only override found in `mb_shop_import`.

Actions:

1. Inventory every `unlink` override and classify it as pure business veto, cleanup,
   cascading side effect, or a combination.
2. Convert only pure veto logic to named `@api.ondelete(at_uninstall=False)` methods.
   Keep real cleanup in `unlink`; split combined methods so uninstall can bypass the
   business veto without skipping required cleanup.
3. Preserve error messages and state predicates. Verify mixin/super behavior for
   overrides that remain.

Tests: forbidden interactive deletion still fails; permitted deletion works; each
affected module uninstalls on a disposable database without the veto blocking it;
cleanup side effects still occur in ordinary deletion.

### DEP-01 — Declare direct manifest dependencies

Owner: Agent D
Priority: medium
Files: affected `__manifest__.py` files and XML views, including `mb_kiln_bridge`,
`mb_ceramics_compliance`, `mb_webshop_carrier_base`,
`mb_webshop_carrier_boxtal`, and `mb_webshop_carrier_sendcloud`

Actions:

1. For every Python import, inherited model, XML `ref`, inherited view, asset bundle,
   security group, and menu parent, map the symbol to the module that owns it.
2. Add that owning module as a direct dependency instead of relying on a transitive
   path. Confirm at least the direct `mb_workshop_base` references in kiln/compliance
   views and direct `delivery` view inheritance in carrier base, Boxtal, and
   Sendcloud adapters.
3. Enhance `tools/dependency_policy.py` to inspect XML inheritance/ref ownership,
   not just imports or local references, with a narrowly documented allowlist for
   intentionally optional integrations.
4. Install each changed module with only its declared dependency closure on a fresh
   database.

Acceptance: dependency checker catches a fixture with a missing direct dependency;
all changed modules install alone and in the full suite. Rollback is manifest-only,
but never deploy code that references a module omitted by the rolled-back manifest.

### ASSET-01 — Fix and continuously compile the brand bundles

Owner: Agent F
Priority: high
Files: `addons/mb_brand/__manifest__.py` and
`addons/mb_brand/static/src/scss/primary_variables.scss`

Problem: `primary_variables.scss` imports `mb_tokens` relatively, but Odoo
concatenates the file into a core bundle and Sass resolves the import under the web
core path. Bundle pre-generation reports “import not found.”

Actions:

1. Put `mb_tokens.scss` explicitly in `web._assets_primary_variables` before
   `primary_variables.scss`, using manifest ordering operations supported by Odoo
   19. Remove the fragile relative import once the token file is a bundle input.
2. Preserve the essential ordering: MakersBrain values must precede Odoo's
   `!default` declarations. Verify backend and frontend bundles consume the same
   resolved values.
3. Keep `tools/check_brand_scss.py` as the source-projection check; compilation is a
   separate required gate.

Tests and acceptance: inspect the resolved `web._assets_primary_variables` input
order, then compile its backend/frontend/login consumers from a clean
attachment/cache state. The underscore-prefixed sub-bundle is not treated as a
standalone HTTP asset. No Sass warning/error is present; a browser smoke test verifies
the expected primary token and font asset; an upstream token projection drift still
fails `brand-check`.

Rollback: revert both manifest order and SCSS together.

### CI-01 — Add asset and Hoot/browser gates

Owner: Agent F with integration owner
Priority: medium/high
Files: `.github/workflows/ci.yml`, `Makefile`, and browser test configuration/scripts

Actions:

1. Add an asset lane that installs all modules on a fresh database, clears generated
   asset attachments/cache, asserts the resolved ordering of the internal primary
   variables sub-bundle, explicitly requests/compiles `web.assets_backend`,
   `web.assets_frontend`, POS assets, and unit-test assets, and fails on compiler
   errors instead of accepting warning text.
2. Add a pinned headless Chromium Hoot lane using Odoo's `/web/tests` runner. Filter
   it to repository test suites and fail on timeout, browser console errors, failed
   tests, or zero tests discovered.
3. Run existing Hoot suites declared by `mb_inventory_capture`, `mb_label`, and
   `mb_label_pos`. Add coverage for the four `mb_pos_sumup` frontend files, especially
   asynchronous terminal callback, cancellation, retry, and teardown behavior.
4. Add browser component/mount tests for camera/scanner lifecycle, label-editor
   drag/resize teardown, device-print flows with mocked browser APIs, and POS payment
   callback cleanup. Physical printer/scanner qualification remains a documented
   manual release test, not a CI claim.
5. Add local `make assets-test` and `make browser-test` targets matching CI exactly.
   Pin browser/image versions and upload screenshots, console logs, and result output
   on failure.
6. Split lanes only where it improves diagnosis; require both for merges that touch
   manifests, JS/XML/SCSS assets, or browser-facing controllers.
7. Guard against a zero-test false green. During implementation, temporarily
   introduce one invalid
   SCSS fixture and one failing Hoot assertion to prove each lane goes red, then
   remove both canaries before merge.

Acceptance: the existing broken Sass import fails the new asset lane; a deliberately
failing Hoot assertion makes CI red; the final lane reports a non-zero expected test
count; server tests remain a separate required job.

Dependency: ASSET-01 may merge with a temporary expected failure only on a branch;
the default branch must receive the fix and gate together or gate first if already
green after a test fixture demonstrates detection.

### OWL-01 — Make label editor event lifecycle safe

Owner: Agent F
Priority: medium
File: `addons/mb_label/static/src/editor/label_editor.js`

Actions:

1. Replace ad-hoc `window` pointer listeners near lines 314–322 and 365–373 with
   pointer capture or a single cleanup registry. Remove listeners on pointer-up,
   pointer-cancel, blur, and `onWillUnmount`.
2. Store stable handler references so `removeEventListener` always receives the same
   function/options. Reset drag/resize state during cleanup.
3. Use Odoo's browser abstraction where supported to make behavior testable.
4. Replace `window.confirm` near line 111 with Odoo's `ConfirmationDialog` service so
   focus, translation, accessibility, and tests follow standard patterns.

Tests: repeated mount/unmount leaves zero listeners; unmount during drag/resize does
not update destroyed state; cancel/blur cleans up; confirm/cancel dialog paths work;
keyboard and pointer paths remain usable.

Dependency: CI-01 browser runner.

### QWEB-01 — Replace deprecated `t-esc` with `t-out`

Owner: Agent F
Priority: low/medium
Files: the 59 occurrences in:

- `addons/mb_commercial_operations/report/commercial_operation_report.xml`;
- `addons/mb_depot/report/mb_depot_invoice_template.xml`;
- `addons/mb_inventory_capture/static/src/capture_action.xml`;
- `addons/mb_label/static/src/editor/label_editor.xml`;
- `addons/mb_label/static/src/printer/device_print.xml`;
- `addons/mb_label_pos/static/src/scanner_enhancements.xml`; and
- `addons/mb_webshop_carrier_base/report/local_handover_report.xml`.

Actions: mechanically replace output directives without changing expression or DOM
structure; inspect contexts involving markup/`Markup` values before replacement;
keep escaping enabled and do not introduce `t-raw`; add a static rule rejecting new
`t-esc` directives in repository-owned addon XML.

Tests and acceptance: server QWeb reports render without deprecation warnings;
OWL templates compile and browser tests pass; snapshot/semantic assertions cover key
report values; repository search returns no `t-esc=` in owned files.

### LOG-01 — Remove production printer protocol logging

Owner: Agent F
Priority: low
Files: `addons/mb_label/static/src/printer/phomymo/ble.js`, `raster.js`,
`printer.js`, and the broad asset glob in `addons/mb_label/__manifest__.py`

Actions:

1. Remove unconditional `console.log` calls that expose device names, protocol
   responses, packet data, or operational details. Route genuinely useful diagnostics
   through a small logger disabled by default and enabled only by an explicit debug
   option.
2. Redact device identifiers and payload bytes even in debug summaries unless the
   user explicitly requests a diagnostic export.
3. Replace the broad backend glob with explicit production entry points or ensure
   vendor/debug-only modules cannot be loaded accidentally. Keep unit-test-only
   helpers in the unit-test bundle.

Tests: production print/mount path emits no console log containing device name or
packet bytes; explicit debug mode is bounded/redacted; printer fixture tests pass.

### UX-01 — Resolve label app/menu semantics and carrier field labels

Owner: Agent F with product decision by integration owner
Priority: low

Actions:

1. `mb_label` declares `application=True` but its menu sits under Inventory. Decide
   whether Label Studio is a standalone app. Recommended: set `application=False`
   while it remains an Inventory child; choose a root app only with an approved
   navigation design and access-group review.
2. Qualify duplicated parcel dimension/content labels and help text in the Boxtal and
   Sendcloud carrier extensions where Odoo reports same-label ambiguity. Prefer a
   shared base field when semantics are identical; otherwise use provider-qualified
   labels and make visibility conditional on provider type.

Acceptance: app switcher/navigation matches the decision; each visible carrier field
is unambiguous; no runtime duplicate-label warning remains.

### FMT-01 — Mechanical XML/SCSS cleanup and relational-command inventory

Owner: Agent F
Priority: low; merge last

Files include compressed XML in `commercial_planning_views.xml`,
`commercial_operation_report.xml`, and `urssaf_rate_views.xml`, plus compressed
`mb_label/static/src/editor/label_editor.scss` and 51 XML relational tuple commands
such as `[(4, ref(...))]`.

Actions:

1. Reformat XML and SCSS with repository-approved tools/settings only. Preserve node
   order, whitespace-sensitive QWeb output, XPath structure, and selector behavior.
2. Inventory relational tuple commands but do not treat them as deprecated: forms
   such as `[(4, ref(...))]` remain valid in Odoo XML data, while `Command` is not
   generally available in the documented XML evaluation context. Keep valid tuples.
   Convert a tuple only when the exact loader context is proven to expose `Command`,
   the semantic operation is unchanged, and fresh-install plus repeated-upgrade tests
   demonstrate that no user-created relation is removed.
3. Keep this work in a mechanical PR with no security, behavior, data, translation,
   or generated-file changes. Review the diff structurally and render affected views
   and reports.

Acceptance: all XML parses, views install, reports render, assets compile, the
relational-command inventory records which valid tuples remain and why, and visual
snapshots show no unintended change. There is no artificial zero-tuple target and no
static rule rejects valid Odoo XML commands.

## 5. Proposed PR and merge sequence

| PR | Owner | Packages | Merge gate |
|---|---|---|---|
| 01 | Integration | BASE-01 | current static/server baseline archived |
| 02 | Agent D/Integration | MIG-01 | predecessor upgrade, repeated upgrade, uninstall, and concurrency targets execute |
| 03 | Agent D | DATA-01 | v2 label remains current after repeated upgrade |
| 04 | Agent S | SEC-01 | RPC denial plus controller contract tests |
| 05 | Agent S | TXN-01, TXN-02 | late-failure and concurrent-idempotency matrix |
| 06 | Agent S | MC-01 | lowest-permission rent-period company isolation |
| 07 | Agent S/D | MC-02 | stock-hold backfill and company isolation |
| 08 | Agent D | DEP-01 | dependency checker and isolated installs |
| 09 | Agent D | CON-01, CON-02 | deterministic two-cursor URSSAF tests |
| 10 | Agent D | CON-03 | kiln concurrency tests preserving current state semantics |
| 11 | Agent D | CON-04 | depot contract concurrency tests |
| 12 | Agent D | CON-05 | lot-allocation database constraint and migration |
| 13 | Agent D | CON-06 | production-capacity concurrency tests |
| 14 | Agent D | DATA-02 | default/version concurrency and upgrade tests |
| 15 | Agent D | DATA-03 | company-scope decision and seed migration tests |
| 16 | Agent D | DATA-04 | compute invalidation and query-budget tests |
| 17 | Agent D | PERF-01 | bounded supplier matching and backfill tests |
| 18 | Agent D | ORM-01 | deletion and uninstall tests |
| 19 | Agent F/Integration | ASSET-01, CI-01 | resolved asset graph and non-zero Hoot suite |
| 20 | Agent F | OWL-01 | listener and dialog lifecycle tests |
| 21 | Agent F | LOG-01 | console-redaction tests |
| 22 | Agent F | QWEB-01 | isolated QWeb render/escaping conversion |
| 23 | Agent F | UX-01 | approved navigation and carrier-label behavior |
| 24 | Agent F | FMT-01 | structural/visual no-change review |
| 25 | Integration | REL-01 | complete release matrix below |

PRs 09–13 may be developed in parallel because they own different model files, but
merge sequentially so the shared concurrency helper has one source. PR 19 should be
developed early in parallel to expose frontend failures, while its edits to shared
manifests and CI remain under one owner. QWeb, UX, logging, ORM, dependencies,
performance, and formatting stay in separate PRs so each can be reviewed and rolled
back independently.

## 6. Data migration and rollout protocol

For every change that requires a data or schema migration:

1. Bump the affected manifest version and add the migration to the directory for that
   exact target version. Put violation detection in the appropriate pre-migration or
   in a separately rehearsed operator preflight. Report actionable IDs, companies,
   keys, and date ranges; abort rather than delete, merge, or pick winners.
2. Take a tested database backup before production upgrade. Restore it into staging
   and run the exact target image and module versions.
3. Backfill new stored fields in bounded batches when volume warrants it; validate
   non-null/company consistency before adding the final constraint.
4. Create unique indexes only after duplicate preflight. For large production tables,
   choose either normal transactional creation or a separately executed and verified
   online maintenance step; never place `CREATE INDEX CONCURRENTLY` inside Odoo's
   module-upgrade transaction.
5. Run post-migration assertions: zero overlaps/duplicates, zero null company IDs,
   every intended company has seeds, and no current label version regressed.
6. Deploy application code and constraints in a safe expand/enforce sequence. Do not
   roll application code back past a new invariant unless the old code also respects
   it.
7. After upgrade, monitor authorization denials, controller error codes, deadlocks,
   serialization/unique violations, asset compilation, job retries, and browser errors.

## 7. Final validation matrix (REL-01)

Owner: integration owner

| Gate | Required evidence |
|---|---|
| Static | `make check`, XML parse, manifest/dependency policy, no unintended formatter scope |
| Fresh install | every add-on installs from only its declared dependency closure |
| Server regression | `make test`; zero failures/errors and non-zero tests per intended module |
| Upgrade | `make upgrade-test` builds the pinned predecessor fixture, runs target-version migrations, upgrades twice idempotently, and preserves label v2 |
| Uninstall | `make uninstall-test` removes every module with deletion guards on a disposable database |
| Security | generic RPC denial matrix and lowest-permission two-company CRUD matrix |
| Transactions | injected failure after each mutation stage leaves no partial business state |
| Concurrency | `make concurrency-test` runs synchronized independent-connection tests for all six invariants and receipt races |
| Assets | `make assets-test` verifies primary sub-bundle order and compiles backend/frontend/POS/unit-test consumers from a clean cache |
| Browser | `make browser-test` discovers the expected Hoot suites with zero failures, unexpected console errors, or leaked listeners |
| Reports | affected QWeb reports render with correct escaping and no `t-esc` warning |
| Performance | supplier matching and kiln counters meet recorded query/cardinality budgets |
| Manual hardware | documented smoke test on supported scanner/camera and representative printers |

Release acceptance requires all automated gates green on the same commit and staging
upgrade evidence reviewed by the four owners. Do not waive a concurrency, security,
upgrade, or asset failure as flaky or warning-only without a root cause and a new
tracked work package.

## 8. Issue traceability

| Audit finding | Work package |
|---|---|
| Public privileged control/email/capture model services reachable by RPC | SEC-01 |
| Caught controller exceptions can commit partial writes | TXN-01 |
| Email controller calls ambient `cr.rollback()` | TXN-02 |
| Accounting users lack a rent-period company rule | MC-01 |
| Webshop stock holds lack company isolation | MC-02 |
| URSSAF declaration/rule overlap races | CON-02 |
| Kiln occupancy race | CON-03 |
| Depot contract/rent-period overlap race | CON-04 |
| Lot allocation search-then-check race | CON-05 |
| Board aggregate-capacity race | CON-06 |
| Brand Sass relative import fails in Odoo bundle compilation | ASSET-01 |
| WIP label version reset on module upgrade | DATA-01 |
| Default-label constraint ignores `active` and races | DATA-02 |
| Label seeds exist only for installation company | DATA-03 |
| Kiln counters lack dependable invalidation/batching | DATA-04 |
| Invoice supplier matching loads all active company partners | PERF-01 |
| Pure unlink vetoes can block uninstall | ORM-01 |
| Direct XML/model owners omitted from manifests | DEP-01 |
| CI omits asset compilation and Hoot/browser suites | CI-01 |
| Label editor leaks global pointer listeners and uses `window.confirm` | OWL-01 |
| 59 deprecated `t-esc` directives | QWEB-01 |
| Printer code emits unconditional device/protocol logs | LOG-01 |
| Label manifest/menu mismatch and ambiguous carrier labels | UX-01 |
| Compressed formatting and 51 relational tuple commands requiring classification | FMT-01 |

## 9. Definition of done for each issue

An issue is not closed when code merely looks idiomatic. It is closed when the
smallest relevant test fails on the pre-fix revision, passes with the fix, its data
upgrade is idempotent, its rollback implications are recorded, and the phase-level
gates remain green. Any new issue discovered while executing this plan receives a
new ID, severity, owner, dependency, regression test, and traceability entry before
implementation continues.
