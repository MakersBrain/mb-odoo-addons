# mb_depot — dépôt-vente

Consignment stock held at galleries and shops, and the statement that settles it.

Odoo has no outbound consignment. Its built-in Consignment setting is the other
direction — vendor-owned stock sitting in *your* warehouse — and a search of
every OCA manifest turns up nothing either — `stock_customer_deposit` and
`vendor_consignment_stock` both point the other way. The model below is therefore
not a workaround; it is what everyone builds.

## The model

A depot is a **warehouse** we own and a gallery physically holds.

```
Galerie Truc           (stock.warehouse, is_depot)
└── TRUC/Stock         (internal)
```

Its stock location is internal, which matters: unsold pieces stay on our balance
sheet and no revenue is recognised until the gallery reports a sale, which is the
legal situation of dépôt-vente. Delivering to the customer location instead would
derecognise the stock with no counterpart revenue.

A warehouse rather than a bare location, and this was learned the expensive way.
A depot used to be an internal location parked outside every warehouse, which
bought exactly one thing — an ordinary delivery cannot reserve a piece standing
in a gallery — and charged for it everywhere else, because Odoo answers "what is
on hand and can I sell it" per warehouse nearly universally. That meant patching
`_read_qties()` so the availability widget stopped claiming the piece could not
be delivered, patching the product picker's context so On Hand stopped reading
0.00, and building a route and pull rule per gallery to do what a warehouse does
for free. A warehouse gives the reservation isolation *and* all of that back:
deliveries source from their own warehouse's stock, so the atelier never touches
the gallery's shelf.

The cost is five picking types and sequences per gallery. That is the whole bill,
and it is smaller than the one it replaced.

The **commission is a pricelist, not code**. Under achat-revente sur vente the
gallery buys at list minus its percentage at the moment it sells.

Storable sale products use **invoicing on delivered quantities**, set by the wizard.
The piece is sold when the depositary says it is, and the transfer out of the
depot is the record of that; on ordered quantities a gallery could be billed at
confirmation — before the movement that triggers the invoice, and before anything
was sold at all if the report turns out to be wrong. Note the reach:
`invoice_policy` is a product field with no per-warehouse variant, so this is the
policy for the existing catalogue and every new product, not only consigned ones.
Confirmation checks it again and restores the depositary's depot warehouse before
creating the delivery. It also removes explicit line routes left by the old
location-based implementation, so an imported product, a manually changed
warehouse, or legacy sourcing metadata cannot silently bypass the stock movement
that gates invoicing.

A depot **receives and delivers in one step**, pinned by a constraint. Multi-step
would put a receiving bay and a packing table inside someone else's shop, and
split one reported sale into two moves whose first leg leaves the depot's stock
location for a sibling.

## What is here

| | |
|---|---|
| `stock.warehouse` | `is_depot`, depositary, commission, pricelist, pieces held |
| `stock.move.line` | `mb_depot_sale_date` — the day the depositary reports the piece sold |
| `mb.depot.create` | Creates a depot — warehouse and commission pricelist — in one action, because that pair repeats per gallery and has to agree with itself |
| `mb.depot.statement` | Opening, placed, sold, returned, closing over a period, per piece, with retail / commission / net |
| `stock.quant` views | Live stock per depot with ageing, retail value, and expected net after commission; accounting cost remains separate |
| `stock.picking` | The product catalog, on placements only |
| `sale.order` | The depositary's warehouse, and the pieces it holds |
| Bon de dépôt | Placement document for the gallery to sign |

## The catalog on a placement

Odoo puts no catalog on a transfer. `product.catalog.mixin` is opt-in per model
and `stock.picking` does not take it — the reasoning being that a picking is
generated from a source document rather than typed, so there is nothing to pick
from a grid. A placement is the case that breaks that reasoning: it starts from
nothing and names a lot of individual pieces.

`mrp.production` is the shape followed here rather than `sale.order`. Its
components are the same thing a placement is — a price-less list of
`stock.move` records — and the method they both lean on,
`stock.move._get_product_catalog_lines_data`, already lives in `stock`.

The catalog quotes **prix public**, not cost: the bon de dépôt and the statement
both value a placement at list price, so `standard_price` on the cards would
contradict the paper the gallery signs. The on-hand badge counts the transfer's
**source location** rather than the company, because what matters when loading a
van is what is at the atelier, not what exists somewhere.

The button is on the moves list and appears only when the destination is a
depot. Being on a one2many's `<control>` it is called on `stock.move`, not on
the picking, so it takes the same detour through `order_id` in the context that
mrp takes for its components.

## Selling from a depot

Odoo's own **Warehouse** field on the quotation is the whole mechanism. It fills
in from the customer when that customer is a depositary, matched on the
commercial partner so an order addressed to a person inside the gallery still
finds it, and it is what sources the delivery from the gallery. No route, no pull
rule, and no `sale_order_global_stock_route`.

On hand, forecast and the availability widget need no help either: they are
warehouse-scoped and the warehouse is the depot.

The pieces offered are on hand **minus reserved**. A unique piece offered on two
orders is a piece that cannot be delivered twice; once a confirmed order has
reserved it, it drops off the picker on its own.

The domain is added to the standard clauses rather than replacing them, so
`sale_ok` and the company check still apply and an ordinary customer sees
exactly what they saw before.

The standalone **Depot Sales** application is the operational workspace. It
links to the same standard Sales Orders, Inventory transfers, deliveries, and
invoices that remain available in their native applications; it does not copy
or replace those documents.

## The statement

The period's movements are the move lines crossing the depot warehouse's **view
location**, not its stock location: anything Odoo ever puts inside a warehouse
hangs off the view, so scoping there means a movement counts only when it
genuinely crosses the gallery's door.

Sold and returned are **both outgoing moves**. What tells them apart is the
destination: `usage == 'customer'` is a sale, anything else is a return.
Anchoring the split there is what makes closing reconcile against the quants
rather than drift from them — `test_closing_reconciles_with_the_quants` pins it.

Moves with both ends inside the depot are excluded: shuffling a piece between
two shelves of the same gallery is not a movement of the statement.

Values come from the sale order line when there is one, since it carries both
the list price and the commission as a discount. A piece that left without a
sale order falls back to the product's list price and the depot's recorded
commission, so it cannot silently value at zero.

## The reported date

A gallery reports last month's sales this month. `stock.move.line.date` is when
the transfer was validated here, so binning on it puts March's sales in April,
leaves March closing too high, and makes April's opening disagree with the paper
the gallery signed.

`mb_depot_sale_date` on the move line is the day the movement actually happened
for the depositary, and the statement bins on `sale_date or date` — for
placements and returns as well as sales, since a placement keyed in a week late
lands in the wrong period the same way.

It is a plain writable `Date` on `stock.move.line` with no side effects on stock
state, so an external sync (a shop's sales sheet, for one) can set it by RPC on
the lines it matches. `stock.picking.mb_depot_sale_date` sets it on every line of
a transfer at once and reads back only when the lines agree, which is the
ordinary case of one transfer standing for one reported sale.

Note that backdating this does **not** backdate the stock valuation layer or its
accounting entry; those stamp at validation.

The statement carries `date_sold` per row, filled when every sale on the row
shares one day. One serialised piece is one row is one sale, so it is normally
filled; an untracked product sold on three days leaves it blank rather than
picking one. Splitting the row per day instead would make its closing balance
meaningless.

Period bounds are whole days, compared against the reported date when there is
one and otherwise against the UTC day of `stock.move.line.date` — the same
window as before for anything not reported.

## Two traps worth knowing

**The commission only appears on the invoice under two conditions.**
`sale/models/product_pricelist_item.py:_show_discount()` returns True exactly
when the Discounts feature is enabled **and** the pricelist item is
`compute_price='percentage'`. Under `'formula'` the percentage is folded into
the unit price, and the invoice shows a quietly cheaper piece instead of the
commission. The wizard sets both.

**Never configure this through `res.config.settings` from a script.** A settings
record carries every setting, so writing one also writes back whatever its own
defaults resolved to — and `product/models/res_config_settings.py` archives
*every pricelist in the database* when `group_product_pricelist` comes out
falsy. This module writes implied groups on `base.group_user` instead.

## Not a dependency

`stock_picking_report_valued` cannot serve as the bon de dépôt: every monetary
field on it is related to or computed from `move_id.sale_line_id`, and a
placement is an internal transfer with no sale line, so it renders blank. Hence
the report here.

## Tests

```
odoo -d <db> -u mb_depot --test-enable --test-tags /mb_depot --stop-after-init
```

The suite covers statement arithmetic, the reported date that decides which
period a movement falls in, navigation and permissions, and the consistency of
a created depot — the parts that decide money and who can act on it.
