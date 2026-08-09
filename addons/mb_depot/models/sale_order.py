from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    mb_depot_id = fields.Many2one(
        comodel_name="stock.location",
        string="Dépôt-vente",
        domain=[("is_depot", "=", True)],
        compute="_compute_mb_depot_id",
        store=True,
        readonly=False,
        help="Sell the pieces the depositary is holding. Set it and the product "
             "picker on the lines offers only what is physically at that depot, "
             "and the delivery sources from there rather than from the warehouse.",
    )
    mb_depot_product_ids = fields.Many2many(
        comodel_name="product.product",
        string="Pieces at the depot",
        compute="_compute_mb_depot_product_ids",
        help="On hand and unreserved at the depot. What the line's product "
             "domain is built from.",
    )

    @api.depends("partner_id")
    def _compute_mb_depot_id(self):
        """The depot of the customer, when the customer is a depositary.

        A gallery reporting its sales is billed as itself, so the depot follows
        from the partner and does not have to be picked by hand. Matching on the
        commercial partner rather than the contact: a depot belongs to the
        company, and orders are often addressed to a person inside it.
        """
        for order in self:
            depot = self.env["stock.location"].search([
                ("is_depot", "=", True),
                ("depot_partner_id", "=", order.partner_id.commercial_partner_id.id),
            ], limit=1)
            order.mb_depot_id = depot

    @api.depends("mb_depot_id")
    def _compute_mb_depot_product_ids(self):
        """What is actually standing on the depositary's shelf.

        Unreserved, not merely on hand: once a confirmed order has reserved a
        piece it is spoken for, and a unique ceramic offered twice is a piece
        that cannot be delivered twice.
        """
        for order in self:
            if not order.mb_depot_id:
                order.mb_depot_product_ids = False
                continue
            available = [
                product.id
                for product, quantity, reserved in self.env["stock.quant"]._read_group(
                    [("location_id", "child_of", order.mb_depot_id.id)],
                    ["product_id"],
                    ["quantity:sum", "reserved_quantity:sum"],
                )
                if quantity - reserved > 0
            ]
            order.mb_depot_product_ids = [fields.Command.set(available)]

    @api.onchange("mb_depot_id")
    def _onchange_mb_depot_id(self):
        """Point the sourcing at the depot as well as the product picker.

        sale_order_global_stock_route is what puts route_ids on the order, and
        it is deliberately not a dependency of this module - it is AGPL-3 and
        this is LGPL-3. Hence the check rather than a plain assignment: without
        that module the depot still filters the products and the route is set by
        hand, which is the documented fallback.
        """
        if "route_ids" not in self._fields:
            return
        for order in self:
            route = order.mb_depot_id.depot_route_id
            if route:
                order.route_ids = [fields.Command.set(route.ids)]


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    # Related rather than reached through `parent.` in the line's domain: the
    # domain is evaluated per row, and a field on the row itself is the form the
    # web client evaluates without ambiguity.
    mb_depot_id = fields.Many2one(
        related="order_id.mb_depot_id", string="Dépôt-vente")
    mb_depot_product_ids = fields.Many2many(
        related="order_id.mb_depot_product_ids", string="Pieces at the depot")

    def _read_qties(self, date, wh):
        """Read availability at the depot rather than at the warehouse.

        sale_stock reads these three quantities with `warehouse_id` in the
        context, and a depot is deliberately outside WH - that is what stops an
        ordinary delivery reserving a piece standing in a gallery. Left alone,
        every line of every depot sale reports nothing on hand and the widget
        says the piece cannot be delivered, while it is sitting on the shelf it
        is being sold from.

        warehouse_id has to go rather than merely be joined by a location:
        _get_domain_locations() intersects the two, and a depot under no
        warehouse intersects to nothing.
        """
        depot = self.order_id.mb_depot_id
        if len(depot) == 1:
            return self.product_id.with_context(
                to_date=date, location=depot.id, warehouse_id=False,
            ).read(["qty_available", "free_qty", "virtual_available"])
        return super()._read_qties(date, wh)
