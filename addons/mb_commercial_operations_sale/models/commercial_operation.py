from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MbCommercialOperation(models.Model):
    _inherit = "mb.commercial.operation"

    sale_order_ids = fields.One2many(
        "sale.order", "mb_commercial_operation_id", string="Sales Orders",
    )
    customer_invoice_ids = fields.One2many(
        "account.move", "mb_commercial_operation_id", string="Customer Invoices",
    )
    sales_documents_expected = fields.Boolean()
    sales_documents_complete = fields.Boolean(compute="_compute_sales_documents_complete")

    @api.depends("sales_documents_expected", "sale_order_ids.state", "customer_invoice_ids.state")
    def _compute_sales_documents_complete(self):
        for operation in self:
            orders = operation.sale_order_ids.filtered(lambda order: order.state != "cancel")
            invoices = operation.customer_invoice_ids.filtered(lambda invoice: invoice.state != "cancel")
            operation.sales_documents_complete = (
                not operation.sales_documents_expected
                or bool(orders) and bool(invoices) and all(invoice.state == "posted" for invoice in invoices)
            )

    def action_view_sale_orders(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("sale.action_orders")
        action["domain"] = [("mb_commercial_operation_id", "=", self.id)]
        action["context"] = {
            "default_mb_commercial_operation_id": self.id,
            "default_partner_id": self.partner_id.id,
            "default_warehouse_id": self.source_warehouse_id.id,
        }
        return action

    def action_view_customer_invoices(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("account.action_move_out_invoice_type")
        action["domain"] = [("mb_commercial_operation_id", "=", self.id)]
        action["context"] = {"create": False}
        return action

    def action_financial_close(self):
        if self.filtered(lambda operation: not operation.sales_documents_complete):
            raise UserError(_("Complete and post the expected market sales documents before financial close."))
        return super().action_financial_close()
