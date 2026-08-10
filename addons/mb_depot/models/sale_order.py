from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    mb_depot_sale_report_id = fields.Many2one(
        "mb.depot.sale.report", string="Depot sale report", copy=False,
        index=True, readonly=True,
    )
    mb_depot_effective_date = fields.Datetime(
        string="Effective depot sale date", copy=False, readonly=True,
    )
    mb_depot_reported_public_total = fields.Monetary(
        string="Reported public total", copy=False, readonly=True,
    )
    mb_depot_reported_net_total = fields.Monetary(
        string="Reported net total", copy=False, readonly=True,
    )

    mb_depot_product_ids = fields.Many2many(
        comodel_name="product.product",
        string="Pieces at the depot",
        compute="_compute_mb_depot_product_ids",
        help="On hand and unreserved at the depot. What the line's product "
             "domain is built from.",
    )

    def _mb_depots_by_company_and_partner(self):
        depots = self.env["stock.warehouse"].search([
            ("is_depot", "=", True),
            ("company_id", "in", self.company_id.ids),
        ])
        return {
            (depot.company_id.id, depot.depot_partner_id.commercial_partner_id.id): depot
            for depot in depots
        }

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
        by_partner = self._mb_depots_by_company_and_partner()
        for order in self:
            depot = by_partner.get((
                order.company_id.id,
                order.partner_id.commercial_partner_id.id,
            ))
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
        by_partner = self._mb_depots_by_company_and_partner()
        for order in self:
            depot = by_partner.get((
                order.company_id.id,
                order.partner_id.commercial_partner_id.id,
            ))
            if depot and order.warehouse_id != depot:
                order.warehouse_id = depot

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

        depot_lines = self.filtered("warehouse_id.is_depot").order_line.filtered(
            lambda line: not line.display_type
        )
        # Depot sales deliberately source on-hand stock from the order's depot
        # warehouse. An explicit route can override that warehouse and was how
        # the pre-warehouse implementation worked; remove any such stale route
        # before procurement creates a delivery from the wrong location.
        depot_lines.route_ids = False

        invalid_lines = depot_lines.filtered(
            lambda line: not line.display_type
            and line.product_id.is_storable
            and line.product_id.invoice_policy != "delivery"
        )
        if invalid_lines:
            products = ", ".join(sorted(set(invalid_lines.product_id.mapped("display_name"))))
            raise UserError(_(
                "Depot sales must invoice delivered quantities. Change the "
                "invoicing policy to Delivered quantities for: %(products)s",
                products=products,
            ))
        return super().action_confirm()

    def _prepare_confirmation_values(self):
        values = super()._prepare_confirmation_values()
        self.ensure_one()
        if self.mb_depot_sale_report_id and self.mb_depot_effective_date:
            values["date_order"] = self.mb_depot_effective_date
        return values

    def _create_account_invoices(self, invoice_vals_list, final):
        """Attach depot evidence to invoices created by Odoo's standard flow."""
        invoices = super()._create_account_invoices(invoice_vals_list, final)
        for invoice in invoices:
            orders = invoice.invoice_line_ids.sale_line_ids.order_id.filtered(
                "mb_depot_sale_report_id"
            )
            reports = orders.mb_depot_sale_report_id
            if not reports:
                continue
            delivery_dates = [
                order.mb_depot_sale_report_id._company_local_date(
                    order.mb_depot_effective_date
                )
                for order in orders
                if order.mb_depot_effective_date
            ]
            invoice.write({
                "mb_depot_sale_report_ids": [fields.Command.set(reports.ids)],
                "mb_depot_sale_report_id": reports.id if len(reports) == 1 else False,
                "mb_depot_delivery_date_from": min(delivery_dates),
                "mb_depot_delivery_date_to": max(delivery_dates),
            })
        return invoices


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    mb_depot_sale_report_line_id = fields.Many2one(
        "mb.depot.sale.report.line", copy=False, readonly=True, index=True,
    )

    # Related rather than reached through `parent.` in the line's domain: the
    # domain is evaluated per row, and a field on the row itself is the form the
    # web client evaluates without ambiguity.
    mb_is_depot_order = fields.Boolean(
        related="order_id.warehouse_id.is_depot", string="Sold from a depot")
    mb_depot_product_ids = fields.Many2many(
        related="order_id.mb_depot_product_ids", string="Pieces at the depot")
