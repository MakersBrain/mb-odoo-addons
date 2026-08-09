from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    mb_depot_product_ids = fields.Many2many(
        comodel_name="product.product",
        string="Pieces at the depot",
        compute="_compute_mb_depot_product_ids",
        help="On hand and unreserved at the depot. What the line's product "
             "domain is built from.",
    )

    # sale_stock's own depends are repeated rather than extended: the field
    # resolves its dependencies from whichever compute method it finds, so
    # decorating the override with partner_id alone would quietly drop them.
    @api.depends("user_id", "company_id", "partner_id")
    def _compute_warehouse_id(self):
        """Sell from the gallery's own warehouse when the customer is a gallery.

        A depositary reporting its sales is billed as itself, so the depot
        follows from the partner and does not have to be picked by hand. Matched
        on the commercial partner rather than the contact: a depot belongs to the
        company, and orders are often addressed to a person inside it.

        This is the whole sourcing mechanism now. The warehouse on the order
        decides which stock location the delivery draws from, so a depot sale
        needs no route, no pull rule and no third-party module to select one.
        """
        super()._compute_warehouse_id()
        depots = self.env["stock.warehouse"].search([("is_depot", "=", True)])
        by_partner = {w.depot_partner_id.id: w for w in depots}
        for order in self:
            depot = by_partner.get(order.partner_id.commercial_partner_id.id)
            if depot:
                order.warehouse_id = depot

    @api.depends("warehouse_id")
    def _compute_mb_depot_product_ids(self):
        """What is actually standing on the depositary's shelf.

        Unreserved, not merely on hand: once a confirmed order has reserved a
        piece it is spoken for, and a unique ceramic offered twice is a piece
        that cannot be delivered twice.
        """
        for order in self:
            if not order.warehouse_id.is_depot:
                order.mb_depot_product_ids = False
                continue
            available = [
                product.id
                for product, quantity, reserved in self.env["stock.quant"]._read_group(
                    [("location_id", "child_of", order.warehouse_id.view_location_id.id)],
                    ["product_id"],
                    ["quantity:sum", "reserved_quantity:sum"],
                )
                if quantity - reserved > 0
            ]
            order.mb_depot_product_ids = [fields.Command.set(available)]

    def action_confirm(self):
        mandate = self.filtered(
            lambda order: order.warehouse_id.is_depot
            and order.warehouse_id.mb_depot_legal_structure == "mandate"
        )
        if mandate:
            raise UserError(_(
                "The selected depot is a mandate. The purchase-resale sales "
                "workflow cannot be used; invoice final customers at retail and "
                "book the gallery commission as a vendor bill."
            ))
        return super().action_confirm()


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    # Related rather than reached through `parent.` in the line's domain: the
    # domain is evaluated per row, and a field on the row itself is the form the
    # web client evaluates without ambiguity.
    mb_is_depot_order = fields.Boolean(
        related="order_id.warehouse_id.is_depot", string="Sold from a depot")
    mb_depot_product_ids = fields.Many2many(
        related="order_id.mb_depot_product_ids", string="Pieces at the depot")
