# mb_depot — dépôt-vente

Consignment stock held at galleries and shops, and the statement that settles it.

Odoo has no outbound consignment. Its built-in Consignment setting is the other
direction — vendor-owned stock sitting in *your* warehouse — and a search of
every OCA manifest turns up nothing either. The location-based model below is
therefore not a workaround; it is what everyone builds.

## The model

A depot is an **internal location** we own and a gallery physically holds.

Internal matters: unsold pieces stay on our balance sheet and no revenue is
recognised until the gallery reports a sale, which is the legal situation of
dépôt-vente. Delivering to the customer location instead would derecognise the
stock with no counterpart revenue.

Depots sit in **their own root tree**, not under a warehouse. Internal keeps them
on the books; being outside `WH` keeps an ordinary delivery from reserving a
piece that is standing on a shelf in Nantes, since deliveries source from
`WH/Stock` and its children. Odoo 19 has no "Physical Locations" root any more —
`WH` is itself a parentless view location — so the depots get their own.

```
Dépôts                 (view, no parent)
└── Galerie Truc       (internal, is_depot)
```

The **commission is a pricelist, not code**. Under achat-revente sur vente the
gallery buys at list minus its percentage at the moment it sells.

Selling from a depot uses **one route per depot** rather than one warehouse per
depot: same sourcing, none of the picking-type and sequence sprawl.

## What is here

| | |
|---|---|
| `stock.location` | `is_depot`, depositary, commission, route, pricelist, pieces held |
| `mb.depot.create` | Creates a depot — location, route, pull rule, commission pricelist — in one action, because that set repeats per gallery and has to agree with itself |
| `mb.depot.statement` | Opening, placed, sold, returned, closing over a period, per piece, with retail / commission / net |
| `stock.quant` views | Live stock per depot with a days-held column and ageing filters |
| Bon de dépôt | Placement document for the gallery to sign |

Menus land under Inventory > Dépôt-vente.

## The statement

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

Period bounds are `[date_from 00:00, date_to+1 00:00)` in UTC, which is how
`stock.move.line.date` is stored.

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

Selecting the depot route on a quotation needs OCA's
`sale_order_global_stock_route`. That is deliberately not in `depends`: it is
AGPL-3 and this module is LGPL-3. Without it the route is still created and can
be set on the order line by hand.

`stock_picking_report_valued` cannot serve as the bon de dépôt: every monetary
field on it is related to or computed from `move_id.sale_line_id`, and a
placement is an internal transfer with no sale line, so it renders blank. Hence
the report here.

## Tests

```
odoo -d <db> -u mb_depot --test-enable --test-tags /mb_depot --stop-after-init
```

Nine tests, all on the statement arithmetic and the consistency of a created
depot — the parts that decide money.
