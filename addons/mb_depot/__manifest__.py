{
    "name": "Makersbrain Dépôt-vente",
    "summary": "Consignment stock held at galleries and shops, and the statement that settles it.",
    "description": """
Odoo has no outbound consignment. Its built-in Consignment setting is the other
direction - vendor-owned stock sitting in your warehouse - and OCA has nothing
either, so the location-based model below is not a workaround, it is the model
everyone builds.

A depot is an *internal* location owned by us and physically held by a gallery.
Internal keeps unsold pieces on our balance sheet with no revenue recognised,
which is the legal situation of dépôt-vente; delivering to the customer location
instead would derecognise the stock with no counterpart revenue. The depots sit
in their own root tree rather than under a warehouse, so an ordinary delivery
never reserves a piece that is standing on a shelf in Nantes.

This module adds what Odoo and OCA do not have:

* a depot flag on the location, carrying the gallery, its commission and the
  route that sources sales from it;
* a wizard that creates a depot - location, route, pull rule and commission
  pricelist - in one action, because that set repeats per gallery;
* live stock per depot with an ageing column, so a piece that has sat unsold
  for four months is visible;
* a reported sale date on the move line, because a gallery reports last month's
  sales this month and the move's own date is when we keyed it in: binning the
  statement on that would put March's sales in April and leave March closing too
  high. It is a plain writable Date with no effect on stock state, so a sync
  from a shop's sales sheet can set it;
* the depot statement: opening, placed, sold, returned and closing over a
  period, per piece. Sold and returned are both outgoing moves and are told
  apart by destination, which is what makes the statement reconcile against the
  quants rather than drift from them;
* a bon de dépôt for the placement transfer. stock_picking_report_valued cannot
  serve here: every value on it comes from move_id.sale_line_id, and a placement
  is an internal transfer with no sale line, so it renders blank.

The commission itself is a pricelist, not code: under achat-revente sur vente
the gallery buys at list minus its percentage at the moment it sells. For that
percentage to appear on the invoice as a discount rather than a quietly reduced
unit price, the pricelist item must be compute_price='percentage' AND the
Discounts feature must be enabled - see sale/models/product_pricelist_item.py,
_show_discount(). The wizard sets both.

Selecting the depot route on a quotation needs OCA's
sale_order_global_stock_route. That is deliberately not a dependency: it is
AGPL-3 and this module is LGPL-3. Without it the route is still created and can
be set on the order line by hand.
""",
    "version": "19.0.1.1.0",
    "license": "LGPL-3",
    "category": "Inventory/Inventory",
    "author": "Makersbrain",
    "depends": [
        "stock",
        # The commission is a pricelist and the statement values sold pieces
        # from the sale order line, so selling has to exist.
        "sale_stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/stock_location_views.xml",
        "views/stock_quant_views.xml",
        "views/stock_picking_views.xml",
        "wizards/mb_depot_create_views.xml",
        "wizards/mb_depot_statement_views.xml",
        "report/mb_depot_reports.xml",
        "report/mb_depot_statement_template.xml",
        "report/mb_depot_bon_template.xml",
        "views/mb_depot_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
