# CI runner-minutes optimization plan

Status: candidate implemented; hosted-runner qualification pending
Prepared: 2026-09-05
Scope: `.github/workflows/ci.yml`, its Make targets, and supporting CI tools

## 1. Objective

Reduce GitHub Actions runner minutes without weakening the evidence required to
release the 41 Odoo add-ons. The target is at least a 30% reduction in median
runner minutes for an add-on pull request, measured over ten representative runs,
while preserving:

1. a clean Odoo database for installation and server-test validation;
2. a real pinned-predecessor upgrade followed by a repeated idempotent upgrade;
3. an uninstall of every repository add-on;
4. all 703 server tests, including the 18 independent-connection concurrency tests;
5. clean-cache compilation of all four asset consumers;
6. all 31 Hoot tests with browser-console checking;
7. translation extraction from an installed database; and
8. an exact-commit successful CI result before release.

Optimization must not cache a successful test conclusion, reuse a database from a
different commit, or allow path filtering to suppress the full `main` validation.

## 2. Current state and sources of cost

The workflow already has useful controls:

- `push` is limited to `main`, while feature work runs through `pull_request`, so a
  normal feature-branch push does not create a second push workflow;
- `cancel-in-progress` stops superseded runs for the same ref;
- a changed-path job skips container lanes for non-Odoo changes;
- the fast static job gates all container work;
- npm uses the setup-node cache; and
- the release workflow checks that the exact commit already passed CI.

The remaining waste is repeated environment preparation. When an add-on changes,
eight container-oriented jobs independently pull or start images and install all
41 add-ons. In particular:

| Current lane | Duplicate work |
|---|---|
| Clean install | The server-test lane also installs all add-ons on a new database. |
| Concurrency invariants | The same 18 tests are selected by the full `/module` server suite. |
| Asset compilation | Installs the same add-ons needed by the browser lane. |
| Hoot browser tests | Repeats the asset lane's database initialization and installation. |
| Upgrade and uninstall | Need distinct database states, but repeat runner, image, and Compose startup. |
| Static | Caches npm, but reinstalls Ruff, mypy, and polib on every run. |

Parallel jobs reduce elapsed wall time but GitHub bills the sum of their runner
time. The first changes should therefore eliminate entire installations before
adding caches whose transfer time may exceed their benefit.

## 3. Safety rules

1. A test result is valid only for its exact commit and pinned Odoo/PostgreSQL image
   digests. Never restore a green-result marker from `actions/cache`.
2. Database caches are prohibited for correctness gates. Schema, registry metadata,
   asset attachments, external IDs, and `noupdate` state make cross-commit database
   invalidation too fragile.
3. Pull requests may use conservative lane-level path routing. Every `main` push and
   manual dispatch runs the complete validation matrix.
4. Do not target only the directly changed add-on unless the complete reverse
   dependency graph is calculated. Odoo inheritance makes filename-only module
   selection unsafe.
5. The full server suite remains the canonical Python test result. A focused lane
   may be removed only after proving its tests are discovered by that suite.
6. Asset and browser checks may share a database only within the same workflow job
   and exact checkout. They may not consume a database artifact from another run.
7. Cache keys must include the relevant lock file, tool version, runner OS and
   architecture. Untrusted pull requests must not be able to overwrite protected
   release caches.
8. Required-check names must be coordinated with branch protection before jobs are
   removed or renamed.

## 4. Target workflow

The end state has seven substantive jobs instead of ten:

```text
changes ─┬─> static ─┬─> server (clean install + all server/concurrency tests)
         │           ├─> upgrade
         │           ├─> uninstall
         │           ├─> frontend (one install + assets + Hoot)
         │           `─> i18n
         `──────────────────────────────────────────────────────────────┐
                                                                        v
                                                                  required gate
```

The final required gate is a lightweight result aggregator only if the repository
uses one stable branch-protection check. If branch protection lists every job,
migrate those settings before deleting old job names; do not retain permanent
one-minute no-op compatibility jobs.

When used, the aggregate job must list `changes`, `static`, and every routed lane in
`needs` and run under `if: always()`. It fails closed according to both the
classifier outputs and job results: `changes` and `static` must succeed; every lane
whose output is true must succeed; and a lane may be skipped only when its output is
false. `failure`, `cancelled`, a missing result, or a selected-but-skipped lane makes
the aggregate fail. This prevents GitHub's skipped-`needs` propagation or an overly
broad `success-or-skipped` expression from turning incomplete validation green.

Upgrade, uninstall and i18n remain separate because they require incompatible
database lifecycle or working-tree behavior. Combining them would save startup
time but reduce failure isolation and make reruns more expensive.

## 5. Work packages

### CI-MIN-01 — Establish a runner-minute baseline

Files: `docs/ci-minutes-optimization-evidence.md`, optional read-only metrics tool

Actions:

1. Query the GitHub Actions API for the last 20 completed non-documentation CI runs.
2. Record per-job queued time, execution time, conclusion, cancellation status, and
   total summed runner time. Calculate median and p95 values separately for pull
   requests and `main` pushes.
3. Record timestamps around image acquisition, database initialization, add-on
   installation, tests, asset compilation, and Hoot execution. Use step summaries;
   do not add a third-party telemetry service.
4. Record the current job count, server/concurrency/Hoot test totals, asset bundle
   count, and number of add-ons installed/upgraded/uninstalled.
5. Select three representative change fixtures: documentation-only, frontend-only,
   and backend/model-plus-migration.

Acceptance: the baseline can answer which setup/install repetitions consume the
most summed runner time. No optimization is accepted solely from local timing.

### CI-MIN-02 — Make path classification explicit and testable

Files: `.github/workflows/ci.yml`, `tools/ci_changed_paths.py`,
`tools/test_ci_changed_paths.py`

Replace the inline single `odoo=true/false` regex with a small deterministic tool
that emits these outputs:

| Output | Conservative trigger |
|---|---|
| `full` | `main`, workflow dispatch, force-push fallback, or classifier uncertainty |
| `server` | Add-on Python/XML/CSV, manifests, security, config, dependency, packaging, or server-test tooling |
| `upgrade` | Add-on manifests/migrations/data/model/schema work or migration tooling/matrix |
| `frontend` | Add-on JS/XML/SCSS/CSS/assets, relevant manifests, package locks, brand projection, Hoot/asset tooling |
| `i18n` | Translatable Python/XML/JS plus PO/POT or translation tooling |
| `lifecycle` | Model, constraint, hook, manifest, access, migration, or uninstall tooling |

Rules:

1. `full=true` implies every other output is true.
2. Unknown files under `addons/`, `tools/`, `config/`, `dependencies/`, or `deploy/`
   fail open by enabling all relevant lanes.
3. Changes to the workflow, Makefile, classifier, or its tests run all lanes.
4. Documentation-only changes run static validation but skip container lanes, except
   migration-matrix documentation, which runs upgrade validation.
5. Add table-driven tests for every file class and for mixed changes.

Acceptance: classifier unit tests include positive, negative, mixed and unknown-path
canaries; a `main` event can never produce a partial matrix.

### CI-MIN-03 — Fold clean installation into the server lane

Files: `.github/workflows/ci.yml`, `Makefile`, server-test invocation

Actions:

1. Confirm the server lane starts with an absent database and installs the packaged
   extension containing all 41 manifests.
2. Preserve the current server and clean-install demo-data semantics during this
   consolidation. Neither current lane passes `--without-demo`, so adding that flag
   here would be a behavior change rather than a runner-minute optimization. If a
   production-oriented no-demo server gate is desired, qualify it in a separate PR:
   first run both old lanes with `--without-demo`, update tests that improperly rely
   on demo records, and establish a new baseline before consolidating them.
3. Preserve the module discovery assertion and fail if zero modules or tests are
   selected.
4. Add a post-run assertion that all 41 repository modules are installed and that
   every intended test-owning module reports a non-zero count.
5. Run the old clean-install job and the new server job side by side for two trial
   commits. Compare installed module state and logs.
6. Remove the standalone clean-install job only after both trials agree.

Acceptance: a deliberately broken manifest/data path fails the consolidated server
lane; all 703 tests pass on a fresh database with the same demo-data mode as both
comparison lanes; all 41 modules are installed.

Rollback: restore the standalone install job. No application code or database
migration is affected.

### CI-MIN-04 — Remove duplicate focused concurrency execution

Files: `.github/workflows/ci.yml`, `Makefile`, test-discovery assertion tooling

Actions:

1. Prove that the full `/module` selection discovers each concurrency class and all
   18 tests, including `post_install` classes.
2. Add a static inventory mapping the seven invariant groups to their owning test
   classes. Fail CI if a class is renamed, loses its import, or is no longer selected
   by the server suite.
3. Keep `make concurrency-test` as a local diagnostic command.
4. For pull requests, remove the standalone concurrency job after the full-suite
   discovery assertion is active.
5. Optionally retain a scheduled focused stress run with repetitions if it provides
   evidence different from a single full-suite execution. A one-pass duplicate does
   not justify a separate lane.

Acceptance: the consolidated server log contains all 18 concurrency tests and ends
with zero failures/errors. Removing or mistagging any concurrency class makes the
inventory check fail.

Rollback: re-enable the focused job; the Make target remains available.

### CI-MIN-05 — Share one frontend database

Files: `.github/workflows/ci.yml`, `Makefile`, `tools/odoo_asset_gate.py`,
`tools/run_hoot.mjs`

Refactor the current wrapper targets into preparation and check-only layers:

```text
frontend-test
  reset allowlisted database
  install all 41 add-ons once without demo data
  run asset-check against that database
  run browser-check against the same database
```

Keep `assets-test` and `browser-test` as safe standalone developer commands; each
continues to prepare its own clean database. `frontend-test` reproduces the combined
sequence locally; CI calls the same preparation and check-only layers as separate
steps in one job so Actions records phase timings.

Actions:

1. Extract `assets-check` so it clears/rebuilds asset attachments without resetting
   or reinstalling the database.
2. Extract `browser-check` so it launches the pinned Playwright container against an
   already prepared database.
3. Make `frontend-test` prepare once and call both check-only targets.
4. Preserve separate asset and browser logs and upload them only on failure.
5. Ensure asset compilation does not leave state that changes Hoot discovery or test
   behavior. Run Hoot both before and after the asset gate once during qualification
   to prove order independence; then use assets-first in CI.

Acceptance: four asset consumers compile with eight generated attachments, followed
by 31/31 Hoot tests and no browser-console errors, after exactly one add-on install.

Rollback: point the two workflow jobs back to their standalone targets.

### CI-MIN-06 — Keep lifecycle gates independent but reduce avoidable setup

Files: `.github/workflows/ci.yml`, `tools/upgrade-test.sh`, Make targets

Upgrade and uninstall validate incompatible states, so do not share a database. Use
these lower-risk savings instead:

1. Ensure each job pulls/starts a pinned image at most once.
2. Avoid repeated `docker compose up` calls inside a target after services are healthy.
3. Reuse the same containers within each target while resetting only the allowlisted
   database.
4. Keep the full pinned predecessor add-on tree initially. The seven
   migration-bearing modules depend on repository modules outside that set, so
   copying only those seven is not a valid fixture. Materialization may be narrowed
   later only by computing the complete transitive repository dependency closure
   from the predecessor manifests, copying every module in that closure, and failing
   if an expected local dependency is unresolved. Continue updating only the seven
   migration-bearing candidate modules.
5. On pull requests, use the classifier to run upgrade only for changes that can
   alter installed schema/data/version behavior. Always run it on `main`.
6. Run uninstall for model, hook, manifest, constraint and security changes; always
   run it on `main`.

Acceptance: the upgrade still starts from pinned commit
`632e043e166d15ceceb8846fea120e3d6e928023`, executes all eight phases twice, and
passes stable fingerprints. Any optimized predecessor fixture contains the complete
validated repository dependency closure. Uninstall still removes all 41 add-ons.

### CI-MIN-07 — Add only measured dependency/build caches

Files: `.github/workflows/ci.yml`, dependency/tool lock metadata

Actions:

1. Retain the existing npm cache keyed by `package-lock.json`.
2. Measure Ruff, mypy and polib installation time. Only add a pip/uv cache if the
   median saving exceeds 20 seconds and cache restore is faster than installation.
3. If added, key the cache by runner OS/architecture, Python version, and the pinned
   Ruff/mypy/polib versions. Do not use a broad restore key across Python versions.
4. Do not store Odoo or PostgreSQL databases in `actions/cache`.
5. Do not cache `node_modules`; cache the package-manager download store and continue
   using `npm ci` for reproducible installation.
6. Measure the extension transport-image build separately. If it is material, use a
   commit-scoped artifact within the same workflow or BuildKit's content-addressed
   GitHub cache. Never use an unverified mutable image tag as test input.
7. Measure Docker image save/restore before considering it. The pinned Odoo and
   Playwright images are large, and artifact/cache transfer can cost more time than a
   registry pull. Default to no Docker tar cache until data proves otherwise.

Acceptance: every new cache reports its key and hit/miss state in the step summary;
cold-cache behavior remains fully functional; no cache is required for correctness.

### CI-MIN-08 — Preserve exact-commit and cancellation semantics

Files: `.github/workflows/ci.yml`, `.github/workflows/release.yml`

Actions:

1. Keep feature pushes from triggering both `push` and `pull_request` workflows.
2. Change the concurrency group to use the pull-request number when available and
   the ref otherwise, preventing accidental collisions between unrelated refs while
   still cancelling superseded commits.
3. Keep manual dispatch as an intentional retest even when the SHA previously passed.
4. Do not query an old successful run to skip current CI: action definitions, secrets,
   base branch, image availability and workflow inputs may have changed.
5. Tighten the release workflow's exact-SHA verification to query the CI workflow by
   workflow file or immutable workflow ID, not by display name alone. Eligible
   evidence must have the exact release SHA, `head_branch == main`, a completed
   successful conclusion, a successful aggregate required gate, and an event that
   always runs the complete matrix (`push` or an explicitly full
   `workflow_dispatch`). A path-filtered `pull_request` run is never release
   evidence, even when its SHA matches.
6. Release must not rerun the complete test matrix, but it must refuse a commit with
   no eligible full-validation run. Verify in particular that a completed partial PR
   run cannot satisfy release while the full `main` run is pending or failed.
7. Verify that cancelled runs cannot be selected as successful release evidence.

Acceptance: pushing two commits quickly to one PR cancels the older run; unrelated
PRs do not cancel each other; release accepts only a completed successful full CI
run on `main` for the exact release SHA and rejects a same-SHA PR-only success.

### CI-MIN-09 — Update branch protection and documentation

Files: repository settings, `README.md`, CI comments, evidence document

Actions:

1. Inventory the currently required GitHub check names before renaming/removing jobs.
2. Introduce a stable aggregate check if desired. Give it explicit `needs` for the
   classifier, static job, and every routed lane; run it with `if: always()`; and
   implement the fail-closed classifier/result contract defined in Section 4. Require
   it in branch protection and only then remove obsolete required checks.
3. Update the stale CI comment that gives a fixed add-on mypy file count; use
   “hundreds of add-on files” so normal repository growth does not create drift.
4. Document which PR paths select each lane and how to force a complete run.
5. Record before/after metrics and the exact test/install/upgrade/uninstall totals.

Acceptance: a pull request cannot merge when any required selected lane fails, is
cancelled, or is unexpectedly skipped; an intentionally skipped non-applicable lane
does not leave branch protection waiting indefinitely.

## 6. Implementation sequence

| PR | Work | Required gate before merge |
|---|---|---|
| 1 | CI-MIN-01 baseline and CI-MIN-02 classifier with tests | Current ten-job workflow passes unchanged |
| 2 | CI-MIN-05 combined frontend target | Old asset/browser jobs and new combined target produce identical results |
| 3 | CI-MIN-03 consolidated install/server lane | Two side-by-side successful trial commits |
| 4 | CI-MIN-04 concurrency deduplication | Discovery inventory proves all 18 tests run in the full suite |
| 5 | CI-MIN-06 lane routing for upgrade/uninstall | PR fixtures exercise every classifier branch; predecessor dependency closure is complete; `main` remains full |
| 6 | CI-MIN-07 measured caches, if justified | Cold and warm cache runs both pass; measured net saving |
| 7 | CI-MIN-08/09 required-check migration and documentation | Branch-protection audit and release exact-SHA test |

Do not combine the consolidation and path-routing changes in one PR. First prove that
the same work executes with fewer installations; then decide when each lane runs.
This makes a missed test distinguishable from a routing mistake.

## 7. Validation matrix

For every phase, run these fixtures through both the old and candidate workflow:

| Fixture | Expected candidate behavior |
|---|---|
| Markdown-only documentation | Static only; no container lane. |
| Python model change | Static, server, lifecycle as classified, i18n; full suite on `main`. |
| Migration and manifest version change | Static, server, upgrade, uninstall, i18n. |
| SCSS/JS/Hoot-only change | Static and combined frontend; server only if a manifest or backend contract changed. |
| PO/POT-only change | Static catalogue checks and i18n freshness. |
| Makefile/workflow/classifier change | Complete matrix. |
| Unknown new add-on file type | Fail open to complete matrix. |
| Two rapid PR commits | First run cancelled; second completes. |
| Manual rerun of a passed SHA | Complete explicitly requested run executes. |
| Same-SHA partial PR success while `main` CI is pending or failed | Release verification rejects the PR run as ineligible evidence. |
| Migration-bearing predecessor module with a repository-local dependency | The pinned dependency is materialized from the predecessor commit and the upgrade completes. |

The final candidate must still report:

- Ruff lint/format/import ordering green;
- mypy green for all tool source files and the advisory add-on scope;
- 41 installed modules and 703 server tests;
- 18 concurrency tests discoverable within those 703 tests;
- eight migration phases across seven add-ons, executed twice;
- 41 modules uninstalled;
- four compiled asset consumers and eight generated attachments; and
- 31 completed Hoot tests with no failures or browser-console output.

Counts may legitimately increase as tests are added. They must never decrease without
an explicit reviewed update to the expected inventory.

## 8. Success metrics and stop conditions

Success requires all of the following over ten comparable add-on pull-request runs:

1. median summed runner minutes decrease by at least 30%;
2. p95 workflow wall time does not increase by more than 10%;
3. no reduction in test, module, migration, asset or browser discovery counts;
4. no increase in reruns caused by flaky database, cache or path-classifier behavior;
5. documentation-only changes start no container jobs; and
6. `main` and manual dispatch still execute the complete matrix.

Stop and roll back the responsible phase if a required test disappears, a cache hit
changes behavior, a path is misclassified, a stale database affects a result, or the
optimization saves less time than it adds in artifact/cache transfer. Correctness
evidence takes precedence over runner-minute reduction.
