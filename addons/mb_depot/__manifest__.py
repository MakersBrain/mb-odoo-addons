{
    "name": "MakersBrain Consignment",
    "summary": "Consignment stock held at galleries and shops, and the statement that settles it.",
    "description": """
Odoo has no outbound consignment. Its built-in Consignment setting is the other
direction - vendor-owned stock sitting in your warehouse - and OCA has nothing
either, so the location-based model below is not a workaround, it is the model
everyone builds.

A depot is a *warehouse* owned by us and physically held by a gallery. Its stock
location is internal, which keeps unsold pieces on our balance sheet with no
revenue recognised - the legal situation of consignment selling; delivering to the
customer location instead would derecognise the stock with no counterpart
revenue. Being a warehouse of its own is what keeps an ordinary delivery from
reserving a piece standing on a shelf in Nantes, and what makes every
warehouse-scoped figure in Odoo - on hand, forecast, the availability widget -
count the gallery's shelf instead of reading zero.

This module adds what Odoo and OCA do not have:

* a depot flag on the warehouse, carrying the gallery and its commission;
* a wizard that creates a depot - warehouse and commission pricelist - in one
  action, because that pair repeats per gallery and has to agree with itself;
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
* a consignment note for the placement transfer. stock_picking_report_valued cannot
  serve here: every value on it comes from move_id.sale_line_id, and a placement
  is an internal transfer with no sale line, so it renders blank;
* the product catalog on a placement transfer. product.catalog.mixin is opt-in
  per model and stock.picking does not take it, on the reasoning that a picking
  is generated from a source document rather than typed - which a placement,
  starting from nothing and naming a lot of individual pieces, is not;
* the depositary's own warehouse defaulted onto their sale orders, and the
  product picker there limited to what they are actually holding and
  unreserved;
* invoicing on delivered quantities as the default for new products, so the
  transfer out of the depot is what gates the gallery's invoice rather than the
  confirmation of an order.

The commission itself is a pricelist, not code: under purchase-resale on sale
the gallery buys at list minus its percentage at the moment it sells. For that
percentage to appear on the invoice as a discount rather than a quietly reduced
unit price, the pricelist item must be compute_price='percentage' AND the
Discounts feature must be enabled - see sale/models/product_pricelist_item.py,
_show_discount(). The wizard sets both.

Sourcing needs no third-party module: a sale from a depot is a sale from that
warehouse, which is Odoo's own Warehouse field on the quotation.
""",
    "version": "19.0.4.0.9",
    "license": "AGPL-3",
    "category": "Inventory/Inventory",
    "author": "MakersBrain",
    "depends": [
        "stock",
        # The commission is a pricelist and the statement values sold pieces
        # from the sale order line, so selling has to exist.
        "sale_stock",
        "account",
    ],
    "data": [
        "security/mb_depot_security.xml",
        "security/ir.model.access.csv",
        "views/stock_warehouse_views.xml",
        "views/stock_quant_views.xml",
        "views/stock_picking_views.xml",
        "views/sale_order_views.xml",
        "views/depot_sale_report_views.xml",
        "views/account_move_views.xml",
        "views/res_company_views.xml",
        "views/mb_depot_navigation_views.xml",
        "wizard/mb_depot_create_views.xml",
        "wizard/mb_depot_statement_views.xml",
        "report/mb_depot_reports.xml",
        "report/mb_depot_statement_template.xml",
        "report/mb_depot_bon_template.xml",
        "report/mb_depot_invoice_template.xml",
        "views/mb_depot_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
