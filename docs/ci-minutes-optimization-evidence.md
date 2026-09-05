# CI runner-minutes optimization evidence

Status: candidate implemented; hosted-runner qualification pending
Baseline queried: 2026-09-05
Source: GitHub Actions API for `MakersBrain/mb-odoo-addons`, workflow `ci.yml`

## Measurement method

The baseline selects the 20 most recent completed CI runs in which at least one
container lane actually started. Skipped jobs contribute zero runner time. For
each run, summed runner time is the sum of `completed_at - started_at` across
jobs; wall time is workflow `updated_at - created_at`. Job start delay is
`started_at - workflow.created_at`; it includes dependency waiting and runner
queueing and therefore is not presented as pure GitHub queue latency.

The sample contains 12 pull-request runs and eight `main` pushes. It contains 17
successful and three failed pull-request/main runs and deliberately retains the
failures so the baseline is not biased toward fast green runs.

## Historical baseline

| Population | Runs | Median summed runner min | p95 summed runner min | Median wall min | p95 wall min |
|---|---:|---:|---:|---:|---:|
| Pull requests | 12 | 9.65 | 17.90 | 5.35 | 7.20 |
| `main` pushes | 8 | 9.43 | 17.77 | 5.16 | 7.17 |

| Historical job | Observations | Success | Failure | Median execution min | Median start delay min |
|---|---:|---:|---:|---:|---:|
| Changed paths | 20 | 20 | 0 | 0.09 | 0.05 |
| Static checks | 20 | 20 | 0 | 1.06 | 0.03 |
| Clean install | 20 | 20 | 0 | 1.48 | 1.13 |
| Upgrade in place | 20 | 20 | 0 | 1.51 | 1.15 |
| Catalogue freshness | 20 | 17 | 3 | 3.90 | 1.13 |
| Server tests | 16 | 16 | 0 | 1.46 | 1.19 |
| Older combined server/browser job | 4 | 4 | 0 | 6.59 | 0.34 |

Historical step timings confirm that whole-lane consolidation is the useful
optimization and dependency caching is not. Across the same recent API sample,
the clean-install step had 18 observations and a 67-second median, while the
standalone server suite had 16 observations and a 66-second median. In contrast,
`npm ci` had a two-second median across 20 observations, the pinned Ruff/mypy
installation had a six-second median across ten comparable observations, and
polib installation had a one-second median across 20 observations. These are
well below the plan's 20-second cache threshold, so the candidate retains only
the existing setup-node download cache and adds no Python, database, Docker-tar,
or result cache.

These hosted runs predate the unpushed remediation working tree that expanded CI
to ten jobs by adding predecessor-upgrade, uninstall, focused concurrency, asset,
and Hoot lanes. Consequently they are a historical cost reference, not sufficient
evidence for the plan's 30% acceptance claim. There are no hosted measurements of
that ten-job intermediate design. The claim remains pending until the candidate
workflow has ten comparable add-on pull-request runs.

## Candidate implementation

The candidate has eight jobs: changed paths, static checks, server, predecessor
upgrade, uninstall, catalogue freshness, combined frontend, and the stable
`Required CI` aggregate. It removes three complete duplicate installations:

- clean install is proven by the fresh server-test installation;
- the 18 focused concurrency tests remain in the 703-test full suite; and
- asset and Hoot checks share one exact-commit, no-demo database.

The classifier is fail-open for unknown runtime paths. All `main` pushes and
manual dispatches select every lane. The aggregate fails when a selected lane is
failed, cancelled, missing, or skipped. Release admission accepts only an exact-SHA
successful full run on `main` whose `Required CI` job succeeded.

Current preserved inventories:

| Evidence | Required count |
|---|---:|
| Repository add-ons installed/uninstalled | 41 |
| Server tests | at least 703 |
| Independent-connection concurrency tests | 18 across seven groups |
| Migration phases | eight across seven add-ons, applied twice |
| Asset consumers/generated attachments | four/eight |
| Hoot tests | 31 |

## Local candidate qualification

The exact candidate targets were exercised on 2026-09-05 against the pinned
Odoo 19 and PostgreSQL images:

| Gate | Result |
|---|---|
| Static and policy suite (`make check`) | Passed; 34 negative/unit canaries, 41 add-ons, eight migration phases, and the 18-test concurrency inventory validated. |
| Consolidated server lane | Passed; fresh database, 41 repository modules installed, 703 tests, zero failures/errors, and all seven concurrency classes present in the log. |
| Predecessor upgrade | Passed; pinned predecessor `632e043e166d15ceceb8846fea120e3d6e928023` upgraded through eight phases twice. |
| Uninstall | Passed; all 41 repository modules removed and post-uninstall assertions succeeded. |
| Combined frontend | Passed after one no-demo installation; four consumers produced eight attachments, then all 31 Hoot tests passed with an empty browser-console error list. A separate qualification installation also passed 31/31 Hoot tests both before and after asset compilation, proving order independence. |
| Workflow syntax/action lint | Both CI and release workflows passed YAML parsing and `actionlint`. |
| Release admission canaries | Exact-SHA full push/dispatch accepted; partial PR, cancelled, failed, pending, wrong-branch, wrong-SHA, missing aggregate, and failed latest rerun rejected. |

During frontend qualification, the persistent web process observed the database
while the one-time installation was still in progress and cached a partial Odoo
registry. The preparation target now restarts the web service after installation
and waits for health before either check-only phase. This preserves the single
installation while ensuring both assets and Hoot use a complete registry.

## Qualification and stop condition

After this workflow reaches a branch, record ten comparable add-on pull-request
runs here, separated from documentation-only runs. Acceptance requires at least a
30% reduction from the appropriate pre-candidate sample, no more than a 10% p95
wall-time increase, unchanged-or-higher discovery counts, and no new classifier,
database, or cache-related reruns. No dependency or Docker cache was added because
the available evidence does not yet prove a net saving.

Branch protection currently requires `Static checks`, `Clean install`, `Upgrade in
place`, `Catalogue freshness`, and `Server tests`. Do not remove those contexts
until `Required CI` exists on the default branch. Immediately after that first full
run, require `Required CI`, verify it blocks a failing selected lane, and then remove
the obsolete contexts.
