# Depot Refill and Market Profitability Plan

## Status

Draft for review. This document proposes an Odoo 19 Community design; it does not authorize implementation or deployment.

## Goal

Add one optional application that answers four operational questions without replacing Odoo's native stock, project, accounting, or analytic workflows:

1. When should a depot be refilled, and with what assortment?
2. When must someone attend a depot under its contract?
3. What will a refill trip or market attendance cost in money and working time?
4. How much must be sold to break even, and what was the actual profit afterward?

The same planning unit should cover:

- a permanent depot-vente contract;
- a refill visit to one depot;
- a contractual permanence shift;
- a temporary market, fair, or pop-up event.

## Design decision

Create a separate addon family. Do not expand `mb_depot` into a project, route, contract, and accounting application, and do not make the base addon refer to models owned by optional applications.

Addon boundaries:

- `mb_commercial_operations`: contracts, operations, calendar, planning cost lines, break-even scenarios, TollQuote estimates, project/task/analytic links, and generic stock targets; depends on `project`, `hr_timesheet`, and `account`.
- `mb_commercial_operations_stock`: exact-product availability, company-owned market locations, preparation/return pickings, and stock readiness; depends on the base addon and `stock`.
- `mb_commercial_operations_depot`: depot contract, refill evidence, consolidated-invoice analytic propagation, and depot smart buttons; depends on the stock bridge and `mb_depot`.
- `mb_commercial_operations_mrp`: manufacturable mappings, MO links, production feasibility, and supply actions; depends on the stock bridge and `mrp`.
- `mb_commercial_operations_purchase`: purchase supply method and purchase-line links; depends on the stock bridge and `purchase`.
- `mb_commercial_operations_fleet`: vehicle assignment and TollQuote vehicle defaults; depends on the base addon and `fleet`.
- `mb_commercial_operations_expense`: actual expense links and project analytic propagation; depends on the base addon and `hr_expense`.
- `mb_commercial_operations_sale`: sales/invoice event selection and analytic propagation; depends on the base addon and the relevant Sales project/account bridges.
- `mb_commercial_operations_pos`: explicit market occurrence on POS configuration/session/order and analytic revenue propagation; depends on the base addon and `point_of_sale`.

Each bridge owns its fields, views, access rules, hooks, and tests. Optional bridge installation must not alter the base workflow for databases where its application is absent.

Use Odoo's existing records as the system of record:

- `stock.warehouse` and `stock.picking` for depot stock and refills;
- `project.project` as the profitability unit;
- `project.task` for refill visits, permanence shifts, and market work;
- the project's `account.analytic.account` for planned-versus-actual costs and revenue;
- timesheets for actual labour;
- vendor bills and, when the expense bridge is installed, expenses for tolls, fuel, rent, stall fees, parking, accommodation, and other external costs;
- customer invoices, POS, or depot consolidated invoices for revenue;
- `fleet.vehicle` for vehicle assumptions only through the Fleet bridge.

This follows Odoo 19's native model: projects and their tasks/timesheets are tied to an analytic account, while auto-installed/native bridge modules extend project profitability with invoices, expenses, purchases, stock moves, manufacturing, and other analytic costs. Every installed commercial bridge must verify that its corresponding Odoo profitability bridge is present and that evidence reaches the intended project account.

Native recurring tasks remain available for simple sequential work where the next task is needed only after the current one closes. They are not used to populate contractual permanence/refill calendars in advance. Contract obligations require a small, idempotent occurrence generator described below.

### Profitability unit

- One permanent depot contract = one long-lived project and analytic account.
- One market occurrence = one project and analytic account, archived after financial close.
- Tasks beneath the project represent the actual activities (travel, setup, selling, teardown, refill, permanence).

This is deliberately one project per item whose profit must be isolated. A single global project with one task per market would mix all events in one analytic account and make native profitability misleading.

## Scope boundaries

### Included

- depot contracts and recurring obligations;
- fixed recurring rent and other planned contract charges;
- depot refill forecasting and suggested assortment;
- planned market assortment, stock readiness, and production shortages;
- route, toll, fuel, and driver-time estimates;
- planning and recording refill/permanence/market work;
- planned and actual profitability;
- break-even sales and units;
- explicit creation of standard internal transfers, tasks, expenses, and vendor bills;
- monthly depot and per-event reporting.

### Not included in the first release

- automatic validation or backdating of stock transfers;
- automatic vendor-bill posting or payment;
- vehicle routing optimization across many depots;
- live GPS/driver tracking;
- payroll or employee scheduling replacement;
- machine-learning demand prediction;
- changing product inventory valuation with travel/refill cost;
- silently subtracting depot rent from sales or URSSAF turnover.

An internal refill transfer is not a sale or an accounting expense. Its stock value remains in the company. Travel and labour are operating costs; the stock carried to the depot is a working-capital/exposure metric, not a second cost of goods entry.

## Public addons and native features reviewed

### Adopt as dependencies

Use standard Odoo 19 Community modules through the addon boundaries above:

- base: `project`, `hr_timesheet`, and `account` for tasks, actual hours, analytic accounts, vendor bills, and the profitability shell;
- stock/depot bridges: `stock`, `stock_account` when valuation evidence is required, and `mb_depot`;
- optional supply bridges: `mrp`/`mrp_account` and `purchase`;
- optional operating-cost bridges: `fleet` and `hr_expense`;
- revenue bridges: the installed Sales and/or POS applications.

Odoo's auto-installed project bridges (`project_account`, `project_stock`, `project_stock_account`, `project_mrp`, `project_mrp_account`, `project_purchase`, `project_hr_expense`, `sale_project`, and `sale_timesheet`, as applicable) are part of the integration acceptance test. The plan must not assume that installing `project` alone supplies every profitability row.

Odoo's [Project profitability documentation](https://www.odoo.com/documentation/19.0/applications/services/project/project_management/project_profitability.html) and [analytic accounting documentation](https://www.odoo.com/documentation/19.0/applications/finance/accounting/reporting/analytic_accounting.html) describe the native cost/revenue backbone. [Recurring tasks](https://www.odoo.com/documentation/19.0/applications/services/project/tasks/recurring_tasks.html) remain useful for sequential recurrence but, as verified in Odoo 19's implementation, do not pre-populate the contractual calendar; the obligation occurrence generator fills that gap. [Fleet cost analysis](https://www.odoo.com/documentation/19.0/applications/hr/fleet/cost_analysis.html) is useful for vehicle-level service and contract costs, but it does not quote a route.

### Evaluate, but do not depend on initially

The OCA [Field Service repository](https://github.com/OCA/field-service/tree/19.0) is the closest public reference. Its 19.0 modules cover locations, workers, orders, agreements, recurrence, calendar, expenses, project, timesheets, vehicles, and stock. It is a good implementation reference for company security, recurring site visits, and links between work and stock.

Do not install the full Field Service stack in phase 1. It introduces `fsm.order` as a second operational work order beside `project.task`, although the present need can use native tasks directly. Reconsider it if this becomes a dispatch system with many workers, territories, skills, vehicles, and daily site routes.

The OCA [Contract repository](https://github.com/OCA/contract/tree/19.0) can be evaluated later if there is a broad need for recurring supplier/customer contract invoicing beyond depots. For the first release, a small depot contract model should generate draft vendor bills through an explicit action because the charge semantics are narrow and must remain reviewable.

The OCA [account-analytic repository](https://github.com/OCA/account-analytic/tree/19.0) contains useful bridges such as stock/picking analytic allocation, but 19.0 migration status must be checked module by module before vendoring. A depot's internal transfer must not automatically become an analytic expense merely because it is linked to a project.

The OCA transport/TMS proposals are aimed at carrier and fleet dispatch businesses and are not mature enough in Odoo 19 to justify a dependency for occasional artisan trips. The [OCA transport RFC](https://github.com/OCA/stock-logistics-transport/issues/127) is useful vocabulary/reference only.

### Licensing and vendoring rule

OCA modules are generally AGPL and each manifest is authoritative. Before copying any implementation, record the source commit and license and preserve notices. Prefer calling public extension hooks or vendoring an intact addon over copying fragments. The initial plan needs no copied OCA code.

## TollQuote integration

TollQuote publishes a live [OpenAPI contract](https://api.stage.tollquote.com/openapi.yaml) and [interactive documentation](https://docs.tollquote.com/). The current contract exposes:

- `POST /v1/route/plan` for route geometry/distance/duration;
- `POST /v1/toll/quote` for toll pricing from a route trace;
- `POST /v1/freight/route-alternatives:compare` for toll, fuel, driver, ferry, zone, and total operating cost comparisons;
- `GET /v1/fuel/daily-average` for dated fuel assumptions;
- batch/async freight quote endpoints for later multi-route use.

The inspected contract identifies itself as version `0.1.0`. Some helper operations are still loosely specified (for example, the route-plan request/response schemas are open objects, and some fuel query parameters are described unusually). Treat this as a provider integration risk: pin the supported API version/fields in adapter tests, tolerate additive response fields, and obtain a stability/deprecation agreement before production use. Do not generate Odoo models directly from this early contract.

### Integration shape

Add `mb.tollquote.connector` and `mb.travel.estimate` models rather than embedding HTTP calls in tasks.

Connector fields:

- company (required, indexed);
- environment (`staging` or `production`);
- base URL with an allow-listed host;
- API bearer token stored as a restricted credential;
- request timeout;
- active flag and last health result.

Travel estimate fields:

- company, project, task, and operation; the Fleet bridge adds `vehicle_id`;
- origin/destination partners and frozen latitude/longitude;
- outward/return or one-way;
- planned departure date/time;
- frozen vehicle class/payment option and fuel assumptions, whether entered manually or copied by the Fleet bridge;
- distance, duration, toll, fuel, driver cost, ferry/zone/other route costs, and provider total;
- currency, quote request ID, calculated-at, completeness/warnings, and provider version;
- sanitized request and response snapshots;
- state: draft, quoted, accepted, superseded, failed;
- planned estimate versus actual entered/expense-backed values.

Rules:

- Call the API only from an explicit **Calculate route cost** action or a bounded refresh cron for future draft operations.
- Use a short timeout, idempotent retry only for safe failures, quota/rate-limit handling, and user-readable warnings.
- Never turn an incomplete or `unpriced` response into zero cost. Mark the estimate incomplete and require acknowledgement/manual cost.
- Store route cost components separately. A scenario may use the provider total or selected components, but cannot add fuel/driver costs again when they are already contained in that total.
- Freeze an accepted quote. Recalculation creates a new revision so past decisions remain auditable.
- Never store the bearer token in chatter, snapshots, logs, or exceptions.
- The Odoo company currency is authoritative; preserve provider currency and conversion rate/date when conversion is required.
- The return leg must be calculated or explicitly doubled only when route symmetry is accepted by the user.
- Stage is for testing only; production operations must use the production host.

## Core data model

### `mb.commercial.contract`

Represents commercial and operational obligations. The base model is venue/partner based; the depot bridge specializes it for a permanent depot.

Key fields:

- company and active state;
- venue/depositary partner; the depot bridge adds the depot warehouse;
- project/analytic account;
- contract start/end and attachment;
- origin partner/address and frozen default travel assumptions; the Fleet bridge adds a default vehicle;
- obligation policy; the depot bridge adds refill policy;
- monthly fixed rent and tax/product/account configuration;
- rent billing method: separate vendor bill, included in depositary settlement, or informational only;
- permanence obligation: occurrences or days/hours per month, duration per occurrence, responsible users;
- occurrence templates for refill and permanence tasks;
- notice period and review date.

Constraints:

- company must match project, analytic account, journals, and products; installed bridges additionally check warehouse, vehicle, and supply records;
- the depot bridge permits only one active contract per depot unless an overlap is explicitly supported later;
- monetary fields cannot be negative;
- a billing method that creates bills requires a supplier, purchase tax/product, expense account, and journal-compatible company configuration;
- terminal months/posted bills are not rewritten when contract terms change.

### `mb.commercial.operation`

Represents one planned/actual refill, permanence shift, or market occurrence.

Key fields:

- base operation type: market/fair or venue attendance; the depot bridge adds depot refill and depot permanence selection values;
- company, project, task, responsible users;
- venue partner/address and optional contract; the depot bridge adds the warehouse;
- planned/actual start/end and working hours;
- travel estimate; the Fleet bridge adds vehicle assignment;
- the stock bridge adds preparation/refill/return picking links;
- expected visitor/sales assumptions;
- stored approved planning baseline plus computed actual revenue/cost/margin from linked evidence;
- lifecycle: draft, quoted, approved, scheduled, in progress, done, financially closed, cancelled;
- close date/user and exception notes.

State rules:

- draft/quoted data are editable;
- approval freezes the planning baseline;
- operational completion freezes actual operation dates and task/work assignments;
- stock close, when the stock bridge is installed, freezes operation-owned stock allocations and evidence links after reconciliation;
- financial close freezes operation-owned assumptions, links, allocation decisions, and the approved baseline; it cannot freeze external accounting records;
- computed actuals may continue to update when already-linked invoices are paid/reconciled or linked supplier documents are posted/credited;
- corrections to operation-owned data after close use controlled reopen rights, while corrections to posted documents use native reversal/credit workflows.

### `mb.commercial.cost.line`

Planning lines only, grouped into:

- toll, fuel, paid travel time;
- working/setup/selling/teardown labour;
- monthly rent allocation;
- stall/registration fee;
- parking, accommodation, meals, card fees, other;
- commission and product variable cost assumptions.

Each line identifies whether it is fixed, per hour, per kilometre, per day, percentage of revenue, or per unit. Base fields may link vendor-bill/timesheet/analytic evidence available through base dependencies; optional bridges add expense, purchase, stock, MRP, Fleet, Sales, and POS evidence links. Actual totals are aggregated from those source records instead of copying a second actual amount.

### `mb.depot.assortment.rule`

Defined by the depot bridge. It defines refill targets by either exact product or assortment bucket:

- depot contract;
- product/product category/collection/price band;
- minimum display quantity;
- target display quantity;
- safety days and target days of cover;
- rolling demand window;
- optional season/date range;
- priority and active flag.

Assortment buckets are important for unique ceramic pieces: the system can say “add four mugs between EUR 25 and EUR 40,” but it cannot forecast the sale of a particular one-off serial number. The final item selection remains manual and shows only available source stock.

### Extensions to native records

- `project.project`: commercial operation/contract type, generic event links, baseline totals, and smart buttons; the depot bridge adds depot links.
- `project.task`: operation link and travel/work hour split.
- `stock.picking`: added only by the stock bridge; operation/project link only, with no custom done-state manipulation.
- vendor/customer invoice lines: analytic distribution through the appropriate base/Sales bridge; expense lines through the expense bridge.
- `mrp.production` and `purchase.order.line`: added only by their supply bridges.
- `fleet.vehicle`: added only by the Fleet bridge for TollQuote defaults and cost-per-kilometre fallback.

All new company-bound models require a required/indexed `company_id`, `_check_company_auto = True`, `check_company=True` on company-bound relations, and standard `company_id in company_ids` record rules.

## Depot refill forecasting

### Evidence

Use only completed depot sale reports/confirmed sales for demand. Exclude draft reports, cancelled lines, returns without their sign, manual stock corrections, and internal transfers from sales velocity.

Read current depot availability from Odoo stock quantities at the depot location. Respect reservations, tracked lots/serials, UoM conversion, and company boundaries.

### First algorithm

For each product or assortment bucket, measure eligible exposure days rather than blindly using every elapsed calendar day. A day is exposed only when the depot had saleable stock for a meaningful part of that day. If historical stock evidence is insufficient to reconstruct exposure, retain calendar-day velocity but flag the result as stockout-biased/low confidence.

```text
average_daily_sales = eligible_sold_quantity / eligible_in_stock_days
forecast_stock_on_visit = available_now - average_daily_sales * days_until_visit
suggested_quantity = max(0, target_quantity - forecast_stock_on_visit)
days_of_cover = available_now / average_daily_sales
refill_due_date = date when projected stock reaches minimum/safety stock
```

If there is insufficient history, use the configured minimum/target display quantities and label the suggestion “policy based,” not “forecast based.” Show sample size, window, exposed days, stockout days, last sale date, and confidence flags so users can judge the result. Guard zero velocity explicitly: days of cover/refill due date are then undefined rather than divided by zero.

### Workflow

1. A daily cron updates cheap forecast metrics only; it does not call TollQuote or create transfers.
2. The depot dashboard shows overdue, due soon, and healthy depots.
3. The user opens a proposed refill, reviews assortment suggestions, and selects actual serialised pieces from source stock.
4. **Create refill transfer** creates a normal draft internal picking with the depot route and scheduled date.
5. Stock users reserve and validate it through Odoo's standard workflow.
6. The operation records the actual completion from the picking; it never writes `date_done` after validation.

Later, several due depots can be grouped into a trip. Multi-stop optimization is a separate phase because cost allocation and route ordering require explicit rules.

## Contract rent and permanence

### Fixed rent

Treat a rent charged by the depot as a supplier cost:

- create a draft vendor bill for the configured monthly period through **Prepare rent bill**;
- use one dedicated service product and the contract's analytic distribution;
- prevent duplicate bills with a unique contract/period key;
- let Accounting review, post, pay, credit, and correct it normally;
- allocate the planned monthly rent directly to the depot project for monthly profitability.

If the depot deducts rent from its settlement, show both gross sales/commission and rent separately. Do not net rent out of recognized turnover or mutate the depot invoice. Any settlement integration must be specified and legally/accountingly reviewed before implementation.

### Permanence

Do not use native task recurrence to populate the contractual calendar: Odoo 19 creates the next native recurrence only when the current task closes. Instead, use `mb.commercial.obligation` and `mb.commercial.obligation.occurrence` records with a rolling planning horizon (default six months).

An obligation stores contract, type, required occurrences/days/hours per period, default duration, responsible users, valid dates, and generation horizon. Each occurrence stores the contractual period, planned start/end, generated task, completion evidence, and state. A unique obligation/period/sequence key makes generation idempotent.

A bounded cron and explicit **Generate occurrences** action extend the horizon without duplicating tasks. Generated occurrences are draft proposals until the user assigns concrete dates; approved occurrences create/link ordinary dated project tasks and become calendar-visible. Changing future contract terms creates new dated terms and regenerates only unapproved future occurrences. Completed or approved historical occurrences are never rewritten.

The user records actual time through timesheets. A monthly compliance indicator compares required, generated, scheduled, completed, and missing days/hours. “X days per month” is not encoded as “every N days”; weekdays, holidays, negotiated dates, leave, and reassignment remain visible and reviewable. Native recurring tasks may still be used for unrelated sequential reminders, but they are not the contract compliance source.

## Market planning

### Setup wizard

Create a market project from a native project template plus commercial fields:

- organizer and venue;
- event dates/opening hours;
- setup and teardown time;
- travel origin and round trip; the Fleet bridge adds vehicle selection;
- number of workers and hourly cost assumptions;
- stall fee, electricity, parking, accommodation, and other fixed costs;
- expected sales mix, average basket, payment fees, and commissions;
- desired market assortment and display stock;
- stock preparation deadline; the stock bridge adds the optional preparation picking.

Approval creates/schedules tasks but does not validate stock or post financial documents.

### Market stock and production planning

Each market operation has a stock plan representing what should be available at the event. This is a planning target, not a stock move or sales forecast by itself.

`mb.market.stock.plan.line` fields:

- market operation and company;
- exact product or assortment bucket (category, collection, product type, and optional price band);
- desired opening quantity;
- safety/replacement quantity kept outside the display;
- expected sold quantity;
- expected unit price and cost source/date;
- the stock bridge adds source warehouse/location, on-hand now, reserved now, incoming/outgoing before cutoff, and forecast available at the preparation date;
- shortage quantity;
- base supply method: manual selection; installed stock/MRP/purchase bridges add take-from-stock, manufacture, and purchase methods respectively;
- linked preparation move lines, manufacturing orders, or purchase lines are defined only by their owning bridges;
- readiness state and blocking notes.

For repeatable exact products, use one internally consistent stock basis:

```text
required_quantity = desired_opening_quantity + safety_quantity
forecast_available = on_hand_now + confirmed_incoming_before_cutoff - confirmed_outgoing_before_cutoff
shortage_quantity = max(0, required_quantity - forecast_available)
```

Reserved outgoing demand is included once in `confirmed_outgoing_before_cutoff`; it is not also subtracted from already-free stock. Prefer Odoo's dated forecast data/hook when it represents the same company, warehouse/location, product, UoM, and cutoff. Store the calculation timestamp and component quantities so the result is explainable and can be refreshed.

Assortment allocation rules prevent overlapping demand:

1. Every concrete serial/lot/product quantity can satisfy at most one market plan line.
2. Explicit exact-product targets allocate first.
3. Concrete pieces manually selected for a bucket reduce that bucket's unmet target and are excluded from every other bucket in the same operation.
4. Remaining buckets are evaluated by explicit priority; overlapping bucket definitions either allocate sequentially or block approval until the user resolves the overlap.
5. Supply created for one plan line carries that line as its origin and cannot cover another line unless it is explicitly reallocated.

Use Odoo's forecast quantities, replenishment/procurement rules, bills of materials, manufacturing lead times, and workcenter calendars. Do not implement a parallel MRP scheduler. The commercial module supplies a dated demand and traceability link; native MRP decides feasibility and execution.

Workflow:

1. The user defines an exact-product or assortment target while planning the market.
2. With the stock bridge, **Check availability** shows on-hand, reserved, dated incoming/outgoing, forecast availability, shortage, calculation time, and the preparation cutoff. The base/stock phase does not claim a safe production-start date.
3. For assortment buckets, the user selects concrete available pieces first; remaining shortage may be assigned to suitable repeatable products/BOMs.
4. With a supply bridge, **Prepare supply** opens a review wizard. The MRP bridge may create idempotently linked draft MOs; the purchase bridge may create idempotently linked draft RFQ lines. Odoo has no generic user-facing “procurement request” document, so the plan does not invent one.
5. Draft supply is **Proposed**, not forecast incoming or in production. Manufacturing/purchase users review quantities, components, capacities, kiln/firing grouping, vendors, and deadlines. An explicit native confirmation makes the resulting stock moves eligible incoming evidence.
6. After a confirmed MO exists, native MRP dates, component availability, routing/workcenter calendars, and the ceramics kiln workflow determine the planned start/finish and late risk. Before then, any lead-time date is clearly labelled a rough estimate.
7. **Prepare market stock** creates a normal draft internal picking to a company-owned internal market location, reserving only completed available goods.
8. The event's POS configuration or sales delivery source must explicitly use that market location. Sold stock leaves it through native POS/sales stock moves, losses/damage use native scrap, and unsold goods return through a standard return/internal transfer.
9. Actual sold, scrapped, and returned quantities reconcile the preparation quantity before stock close and feed profitability and the next planning baseline.

The market date alone must not create production. Supply is generated only after the stock plan is approved, because event cancellation, assortment changes, and shared stock demand can materially change production.

For unique ceramics, an assortment shortage such as “six mugs in the EUR 25–40 range” is not automatically converted into six copies of an arbitrary SKU. The user chooses existing serialised pieces or explicitly maps the bucket to one or more manufacturable templates. This preserves lot/serial genealogy and avoids false demand precision.

Readiness indicators:

- **Unplanned**: no stock target;
- **Shortage**: target exceeds forecast availability and no supply covers it;
- **Supply proposed**: linked draft MOs/RFQs cover part/all of the shortage but are not forecast incoming;
- **Supply confirmed**: confirmed MOs/purchases cover part/all of the shortage and now count as incoming evidence;
- **In progress**: the native MO/purchase state shows production or supplier fulfilment has started;
- **At risk**: planned completion is after the preparation cutoff or components/capacity are unavailable;
- **Ready to pick**: sufficient finished stock is free;
- **Prepared**: preparation picking is assigned/done;
- **Returned/closed**: post-market reconciliation is complete.

Show this readiness on the market form, planning calendar, and dashboard. Calendar warnings should surface production/preparation lateness without turning every MO into a duplicate commercial calendar event.

### Market stock location

The stock bridge creates or selects a company-owned `usage='internal'` location under an explicit warehouse/view location. Do not use the generic company-neutral inter-warehouse transit location. Configuration identifies whether a reusable market location or one internal child location per occurrence is appropriate; either choice preserves company ownership and valuation.

The operation cannot be stock-closed until preparation moves, POS/sales deliveries, scraps, and return moves reconcile by product and lot/serial. The stock bridge provides discrepancies rather than forcing quantities or done states. Cancelling an event cancels only draft moves; completed preparation is reversed with normal returns.

### Break-even calculations

For each expected product or sales-mix line:

```text
channel_fee_amount = sale_price_excluded_tax * channel_fee_rate
net_unit_revenue = sale_price_excluded_tax - channel_fee_amount
unit_contribution = net_unit_revenue - product_unit_cost - other_variable_unit_cost
weighted_contribution_per_unit = sum(mix_share * unit_contribution)
work_labour_cost = planned_work_hours * work_hourly_cost
travel_labour_cost = planned_travel_hours * travel_hourly_cost
accepted_travel_cost = exactly_one(provider_total, selected_route_components, manual_travel_total)
selected_route_components = toll + fuel + travel_labour_cost + ferry + zone + other_route_costs
fixed_event_cost = accepted_travel_cost + work_labour_cost + stall/rent + parking + accommodation + other_fixed_fees
break_even_units = ceil(fixed_event_cost / weighted_contribution_per_unit)
contribution_margin_ratio = weighted_contribution / weighted_net_revenue
break_even_revenue = fixed_event_cost / contribution_margin_ratio
```

Mix shares must be non-negative and normalize to 100% (or the calculation is blocked). Rates are stored as decimal/percentage fields and converted to monetary amounts before subtraction. Hours are multiplied by a monetary hourly rate before inclusion.

Guard against zero/negative contribution and missing product cost. Because this installation may use estimated unit costs, show the cost source and date on every scenario and label the result “estimate.” Allow optimistic/base/pessimistic scenarios without creating accounting entries.

Route-cost selection is explicit and mutually exclusive:

- either use TollQuote's accepted total operating cost;
- or sum selected accepted components such as toll, fuel, driver, ferry, and zone costs;
- or use manually entered components.

If the accepted provider total already contains driver or fuel cost, the scenario cannot add the same travel labour/fuel component again. On-site setup/selling/teardown labour remains separate from travel labour.

Actual profitability comes from native project/accounting/analytic evidence and any narrow channel profitability hook, not by overwriting the plan with actuals. Show variance for revenue, labour hours, travel, other cost, margin, units/baskets, and break-even attainment.

## Navigation and user experience

Add a top-level **Commercial Operations** app, separate from Inventory:

- Dashboard
  - due depot refills;
  - permanence obligations;
  - upcoming markets;
  - incomplete quotes/configuration;
- Operations
  - all operations;
  - planning calendar;
  - refill visits;
  - permanence;
  - markets;
- Depots
  - contracts;
  - refill forecast;
  - assortment rules;
- Profitability
  - planned versus actual;
  - depot by month;
  - market/event comparison;
  - break-even scenarios;
- Configuration
  - TollQuote connector;
  - cost assumptions;
  - operation/project templates.

Bridge-owned menus and fields appear only when that bridge is installed: the depot bridge owns **Depots**, stock/MRP bridges own availability/supply actions, the Fleet bridge owns vehicle filters/conflicts, and revenue/expense bridges own their evidence smart buttons. The base app must render and operate cleanly without them.

Depot menus should expose smart buttons into the same records, but should not duplicate actions with different domains or context behavior.

### Planning calendar

Provide a native Odoo calendar view on `mb.commercial.operation`, with day, week, month, and year navigation. It is the shared planning calendar for:

- markets and fairs;
- depot refill visits;
- depot permanence shifts;
- setup and teardown periods;
- optional travel windows.

Calendar behavior:

- clicking an empty date/time opens a quick-create market/operation with the selected start already populated;
- the full form captures venue, organizer, opening dates, setup/teardown, assigned workers, project, expected costs, and stock-preparation deadline;
- multi-day markets display as one continuous event using planned start/end datetimes;
- all-day events are supported, while actual working hours remain separate for labour costing;
- colors identify operation type and state, with base filters for market, responsible person, company, and approval state; the depot bridge adds refill, permanence, and depot filters;
- drag-and-drop rescheduling is allowed only before approval and must update the linked task dates through a controlled model method;
- approved, completed, financially closed, or cancelled operations cannot be silently moved from the calendar;
- overlapping assignments for the same responsible user show a warning before approval; the Fleet bridge adds vehicle conflicts;
- deadlines for stock preparation and vendor/organizer payment remain task activities, not fake calendar events;
- opening an event shows base smart links to route quote, break-even scenario, project/tasks, timesheets, and actual profitability; installed bridges add stock, expense, supply, vehicle, and revenue links.

Use the commercial operation as the calendar source and keep its linked `project.task` synchronized. Do not maintain an unrelated custom calendar record or generate duplicate events in both models. Odoo calendar activities may provide reminders, while the operation remains the authoritative market/refill/permanence schedule.

## Accounting and analytic propagation

- Each commercial project owns the analytic account used for the profitability unit.
- Generated draft vendor bills and bridge-created expenses receive that analytic distribution through standard Odoo fields.
- Depot consolidated invoice revenue must receive the depot project's analytic distribution through a narrow extension hook when the invoice is prepared. The existing “URSSAF when consolidated invoice is paid” recognition remains unchanged.
- Market POS/sales/invoice revenue needs an explicit event/project selection or event-specific POS configuration; do not infer the event from invoice date alone. The relevant bridge also links the native outbound picking/stock evidence to the same event.
- Product cost in the planning scenario is informational. Actual cost of goods sold should come from Odoo accounting/stock valuation when configured; do not create duplicate analytic cost lines.
- Each Sales/POS/depot bridge must prove both sides independently: revenue reaches the project exactly once and the corresponding outbound stock/valuation cost reaches project profitability exactly once. If the installed Odoo bridge cannot carry analytic cost for that channel, implement a narrow `_get_profitability_items` extension backed by native stock/account evidence rather than manufacturing duplicate analytic journal lines.
- If stock operation analytic cost is enabled, test internal refill moves carefully so a transfer does not appear as consumption. Only actual outbound customer delivery/consumption belongs in profitability.
- Posted moves and locked accounting periods remain immutable.

Operational close, stock close, financial-document completeness, accounting reconciliation, and URSSAF recognition are separate statuses:

- **Operationally done** freezes actual event dates/work evidence owned by the operation.
- **Stock reconciled** means prepared, sold, scrapped, and returned quantities balance.
- **Documents complete** means expected invoices, bills, expenses, and credits are linked and no draft document is missing.
- **Financially closed** freezes operation-owned assumptions/allocations after Accounting review.
- **Accounting reconciled** is computed from linked posted documents and their payment/reconciliation state and may become true after financial close.
- **URSSAF recognized** remains computed by the URSSAF module from its legal recognition events, including payment of consolidated depot invoices; it is not frozen or rewritten by this module.

Financial close does not copy a final “actual” number or prevent native payment, reconciliation, credit, or reversal. Reports recompute actuals from immutable links to accounting/analytic evidence. Adding/removing evidence links or changing allocation after close requires a controlled reopen with chatter, but state changes on already-linked native documents continue to flow into computed reporting.

## Security and audit

Groups:

- Commercial Operations User: view and operate assigned tasks/operations, request quotes, prepare transfers;
- Commercial Operations Manager: contracts, forecasts, scenarios, approvals, reopen before financial close;
- Accounting: bill configuration, bill preparation/posting through native rights, financial close;
- System Administrator: connector credentials.

Required controls:

- multi-company rules on every new parent and line model;
- secrets restricted to System Administrator and redacted everywhere;
- chatter on contract/operation/estimate lifecycle changes;
- immutable accepted quote snapshots and approved planning baselines;
- SQL uniqueness for rent contract/period, obligation/period/sequence, and supply-origin generation idempotency;
- no `sudo()` around business access; narrow sudo only for protected credential retrieval and scheduled service calls;
- no manual cursor commits; use normal transactions and Odoo 19 cron progress for bounded batch jobs;
- financial close server-side guards, not view-only readonly fields.

## Failure and edge cases

- TollQuote unavailable, quota exceeded, authentication rejected, incomplete country pricing, or no route;
- destination without geocodable address or coordinates;
- different outward and return routes;
- route/date or contract changed after a quote was accepted;
- overlapping depot contracts or contract ended mid-month;
- partial-month rent, rent increase, rent credit, or bill already posted;
- permanence expressed in days but recorded in hours;
- multiple employees sharing one event;
- employee time cost absent or access-restricted;
- no product cost, negative margin, or one-off products;
- overlapping assortment buckets or the same serial/product allocated twice;
- depot demand history containing long stockout periods or insufficient exposure evidence;
- returns and cancelled depot sales;
- depot out of stock while source warehouse also lacks suggested pieces;
- reserved/serialised stock selected by two refill drafts;
- market cancelled after expenses or stock preparation;
- draft supply proposed but never confirmed, or confirmed supply later cancelled/shortened;
- operation spanning two months/currencies/companies;
- analytic distribution edited after approval;
- financially closed operation followed by payment, reconciliation, credit, reversal, or later URSSAF recognition.

## Delivery phases

### Phase 0 — decisions and accounting prototype

- Confirm whether rent always arrives as a supplier bill or can be settlement-netted.
- Confirm the source address, vehicle assumptions, employee cost policy, and company timezone/currency.
- Confirm whether market revenue is recorded in POS, Sales, depot reports, or a mixture.
- Select the required bridge-addon matrix for the installed Odoo applications and verify the matching native project-profitability bridges.
- Prototype one project/analytic account and prove actual revenue, timesheet, expense, vendor bill, and cost-of-goods behavior in Odoo 19.
- Obtain TollQuote production credentials, quotas, retention terms, and API stability expectations.

Exit: one manual depot month and one market event reconcile from accounting evidence to the expected margin.

### Phase 1 — planning and TollQuote

- Scaffold `mb_commercial_operations` and the selected bridge skeletons with dependency isolation, security, and company rules.
- Add contract, operation, cost line, quote connector/estimate, and project/task links.
- Implement one-way/return TollQuote calculation, snapshots, revisions, warnings, and manual fallback.
- Add market setup and break-even scenarios.
- Add generic market assortment targets plus, through the stock bridge, explainable dated availability, shortage/readiness indicators, and stock-preparation deadlines without supply creation or production-start claims.
- Add the shared planning calendar, calendar quick-create, conflict warnings, contractual obligations, and an idempotent six-month occurrence horizon.

Exit: a user can approve a fully costed market or depot visit without creating accounting or stock side effects.

### Phase 2 — accounting evidence and actual profitability

- Propagate analytic distribution through the selected bill, expense, Sales, POS, and depot bridges.
- Prepare idempotent monthly rent vendor bills.
- Record actual time through timesheets and actual route costs through expenses/bills.
- Add planned-versus-actual and event/depot/month reports.
- Implement separate operational, stock, document-completeness, financial-close, accounting-reconciliation, and URSSAF status semantics.

Exit: planned-to-actual variance reconciles to analytic/accounting records, with no duplicate costs.

### Phase 3 — refill forecast and stock execution

- Add assortment rules, eligible sale/exposure evidence, stockout-aware rolling velocity, due dates, and confidence flags.
- Add the review wizard for unique serialised pieces.
- Create standard draft internal pickings and link completion back to operations.
- Add the optional MRP/purchase bridges, idempotent reviewed draft MO/RFQ creation, explicit native confirmation, and production deadline/risk links only after supply exists.
- Add market preparation and return transfers with stock reconciliation.
- Add depot refill dashboard and notifications.

Exit: suggestions are reproducible from sales/stock evidence and stock execution remains fully native.

### Phase 4 — optional optimization

- group multiple depot visits into one trip;
- use TollQuote batch/freight alternatives where appropriate;
- define explicit shared-trip cost allocation by distance/time/stop;
- evaluate OCA Field Service if dispatch volume now justifies its separate order model;
- add optional Fleet bridge and deeper vehicle actual-cost allocation.

## Test plan

### Unit/model tests

- break-even formulas, rate-to-amount conversion, hours-to-cost conversion, mix normalization, provider-total/component exclusivity, rounding, tax-excluded prices, and zero/negative contribution;
- rent partial periods, unique generation, revisions, credits;
- route outward/return totals, currencies, warnings, incomplete quote handling;
- forecast windows, returns, no-history policy, stockout/exposure days, zero velocity, assortment buckets, and UoM;
- market on-hand/reserved/incoming/outgoing/forecast/shortage quantities and cutoff dates, proving reserved demand is counted once;
- exact products versus overlapping assortment buckets, unique allocation, and explicit manufacturable-template mapping;
- contractual horizon generation, unique occurrence keys, dated term changes, and no duplicate/rewrite of approved history;
- base installation and upgrade with every optional bridge absent, plus each bridge's isolated installation/upgrade;
- company consistency, record rules, state immutability, close/reopen rights.

### HTTP/provider tests

- mock the published TollQuote contract; never depend on the live service in the standard suite;
- success, timeout, 401, 429, 5xx, malformed payload, missing totals, `unpriced`, and API revision;
- verify tokens and sensitive headers never enter logs/chatter/snapshots.

### Odoo integration tests

- contractual occurrence horizon/task creation and completion; native recurrence is tested only for unrelated sequential reminders;
- calendar quick-create, multi-day events, filters, conflict warnings, and task-date synchronization;
- calendar drag/drop is accepted only in editable states and rejected after approval/close;
- timesheet cost reaches the correct project profitability unit;
- expense/vendor bill/revenue analytic distributions and Sales/POS/depot revenue plus matching outbound cost exactly once;
- internal refill transfer does not create a duplicate expense;
- normal picking validation, return, cancellation, and serial reservation;
- approved shortages create reviewed draft native MOs/RFQs only once; draft supply remains proposed, and confirmation/cancellation updates forecast/readiness without duplication;
- MRP component availability, lead time, workcenter/kiln capacity, completion, cancellation, and late-risk propagation;
- market preparation picks only completed free stock and post-event returns reconcile correctly;
- company-owned internal market location preserves valuation; POS/sales deliveries, scraps, and returns reconcile prepared stock by lot/serial;
- consolidated depot invoice keeps its payment-date URSSAF recognition and separately carries analytic revenue;
- operational/financial locks reject unsafe operation mutations while payment, reconciliation, credits, reversals, and later URSSAF recognition on linked evidence remain possible and recompute statuses;
- multi-company users cannot see or alter another company's contract, quote, operation, or credential.

### Acceptance scenarios

1. Monthly-rent depot with two permanence days and one refill trip, all visible six months ahead without closing the prior occurrence.
2. Commission depot with rent deducted on the statement, displayed gross and separate.
3. Market with two workers, outward/return tolls, stall fee, card percentage, and mixed product margins.
4. Cancelled market after a non-refundable fee.
5. One-off ceramics assortment with no exact-SKU demand history.
6. TollQuote returns a route but flags an unpriced charge; approval is blocked until acknowledged/manual cost is entered.
7. A market target needs 20 mugs, with 10 on hand, 4 reserved outgoing, and 2 confirmed incoming before cutoff: forecast availability is 8 and an idempotently reviewed 12-unit draft MO remains “Supply proposed” until native confirmation.
8. Exact-product and overlapping bucket targets cannot allocate the same mug/serial twice.
9. A financially closed depot operation later receives payment; accounting reconciliation and URSSAF status update without reopening or rewriting the operation baseline.

## Open decisions for review

1. Should monthly depot rent always create a separate supplier bill, or are some depositaries contractually allowed to net it on the sales settlement?
2. Which system records market revenue today: POS, Sales invoices, depot-style consolidated reports, or manual accounting?
3. Is labour cost the employee's Odoo hourly cost, a standard company rate, or opportunity cost including social charges?
4. Should travel time be fully paid/costed, or use a separate rate from on-site work?
5. For product cost estimates, should the baseline be the Odoo cost, an explicit planning cost, or the sale price temporarily used as a conservative proxy?
6. Do depot refill targets operate by exact product, category/collection/price band, or a mixture?
7. Is one project per market occurrence acceptable operationally? This is the cleanest native profitability boundary.
8. Who may financially close or reopen an operation?
9. Which bridges are required initially: depot, stock, MRP, purchase, Fleet, expense, Sales, and/or POS?
10. Should market stock use one reusable company-owned internal location or one internal child location per occurrence?
11. Is the default six-month contractual occurrence horizon sufficient?

## Recommended first slice

Implement one vertical slice before forecasting: create a market project/operation, quote a round trip with TollQuote, add labour and stall costs, calculate break-even, schedule tasks, collect timesheets/expenses/revenue, and reconcile actual profitability. This proves the common cost and analytic model. Then add depot contract obligation horizons/rent and finally the more domain-specific refill forecast.
