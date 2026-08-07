"""Dépôt-vente fixture: a gallery, its depot location, a sourcing route and a
commission pricelist.

Run it against a database with `sale_order_global_stock_route` installed:

    docker compose exec -T odoo odoo shell -d odoo --no-http --log-level=warn \
        < ../makersbrain-odoo/scripts/setup_depot_fixture.py

Idempotent: re-running updates rather than duplicates, except for the sale order
at the end, which is only created if the gallery has none.

The model this encodes, for the achat-revente-sur-vente contract shape:

  * A depot is an *internal* location, so unsold pieces stay on our balance
    sheet and no revenue is recognised while they sit at the gallery. Delivering
    to the customer location instead would derecognise the stock with no
    counterpart revenue.
  * Depots live in their own root tree, NOT under WH. Internal keeps them on the
    books; being outside WH keeps an ordinary warehouse delivery from reserving
    a piece that is physically in a gallery.
  * The commission is a pricelist, not code. The gallery buys at list minus its
    percentage at the moment it sells.
  * A route per depot, selected on the quotation, sources the delivery from that
    gallery. Cheaper than a warehouse per gallery.
"""

GALLERY = "Galerie Démo"
COMMISSION = 40.0


def ref(xid):
    return env.ref(xid, raise_if_not_found=False)


log = []

# --- 1. Settings ------------------------------------------------------------
# Set the groups directly rather than through res.config.settings. A settings
# record carries EVERY setting, so writing one from a script also writes back
# whatever its own defaults resolved to - and product/models/res_config_settings
# .py:42 archives every pricelist when group_product_pricelist comes out falsy.
# That silently wiped the commission pricelist once already. Implied groups are
# the surgical equivalent with no side effects.
FEATURES = [
    "stock.group_stock_multi_locations",   # depot locations at all
    "stock.group_adv_location",            # the route that sources from them
    "stock.group_production_lot",          # a piece is individually identified
    "product.group_product_pricelist",     # the commission
    "sale.group_discount_per_so_line",     # ...shown as a discount, not a lower price
]
group_user = env.ref("base.group_user")
group_user.write({
    "implied_ids": [(4, env.ref(x).id) for x in FEATURES if env.ref(x, raise_if_not_found=False)]
})
log.append("features: " + ", ".join(f.split(".")[1] for f in FEATURES))

wh = env["stock.warehouse"].search([], limit=1)
customers = ref("stock.stock_location_customers")

# --- 2. The gallery ---------------------------------------------------------
partner = env["res.partner"].search([("name", "=", GALLERY)], limit=1)
if not partner:
    partner = env["res.partner"].create({
        "name": GALLERY,
        "is_company": True,
        "city": "Nantes",
        "country_id": ref("base.fr").id,
    })
log.append(f"partner: {partner.display_name} (id={partner.id})")

# --- 3. Locations -----------------------------------------------------------
# Odoo 19 has no "Physical Locations" root any more - WH is itself a parentless
# view location - so the depots get their own root tree beside it.
depots = env["stock.location"].search(
    [("name", "=", "Dépôts"), ("location_id", "=", False)], limit=1)
if not depots:
    depots = env["stock.location"].create({
        "name": "Dépôts", "usage": "view", "location_id": False,
    })

depot = env["stock.location"].search(
    [("name", "=", GALLERY), ("location_id", "=", depots.id)], limit=1)
if not depot:
    depot = env["stock.location"].create({
        "name": GALLERY, "usage": "internal",
        "location_id": depots.id, "company_id": env.company.id,
    })
log.append(f"location: {depot.complete_name} (id={depot.id})")

# --- 4. Operation types -----------------------------------------------------
def picking_type(name, seq, src, dest):
    vals = {
        "name": name, "code": "internal", "sequence_code": seq,
        "warehouse_id": wh.id, "company_id": env.company.id,
        "default_location_src_id": src.id, "default_location_dest_id": dest.id,
    }
    pt = env["stock.picking.type"].search(
        [("name", "=", name), ("warehouse_id", "=", wh.id)], limit=1)
    if pt:
        pt.write(vals)
        return pt
    return env["stock.picking.type"].create(vals)


pt_out = picking_type("Mise en dépôt", "DEP", wh.lot_stock_id, depot)
pt_back = picking_type("Retour de dépôt", "RET", depot, wh.lot_stock_id)
log.append(f"picking types: {pt_out.name} ({pt_out.id}), {pt_back.name} ({pt_back.id})")

# --- 5. Sourcing route ------------------------------------------------------
# sale_order_global_stock_route puts the route on the quotation and copies it to
# every line; the pull rule then sources from the depot instead of WH/Stock.
route_name = f"Dépôt-vente: {GALLERY}"
route_vals = {
    "name": route_name, "sale_selectable": True, "product_selectable": False,
    "company_id": env.company.id, "sequence": 20,
}
route = env["stock.route"].search([("name", "=", route_name)], limit=1)
if route:
    route.write(route_vals)
else:
    route = env["stock.route"].create(route_vals)

rule_vals = {
    "name": f"{GALLERY} → Client", "route_id": route.id, "action": "pull",
    "location_src_id": depot.id, "location_dest_id": customers.id,
    "picking_type_id": wh.out_type_id.id, "procure_method": "make_to_stock",
    "company_id": env.company.id, "warehouse_id": wh.id,
}
rule = env["stock.rule"].search([("route_id", "=", route.id)], limit=1)
if rule:
    rule.write(rule_vals)
else:
    rule = env["stock.rule"].create(rule_vals)
log.append(f"route: {route.name} (id={route.id}) — rule {rule.id}: "
           f"{rule.location_src_id.complete_name} -> {rule.location_dest_id.complete_name}")

# --- 6. Commission pricelist ------------------------------------------------
# compute_price must be 'percentage'; under 'formula' the percent_price field is
# ignored and the gallery silently pays list price.
pl_name = f"{GALLERY} (-{COMMISSION:.0f}%)"
item_vals = {"applied_on": "3_global", "compute_price": "percentage",
             "percent_price": COMMISSION}
# active_test=False: an archived pricelist must be reused, not duplicated.
pl = env["product.pricelist"].with_context(active_test=False).search(
    [("name", "=", pl_name)], limit=1)
if pl:
    pl.item_ids[:1].write(item_vals) if pl.item_ids else pl.write(
        {"item_ids": [(0, 0, item_vals)]})
else:
    pl = env["product.pricelist"].create({
        "name": pl_name,
        "currency_id": env.company.currency_id.id,
        "item_ids": [(0, 0, item_vals)],
    })
pl.action_unarchive()
partner.property_product_pricelist = pl
log.append(f"pricelist: {partner.property_product_pricelist.name} "
           f"(id={pl.id}) assigned to {partner.name}")

# --- 7. Invoicing rhythm ----------------------------------------------------
# The gallery reports sales as they happen but is invoiced once, at month end.
# sale_invoice_frequency is only the label and the group-by; the mechanism is
# Odoo's own: _get_invoice_grouping_keys() groups by partner, so invoicing a
# whole month of orders in one action yields a single invoice.
monthly = ref("sale_invoice_frequency.sale_invoice_frequency_monthly")
if monthly:
    partner.invoice_frequency_id = monthly
    log.append(f"invoicing frequency: {partner.invoice_frequency_id.name}")
else:
    log.append("invoicing frequency: sale_invoice_frequency not installed, skipped")

# --- 8. Hand the depot over to mb_depot -------------------------------------
# This script predates the module and builds the same objects by hand. Once
# mb_depot is installed, flagging the location is what makes the depot appear in
# its stock view and statement. New depots should go through the wizard
# (Inventory > Dépôt-vente > Nouveau dépôt) instead of this script.
if "is_depot" in env["stock.location"]._fields:
    depot.write({
        "is_depot": True,
        "depot_partner_id": partner.id,
        "depot_commission": COMMISSION,
        "depot_route_id": route.id,
        "depot_pricelist_id": pl.id,
    })
    log.append("mb_depot: location flagged as a depot")

env.cr.commit()
print("\n".join("OK  " + line for line in log))
