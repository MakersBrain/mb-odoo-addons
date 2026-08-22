"""Dépôt-vente fixture: a gallery, its depot warehouse and a commission
pricelist.

Run it against a database with mb_depot installed:

    docker compose exec -T odoo odoo shell -d mb_odoo --no-http --log-level=warn \
        < scripts/setup_depot_fixture.py

Idempotent: re-running updates rather than duplicates, except for the sale order
at the end, which is only created if the gallery has none.

The model this encodes, for the achat-revente-sur-vente contract shape:

  * A depot is a *warehouse*. Its stock location is internal, so unsold pieces
    stay on our balance sheet and no revenue is recognised while they sit at the
    gallery. Delivering to the customer location instead would derecognise the
    stock with no counterpart revenue.
  * Being its own warehouse keeps an ordinary delivery from reserving a piece
    that is physically in a gallery, and makes on hand, forecast and the
    availability widget count the gallery's shelf instead of reading zero.
  * The commission is a pricelist, not code. The gallery buys at list minus its
    percentage at the moment it sells.
  * Selling from a depot is selecting that warehouse on the quotation. No route,
    no pull rule, no third-party module.
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
    "stock.group_stock_multi_locations",  # locations inside the depot at all
    "stock.group_stock_multi_warehouses",  # ...and the Warehouse field that picks one
    "stock.group_production_lot",  # a piece is individually identified
    "product.group_product_pricelist",  # the commission
    "sale.group_discount_per_so_line",  # ...shown as a discount, not a lower price
]
group_user = env.ref("base.group_user")
group_user.write(
    {"implied_ids": [(4, env.ref(x).id) for x in FEATURES if env.ref(x, raise_if_not_found=False)]}
)
log.append("features: " + ", ".join(f.split(".")[1] for f in FEATURES))


# --- 2. The gallery ---------------------------------------------------------
partner = env["res.partner"].search([("name", "=", GALLERY)], limit=1)
if not partner:
    partner = env["res.partner"].create(
        {
            "name": GALLERY,
            "is_company": True,
            "city": "Nantes",
            "country_id": ref("base.fr").id,
        }
    )
log.append(f"partner: {partner.display_name} (id={partner.id})")

# --- 3. The depot ------------------------------------------------------------
# A depot is a warehouse: its stock location is internal, so unsold pieces stay
# on our balance sheet, and being its own warehouse is what keeps an ordinary
# delivery from reserving a piece standing in the gallery - and what makes every
# warehouse-scoped figure in Odoo count the gallery's shelf rather than zero.
#
# Built through the wizard rather than by hand. It is idempotent, it creates the
# commission pricelist alongside the warehouse so the two agree, and doing it
# here by hand would be a second implementation to keep in step.
wizard = env["mb.depot.create"].create(
    {
        "partner_id": partner.id,
        "commission": COMMISSION,
    }
)
wizard.action_create()
depot = env["stock.warehouse"].search(
    [("is_depot", "=", True), ("depot_partner_id", "=", partner.id)], limit=1
)
pl = depot.depot_pricelist_id
log.append(f"depot: {depot.name} ({depot.code}) — stock at {depot.lot_stock_id.complete_name}")
log.append(f"pricelist: {pl.name} (id={pl.id}) assigned to {partner.name}")

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

env.cr.commit()
print("\n".join("OK  " + line for line in log))
