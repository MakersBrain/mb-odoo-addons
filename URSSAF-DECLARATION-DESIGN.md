# URSSAF declaration for a micro-entreprise

Research and implementation design for the periodic *déclaration de chiffre
d'affaires* of a French micro-entrepreneur ceramist selling through three
channels: dépôt-vente at galleries, direct B2C, and market stalls.

Reviewed and corrected August 2026. Rates, thresholds, exemptions and reliefs
are law-dated and must be treated as configuration, not constants in code.

The implementation half was rewritten against the Odoo 19 Community sources
(`odoo:19`, `addons/account`, `addons/point_of_sale`) after the first draft
proposed rebuilding machinery Odoo already ships. Every claim about existing
behaviour below carries the file and line it was read from.

---

## 1. What the declaration actually is

The micro-social regime replaces the whole self-employed contribution
calculation with a percentage applied to turnover. There is no result, no
deductible charge, no annual regularisation. Three consequences drive the entire
design:

**Cash basis, without exception.** The turnover of a period is what was
*encaissé* during that period, not what was invoiced. An invoice issued in
November and paid by transfer in January is declared in January. The trigger is
the date the money is received - cheque received, transfer credited, card
settled, cash taken. A cheque is encaissé the day it is handed over, not the day
it is banked, which is a data-entry rule and not something software can infer.

**Gross, before any deduction.** Turnover is the total sum received in
consideration of the sale, before any fee, commission or cost is taken out. A
platform that collects 100 EUR from the customer and remits 95 EUR to you
produces 100 EUR of declared turnover; the 5 EUR is a charge, and the micro
regime deducts no charge. Shipping re-invoiced to the customer is part of the
turnover. This rule is the one that decides the dépôt-vente treatment in
section 3.

*Gross* here means before deduction of fees, not tax-inclusive. Under the
franchise en base the two coincide, since there is no VAT. Once VAT applies the
declared base is the amount **hors taxes**; the design keeps that distinction
explicit rather than relying on the coincidence.

**Split by activity category.** The declaration form is not one box. Turnover is
entered separately per category because each carries its own rate and its own
abattement:

| Category | Cotisations 2026 | Abattement (income tax) | CFP |
| --- | --- | --- | --- |
| BIC vente de marchandises | 12,3 % | 71 % | 0,1 % (commerçant) / 0,3 % (artisan) |
| BIC prestation de services artisanale/commerciale | 21,2 % | 50 % | 0,3 % (artisan) |
| BNC profession libérale non réglementée | 25,6 % | 34 % | 0,2 % |

The BNC rate reached 25,6 % on 1 January 2026. It does not affect ceramics
sales; a teaching activity must be classified as BIC service or BNC from the
actual registered activity rather than inferred merely from the product being a
service.

**Zero is still a declaration.** Filing nothing triggers *taxation d'office* on
an over-estimated base plus a penalty per missing declaration. A period with no
receipts must be filed at 0.

**A period is never negative.** Refunds reduce the turnover of the period in
which they are paid out, but the URSSAF form cannot accept a negative category.
The software therefore displays a negative computed balance as an anomaly and
proposes 0 for transcription. Carrying the unused amount into a later filing is
not automated until the operator records the treatment confirmed by URSSAF in a
regularisation adjustment. The reviewed public guidance does not establish a
general automatic carry-forward rule strongly enough to encode one as law.

**Periodicity.** Monthly by default, quarterly on option, chosen at registration
and changeable once a year. Quarterly deadlines are 31 January, 30 April,
31 July, 31 October, each covering the three preceding months. The first
declaration is deferred. Monthly, it is due at the end of the fourth month after
the activity-start month and covers the start date through the end of the month
before filing (a 6 March start is due 31 July for March-June). Quarterly, it is
due at the end of the month following the calendar quarter after the start
quarter and covers both partial/start and following quarters (a 12 April start
is due 31 October for April-September).

**Other levies riding on the same declaration.** The CFP (table above) and the
*taxe pour frais de chambre consulaire* - CMA for an artisan - use the same
declared turnover and are collected with the social contributions. Chamber-tax
eligibility depends on registration and location. It is not due in the first
year; from the second year it is due only when the previous year's turnover
exceeded 5 000 EUR. The declaration report derives that condition from the
annual reference record rather than a timeless checkbox. Alsace and Moselle
have their own rates.

**Versement libératoire, if elected.** Income tax paid at the same time, at 1 %
of turnover for vente de marchandises, 1,7 % for BIC services, 2,2 % for BNC.
It is an option conditioned on the prior-prior year *revenu fiscal de
référence*. If not elected, turnover goes to the annual 2042-C-PRO and the
abattement applies there.

**ACRE.** This is taxpayer-specific and time-limited. For micro-enterprises
created before 1 July 2026 the payable rate is 50 % of the normal rate; for
those created from 1 July 2026 it is 75 % of the normal rate (a 25 % exemption),
through the end of the third civil quarter following creation. The grant, start,
end and payable coefficient belong in dated company configuration. The setup
wizard derives the coefficient from a dated ACRE rule record and snapshots it;
it is never a universal field on the ordinary contribution rate.

## 2. Thresholds that must be watched separately

Two independent ceilings, frequently conflated, but **not measured with the
same recognition rule**:

- **Franchise en base de TVA** - 85 000 EUR base / 93 500 EUR majoré globally,
  with 37 500 / 41 250 EUR service sub-limits,
  for mixed activity. The single 25 000 EUR threshold announced in the 2025
  finance law was definitively abandoned by the law of 3 November 2025;
  2026 thresholds are unchanged. Crossing the *majoré* figure ends the franchise
  immediately, from the actual date of the overrun. Its reference turnover is
  based on operations whose VAT exigibility has occurred: delivery for goods,
  and generally encaissement for services. It is therefore not the URSSAF
  cash-receipt total.
- **Régime micro itself** - 203 100 EUR goods / 83 600 EUR services for
  2026-2028. Crossing it after two consecutive years exits the micro regime
  entirely.

Both are annual and prorated in the first year, but their source events remain
different. The micro-regime ceiling follows turnover actually received; the VAT
franchise follows the hypothetical VAT exigibility of the underlying operation.

**Mixed activity is the case that actually applies here**, as soon as a workshop
is sold alongside pots, and each ceiling then has two limbs that must both hold:
for the VAT franchise, the global 85 000 EUR *and* a 37 500 EUR sub-limit on the
services part; for the micro regime, the global 203 100 EUR *and* a 83 600 EUR
sub-limit on services. Four numbers, not two, and a single "plafond" field in
the UI is wrong under every reading.

## 3. The three channels

### 3.1 Ceramics are vente de marchandises, not a service

An artisan who supplies both the labour and the raw materials that principally
compose the finished object is selling goods. BOI-BIC-PDSTK-10-10-10 states it
directly, and the practical consequence is 12,3 % rather than 21,2 %, and a 71 %
abattement rather than 50 %. A commissioned piece where the customer supplies
the materials, and any teaching or workshop revenue, fall on the other side and
must be tracked separately. This is a per-product-line classification, not a
per-channel one - which is why section 4.2 puts the category on the tax the
product carries.

### 3.2 Dépôt-vente: the contract decides the base, and the difference is large

Two structures wear the same name, and they produce different declared turnover
for the same physical sale.

**Achat-revente sur vente** - the gallery buys the piece from us at the moment it
sells it, at list price less its percentage. The gallery is our customer. Our
turnover is the net amount we invoice the gallery, recognised when the gallery
pays us. This is what `mb_depot` implements: the commission is a pricelist
discount on an invoice addressed to the gallery, invoiced on delivered
quantities.

**Mandat / dépôt-vente stricto sensu** - the gallery sells in our name and for
our account, and remits the price less its commission. The end customer is our
customer. Our turnover is then the **full retail price** paid by the end
customer, and the commission is a charge we cannot deduct. This is the same
mechanism as a marketplace fee, and the administration treats it identically.

On a 1 000 EUR piece with a 40 % commission, the first structure declares 600 EUR
and pays 73,80 EUR of cotisations; the second declares 1 000 EUR and pays
123 EUR. Nothing in the stock movements distinguishes them. Only the signed
contract does.

A mandat is not a different report over the same books. It is different books:
revenue at retail against an end customer we must invoice ourselves, the
gallery's commission as a purchase we book and pay, and the gallery's remittance
reconciled against both. Producing a declaration at retail while the ledger
records 600 EUR of revenue creates two contradictory truths with nothing between
them, and no amount of care in the declaration module fixes that.

So the design takes a position rather than building both:

- The **contract policy is achat-revente**. It is what `mb_depot` implements
  end to end, it is the cheaper of the two for the same shelf price, and it
  removes the obligation to invoice end customers we never meet. New depot
  agreements are negotiated on that basis.
- The structure is nonetheless **recorded per depot**, because it is a fact about
  a signed contract and not a preference (section 4.6).
- A depot recorded as `mandate` is **not half-served by the resale workflow**:
  sales and statements through that workflow block. The manual route is spelled
  out - invoice the end customers at retail from the gallery's sales report and
  enter the commission as a vendor bill. The declaration remains blocked until
  an Accounting Administrator records that this remediation has been reviewed
  through the declaration end date; the ordinary recognition machinery then
  produces the right base with no retail-price special case.

`mb_depot`'s `mb_depot_sale_date` on the move line and the retail figure already
computed by the statement wizard (`_values`, `amount_gross`) are what a mandat
implementation would build on if the policy ever changes. Recording that is the
whole of the mandate work for now.

One question is deliberately left open because it does not arise under the
policy above: under a mandat, whether the encaissement date is the day the end
customer pays the gallery - the gallery holding the funds for our account, as
for a marketplace - or the day the gallery remits to us. It must be settled
against URSSAF doctrine before any mandate implementation, not during it.

### 3.3 Direct B2C

Turnover is the total the customer pays, shipping included, on the date the
payment lands. Card payments are declared on receipt, not on payout net of
acquirer fees - the SumUp fee is a non-deductible charge exactly like a
marketplace commission. Invoicing to a private customer is not mandatory below
the usual thresholds, but a receipt must exist and the *livre des recettes*
entry must be justifiable.

### 3.4 Market sales

Cash and card at a stall. Declared on the day taken. The accounting obligation is
the *livre des recettes*: chronological, paginated, amount and origin of each
receipt, cash separated from other means of payment. The concession that matters
for a market: retail sales to private customers whose unit amount does not exceed
76 EUR may be grouped on a single daily line, provided the detail is retained in
supporting documents - a POS session summary and its ticket detail satisfy this
exactly.

The concession is *daily*, not per session, and Odoo dates a POS session's
accounting entry at the day the session is closed in the system
(`pos_session.py:869`, `fields.Date.context_today`). One session per market day,
closed the same day, makes the two coincide. That is a procedure, and section
4.7 checks it rather than working around it.

## 4. Implementation

### 4.1 The principle: recognition is already solved in Odoo

The first draft of this design proposed a `receipt` model populated by walking
reconciliations, splitting each payment across invoice lines pro rata, and
handling refunds and instalments by hand. All of that exists in `account`, is
called *cash basis tax exigibility*, and is what every cash-basis VAT country
runs on.

A tax whose `tax_exigibility` is `on_payment` is not reported when the invoice is
posted. Instead, each time a receivable line of that invoice is reconciled, Odoo
posts an entry in the cash basis journal dated at the reconciliation
(`account_partial_reconcile.py:548`, `partial.max_date`), carrying the share of
each base line that this payment covers
(`_prepare_cash_basis_base_line_vals`). Partial payments split pro rata, credit
notes reverse, and `account.move.line._get_tax_exigible_domain()`
(`account_move_line.py:3448`) is the ready-made filter that selects the
recognised lines and excludes the original invoice lines.

This supplies the recognition events without a parallel receipt ledger. The
declaration module still has to correct the final category-cent rounding
described in 4.4, claim sources into filings, apply dated rules and render the
filing aid.

### 4.2 Classification is the tax on the line, not a product field

There is no `l10n_fr_micro_urssaf_category` on the product. The category of a
sale is the franchise tax the line carries, and that tax is already chosen per
line by `l10n_fr_micro_enterprise` from the product's type
(`account_move_line.py:23`: service products get the service tax, everything
else the goods tax), already overridable per product, visible on the invoice,
and carried through Factur-X.

`l10n_fr_micro_enterprise` owns the field because its own tax-setup code must be
able to use it before the declaration addon is installed:

    account.tax.l10n_fr_micro_urssaf_category
        selection: bic_goods | bic_service | bnc

The existing goods and service franchise taxes are marked respectively, and a
third BNC franchise tax is prepared when
`res.company.l10n_fr_micro_bnc_enabled` is selected in the company setup; its
record is stored in `l10n_fr_micro_bnc_tax_id` beside the existing goods and
BIC-service tax fields.
The search key for a franchise sale tax is this category, not `tax_scope`, since
both BIC and BNC services have `tax_scope = 'service'`. Keeping the field in an
addon that depends on `l10n_fr_micro_enterprise` would create an impossible
dependency cycle.

This buys more than a saved field:

- a commissioned piece from the customer's own clay is reclassified by putting
  the service franchise tax on that product - a native, one-click operation an
  accountant already understands;
- posted sale lines without a category are detectable in one place. Odoo does
  allow tax-less lines to post, so the declaration lists them as blocking
  anomalies rather than silently omitting their turnover;
- down payments classify themselves. `account.tax._prepare_down_payment_lines`
  (`account_tax.py:4006`) groups a down payment by tax, so an advance invoice
  carries one line per tax and lands in the right box, and the deduction line on
  the final invoice nets the same way. Under a product-level category field this
  was a nine-point rate error waiting on the "Down payment" service product.

The trade is that the category can only be as granular as the tax. That is
exactly the granularity the URSSAF form has.

### 4.3 Recognition is cash-basis exigibility, switched on once

Setup, performed by `l10n_fr_micro_enterprise`'s existing tax-preparation code
(section 4.9):

- `res.company.tax_exigibility = True` (`company.py:220`)
- `res.company.tax_cash_basis_journal_id` - a dedicated recognition journal;
  it is not itself a complete *livre des recettes*, because every invoice
  receipt lands in this one journal regardless of payment method
- `res.company.account_cash_basis_base_account_id` - a transitional account the
  base and its mirror both hit, netting to zero
- `tax_exigibility = 'on_payment'` on the three franchise sale taxes

Then, per channel, with no bridge module for any of them:

- **Invoices** - any reconciliation of the receivable posts the cash basis entry
  at the payment date. This covers `account.payment`, a bank statement line
  reconciled straight to the invoice, a write-off, and a manual entry alike,
  because the trigger is `account.partial.reconcile` and not the payment object.
  The first draft's rule missed the three latter cases.
- **POS** - nothing to do. Odoo forces `always_tax_exigible` on a session's
  closing move (`point_of_sale/models/account_move.py:25-33`: "the pos closing
  move does not create caba entries (anymore); we set the tax values directly on
  the closing move"), so session revenue is recognised on the closing move's own
  date and never twice. An invoiced POS order carries its revenue on the invoice
  instead, which is reconciled at closing and recognised through the ordinary
  path.
- **Depot, achat-revente** - an ordinary customer invoice to the gallery. The
  net after commission is what is invoiced, so the net is what is recognised,
  when the gallery pays.

### 4.4 Recognition query and exact cumulative amounts

    lines = env['account.move.line'].search(
        env['account.move.line']._get_tax_exigible_domain()
        & Domain([
            ('parent_state', '=', 'posted'),
            ('company_id', '=', company.id),
            ('date', '>=', period.date_from),
            ('date', '<=', period.date_to),
            ('tax_ids.l10n_fr_micro_urssaf_category', '=', category),
        ])
    )
    ledger_turnover = -sum(lines.mapped('balance'))

Sign is not a convention to be discovered: a sale credits, so `-balance` is
positive turnover and a credit note subtracts. The mirror line of a cash basis
entry is not double-counted because
`_prepare_cash_basis_counterpart_base_line_vals` copies neither `tax_ids` nor
`tax_tag_ids` (`account_partial_reconcile.py:385`), so it cannot match the
domain. Under VAT this reads the untaxed base, since only base lines carry
`tax_ids` in this shape.

Odoo rounds every partial cash-basis base line independently. On a mixed invoice
paid in several instalments, those rounded category shares can finish one or two
cents away from the original category totals. The recognition helper therefore
groups cash-basis lines by origin move and category. Intermediate receipts keep
Odoo's rounded amount; when a receipt fully settles the origin move, that event
receives the residual between the original category base and all earlier
recognitions. The cumulative recognised amount of a fully paid invoice then
equals its original untaxed category total exactly in company currency.

No tax tags and no `account.report` record: the report engine ships in Community
19 (`account/models/account_report.py`) but its viewer does not, so a report
definition would render nowhere.

### 4.5 Addon boundaries and persistent model

`l10n_fr_micro_urssaf` depends directly on
`l10n_fr_micro_enterprise`, `account`, `mail`, `mb_depot` and
`point_of_sale`. These are real dependencies, not bridge addons: the declared
scope requires depot blocking, POS anomaly checks and accounting activities,
and a module must not assume models from undeclared optional dependencies are in
the registry.

`l10n_fr_micro_enterprise` contains the category field, the three franchise sale
taxes and the cash-basis preparation described in section 4.9. The new addon
contains:

    res.company                                      taxpayer configuration
        l10n_fr_micro_activity_start_date
        l10n_fr_micro_urssaf_tracking_start_date
        l10n_fr_micro_urssaf_periodicity
        l10n_fr_micro_versement_from / _to
        l10n_fr_micro_acre_granted / _from / _to / _coefficient
        l10n_fr_micro_cfp_kind
        l10n_fr_micro_chamber_kind / _zone
        l10n_fr_micro_accounting_responsible_id

    account.move.line                                VAT threshold evidence
        l10n_fr_micro_vat_operation_date

    account.journal                                  receipt-book classification
        l10n_fr_micro_receipt_method
            transfer | card | cash | cheque | other

    l10n.fr.micro.urssaf.rate                        dated levy rate
        date_from / date_to, levy, category
        taxpayer_kind / chamber_kind / chamber_zone when relevant
        rate

    l10n.fr.micro.urssaf.acre.rule                   dated creation rule
        creation_date_from / creation_date_to, payable_coefficient

    l10n.fr.micro.urssaf.threshold                   dated thresholds
        vat_global_base / major, vat_service_base / major
        micro_global / micro_service

    l10n.fr.micro.urssaf.annual                      annual reference evidence
        company_id, year
        urssaf_goods / services / total
        vat_global / vat_services
        computed | manual, manual_reason

    l10n.fr.micro.urssaf.declaration                 one filing
        company_id, date_from / date_to, periodicity, state draft | filed
        line_ids, anomaly text, filed_at, filed_by

    l10n.fr.micro.urssaf.declaration.line            one filing box
        category, source_ids
        current_turnover, prior_period_adjustment, manual_adjustment
        manual_adjustment_reason
        computed_turnover, declared_turnover
        snapshot rate summary and amounts for every levy

    l10n.fr.micro.urssaf.declaration.source          one recognised event
        declaration_line_id, event_key, recognition_date, category, amount
        engine: caba | reconciliation | pos
        source_move_line_id / partial_id / origin_move_id / pos_order_id
        receipt method and applicable snapshotted rate ids/values

There is no independent cached receipt ledger. A draft discards and recomputes
its child source rows from accounting, reconciliation and POS records. Filing
snapshots the recognised events and their provenance. `event_key` includes the
engine, source, origin move and category; this matters when one partial
reconciliation recognises more than one invoice or category. A draft includes:

- unreported sources dated inside its own period as `current_turnover`;
- unreported sources between the company's tracking start and `date_from - 1`
  as `prior_period_adjustment`.

Event keys already linked to a filed declaration are excluded. This makes a late
reconciliation for a closed period visible in the next filing without changing
its legal accounting date or double-reporting it. The tracking start is an
explicit period boundary because receipts before module installation were filed
manually and have no cash-basis entries to claim.

Negative computed turnover proposes zero and blocks filing until the operator
records the treatment agreed with URSSAF as a reasoned manual adjustment. The
software does not invent a statutory carry-forward.

Filing is immutable in server code, not merely in the view: `write()` and
`unlink()` reject changes to filed declarations and their lines, including RPC,
imports and server actions. A manager-only `action_reset_to_draft` logs a
chatter reason and is the sole controlled correction path.

Company record rules isolate every declaration, source and configuration row.
Accounting users may read and recompute drafts; Accounting Administrators alone
may change taxpayer/rate configuration, enter manual adjustments, file, reset or
delete a draft. Constraints reject overlapping declarations for one company,
overlapping rule validity for one applicability key, and duplicate `event_key`
claims. Consequently two overlapping drafts cannot quietly claim the same
receipt.

Declaration creation derives standard month/quarter boundaries from the
company's periodicity. The first period begins on the registered activity start
date and ends after the deferred coverage described in section 1; later periods
are one calendar month or quarter. It validates continuity with the preceding
filed period and computes the statutory due date. A manager can create a late
past period, but cannot create arbitrary overlapping or gapped periods without
recording an explicit migration/setup boundary.

Rates and thresholds are data with non-overlapping validity constraints per
complete applicability key, never literals. A levy-rate row can therefore hold
the alternative artisan/commerçant CFP and geographic chamber rates without
ambiguous overlapping category records. Each recognised source selects rates by
its recognition date and copies the numeric values when filed; the declaration
line aggregates those source amounts and exposes a rate summary. This also
handles a period spanning a statutory rate change without pretending it has one
rate. Later correction of configuration cannot rewrite a historical filing.
Versement libératoire, ACRE and chamber amounts are applied only when the dated
company configuration and annual evidence say they apply. The annual record is
computed from filed sources; a manager may enter a reasoned opening balance for
years predating installation. It drives the previous-year chamber exemption,
the VAT prior-year test and the two-consecutive-year micro-regime warning. CFP,
chamber tax and contribution amounts are labelled estimates:
the transcription boxes are turnover boxes, and the URSSAF portal remains the
authority for the amount it calculates.

The QWeb filing aid renders, in order:

1. the turnover boxes to transcribe, with current, prior-period and manual
   adjustment disclosure;
2. estimated cotisations and optional levies with their snapshotted rules;
3. anomalies and the year-to-date micro and VAT threshold positions;
4. the *livre des recettes* supporting detail.

The *livre des recettes* cannot classify a receipt from the recognition line's
journal: all invoice CABA lines use the one cash-basis journal. For invoice
events the report follows `move_id.tax_cash_basis_rec_id` to the partial
reconciliation and its counterpart move, then uses payment metadata and the
counterpart journal's explicit receipt-method classification. Direct bank-statement
reconciliations use the statement line's journal. Write-offs and manual entries
are shown with their actual journal and a visible anomaly when no receipt method
can be proven. POS events use `pos.payment.payment_method_id` and are grouped by
local calendar day and method while retaining the session and ticket detail.
The resulting report is chronological and shows date, customer/origin,
description, category, gross amount and receipt method; it is not merely a
printout of the CABA journal.

### 4.6 The depot structure flag lives in `mb_depot`

    stock.warehouse.mb_depot_legal_structure
        selection: resale | mandate       required when is_depot
    stock.warehouse.mb_depot_mandate_reviewed_through
    stock.warehouse.mb_depot_mandate_review_note

Field, wizard question and workflow guards all live in `mb_depot`, because they describe a
signed contract and are meaningful with or without the declaration module. No
default: the wizard asks, since neither answer is safe to assume. `mandate` must
remain storable: otherwise the legal fact cannot be recorded and the declaration
could never find it. Creating a sale/statement through the resale workflow for a
mandate raises with the explanation from section 3.2. A declaration blocks when
the company holds a mandate whose manager review date is earlier than the
declaration end. The mandatory note/date can be advanced only by an Accounting
Administrator after the retail invoices and commission bills have been checked.
The block is not line-level, because a mandate that has already sold is first a
booking problem and only then a reporting input.

Existing depots need a migration in `mb_depot/migrations/` setting `resale`,
which is what they all are today; `19.0.2.0.0/pre-migrate.py` is the pattern.

### 4.7 POS needs a check, not a bridge

The declaration lists as an anomaly any POS session in the period whose
`start_at`, converted from UTC to the company/user timezone, and the date of its
closing move fall on different local days, and says
plainly that its takings are dated at the close. It does not re-date anything:
the accounting entry is the legal record and moving turnover away from the entry
that carries it would be worse than the discrepancy. The fix is to close the
session at the end of the market day, and the check is what makes that visible.

### 4.8 Two threshold engines close the loop

The micro-regime ceiling uses the year-to-date URSSAF receipt events of 4.4.
The VAT-franchise ceiling uses a separate chronological stream of hypothetical
VAT-exigibility events:

- goods from the completed delivery event linked through sale/stock, and POS
  goods from the POS order event;
- services from cash-basis recognition;
- manually invoiced goods from an explicit operation/delivery date, with a
  blocking anomaly when that date cannot be established.

The VAT stream maintains the global and service subtotals independently. On the
first event crossing 93 500 or 41 250, it raises one idempotent `mail.activity`
for the accounting manager proposing the **actual event date** as the switch
date. It never changes the regime automatically: the manager must verify the
source events, contact the SIE where necessary, and invoke the dated switch.
The 85 000 / 37 500 prior-year conditions are reported separately from the
in-year major thresholds. The micro ceilings are reported alongside but trigger
no automatic exit, since that requires two consecutive years and a decision.

### 4.9 What `l10n_fr_micro_enterprise` has to change

Three small, contained changes; none of them is a new dependency, and all three
are useful to that module on their own terms.

- `_l10n_fr_micro_prepare_tax_setup` also prepares the cash basis journal, the
  transitional base account and `company.tax_exigibility`, and sets
  `tax_exigibility = 'on_payment'` on the franchise sale taxes.
- The category field moves into this addon and the BNC franchise tax joins the
  goods and BIC-service ones. `_l10n_fr_micro_prepare_one_tax` keys its search
  on the category field because `tax_scope` has no third value.
- `action_l10n_fr_micro_activate_vat` gains an effective date.
  `_l10n_fr_micro_switch` already accepts one (`res_company.py:206`) but the
  action calls it bare (`res_company.py:243`), as does the settings wrapper
  (`res_config_settings.py:34`), so 4.8 cannot pass the legal date through
  today. Back-dating to the actual overrun date is accepted; note that
  `res_company.py:213` refuses a *future* date, so a crossing seen in advance
  cannot be pre-scheduled and must be applied in the month it takes effect.

The manager-group gate on the switch (`res_company.py:66`) is why 4.8 raises the
activity for the accounting manager rather than switching by itself.

### 4.10 Installation boundary and late regularisation

Invoices already paid before the taxes became `on_payment` have no cash basis
entry and will never get one, so the query in 4.4 returns nothing for them. The
first declaration produced by the module is therefore only correct if the module
is installed before any receipt of the period it covers. Install at a period
boundary and store it as `l10n_fr_micro_urssaf_tracking_start_date`; periods
before it were filed by hand and stay outside the source-claim query. A
migration that fabricates cash basis entries for historical reconciliations is
possible and is not worth it for a first year. Receipts entered late after that
boundary are handled by the unreported-source logic of section 4.5.

### 4.11 Recognition after the VAT switch

A threshold monitor that makes its own declaration module stop working is not a
closed loop. The recognition service therefore has two strategies behind the
same event interface:

- while the company is in franchise mode, it uses the cash-basis base lines of
  4.4;
- after the VAT switch, it walks `account.partial.reconcile` on customer
  receivable lines, allocates each receipt pro rata over the invoice's untaxed
  base by URSSAF category, and assigns the exact residual to the final receipt.

Economic VAT sale taxes must carry the same category marker as their franchise
counterpart. The setup maps the ordinary goods taxes to `bic_goods`; BIC and BNC
services use distinct tax records even where their VAT percentage is identical,
because one tax cannot represent two URSSAF boxes. Real VAT tax exigibility is
left entirely at its legally correct value. POS takings remain direct receipt
events and are not walked through invoice reconciliation unless the POS order
was invoiced, in which case the invoice strategy counts them once.

Multi-currency receipts are recognised in company currency at the reconciliation
rate. The source foreign amount, currency and rate are printed for audit, but the
declaration has only the company-currency amount.

### 4.12 What to test

- A November invoice paid in January lands in January, in both periodicities.
- A partial payment splits across categories, and the sum of all cash basis
  recognitions over a fully paid invoice equals each original category total
  exactly after the final-receipt residual correction.
- An invoice settled by a bank statement line reconciled directly, with no
  `account.payment`, is recognised on the statement line's date.
- A credit note refunded in a later period subtracts in that later period.
- A period whose refunds exceed its receipts proposes 0, blocks filing without
  review, and accepts only a reasoned manager adjustment rather than inventing a
  carry-forward.
- A down payment invoice on a mixed order splits across the two categories and
  the final invoice's deduction line nets it back.
- A resale depot invoice declares the net, and only when the gallery pays.
- A depot marked `mandate` remains storable and its resale workflows are
  refused; a declaration blocks until a manager's reasoned mandate-accounting
  review covers its end date.
- A POS session opened on the last day of a period and closed the next day is
  reported as an anomaly using the local timezone, and its takings are declared
  in the period of the close.
- A POS order invoiced to a customer is counted once, not twice.
- A posted sale line with no category is a blocking anomaly.
- A receipt posted late into an already filed period is claimed exactly once as
  a prior-period adjustment by the next draft declaration.
- Filed declarations and lines reject write/unlink through ORM and RPC; a
  manager reset records its mandatory reason in chatter.
- Invoice receipt methods are recovered through partial-reconciliation
  counterparts, and cash/card POS methods remain separate in the daily receipt
  book.
- A goods delivery can cross the VAT threshold before its payment crosses the
  URSSAF total; the engines report their different dates.
- Crossing 93 500 EUR globally or 41 250 EUR of services proposes the actual
  event date, creates only one activity, and the dated switch accepts it.
- ACRE creation before 1 July 2026 uses a 0.50 payable coefficient; creation on
  or after that date uses 0.75, and both expire at the configured quarter end.
- Versement libératoire, CFP and chamber estimates appear only under applicable
  dated taxpayer configuration, including chamber kind/zone/exemption.
- After switching to VAT, a partially paid mixed invoice is recognised HT from
  reconciliations by category and its final receipt clears rounding residuals.
- A period with no receipts still produces a filable declaration at 0.

## 5. Traps worth naming

- Declaring net of SumUp, Etsy or gallery commission understates turnover. The
  platforms report their gross figures to the administration directly.
- Using the invoice date instead of the payment date is the single most common
  error and is invisible until a year-end reconciliation against bank receipts.
  Cash basis exigibility is precisely what removes the opportunity to make it.
- Treating a commissioned piece where the customer supplies the clay as a sale of
  goods misclassifies it as BIC vente; it is a service, and the fix is the tax on
  that product.
- The VAT franchise threshold and the micro regime ceiling are different numbers
  with different consequences, source events and service sub-limits under mixed
  activity. A goods receipt date is valid for URSSAF but its delivery date is
  the VAT-threshold event. Four limits, not one query.
- ACRE is not a permanent 50 % rate: its payable coefficient depends on the
  creation date and, from 1 July 2026, is 75 % of the normal rate.
- Leaving a POS session open across midnight moves a market day's takings into
  the next accounting day, and across a quarter boundary into the next
  declaration.
- E-invoicing reform: reception of electronic invoices becomes mandatory for all
  companies on 1 September 2026, including franchise micro-entreprises, and
  emission follows for the smallest firms on 1 September 2027 - the one that
  actually bites here. Unrelated to the URSSAF declaration, but it shares the
  Factur-X plumbing in `l10n_fr_micro_enterprise` and both dates are inside this
  project's horizon.

---

Sources: URSSAF *Déterminer mon chiffre d'affaires* and *Déclarer et payer mes
cotisations*; Entreprendre Service Public F36232 (2026 rates), F36249 (gross
turnover), F23257/F23266 (filing and receipt book), F23267 (micro thresholds),
F11677 (ACRE), F23459 (CFP) and F37483 (chamber taxes);
BOI-TVA-DECLA-40-10-10 and BOI-TVA-DECLA-40-10-20 (VAT threshold basis and
effective date); BOI-BIC-PDSTK-10-10-10 and BOI-BIC-DECLA-10-10-10; decree
2026-69 of 6 February 2026; and the law of 3 November 2025 abandoning the single
VAT threshold. Figures and portal wording must be re-verified against urssaf.fr
before each fiscal year.
