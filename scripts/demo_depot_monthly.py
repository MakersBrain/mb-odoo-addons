"""Daily reporting, monthly invoicing, commission visible on the invoice.

Run after scripts/setup_depot_fixture.py:

    docker compose exec -T odoo odoo shell -d odoo --no-http --log-level=warn \
        < ../makersbrain-odoo/scripts/demo_depot_monthly.py

The shape it demonstrates:

  * One sale order per day the gallery reports, dated that day, confirmed and
    delivered the same day. Correcting a day means touching one document.
  * invoice_policy='delivery' on the product, so a line reaches the invoice only
    once the piece has actually left the depot.
  * At month end, invoicing all of the month's orders in one action produces ONE
    invoice: sale.order._get_invoice_grouping_keys() groups by company, partner,
    shipping address, currency and fiscal position, so same-gallery orders merge.
    sale_invoice_frequency supplies the "Monthly" label to filter on.
  * The commission shows as a per-line discount rather than a quietly lower unit
    price, because sale/models/product_pricelist_item.py:_show_discount()
    returns True exactly when the Discounts feature is on AND the pricelist item
    is compute_price='percentage'. Under 'formula' it stays hidden.
"""

from datetime import datetime

GALLERY = "Galerie Démo"
DAYS = ((4, 1), (11, 2), (25, 1))   # (day of month, pieces sold)
STOCK_TARGET = 16                   # serials to have made at all

partner = env["res.partner"].search([("name", "=", GALLERY)], limit=1)
route = env["stock.route"].search([("name", "=", f"Dépôt-vente: {GALLERY}")], limit=1)
depot = env["stock.location"].search(
    [("complete_name", "=", f"Dépôts/{GALLERY}")], limit=1)
pt_out = env["stock.picking.type"].search([("name", "=", "Mise en dépôt")], limit=1)
wh = env["stock.warehouse"].search([], limit=1)

# --- the product ------------------------------------------------------------
prod = env["product.product"].search([("default_code", "=", "BOL-G14")], limit=1)
if not prod:
    prod = env["product.product"].create({
        "name": "Bol grès émaillé Ø14", "default_code": "BOL-G14",
        "type": "consu", "is_storable": True, "tracking": "serial",
        "list_price": 45.0, "standard_price": 12.0,
    })
# Invoice what was reported sold, not what was ordered.
prod.product_tmpl_id.invoice_policy = "delivery"
print(f"product: {prod.display_name}  list {prod.list_price}  "
      f"invoice_policy={prod.invoice_policy}")

# --- keep the depot stocked -------------------------------------------------
fresh = []
for i in range(1, STOCK_TARGET + 1):
    name = "BOL-G14-%03d" % i
    lot = env["stock.lot"].search(
        [("name", "=", name), ("product_id", "=", prod.id)], limit=1)
    if not lot:
        lot = env["stock.lot"].create({"name": name, "product_id": prod.id})
    if not env["stock.quant"].search([("lot_id", "=", lot.id)]):
        env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": prod.id, "location_id": wh.lot_stock_id.id,
            "lot_id": lot.id, "inventory_quantity": 1,
        }).action_apply_inventory()
        fresh.append(lot)

if fresh:
    pick = env["stock.picking"].create({
        "picking_type_id": pt_out.id, "partner_id": partner.id,
        "location_id": wh.lot_stock_id.id, "location_dest_id": depot.id,
        "move_ids": [(0, 0, {"product_id": prod.id, "product_uom_qty": len(fresh),
                             "location_id": wh.lot_stock_id.id,
                             "location_dest_id": depot.id})],
    })
    pick.action_confirm()
    pick.action_assign()
    pick.move_ids.picked = True
    pick.button_validate()
    print(f"mise en dépôt: {pick.name} {pick.state}  +{len(fresh)} pieces")

on_hand = sum(env["stock.quant"].search([("location_id", "=", depot.id)]).mapped("quantity"))
print(f"at depot: {on_hand:.0f} pieces")

# --- daily reports ----------------------------------------------------------
print("\ndaily reports")
for day, qty in DAYS:
    origin = "Relevé dépôt 2026-08-%02d" % day
    so = env["sale.order"].search([("origin", "=", origin)], limit=1)
    if not so:
        so = env["sale.order"].create({
            "partner_id": partner.id,
            "origin": origin,
            "date_order": datetime(2026, 8, day, 10, 0),
            "route_ids": [(6, 0, [route.id])],
            "order_line": [(0, 0, {"product_id": prod.id, "product_uom_qty": qty})],
        })
        so.action_confirm()
        for p in so.picking_ids.filtered(lambda p: p.state not in ("done", "cancel")):
            p.action_assign()
            p.move_ids.picked = True
            p.button_validate()
    line = so.order_line[0]
    print(f"  {origin}  {so.name}  qty={line.product_uom_qty:.0f}  "
          f"unit={line.price_unit:.2f}  remise={line.discount:.0f}%  "
          f"net={line.price_subtotal:.2f}  delivered={line.qty_delivered:.0f}  "
          f"[{so.invoice_status}]")

env.cr.commit()

# --- month end --------------------------------------------------------------
monthly = env.ref("sale_invoice_frequency.sale_invoice_frequency_monthly",
                  raise_if_not_found=False)
domain = [("partner_id", "=", partner.id), ("invoice_status", "=", "to invoice")]
if monthly:
    domain.append(("invoice_frequency_id", "=", monthly.id))
orders = env["sale.order"].search(domain)
print(f"\nmonth end — invoicing {orders.mapped('name')}")

if not orders:
    invoices = env["account.move"].search(
        [("partner_id", "=", partner.id), ("move_type", "=", "out_invoice")])
    print("nothing left to invoice; showing the existing invoice")
else:
    invoices = orders._create_invoices()
print(f"INVOICES CREATED: {len(invoices)}")
for inv in invoices:
    print(f"  {inv.partner_id.name}  origin: {inv.invoice_origin}")
    for l in inv.invoice_line_ids:
        print(f"    {l.product_id.default_code}  qty={l.quantity:.0f}  "
              f"unit={l.price_unit:.2f}  remise={l.discount:.0f}%  "
              f"net={l.price_subtotal:.2f}")
    print(f"  total HT: {inv.amount_untaxed:.2f}  "
          f"(commission retenue: {sum(l.quantity * l.price_unit for l in inv.invoice_line_ids) - inv.amount_untaxed:.2f})")

still = sum(env["stock.quant"].search([("location_id", "=", depot.id)]).mapped("quantity"))
print(f"\nstill at depot: {still:.0f} pieces")
env.cr.commit()
