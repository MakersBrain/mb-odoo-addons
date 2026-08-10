# Commercial Operations Planning and Report Plan

## Status

Implemented and deployed to the `odoo_test` proof-of-concept database on
2026-08-11. The implementation follows the installed Odoo 19 APIs and keeps
planning records separate from native stock, manufacturing, purchasing,
accounting, POS, expense, and URSSAF evidence.

## Objective

Make markets, depot refills, and depot permanence visits equally easy to plan,
cost, compare, and print.

A user should be able to start from one operation, enter the minimum missing
information, and obtain:

1. a dated operation visible in the shared calendar;
2. a live travel estimate and work-time plan;
3. stock and production requirements when products are involved;
4. fixed and variable costs with explicit assumptions;
5. break-even units, sales excluding VAT, and customer receipts including VAT;
6. projected profit for one or more sales scenarios;
7. a one-page summary on the operation form;
8. a native Odoo HTML/PDF planning pack;
9. a later planned-versus-actual outcome report from the same operation.

The same concepts and calculations must be reused for:

- a market or fair;
- a depot refill visit;
- a depot permanence shift;
- a generic venue visit where profitability or cost recovery matters.

## Existing foundation

The addon family already has the correct high-level separation:

- `mb_commercial_operations` owns operations, projects/tasks, travel estimates,
  planned cost lines, scenarios, the calendar, and planned-versus-actual data;
- `mb_commercial_operations_stock` owns availability, market/depot preparation,
  return pickings, and stock reconciliation;
- `mb_commercial_operations_depot` owns depot contracts, refill forecasts,
  permanence occurrences, rent, and depot-sale evidence;
- `mb_commercial_operations_mrp` and
  `mb_commercial_operations_purchase` own supply proposals;
- `mb_commercial_operations_fleet` owns vehicle assumptions;
- Sales, POS, expense, and URSSAF bridges own their respective evidence.

Do not add a separate market-report application or move the calculations into
`mb_depot`. Extend this family so every operation uses the same engine.

Current gaps:

- planning is spread across operation, travel, stock, scenario, and task forms;
- creating a complete plan requires too many manual records;
- the operation form does not provide an executive summary;
- `break_even_revenue` is net after deductions, although users naturally read it
  as sales revenue before deductions;
- the scenario does not compute projected profit at the planned sales quantity;
- URSSAF/CFP/CMA estimates are currently easy to mix with card or channel fees;
- no native QWeb report or Print action exists;
- no frozen planning-pack PDF preserves what was approved;
- depot refill and permanence need type-specific guidance without duplicating
  the market calculation code.

## Architectural decision

### One operation, one calculation service

`mb.commercial.operation` remains the planning and calendar authority.
`mb.commercial.profitability.scenario` remains the economic calculation record.
No second report-only business model should copy totals.

Add model methods that return normalized report/KPI values from authoritative
records, for example:

```python
operation._get_planning_summary(scenario)
operation._get_planning_warnings(scenario)
scenario._get_economic_summary()
```

The form, wizard confirmation, QWeb report, and tests must all call the same
methods. Do not reimplement formulas in XML templates or JavaScript.

### Authoritative records and snapshot boundaries

Use one authoritative record for each kind of value:

| Value | Draft/approved authority | Historical authority |
|---|---|---|
| Schedule and responsibilities | `mb.commercial.operation` | approved operation revision and frozen report snapshot |
| Route distance/cost | accepted `mb.travel.estimate` revision | immutable accepted estimate and frozen report snapshot |
| Fixed planning costs | scenario-owned `mb.commercial.cost.line` records | immutable approved scenario lines |
| Product demand | base `mb.market.stock.plan.line`; stock bridge adds availability/execution | approved operation revision and native stock documents |
| Product-mix economic assumptions | scenario lines linked to their source stock-plan lines | immutable approved scenario lines |
| Average-basket assumptions | scenario lines/fields only | immutable approved scenario |
| Actual costs/revenue | explicitly linked native evidence | posted/done native documents and analytic entries |

Extend `mb.commercial.cost.line` with a required `scenario_id`; derive its
`operation_id` and company from the scenario. Each scenario owns its complete
fixed-cost set. Deprecate the duplicate fixed-cost scalar fields on the scenario
after migration. `operation.planned_cost`, `planned_revenue`, and
`planned_margin` are computed from `primary_scenario_id`, not from a second set
of operation totals.

Represent the chosen route basis as scenario cost lines with one mutually
exclusive `travel_basis_key`: accepted provider total, selected accepted
components, or manual total. A constraint prevents more than one basis in the
same scenario. Migrate `route_cost_mode` and its scalar component fields into
these lines, then deprecate them. An accepted `mb.travel.estimate` remains the
route evidence; a cost line references its exact revision rather than copying a
mutable current estimate.

Keep `operation.expected_revenue` only as a temporary compatibility computed
field backed by the primary scenario; it is no longer independently editable.
Stock-plan price/cost fields remain operational suggestions and stock-exposure
inputs, not profitability totals. A scenario receives them only through the
explicit draft refresh described below.

Product-mode scenario lines may store `source_stock_plan_line_id` to the base
generic target model. While the scenario is draft, **Refresh From Stock Plan**
explicitly copies the current
planned-sales quantity, price, cost source, and cost date. Approval freezes
those copied values. They are not related fields that can change underneath an
approved scenario. A draft mismatch between source and copied values produces a
warning and blocks approval until refreshed or explicitly detached.

`mb.commercial.report.snapshot` is an audit envelope only. It stores the frozen
input payload, PDF attachment, digests, revisions, and generation metadata; it
is never a calculation source for live KPIs.

### Optional bridges extend, not fork

The base report contains only base fields. Installed bridge addons inherit the
base QWeb template and insert their own sections:

- stock: availability, shortages, preparation and reconciliation;
- MRP/purchase: linked supply and deadline risk;
- depot: contract, refill destination, forecast and permanence compliance;
- Fleet: vehicle details;
- expense/sale/POS: evidence links and actuals;
- URSSAF: dated turnover-levy assumptions and recognition status.

The base module must install, render, and test without any optional bridge.
Templates must never reference fields owned by an uninstalled addon.

The base transient wizard contains only fields owned by
`mb_commercial_operations`. Optional addons extend the same `TransientModel`
and its views through `_inherit`:

- stock adds warehouse, preparation deadline, availability, readiness and stock
  execution; generic target entry remains available in the base wizard;
- Fleet adds vehicle and vehicle-derived assumptions;
- depot adds depot, refill forecast, contract occurrence and recovery scope;
- MRP/purchase add supply review actions;
- URSSAF adds dated levy suggestions and their evidence.

Type-specific menu actions and default contexts live in the addon that owns the
type. The base addon must not import or search an optional model by name.

## Shared operation planning wizard

Add a transient `mb.commercial.operation.plan.wizard`, opened by:

- **New Planned Operation** from the Commercial Operations app;
- **Complete Planning** on an existing draft operation;
- type-specific shortcuts such as **Plan Market**, **Plan Refill**, and
  **Plan Permanence**.

The wizard and its editable helper lines are `TransientModel` records. Opening
an existing plan copies current draft values into transient fields; the final
`action_save_draft()` validates and creates/writes ordinary persistent records
in one transaction using `fields.Command`. Cancelling the dialog leaves no
business records. The wizard is not a second source of truth, and it must not
create persistent cost/scenario/stock lines from onchange methods. Use explicit
buttons for provider calls and stock refreshes because Odoo's web client does
not support a one2many modifying itself reliably in onchange.

### Step 1 — operation

- operation type;
- company;
- venue and organizer; the depot bridge adds the depot;
- contract when applicable;
- responsible people; the Fleet bridge adds the vehicle;
- the stock bridge adds the source warehouse;
- exact address or frozen coordinates;
- event/service date.

Type-specific defaults:

- market: organizer, public opening, setup, teardown, exhibitor deadline;
- refill: depot contract, source warehouse, refill review date, time on site;
- permanence: contract occurrence, required hours/days, scheduled shift;
- visit: venue, purpose, and time on site.

### Step 2 — time and route

Store separate user-facing segments instead of hiding everything in a single
start/end interval:

- departure;
- expected arrival;
- setup or loading/unloading duration;
- public/service start and end;
- teardown duration;
- expected return;
- the stock bridge adds the stock-preparation deadline;
- application/payment/document deadlines.

`planned_start` and `planned_end` remain the complete worker/vehicle commitment
shown in the calendar. Segment fields explain how those dates were derived.

The wizard may calculate a TollQuote estimate explicitly. It must:

- require usable coordinates;
- show outward and return duration separately;
- copy vehicle/fuel assumptions visibly;
- preserve accepted quote revisions;
- never treat an incomplete route as zero cost;
- permit a clearly labelled manual travel cost when the provider is unavailable.

For a new unsaved operation, the connector service returns sanitized quote data
to transient wizard fields; `action_save_draft()` persists the operation and
the quoted `mb.travel.estimate` together. Acceptance requires the user's
explicit **Accept Quote** choice; saving a draft never silently accepts it. For an existing operation,
the same final action creates the new immutable revision. Cancelling a wizard
must not leave an orphan estimate. Provider credentials remain restricted and
are never copied into transient values.

### Step 3 — costs and labour

Prefill editable scenario-owned `mb.commercial.cost.line` records for:

- route total or selected route components;
- setup, attendance, permanence, loading/unloading, and teardown labour;
- stall/registration fee;
- parking, accommodation, meals, electricity, and other fees;
- allocated depot rent where the chosen comparison requires it.

Every default must display its source:

- contract;
- vehicle;
- company planning template;
- accepted provider quote;
- manual assumption.

Each cost line stores its source kind, source record when permitted, assumption
date, currency/conversion evidence, and whether it is fixed or driven by hours,
distance, units, or revenue. The scenario calculation consumes these lines
directly. The wizard must not copy their totals into duplicate scenario scalar
fields.

The wizard must prevent double counting. In particular:

- provider-total travel cannot also add its fuel/toll components;
- travel labour included by the provider cannot be added again;
- monthly depot rent cannot be charged to every refill unless an explicit
  allocation rule is selected;
- internal stock moved to a depot/market is not an operating expense.

### Step 4 — products or sales basis

Support two shared scenario modes.

#### Product-mix mode

Used when concrete products are known:

- exact products or reviewed assortment allocations;
- source stock-plan line when stock planning is installed;
- frozen planned quantity and expected sold quantity;
- sales price excluding VAT and customer price including VAT;
- product-cost source and date;
- payment/channel fee;
- dated turnover-levy assumption;
- other variable unit cost.

Stock planning feeds this mode through the explicit refresh/snapshot action; the
economic scenario never creates or mutates stock demand implicitly.

#### Average-basket mode

Used for permanence or refill profitability before a concrete sales mix exists:

- average sales basket excluding VAT and customer basket including VAT;
- average product-cost percentage or amount;
- average channel/payment fee;
- turnover-levy rate;
- expected baskets or sales excluding VAT over the recovery period.

Average-basket mode is an estimate and cannot create stock demand or supply.
It avoids inventing an arbitrary product merely to compute break-even sales.

For a refill operation, the recovery period must be explicit, such as “sales
until the next refill” or a dated contract period. For permanence, it may be the
shift itself or the contract month. Reports must state the selected scope.

### Step 5 — stock and supply

When the stock bridge is installed, show:

- target quantity;
- on hand and reserved;
- confirmed incoming/outgoing before the cutoff;
- forecast available;
- shortage;
- supply method and readiness;
- calculation time.

When MRP/purchase bridges are installed, the wizard may propose supply but must
not silently confirm it. Missing Bills of Materials, components, vendors, or
lead time become report warnings. Draft MOs/RFQs are created only by the existing
explicit **Prepare Supply** workflow and remain linked to the stock-plan line.

### Step 6 — review

Before saving, show the same executive summary that will appear on the operation:

- total planned units/revenue;
- known fixed cost;
- estimated variable cost;
- contribution per unit/basket;
- excluding-VAT break-even sales and including-VAT customer receipts;
- break-even units/baskets;
- projected margin at the planned sales quantity;
- stock shortages and blocking warnings;
- assumptions that are proxies or out of date.

**Save Draft Plan** creates/updates records only. It must not approve the
operation, validate stock, confirm supply, post bills, or create sales.

## Reusable planning templates

Add `mb.commercial.plan.template` in the base addon with company rules and
operation-type applicability.

Reusable fields:

- default setup/teardown/on-site durations;
- work and travel hourly rates;
- default cost-line templates;
- default profitability mode and scenario lines;
- fuel price and route policy when Fleet is absent;
- default report language and sections;
- warning-age threshold for cost assumptions.

Bridge extensions:

- depot contract may select refill and permanence templates;
- stock extension may define stock-target templates;
- Fleet may select a default vehicle;
- URSSAF may provide dated rate defaults.

Applying a template copies dated assumptions into the draft operation/scenario.
Later template changes must not silently rewrite an approved plan.

## Profitability model update

### Separate deductions clearly

Do not overload `channel_fee_rate` with every percentage deduction. Scenario
lines need separate fields:

- `channel_fee_rate` and amount;
- `turnover_levy_rate` and amount;
- `product_unit_cost`;
- `other_variable_unit_cost`;
- net revenue after channel fees;
- contribution after all variable costs.

The URSSAF bridge should propose the dated BIC-goods rates from company settings
and the existing URSSAF rule engine, including applicable
ACRE/CFP/chamber/versement rules, thresholds, exemptions, and company choices.
It must not duplicate the legal formulas in the commercial addon. The bridge
stores the rule IDs, effective date, component rates and computed planning
coefficient on the immutable scenario line. This remains a planning estimate;
legal recognition stays in the URSSAF declaration module and continues to
follow payment of the consolidated depot invoice.

The report must show the component rates instead of only one combined number.

### Clarify revenue definitions

Do not use “gross” to mean “excluding VAT.” Use explicit values:

```text
sales_price_excl_vat
vat_amount
customer_price_incl_vat
sales_revenue_excl_vat
net_sales_revenue_after_channel_fees
eligible_turnover_levy_base
unit_turnover_levies
unit_product_and_variable_cost
unit_contribution
break_even_sales_excl_vat
break_even_customer_receipts_incl_vat
break_even_units_or_baskets
projected_sales_excl_vat
projected_customer_receipts_incl_vat
projected_contribution
projected_margin
```

Profitability is calculated consistently excluding recoverable/output VAT;
customer receipts including VAT are displayed separately. For VAT-exempt sales,
the two values are equal. The URSSAF bridge supplies the legally eligible dated
turnover basis rather than assuming that either displayed amount is always the
declaration base. Migration may keep existing fields temporarily, but views and
APIs must not label net revenue as gross sales.

### Shared formulas

```text
channel_fee = sales_revenue_excl_vat * channel_fee_rate
turnover_levies = eligible_turnover_levy_base * turnover_levy_rate
contribution = sales_revenue_excl_vat - channel_fee - turnover_levies
               - product_cost - other_variable_cost

fixed_cost = selected_travel_cost + work_labour + stall_or_visit_cost
             + allocated_rent + parking + accommodation + other_fixed_cost

break_even_units = ceil(fixed_cost / weighted_unit_contribution)
break_even_sales_excl_vat = fixed_cost / contribution_margin_ratio_excl_vat
projected_margin = projected_contribution - fixed_cost
```

Keep unrounded decimal bases through the calculation. Aggregate compatible
sales, fee and levy bases first, then use `currency_id.round()` on monetary
totals. Displayed per-unit values may be rounded for readability but must not be
multiplied back into totals. This matches the URSSAF declaration approach and
avoids cumulative per-product/per-receipt rounding drift.

In product mode, derive each line's weight from its frozen expected-sold
quantity divided by the scenario's total expected-sold quantity. Do not store an
independently editable mix share. Average-basket mode has one basket assumption
and therefore needs no artificial mix normalization.

Block calculations when:

- total expected-sold quantity is zero in product mode;
- contribution is zero or negative;
- price or dated product cost is missing;
- the selected quote is not accepted/complete;
- an operation requiring a recovery period has none.

A zero product cost is allowed only with an explicit “exclude product cost”
assumption and a prominent warning. Cost proxies must show their method and date.

### Planned and actual scope

Native Odoo project profitability is project/analytic-account scoped. It must
remain the contract-level truth for a long-lived depot project. It cannot be
relabelled as the actual result of every refill or permanence operation.

Operation actuals use only native evidence explicitly linked to that operation:

- its task/timesheets;
- linked expenses, bills, purchases, MOs and stock moves;
- Sales/POS/invoice evidence carrying `mb_commercial_operation_id`;
- correction/reversal documents linked through their native origin.

Implement this as a small extension registry, not a base-module search for
optional models. The base method returns base evidence; each installed bridge
extends `_get_operation_profitability_items()` with normalized items containing
`model`, `res_id`, `component`, `date`, `amount`, and `currency`. Deduplicate by
stable source key and component so one invoice/stock/accounting fact is counted
exactly once. Preserve links to the native records for drill-down. Do not create
synthetic analytic lines merely to make the report easier.

Replace the current operation computation that sums the entire analytic account.
The project dashboard remains available for contract-wide profitability.

The depot bridge adds a separate `recovery_scope` with explicit date boundaries:

- `operation_only`: no contract sales are attributed without an explicit link;
- `until_next_refill`: depot economic sales from this refill through the instant
  before the next approved refill;
- `contract_period`: a selected non-overlapping contract period;
- `informational`: planning break-even only, with no actual-profit claim.

Recovery windows for the same depot contract cannot overlap when they are used
in aggregated reporting. Permanence may show contract sales during a selected
window, but labels them “contract sales in comparison window,” not “revenue
generated by this shift.” Economic sale evidence uses the sale/report date;
URSSAF recognition remains separately based on the legally required payment
event. Outcome reports show both scopes and never allocate one sale twice.

## Operation overview

Add a first **Overview** page to the operation form. It should be useful without
opening four child records.

KPIs:

- schedule and operation duration;
- accepted travel cost/distance/time;
- fixed cost;
- planned sales excluding VAT and customer receipts including VAT;
- break-even sales excluding VAT and receipts including VAT;
- break-even units/baskets;
- projected margin;
- stock required/available/shortage;
- preparation and supply readiness;
- warning count;
- operation-linked actual revenue/cost/margin after execution;
- contract-window comparison figures when the depot bridge supplies them.

Add smart buttons for:

- **Complete Planning**;
- **Travel Quote**;
- **Primary Scenario**;
- **Supply** when installed;
- **Print Planning Pack**;
- **Print Outcome Pack** when operationally done.

The Overview uses the selected primary scenario. `primary_scenario_id` must
belong to the operation and company. A draft scenario may be selected explicitly
for simulation. The atomic **Approve Planning Baseline** action validates the
operation, makes that scenario primary/approved, supersedes the previous primary
scenario, approves the operation revision, and freezes the report snapshot. A
draft report must never silently choose an arbitrary scenario.

Market, refill and permanence types require a valid primary scenario before
planning approval. A generic visit may explicitly opt out of profitability and
prints “Cost plan only.” Reopening increments `planning_revision`, leaves the
old scenario/snapshot immutable, and creates or selects a new draft scenario.

Replace the separate scenario/operation approval buttons for these required
types with this one public action. The model-level legacy actions delegate to
the same validation service or reject an incomplete sequence, so RPC/import code
cannot create an approved operation with a draft scenario or a missing snapshot.
Store approval user/date/revision on both the operation and scenario.

## Native Odoo report

### Report action

Add two deterministic `ir.actions.report` records on
`mb.commercial.operation`, sharing QWeb partial templates:

- **Commercial Operation Planning & Profitability Pack**;
- **Commercial Operation Outcome Pack**.

Use a native QWeb HTML/PDF report and standard paper format. Do not introduce a
custom PDF library or browser-side document generator.

The planning report is available from:

- the operation **Print** menu;
- **Print Planning Pack** on the form;
- the completion screen of the planning wizard.

The outcome action appears only after operational completion and always renders
outcome mode. Do not switch modes through an undocumented context flag. Both
actions declare `binding_model_id`, the installed Odoo 19 field `group_ids`,
`print_report_name`, and the
appropriate paper-format behavior supported by Odoo 19 report actions. Omit a
fixed `paperformat_id` to use the active company's default unless review chooses
a dedicated report format. Normal live reports use `attachment_use=False`;
approved snapshots use the controlled approval/freeze action.

### Common report sections

1. **Header**
   - company, operation, type, state and revision;
   - generated date/user and planning currency;
   - `DRAFT / SIMULATION` watermark unless the operation and scenario are
     approved.
2. **Executive summary**
   - fixed cost, sales/receipts, break-even, projected margin;
   - clear green/amber/red readiness indicators.
3. **Schedule and responsibilities**
   - travel, setup/service/public hours, teardown and return;
   - responsible users, venue and organizer;
   - application and payment deadlines;
   - inherited Fleet and stock templates add vehicle and stock deadlines.
4. **Travel**
   - frozen origin/destination, distance and route duration;
   - toll, fuel, driver/other components, total and quote revision;
   - warnings and manual assumptions.
5. **Cost breakdown**
   - grouped fixed and variable costs with source and date.
6. **Sales and break-even**
   - product mix or average basket;
   - excluding-VAT sales, including-VAT receipts, and net contribution;
   - channel fee and turnover levies separately;
   - break-even units/baskets, excluding-VAT sales and customer receipts;
   - projected result at the planned quantity.
7. **Checklist and warnings**
   - overdue activities and configuration gaps;
   - proxy/outdated costs and incomplete evidence.
8. **Approval/audit**
   - scenario state, approved user/date, quote ID/revision;
   - report-generation timestamp.

### Bridge report sections

- **Stock:** target, forecast, shortage, preparation picking and reconciliation.
- **MRP/Purchase:** supply document, quantity, state, components/vendor readiness,
  and deadline risk.
- **Depot refill:** depot, contract, forecast basis, current depot stock,
  suggested/refill quantity, recovery period and next review.
- **Permanence:** contractual period, required versus scheduled/completed hours,
  shift cost, allocated rent if chosen, and sales needed to recover the shift.
- **Market:** public hours, exhibitor deadline/fee, planned assortment, setup and
  teardown.
- **Actual evidence:** timesheets, expenses, bills, Sales/POS/depot revenue,
  stock cost and URSSAF recognition when installed.

### Frozen approval copy

Normal printing renders current data and does not cache a stale draft.

**Approve Planning Baseline** performs a mandatory freeze in the same
transaction. If validation or rendering fails, approval is rolled back with a
user-readable error. Managers may use **Freeze Replacement Copy** only when the
approved inputs are unchanged and the original snapshot is retained.

Freezing must:

- render the approved QWeb PDF;
- create a normal `ir.attachment` on the operation;
- post it in chatter with scenario and quote revision;
- store generated user/date and a SHA-256 digest in a small
  `mb.commercial.report.snapshot` audit record;
- store both a canonical JSON-input digest and PDF-content digest;
- protect the snapshot and attachment from replacement or deletion.

Reopening and approving a revision creates a new snapshot; it never replaces the
old attachment. Do not automatically render PDFs inside cron jobs.

Implement attachment protection explicitly. Extend `ir.attachment` with a
restricted `mb_commercial_report_snapshot_id`. An `@api.ondelete(at_uninstall=False)`
guard blocks deleting a linked snapshot or managed attachment, and `write()`
blocks changing its binary content, resource link or filename. Managers can
mark a snapshot **void** with a required reason and chatter message, but the
record and PDF remain. ACLs grant no normal unlink right on snapshots. Do not
assume that protecting only the snapshot also protects `ir.attachment`.

### Outcome report

The outcome report reuses the planning report partials and adds:

- planned and actual dates/hours;
- planned and actual travel/fees;
- prepared, sold, scrapped and returned quantities;
- planned and actual revenue/cost/margin;
- margin and break-even variance;
- document completeness, accounting reconciliation and URSSAF status.

Actuals continue to come from operation-linked native evidence. Depot comparison
windows are separately labelled and deduplicated as described above. The report
must not create duplicate analytic or accounting lines.

## Type-specific workflows

### Market

1. Select event, public hours and deadlines.
2. Calculate travel and full worker/vehicle commitment.
3. Enter assortment and planned quantities.
4. Check stock and review supply shortages.
5. Select/apply a profitability template.
6. Review break-even and projected profit.
7. Save Draft and print a simulation.
8. **Approve Planning Baseline** validates, approves and freezes revision 1.

### Depot refill

1. Start from a due refill forecast/contract.
2. Select suggested products and actual refill date.
3. Calculate travel, loading/unloading and on-site cost.
4. Select a non-overlapping sales recovery scope/period.
5. Show stock value as exposure, not a duplicated expense.
6. Compute sales required to recover refill operating cost and any explicitly
   allocated contract cost.
7. After approval, use the existing standard transfer workflow.
8. Outcome reporting separates operation-linked trip cost from contract sales in
   the recovery window.

### Permanence

1. Start from a contract occurrence.
2. Select shift date, people and contractual hours.
3. Calculate travel and work cost.
4. Use an average-basket or reviewed product-mix scenario.
5. Compute baskets/sales excluding VAT and customer receipts needed to recover
   the shift and chosen monthly
   allocation.
6. Record actual time through timesheets; show explicitly linked operation
   revenue separately from contract-window comparison sales.

## Warnings and readiness

Compute warnings centrally so the form and report agree:

- missing/approximate venue address or coordinates;
- failed, incomplete, expired, or superseded travel quote;
- schedule cannot meet an arrival/setup cutoff;
- worker or vehicle conflict;
- overdue exhibitor/contract activity;
- product cost missing, proxy, or older than the configured age;
- break-even greater than planned units/baskets;
- stock shortage without supply;
- MRP product without a Bill of Materials;
- supply completion after preparation deadline;
- preparation picking absent or not fully reserved;
- recovery period absent for refill/permanence;
- actual documents incomplete after operation completion.
- source stock plan and draft product scenario are out of sync;
- depot recovery window overlaps another reportable window;
- approved operation lacks its immutable report snapshot.

Warnings have severity (`info`, `warning`, `blocking`) and stable codes for tests.
Only blocking warnings prevent approval; drafts remain printable with warnings.

## Security, audit, and Odoo 19 alignment

- Use standard QWeb reports, `ir.actions.report`, `ir.attachment`, chatter,
  activities, calendar, project tasks, timesheets, pickings, MOs/RFQs and
  accounting documents.
- Do not write done stock dates/states, accounting totals, or actual analytic
  values manually.
- Require/index `company_id` and use `company_id in company_ids` record rules on
  every persistent report/template/snapshot model.
- Use `_check_company_auto = True` and `check_company=True` relations.
- Printing respects operation/report record rules; report rendering does not
  use broad `sudo()`.
- Connector secrets and raw sensitive provider payloads never appear in reports.
- Approved scenario and quote revisions remain immutable.
- Financial close keeps the existing controlled reopen/reversal behavior.
- Use `TransientModel` for the planning wizard and `AbstractModel` only for the
  optional custom QWeb report-value provider; persistent assumptions remain on
  normal business models.
- Declare report bindings and access groups explicitly. Use `attachment_use=False`
  for live reports and the controlled snapshot action for immutable copies.
- Use `@api.ondelete(at_uninstall=False)` for business deletion guards so addon
  uninstall is not left inconsistent.
- Use `list` views, `fields.Command`, `@api.model_create_multi`, and other Odoo 19
  APIs already adopted by the addon family.

Primary Odoo 19 references for implementation review:

- [Report actions](https://www.odoo.com/documentation/19.0/developer/reference/backend/actions.html#report-actions)
  for `ir.actions.report`, bindings, QWeb HTML/PDF, paper formats and attachment
  behavior;
- [ORM API](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html)
  for `TransientModel`, computed dependencies, `@api.model_create_multi`,
  constraints and `@api.ondelete`;
- [Multi-company guidelines](https://www.odoo.com/documentation/19.0/developer/howtos/company.html)
  for company-dependent defaults, `with_company`, strict `check_company`, and
  company record rules;
- [Project profitability](https://www.odoo.com/documentation/19.0/applications/services/project/project_management/project_profitability.html)
  for native project-linked revenue/cost evidence and stock analytic-cost
  configuration;
- [Analytic accounting](https://www.odoo.com/documentation/19.0/applications/finance/accounting/reporting/analytic_accounting.html)
  for analytic plans, accounts and distributions.

## Data migration

1. Add `primary_scenario_id` and set it from the single approved scenario where
   one exists.
2. Preserve all existing scenarios, scalar scenario costs and operation cost
   lines as legacy evidence during migration.
3. Do not silently choose between legacy operation cost lines and scenario fixed
   fields when their totals differ. Mark the operation **Needs baseline review**;
   the reconciliation wizard shows both sets and creates new scenario-owned cost
   lines only after an explicit user choice.
4. For matching unambiguous totals, create scenario-owned cost lines with a
   `migration` source and retain read-only legacy fields until a later cleanup
   release.
5. Interpret existing `channel_fee_rate` only as channel fee; do not silently
   relabel historical combined rates as URSSAF.
6. Mark potentially combined rates for review using a documented deterministic
   rule; never alter the numerical value automatically.
7. Add explicit excluding-VAT, including-VAT, contribution and break-even fields.
   Recompute only draft/new-engine scenarios; preserve displayed legacy results
   on historical approved scenarios.
8. Replace operation actuals that sum a shared analytic account with explicit
   operation-linked evidence. Show contract-project totals separately.
9. Existing operations remain printable in a labelled **Legacy plan** mode with
   missing-section warnings.
10. Do not auto-approve scenarios or fabricate historical frozen PDFs.

## Delivery phases

### Phase 1 — calculation and overview

- establish scenario-owned cost lines and product-source snapshot links;
- normalize profitability calculations;
- add VAT-explicit break-even and projected margin;
- add primary scenario and central warnings;
- correct operation actual scope and add depot recovery-window semantics;
- add the operation Overview page;
- migrate and test existing scenario records.

### Phase 2 — easy planning

- add operation templates;
- add the shared planning wizard;
- add market, refill and permanence specializations;
- create activities/checklists, but no automatic business-document validation.

### Phase 3 — planning report and approval audit

- add base QWeb HTML/PDF report and Print action;
- add bridge-owned inherited sections;
- add Draft/Simulation watermark and warnings;
- add the atomic approval/revision lifecycle;
- add mandatory immutable planning snapshots and protected chatter attachments;
- verify French labels, locale, currency and timezone rendering.

### Phase 4 — outcomes

- add planned-versus-actual outcome mode;
- add report comparison and controlled revision workflow.

## Test plan

### Calculation tests

- product mix and average basket produce the same result for equivalent inputs;
- quantity-derived product mix does not depend on manually rounded shares;
- excluding-VAT sales, including-VAT receipts and contribution are not confused;
- channel fees, URSSAF estimates and product costs are each counted once;
- scenario-owned cost lines are the only fixed-cost input;
- refreshing a draft from stock copies values, while an approved scenario cannot
  change when its source stock line is later revised;
- provider-total and component route modes cannot double count;
- rent allocation is explicit and idempotent;
- zero/negative contribution blocks approval;
- projected margin uses planned quantity and the primary scenario;
- operation actuals contain only explicitly linked evidence;
- contract-window sales cannot be allocated to overlapping recovery windows.

### Wizard tests

- create and update each operation type;
- timezone-correct departure, public hours and return;
- templates copy assumptions without remaining dynamically linked;
- cancellation/error rolls back without partial operations;
- draft save creates no picking, MO, RFQ, bill, sale or accounting entry;
- optional bridge absence does not break the base wizard;
- base wizard/model loading never resolves optional Stock, Fleet or Depot models.

### Report tests

- base report renders HTML and PDF with only the base addon;
- each installed bridge contributes only its own section;
- multi-company users cannot print another company's operation;
- Draft watermark and blocking warnings appear;
- approved data show exact scenario and quote revisions;
- frozen attachments remain unchanged after a controlled reopen/revision;
- direct unlink or binary/resource-link changes on managed attachments are
  rejected, while voiding retains the evidence and reason;
- no connector token or unsafe HTML appears;
- French accents, dates, amounts and page breaks render correctly.

### Acceptance scenarios

1. **Grasse market:** 20 mixed mugs and 10 decorative plates, live round-trip
   quote, official stall fee, 18-unit production shortage, VAT-explicit
   break-even and projected margin, printable Draft pack, no automatic
   transfer/MO.
2. **La Méduse Électrique — Sète refill:** forecast-derived refill assortment,
   live route cost, loading/on-site time, explicit recovery period, sales needed
   to recover the trip, operation-linked costs separated from contract-window
   sales, then a standard approved internal transfer.
3. **Depot permanence:** contract shift, travel and labour cost, monthly-rent
   allocation choice, average basket, required sales, timesheet actuals and an
   outcome report.
4. **No optional bridges:** generic venue visit with manual travel and average
   basket still produces a valid base report.

## Implemented defaults and explicit choices

1. Labour rates come from an explicitly selected template or an edited cost
   line; no hidden owner-time rate is assumed.
2. A product-cost proxy is never automatic. It is labelled as a proxy with its
   date; a zero product cost requires an explicit exclusion and warning.
3. A refill shortcut suggests `until_next_refill`, but approval still requires
   explicit, non-overlapping recovery boundaries.
4. Permanence comparisons remain explicitly labelled comparison-window revenue,
   never revenue caused by the shift.
5. Reports use Odoo's normal user/company language, currency, and timezone
   rendering rather than a parallel formatting engine.
6. Reusable venue equipment/dimensions remain outside this profitability
   baseline; they can be added later as operation resources without changing
   the calculation or evidence model.

## Definition of done

The update is complete when a normal Commercial Operations user can create a
market, depot refill, or permanence plan through one workflow, see one consistent
summary, understand every assumption and warning, print a native Odoo PDF, and
later compare it with actual evidence—without duplicated calculations, forced
stock/accounting states, or dependencies on optional bridge models.
