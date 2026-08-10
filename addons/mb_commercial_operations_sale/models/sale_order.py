from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import float_compare


class SaleOrder(models.Model):
    _inherit = "sale.order"

    mb_commercial_operation_id = fields.Many2one(
        "mb.commercial.operation",
        string="Commercial Operation",
        check_company=True,
        copy=False,
        index=True,
        domain="[('operation_type', '=', 'market'), ('state', 'in', ('approved', 'scheduled', 'in_progress'))]",
    )
    mb_market_product_ids = fields.Many2many(
        "product.product", compute="_compute_mb_market_product_ids",
    )

    @api.depends("mb_commercial_operation_id", "mb_commercial_operation_id.market_location_id")
    def _compute_mb_market_product_ids(self):
        for order in self:
            location = order.mb_commercial_operation_id.market_location_id
            if not location:
                order.mb_market_product_ids = False
                continue
            product_ids = [
                product.id
                for product, quantity, reserved in self.env["stock.quant"]._read_group(
                    [("location_id", "child_of", location.id)],
                    ["product_id"], ["quantity:sum", "reserved_quantity:sum"],
                )
                if quantity - reserved > 0
            ]
            order.mb_market_product_ids = [fields.Command.set(product_ids)]

    @api.onchange("mb_commercial_operation_id")
    def _onchange_commercial_operation(self):
        for order in self.filtered("mb_commercial_operation_id"):
            operation = order.mb_commercial_operation_id
            order.warehouse_id = operation.source_warehouse_id
            order.date_order = operation.actual_start or operation.planned_start

    @api.constrains("mb_commercial_operation_id", "company_id", "warehouse_id")
    def _check_commercial_operation(self):
        for order in self.filtered("mb_commercial_operation_id"):
            operation = order.mb_commercial_operation_id
            if operation.company_id != order.company_id:
                raise ValidationError(_("The sales order and market operation must share a company."))
            if operation.source_warehouse_id and order.warehouse_id != operation.source_warehouse_id:
                raise ValidationError(_("The sales order must use the market operation's source warehouse."))

    def _get_product_catalog_domain(self):
        domain = super()._get_product_catalog_domain()
        self.ensure_one()
        if self.mb_commercial_operation_id:
            domain &= Domain("id", "in", self.mb_market_product_ids.ids)
        return domain

    def _check_market_stock(self):
        for order in self.filtered("mb_commercial_operation_id"):
            operation = order.mb_commercial_operation_id
            if not operation.market_location_id or not operation.preparation_picking_id \
                    or operation.preparation_picking_id.state != "done":
                raise ValidationError(_("Complete market stock preparation before recording market sales."))
            picking_type = order.warehouse_id.out_type_id
            if not picking_type.analytic_costs:
                raise ValidationError(_(
                    "Enable Analytic Costs on operation type %(operation_type)s so product cost reaches market profitability exactly once.",
                    operation_type=picking_type.display_name,
                ))
            required = defaultdict(float)
            for line in order.order_line.filtered(lambda item: not item.display_type and item.product_id.is_storable):
                required[line.product_id] += line.product_uom_id._compute_quantity(
                    line.product_uom_qty, line.product_id.uom_id
                )
            quant_model = self.env["stock.quant"]
            for product, quantity in required.items():
                available = quant_model._get_available_quantity(
                    product, operation.market_location_id, strict=False,
                )
                if float_compare(available, quantity, precision_rounding=product.uom_id.rounding) < 0:
                    raise ValidationError(_(
                        "Only %(available)s %(uom)s of %(product)s is free at this market.",
                        available=available, uom=product.uom_id.display_name,
                        product=product.display_name,
                    ))

    def action_confirm(self):
        self._check_market_stock()
        result = super().action_confirm()
        for order in self.filtered("mb_commercial_operation_id"):
            order.picking_ids.filtered(lambda picking: picking.state != "cancel").write({
                "mb_commercial_operation_id": order.mb_commercial_operation_id.id,
                "project_id": order.mb_commercial_operation_id.project_id.id,
            })
        return result

    def write(self, vals):
        if "mb_commercial_operation_id" in vals:
            operations = self.mb_commercial_operation_id | self.env["mb.commercial.operation"].browse(
                vals.get("mb_commercial_operation_id")
            )
            if operations.filtered(lambda operation: operation.state == "financially_closed"):
                raise UserError(_("Reopen the financially closed operation before changing sales links."))
            if self.filtered(lambda order: order.state not in ("draft", "sent")):
                raise UserError(_("A confirmed sales order cannot be moved to another commercial operation."))
        return super().write(vals)

    def _prepare_invoice(self):
        values = super()._prepare_invoice()
        if self.mb_commercial_operation_id:
            values["mb_commercial_operation_id"] = self.mb_commercial_operation_id.id
        return values

    def _create_account_invoices(self, invoice_vals_list, final):
        invoices = super()._create_account_invoices(invoice_vals_list, final)
        for invoice in invoices:
            operations = invoice.invoice_line_ids.sale_line_ids.order_id.mb_commercial_operation_id
            if len(operations) == 1:
                invoice.mb_commercial_operation_id = operations
                distribution = {str(operations.analytic_account_id.id): 100.0}
                invoice.invoice_line_ids.filtered(
                    lambda line: line.display_type == "product"
                ).analytic_distribution = distribution
        return invoices


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    mb_commercial_operation_id = fields.Many2one(
        related="order_id.mb_commercial_operation_id", store=True,
    )
    mb_market_product_ids = fields.Many2many(related="order_id.mb_market_product_ids")

    def _prepare_procurement_values(self):
        values = super()._prepare_procurement_values()
        if self.mb_commercial_operation_id:
            values["mb_commercial_operation_id"] = self.mb_commercial_operation_id
        return values

    def _prepare_invoice_line(self, **optional_values):
        values = super()._prepare_invoice_line(**optional_values)
        if self.mb_commercial_operation_id:
            values["analytic_distribution"] = {
                str(self.mb_commercial_operation_id.analytic_account_id.id): 100.0
            }
        return values
