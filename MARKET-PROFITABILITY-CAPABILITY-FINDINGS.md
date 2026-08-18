# Market Profitability: Current Capability Findings

Date: 2026-08-17
Question answered: can we define a marketplace event, set what we intend to sell, enter
entry fee / commission / stand setup and teardown / worked hours, reuse the toll quote API,
and get an answer on whether the market is worth it?

Short answer: almost all of it already exists in `addons/mb_commercial_operations`. The
calendar is not the feature — it is one view (`calendar,list,form,pivot,graph`) on the
`mb.commercial.operation` model. Four gaps remain, listed at the end.

## 1. Defining the market event

Model: `mb.commercial.operation` — `addons/mb_commercial_operations/models/commercial_operation.py:9`

- `operation_type`: `market` (Market / Fair) | `attendance` (Venue Attendance) | `visit` (Site Visit) — line 21
- Organizer, partner, contract, project, analytic account, assigned users
- State machine: `draft -> quoted (Costed) -> approved -> scheduled -> in_progress -> done -> financially_closed`, plus `cancelled` — line 29
- Deadlines that matter for fairs: `application_deadline`, `payment_deadline`,
  `stock_preparation_deadline`
- Calendar and obligation-calendar views and menus:
  `views/commercial_operation_views.xml:169`, `views/commercial_contract_views.xml:146`,
  `views/mb_commercial_operations_menus.xml:17`
- Recurring markets are modelled as contracts with obligation occurrences
  (`models/commercial_contract.py`)

## 2. Hours: setup, service, teardown, worked

`commercial_operation.py:78-86`

- `expected_arrival`, `setup_duration_hours`, `service_start`, `service_end`,
  `teardown_duration_hours`, `expected_return`
- `planned_work_hours` — computed and stored from the above
- Costed in the scenario as `planned_work_hours * work_hourly_cost`
- `actual_work_hours` computed from timesheets, so planned vs real hours is comparable
  after the event

## 3. Entry fee, commission, stand cost

Two levels, both native.

Event level — `mb.commercial.cost.line` (`commercial_operation.py:801`):

- `category`: `travel`, `labour`, `rent`, `venue` (Venue / Stall), `accommodation`,
  `parking`, `fee` (Fee / Commission), `other` — line 818
- `calculation`: `fixed`, `hour`, `kilometre`, `day`, `revenue_percent`, `unit` — line 827
- So a percentage commission on turnover is a first-class line: `revenue_percent` resolves
  against the scenario revenue, falling back to `operation.expected_revenue`
  (`_compute_planned_amount`, line 864)
- `source_kind` traces where a line came from: `manual`, `travel` (quote), `contract`,
  `template`, `migration`. Multi-currency source amount, rate and conversion date are kept.
- Cost lines are locked once the operation leaves `draft`/`quoted`, and once a scenario is
  approved (create a revision instead) — lines 873-907

Product level — `mb.commercial.profitability.scenario.line`
(`models/profitability_scenario.py:255`):

- `channel_fee_rate` / `channel_fee_amount` (per-sale channel fee)
- `turnover_levy_rate` + `eligible_turnover_basis` (URSSAF / cotisation on turnover)
- `vat_rate` -> `customer_price_incl_vat`

## 4. What we plan to sell

`mb.market.stock.plan.line` — `commercial_operation.py:910`

- `target_type`: `product` (exact product) or `bucket` (assortment: product category +
  `price_min` / `price_max`)
- `priority`, `desired_opening_qty`, `safety_qty`, computed `required_qty`
- `expected_sold_qty`, `expected_unit_price`, `expected_unit_cost`
- These feed scenario lines via `source_stock_plan_line_id`; a warning fires if the
  scenario later drifts from its source stock plan line

## 5. Travel cost from the toll quote API

`models/travel_estimate.py`

- `mb.tollquote.connector` (line 13): environment, base URL, API token, timeout,
  health check with `last_health_at` / `last_health_status`
- `mb.travel.estimate` (line 121): origin/destination partner or coordinates, `round_trip`,
  `departure_at`, `vehicle_class`, `payment_option`, `fuel_consumption_l_per_100km`,
  `fuel_price_eur_per_l`, `driver_cost_eur_per_hour`
- Returns: `distance_km`, `duration_hours`, `toll_cost`, `fuel_cost`, `driver_cost`,
  `ferry_cost`, `zone_cost`, `other_route_cost`, `total_operating_cost`
- Auditability: `request_id`, `provider_version`, `calculated_at`, `request_snapshot`,
  `response_snapshot`, `revision` / `previous_revision_id`, currency conversion rate and date
- `incomplete` + `warning_text` + `incomplete_acknowledged`: a partial quote must be
  acknowledged explicitly, it cannot slip through silently
- Accepted result lands on the operation as `accepted_travel_cost`,
  `accepted_travel_distance_km`, `accepted_travel_duration_hours`
- The scenario chooses between quote and manual via `route_cost_mode`
  (`profitability_scenario.py:43`)

## 6. Is the market worth it

`mb.commercial.profitability.scenario` — `models/profitability_scenario.py:9`

Computed and stored by `_compute_results` (line 115):

- `weighted_unit_revenue`, `weighted_unit_contribution`, `contribution_margin_ratio`
- `fixed_event_cost` (travel + labour + stall rent + parking + accommodation + other fixed)
- `break_even_units`, `break_even_revenue`
- `break_even_sales_excl_vat`, `break_even_customer_receipts_incl_vat`
- `planned_units`, `sales_revenue_excl_vat`, `customer_receipts_incl_vat`
- `total_variable_cost`, `projected_contribution`, `projected_margin`
- `calculation_blocked` + `calculation_note` when inputs are unsound

Governance around it:

- Several scenarios per operation (pessimistic / realistic / optimistic), one approved as
  `primary_scenario_id`; approved scenarios are immutable, revisions are explicit
- `profitability_required` with a mandatory `profitability_opt_out_reason` when skipped
- Blocking vs warning vs info planning checks in `_get_planning_warnings`
  (`commercial_operation.py`): missing primary scenario, blocked scenario, legacy/scenario
  cost mismatch, product cost excluded, product cost from a sale-price proxy, cost
  assumption older than 90 days, scenario drifted from its stock plan
- Approval freezes evidence: `mb.commercial.report.snapshot` with a canonical payload
  digest and a rendered PDF attachment (`models/planning_report.py:322`)
- After the event: `actual_revenue`, `actual_cost`, `actual_margin` from POS, invoices and
  analytic lines, plus an outcome snapshot comparing plan against reality

## 7. Verdict and hourly KPIs (implemented 2026-08-17)

Gaps 1 and 2 below are now closed. On `mb.commercial.profitability.scenario`:

- `effort_hours` — the hours the market really costs: stand work plus travel. Work hours are
  taken from `planned_work_hours`, else from hourly labour cost lines
  (`category = labour`, `calculation = hour`), else from the operation's own planned hours.
  Travel hours come from the accepted TollQuote duration in `provider_total` mode, else from
  `planned_travel_hours`, else from `operation.accepted_travel_duration_hours`.
- `margin_per_effort_hour` — projected margin over work plus travel hours. This is the number
  that separates a distant fair with a 45 EUR stall from a local one.
- `margin_per_work_hour` — the same over stand hours only.
- `break_even_headroom_ratio` — how far planned units sit above `break_even_units`.
- `target_margin_per_hour` — the hourly floor this market is judged against, defaulted at
  creation from the company policy `res.company.mb_market_target_margin_per_hour`
  (Settings, under Accounting). Zero means judge on break-even headroom alone.
- `recommendation` + `recommendation_note` — the verdict, in plain words:
  - `unknown` — the scenario is incomplete, or it is an average-basket mix with no expected
    quantities, so nothing can be judged.
  - `no_go` — projected margin not positive, or planned units below break-even.
  - `marginal` — below the hourly target, or less than
    `BREAK_EVEN_HEADROOM_RATIO` (15%) above break-even, or no hours planned so the hourly
    return cannot be checked.
  - `go` — clears both tests.

Mirrored on `mb.commercial.operation` as `planning_recommendation` (stored and indexed),
`planning_recommendation_note`, `planning_effort_hours` and `planning_margin_per_hour`, shown
on the operation list and Plan tab, filterable and groupable in the search view, and printed
in the planning report next to the break-even block. The frozen snapshot payload was
deliberately left untouched: the verdict is derived from figures already in it, and changing
the payload would break the digest comparison in `action_freeze_replacement_copy` for
snapshots taken before the upgrade.

Covered by six tests in `tests/test_commercial_operations.py`; the module's 31 tests pass.

## 8. The same verdict for a depot contract (implemented 2026-08-17)

A market is one day; a dépôt-vente is a standing arrangement, so the same question
("is it worth it") is answered per month and then multiplied over the term.
`mb.depot.profitability.scenario` in `mb_commercial_operations_depot`:

- **Inputs.** Expected monthly sales at public price, VAT rate, commission rate
  (defaulted from `stock.warehouse.depot_commission`) with an explicit
  `commission_basis` (public price or excluding VAT, because contracts differ),
  product cost ratio, other monthly variable cost, the monthly fixed fee (defaulted
  from `contract.monthly_fixed_rent`), other monthly fixed cost, and an hourly cost
  for permanence work.
- **Term and permanences** come from the contract: `term_months` from
  `date_start`/`date_end` (falling back to the six-month planning horizon when the
  contract is open-ended), `permanences_per_month` and `hours_per_permanence` summed
  from the contract's obligations. A weekly obligation counts as 52/12 a month, not
  four. All three are computed but overridable.
- **Travel** is one TollQuote round trip to the depot, multiplied by the number of
  permanences over the term (`travel_cost_per_permanence` and
  `travel_hours_per_permanence`, computed from the estimate, overridable so a
  scenario can be drafted without calling the API).
- **Results.** Monthly commission, receipts after commission, product cost,
  contribution and contribution ratio; monthly fixed cost including permanence
  labour and travel; monthly margin; the same figures over the term; the break-even
  *monthly sales* the depot must make (expressed at public price, the number a
  gallery actually quotes); headroom; and margin per hour of permanences and travel.
- **Verdict.** Same four values and the same thresholds as a market, worded for a
  contract: e.g. "3 300,00 € over 6 months (550,00 € a month) for 66.0 hours of
  permanences and travel, 50,00 € per hour, 157% above break-even."

The decision tree itself now lives once, in `mb.profitability.verdict.mixin`
(`mb_commercial_operations/models/profitability_verdict.py`), which both scenario
models inherit. It returns a verdict plus a reason; each model words its own note
from that reason, so the thresholds cannot drift apart while the prose stays in the
terms the user negotiates in — units on a market day, turnover over a depot term.

Mirrored on the contract as `depot_recommendation` (stored, indexed),
`depot_recommendation_note`, `depot_term_margin`, `depot_margin_per_hour` and
`depot_break_even_monthly_sales`, on a Depot Profitability page, with a Depot
Break-even list under the Depots menu. Approval supersedes the previous scenario and
freezes it, as on the market side.

Covered by seven tests in `mb_commercial_operations_depot/tests/test_commercial_depot.py`.

## 9. Comparison, per-kilometre return, and seeding (implemented 2026-08-18)

The three gaps left after the depot work are closed.

**Compare Markets.** A ranked candidate list (`action_commercial_market_candidates`, menu under
Commercial Operations) showing markets still open to apply for, ordered by planned margin per hour,
with the verdict badge, break-even headroom and the application deadline. An `Open Applications`
filter hides markets whose deadline has passed. `planning_break_even_headroom` was added to the
operation as a related field so the headroom is readable beside the rest.

**Margin per kilometre.** `planned_travel_km` on the scenario, resolved through
`_resolved_travel_km()` — the accepted quote's distance in `provider_total` mode, else the typed
distance, else the longest per-kilometre cost line (distance is not additive across parallel cost
lines: two vehicles drive the same road once). It yields `travel_distance_km`,
`travel_distance_known` and `margin_per_travel_km`, mirrored on the operation as
`planning_margin_per_km`. An unknown distance is never shown as zero per kilometre: forms and the
report hide the figure, and the comparison list carries the flag in a column beside it.

**Seeding from the last comparable market.** The planning wizard finds the most recent comparable
operation (same contract first, then the same venue) and seeds a **draft** plan from its primary
scenario: the sales mix, its cost dating so an ageing assumption still raises
`product_cost_outdated`, and the fixed costs — including those held in the legacy scalar fields,
since seeding only the cost lines would carry last year's sales forward with none of last year's
costs. Provenance stays behind: no travel quote, no stock-target link, no cost-line source, and
never an approved baseline. The source's actual revenue, cost and margin are shown as context, but
only once that market has actually happened.

### What the review pass caught

Three agents reviewed the diff through separate lenses. Two findings mattered and are fixed here:

- **A frozen scenario followed the operation.** The new per-kilometre computes — and, it turned out,
  the hours computes shipped earlier — fell back to `operation_id` fields that stay mutable after a
  scenario is approved. Stored computes are written by `_write()` and never meet the guard in
  `write()`, so moving a market's dates or accepting a new quote silently rewrote an approved
  baseline's margin per hour. The resolvers now read only scenario-owned data. Regression test:
  `test_approved_scenario_keeps_its_hourly_and_per_km_figures`.
- **Seeding lost legacy fixed costs**, described above, which would have handed back a verdict
  saying every market is worth attending. Regression test:
  `test_seeding_carries_costs_planned_in_the_legacy_scalar_fields`.

Also fixed: prior actuals no longer read as a break-even for a market that has not happened; the
`Open Applications` filter compares real time rather than a local calendar date rendered as UTC;
seeded lines keep the default opening quantity instead of a blank target's zero.

## Key files

| Concern | File |
| --- | --- |
| Event, cost lines, stock plan | `addons/mb_commercial_operations/models/commercial_operation.py` |
| Break-even and margin engine | `addons/mb_commercial_operations/models/profitability_scenario.py` |
| Toll quote connector and estimates | `addons/mb_commercial_operations/models/travel_estimate.py` |
| Planning wizard, snapshots, evidence | `addons/mb_commercial_operations/models/planning_report.py` |
| Recurring markets and obligations | `addons/mb_commercial_operations/models/commercial_contract.py` |
| Calendar and other views | `addons/mb_commercial_operations/views/commercial_operation_views.xml` |
| POS actuals feedback | `addons/mb_commercial_operations_pos/` |
| Stock planning for the stand | `addons/mb_commercial_operations_stock/` |
