# Depot Sale Interface Plan

## Objective

Provide a single interface under **Dépôt-vente → Record a sale** where an
authorised user selects a depot, enters the actual sale date and the pieces
reported as sold, then records the complete transaction atomically.

One successful action must produce one correctly sourced Sales Order and one
validated delivery for each distinct effective sale date in the depot report.
It may optionally create one draft consolidated invoice; otherwise the completed
orders remain available for later consolidated invoicing.

Recording or delivering the depot sale must not create URSSAF turnover. URSSAF
turnover is cash-basis evidence and is recognised only when the customer pays
the invoice, including a later consolidated invoice.

The interface must preserve the distinction between:

- the date on which the depositary says the item was sold;
- the effective stock-movement date;
- the date on which the sale was entered in Odoo; and
- the invoice date.

### Accounting and reporting date rules

The implementation must keep the following timelines independent:

- **Depot statement:** use the depositary's reported **Sold on** date.
- **Stock history:** use the delivery's effective date.
- **VAT threshold evidence for goods:** use the completed delivery date.
- **URSSAF turnover and receipt book:** use the payment or reconciliation date
  of the posted customer invoice.

Neither Sales Order confirmation, delivery validation, invoice creation, nor
invoice posting is itself an URSSAF receipt event. A partial payment recognises
only its proportional share on the payment date. The final payment clears the
remaining category-level rounding residual. If several depot Sales Orders are
combined into one invoice, payment recognition must use that consolidated
invoice and must not duplicate its underlying deliveries.

## 1. Stabilise the existing workflow

Before adding the interface:

- Commit the current depot fixes and migrations.
- Retain delivered-quantity invoicing for storable sale products.
- Retain depot-warehouse enforcement during Sales Order confirmation.
- Retain removal and archival of legacy depot routes.
- Confirm that the existing cross-module test suite remains green.

These behaviours are prerequisites for the automated workflow and must not be
reimplemented inside the interface. The existing fixes must be committed as a
separate baseline before implementation starts.

## 2. User interface

Add a menu entry:

**Dépôt-vente → Record a sale**

Implement this as a persistent `mb.depot.sale.report` model with persistent
`mb.depot.sale.report.line` records. A transient wizard is not sufficient: the
external report, its processing state, the generated documents, and any later
reversal must remain auditable.

The report header should contain:

- **Depot**: required depot warehouse.
- **Depot report reference**: required external reference.
- **Report received on**: required; defaults to the current date.
- **Notes**: optional contextual information from the depositary.
- **Create draft invoice**: optional and disabled by default.
- **State**: Draft, Processed, Reversal required, or Reversed.
- Links to every generated Sales Order, delivery, invoice, return, and credit
  note.

Each report line should contain:

- **Sold at**: required effective sale date and time;
- product;
- lot or serial number where applicable;
- quantity;
- **reported public unit price**: required immutable commercial evidence;
- **reported commission percentage**: required immutable commercial evidence;
- computed net unit price and net line amount; and
- an optional depositary line reference.

One report may contain sales from several dates. Processing groups its lines by
effective sale date and creates one Sales Order and delivery per date. This
allows one monthly external reference to remain unique without forcing the user
to invent a reference for each day.

After completion, keep the processed report open and expose smart buttons for
all generated documents.

## 3. Persistent reference and idempotency

Add a database uniqueness constraint covering company, depot warehouse, and the
required external report reference on `mb.depot.sale.report`. The constraint
continues to apply to processed and reversed reports; a reference is never
reusable.

Submitting the same depot reference twice must fail before creating any business
documents. The error must identify and link to the existing report.

Propagate the report reference and report record to every generated Sales Order,
delivery, and invoice. The Sales Orders additionally store their effective sale
date and immutable reported commercial totals.

## 4. Preflight validation

Perform every validation before confirming the Sales Order:

- The selected warehouse is an active depot.
- Its legal structure is **Purchase-resale on sale**.
- A depositary and commission pricelist are configured.
- No line's effective date is in the future.
- No line's effective date crosses the closed-period barrier defined below.
- At least one non-zero sale line exists.
- Every product is storable, saleable, and configured for delivered-quantity
  invoicing.
- Every product is present and unreserved at the selected depot.
- The requested quantity does not exceed current availability.
- The requested quantity was present at the depot at the selected historical
  instant.
- Required serial or lot numbers are supplied and belong to the selected product.
- Each selected serial or lot is currently at the selected depot and unreserved.

For untracked products, reconstruct the depot balance at the selected instant and
at every subsequent stock-movement boundary through the present. Applying the
backdated sale must not make any intermediate or current balance negative.

For serialised products, validate the complete crossing history for the exact
serial number. It must have entered the depot no later than the selected instant,
must not have left before that instant, and must still be present and unreserved.
A serial-tracked line has quantity exactly one, and the same serial may appear
only once in the report.

### Closed-period barrier

Add a company-level, read-only `depot_sale_closed_through` date in
`l10n_fr_micro_urssaf`. Filing an URSSAF declaration advances it to the later of
its current value and the filed declaration's `date_to`. Resetting, deleting, or
replacing a declaration must never reduce this date.

Do not add a reverse dependency from `mb_depot` to
`l10n_fr_micro_urssaf`—the latter already depends on the former. `mb_depot`
exposes an overridable closed-period-barrier hook for accounting and inventory;
`l10n_fr_micro_urssaf` extends that hook with its permanent horizon and advances
the horizon in `action_file` in the same transaction.

During migration, initialise the horizon from every currently filed declaration
and any reliably recoverable tracked filing history. Because an earlier filing
may already have been reset, require an Accounting Manager to review and confirm
the migrated horizon before enabling **Record Sale** for each company. The
confirmation may advance the date but must never reduce an inferred date.

Compute one effective backdate barrier per company as the latest of:

- every applicable Odoo accounting lock date;
- the date of the latest posted inventory closing; and
- the permanent `depot_sale_closed_through` horizon advanced by filing an URSSAF
  declaration.

Every sale timestamp whose local company date is on or before that barrier is
rejected. In particular, once an URSSAF declaration is marked filed, no depot
sale may be inserted into that period or any earlier period, because goods VAT
threshold evidence is cumulative.

There is no manager, superuser, declaration-reset, or context bypass in the
report action. Reopening an URSSAF declaration for an accounting correction does
not reopen its dates for depot-sale entry. Late depot reports dated on or before
this permanent horizon must be handled outside this backdating interface through
an explicitly reviewed current-period correction workflow. The interface never
resets or edits a filed declaration.

Expose the computed barrier and its source on the report form so the rejection is
understandable. If the URSSAF module is installed and the company's migrated
horizon has not been confirmed, block processing entirely instead of assuming
that no closed period exists.

Failures must be actionable and name the affected product or serial number.

### Concurrency and exact reservation

Preflight checks alone are not sufficient. When processing begins:

1. Lock the report row so the same report cannot be processed concurrently.
2. Resolve the exact current quants needed by all report lines in a stable order.
3. Reserve through Odoo's stock APIs inside the same transaction.
4. If standard reservation selects different lots or serials, unreserve and build
   exact detailed operations for the selected quants using supported stock APIs.
5. Recheck quantities, reservations, lots, serials, historical balances, and the
   closed-period barrier after reservation and immediately before validation.

The concurrent loser must receive a clean availability error. Do not update
`stock.quant` quantities directly, and do not rely on a preflight result obtained
before another transaction acquired the stock.

## 5. Sales Order creation

For each distinct effective sale date, when validation succeeds:

1. Create a Sales Order using the depositary as customer.
2. Force the selected depot warehouse.
3. Apply the depot's commission pricelist.
4. Set the Sales Order date to that group's effective sale date and time.
5. Store the depot report, external reference, and effective date.
6. Create the requested product lines using the immutable reported public unit
   price and commission percentage. Do not recompute a historical sale from the
   product's current sales price or the depot's current commission.
7. Confirm the order through the standard Sales Order API.

The implementation must not manually create stock moves. The confirmed Sales
Order must remain the source of the delivery and invoice relationship.

After each confirmation, assert that:

- exactly one active delivery was produced;
- its operation type belongs to the selected depot;
- its source is the depot's stock location; and
- its destination is a customer location.

Any failed assertion must roll back every Sales Order and delivery created from
the report, including earlier date groups in the same action.

## 6. Delivery reservation and validation

For each generated delivery:

1. Reserve the requested quantities.
2. Match the exact serial and lot numbers from the submitted lines. Multiple
   lines for one product may be merged into one stock move, so distribute the
   report's selected lots across detailed operations by product, unit of measure,
   and reported commercial terms rather than assuming one move per report line.
3. Set completed quantities exactly to the reported quantities.
4. Ensure that no backorder or immediate-transfer ambiguity remains.
5. Validate the delivery through Odoo's standard validation method.
6. Write the selected effective date to the completed transfer.
7. Set **Sold on** on the transfer and its move lines.

After validation, verify that the picking, stock moves, and move lines carry the
selected effective date and that every move line carries the reported sale date.

The entire action must run in one database transaction. Do not commit between
date groups, Sales Order creation, reservation, delivery completion, or optional
invoice creation. An exception may leave the persistent report in Draft, but it
must leave no generated business document or partial stock movement.

## 7. Invoice behaviour

The default workflow should leave the completed order ready for later
consolidated invoicing.

When **Create draft invoice** is enabled:

- Consolidate all Sales Orders generated by the report using the standard Sales
  Order invoicing API.
- Keep it in draft; never post it automatically.
- Use the actual invoice creation/issuance date, not a backdated depot sale date,
  as the proposed invoice date.
- Store the earliest and latest delivery dates separately and display the
  report reference and delivery period on the invoice and PDF.
- Preserve the depot report reference and Sales Order relationship.

Creating the draft invoice must not affect an URSSAF declaration. Posting the
invoice must still leave URSSAF turnover at zero until a payment is reconciled.
The existing URSSAF CABA/reconciliation engine remains the source of receipt
events; the depot sale interface must not write declaration sources directly.

For the default consolidated workflow, multiple completed depot orders may be
combined into one customer invoice. URSSAF recognition then occurs when that
consolidated invoice is paid, on the payment dates and pro rata for partial
payments.

If today's invoice date is locked or the orders cannot legally be consolidated,
reject the optional invoice creation before any business documents are committed.
The user may then record the stock sale without the invoice option and handle
invoicing separately.

## 8. Security and auditability

- Add a dedicated **Depot Sale Manager** group with explicit access to the report
  models and the Sales and Stock permissions required to create and validate the
  underlying documents.
- Show and accept **Create draft invoice** only for users who also have the
  standard Accounting/Invoicing permission. Reject the option server-side when
  that permission is absent.
- Use the active company and its allowed depots only.
- Apply ordinary multi-company record rules.
- Record the responsible user and creation timestamp.
- Post a chatter message on the Sales Order and delivery containing the depot,
  report reference, effective date, and originating interface.
- Do not delete cancelled historical documents during migrations or recovery.
- Do not use `sudo()` to bypass Sales, Stock, Accounting, company, or record-rule
  checks in the processing action.

Backdating must be explicit in the interface and must not be available through a
silent default. Require an additional confirmation whenever at least one line is
dated before today.

## 9. Correction and reversal workflow

Processed report headers and lines are immutable. Corrections never edit the
original completed delivery or reuse its external reference.

Provide **Start reversal** for Depot Sale Managers:

1. Mark the report **Reversal required** and open the standard return workflow
   for every completed delivery.
2. Require the returned products, quantities, and serial numbers to match the
   original report unless a reason documents a partial correction.
3. If a draft invoice exists, cancel it through the standard invoice action.
4. If a posted invoice exists, require a linked credit note; if it has payments,
   use the standard reconciliation/refund workflow.
5. Mark the report **Reversed** only after all required returns and accounting
   corrections are linked and complete.

Returns and credit notes use their real correction dates. They are not silently
backdated, and their dates must be later than the same permanent closed-period
barrier. Reopening an URSSAF declaration does not permit a correction document
to be backdated into its filed horizon. The original report, reference, Sales
Orders, deliveries, invoices, and chatter remain intact for audit.

## 10. Tests

Add regression coverage for:

- One product and one serialised piece.
- Several products sold by one depot on one date.
- One external report containing several sale dates, producing one order and
  delivery per date without inventing additional references.
- Correct depositary, pricelist, commission, and order total.
- Historical public prices and commissions remain correct after current product
  prices or depot commission change.
- Correct depot warehouse, picking type, source, and customer destination.
- Reservation and delivery completion.
- Effective date propagation to picking, moves, and move lines.
- **Sold on** propagation and depot-statement recognition.
- VAT goods-threshold evidence on the selected delivery date.
- No URSSAF turnover after Sales Order confirmation or delivery validation.
- No URSSAF turnover after creating or posting an unpaid invoice.
- URSSAF turnover on the payment date of a consolidated invoice.
- Proportional URSSAF recognition across partial payments, including payments
  spanning declaration periods or calendar years.
- No duplicate URSSAF event when one consolidated invoice contains several
  depot Sales Orders and deliveries.
- No invoiceable quantity before the delivery is completed.
- Invoiceable quantity after delivery completion.
- Optional draft invoice creation.
- Default compatibility with consolidated invoicing.
- Duplicate depot report references.
- Concurrent submissions for the same product or serial number; exactly one may
  succeed.
- Missing, insufficient, or reserved stock.
- Incorrect and duplicate serial numbers.
- Sale date before placement at the depot.
- Future and locked dates.
- A filed URSSAF declaration blocks every sale date on or before its cumulative
  horizon, with no manager or superuser bypass.
- Resetting a filed declaration to Draft does not lower the permanent horizon or
  permit a sale in a previously filed period.
- Filing an older declaration never lowers a horizon already advanced by a later
  declaration.
- A company with an unconfirmed migrated URSSAF horizon cannot process a depot
  sale; confirmation can only preserve or advance the inferred horizon.
- Mandate depot rejection.
- An explicitly configured wrong warehouse or stale route.
- Multi-company access restrictions.
- Time-zone conversion around midnight and daylight-saving transitions.
- Atomic rollback after a forced failure during delivery validation.
- Invoice issuance date remains distinct from the delivery dates and the PDF
  displays the delivery period.
- Processed reports are immutable and the reversal workflow creates linked
  returns and credit notes without reusing the external reference.

Run the complete `mb_depot`, `l10n_fr_micro_enterprise`, and
`l10n_fr_micro_urssaf` suites after the focused tests.

## 11. Deployment and recovery

- Bump the `mb_depot` module version.
- Add migrations for the persistent report models, uniqueness constraints,
  security data, and the monotonic company-level URSSAF closing horizon.
- Upgrade a disposable test database and run the complete cross-module suite.
- Upgrade `odoo_test`.
- Verify the menu, access rights, date fields, generated relationships, and web
  health.
- Do not create a live smoke-test sale in `odoo_test` unless it represents a real
  depositary report; use a disposable database for mutation testing.

## Definition of done

An authorised user can enter one unique depot report containing one or more sale
dates and the sold pieces, then click **Record Sale** and receive:

- one confirmed Sales Order per effective sale date using the correct depot and
  immutable reported prices and commission;
- one completed delivery per effective sale date sourced from the depot;
- stock moves dated on the selected effective date;
- depot evidence carrying the selected **Sold on** date;
- invoiceable delivered quantities; and
- either no invoice, ready for consolidated billing, or one linked draft
  consolidated invoice dated on its actual issuance date when explicitly
  requested.

The completed delivery may affect stock history, the depot statement, and VAT
goods-threshold evidence, but it must not affect URSSAF turnover. URSSAF evidence
must appear only in the declaration period containing payment of the posted
invoice, including payment of a later consolidated invoice.

Duplicate entry, concurrent reservation loss, unavailable stock, a date on or
before the filed URSSAF/closing barrier, invalid commercial evidence, permission
failure, or any downstream error must leave no partial business transaction
behind. Processed reports are immutable and correctable only through linked
returns and accounting reversals.
