# Odoo add-ons remediation evidence

Recorded on 2026-09-05 for the implementation of
`docs/odoo-addons-remediation-plan.md` across all 41 repository add-ons.

## Outcome

All identified code, data, security, transaction, concurrency, migration,
frontend, formatting, dependency, and CI findings have been remediated. All
automated REL-01 gates pass. The remaining physical scanner, camera, and printer
smoke test is an operational deployment-site check, not an unresolved source-code
finding.

The work was split across three specialist review tracks—security/transactions,
data integrity/migrations, and frontend/CI—with final integration and validation
performed against the shared candidate tree.

## Issue closure

| Package | Implemented result | Primary regression evidence |
|---|---|---|
| SEC-01 | Privileged control, email, and capture services are private to model RPC and remain callable through authenticated controllers. | Static AST policy canaries and controller/RPC denial tests. |
| TXN-01, TXN-02 | Controller mutations use savepoint-scoped atomic operations; caught failures cannot commit partial state and no controller performs an ambient rollback. | Injected late-failure tests and transaction policy canaries. |
| MC-01, MC-02 | Rent periods and stock holds are company-owned, backfilled, constrained, and protected by company rules for every ACL-bearing group. | Lowest-permission multi-company CRUD tests and migration assertions. |
| CON-01 through CON-06 | URSSAF overlaps, kiln occupancy, depot contracts, lot allocations, board capacity, and operation receipts serialize or reject a loser at the database boundary. | Eighteen synchronized independent-connection tests across seven invariant groups. |
| DATA-01 through DATA-04 | Label versions are upgrade-safe; active defaults are unique; company seed projection is explicit and idempotent; stored kiln counters invalidate and batch correctly. | Pinned-predecessor upgrades run twice, fingerprint assertions, concurrency tests, and query-budget tests. |
| PERF-01 | Supplier matching is company-scoped and bounded rather than loading all active suppliers. | Cardinality/query-budget regression tests. |
| ORM-01 | Business deletion vetoes use uninstall-safe Odoo deletion hooks. | Full 41-add-on uninstall and deletion-guard tests. |
| DEP-01 | Manifests declare direct model/XML owners and dependency-policy checks enforce the rule. | Dependency policy and isolated fresh installation. |
| ASSET-01, CI-01 | The brand Sass graph compiles in each consumer; CI now covers static, install, upgrade, uninstall, concurrency, i18n, server, assets, and browser gates. | Clean-cache asset compilation and parsed ten-job workflow. |
| OWL-01 | Label editor listeners and dialogs follow OWL lifecycle and service idioms. | Hoot lifecycle/dialog suites. |
| QWEB-01 | Deprecated escaping directives were replaced while preserving rendered escaping. | Native report-render tests and static catalogue checks. |
| LOG-01 | Production printer paths do not emit device or payload details; diagnostics are explicit and redacted. | Printer protocol/logging Hoot tests. |
| UX-01 | Label Studio navigation matches its Inventory-child role and provider fields have unambiguous labels. | Manifest/view validation and browser suites. |
| FMT-01 | Flagged XML and SCSS were structurally formatted without semantic tuple rewrites. All 51 XML relational tuple commands are classified. | XML parse/render gates and `docs/odoo-xml-relational-command-inventory.md`. |
| MIG-01 | A reproducible pinned-predecessor fixture, migration matrix, assertions, repeated-upgrade target, and uninstall target are available locally and in CI. | Eight migration phases across seven add-ons upgraded twice. |

## Final automated gate results

| Gate | Command/evidence | Result |
|---|---|---|
| Static and policy | `make check` | Passed: Ruff lint/format, import order, typed tooling, 41 translation catalogues, 82 catalogues, brand tokens, dependencies, 19 bridge endpoints, 11 policy canaries, 8 migration phases, and all 41 manifests/data/assets/security checks. |
| Fresh install and server regression | `make test DISPOSABLE_DB=mb_scratch` | Passed: all 41 add-ons installed; 703 tests, 0 failures, 0 errors. |
| Upgrade | `make upgrade-test DISPOSABLE_DB=mb_test` | Passed from predecessor `632e043e166d15ceceb8846fea120e3d6e928023`; seven candidate modules/eight phases upgraded twice with stable data and schema fingerprints. |
| Uninstall | `make uninstall-test DISPOSABLE_DB=mb_test` | Passed: all 41 repository add-ons installed and then uninstalled; no repository add-on remained installed. |
| Concurrency | `make concurrency-test DISPOSABLE_DB=mb_test` | Passed: 18 tests, 0 failures, 0 errors across seven invariant groups, including the receipt race. |
| Assets | `make assets-test DISPOSABLE_DB=mb_test` | Passed: backend, frontend, POS, and unit-test bundles compiled; 8 generated attachments and correct primary-variable ordering. |
| Browser | `make browser-test DISPOSABLE_DB=mb_test` | Passed: 31/31 Hoot tests (`mb_label` 18, `mb_inventory_capture` 3, `mb_label_pos` 10), no failed suites, failures, or browser-console output. |
| Workflow syntax | `yq eval '.' .github/workflows/ci.yml` | Passed for the ten-job CI workflow. |
| Patch hygiene | `git diff --check` | Passed. |

Expected error-level PostgreSQL messages in concurrency runs are assertions of the
loser path (unique or serialization rejection); Odoo's final summaries report zero
test errors.

## Operational follow-up

Before production deployment, restore a current production backup to staging and
run the same upgrade command against that data volume. At the deployment site,
perform the documented scanner/camera and representative printer smoke tests. These
checks validate environment- and device-specific behavior and do not require source
changes unless they expose a new defect.
