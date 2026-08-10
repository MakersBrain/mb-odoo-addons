from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    mb_commercial_operation_id = fields.Many2one(
        "mb.commercial.operation", check_company=True, copy=False, index=True,
    )

    def write(self, vals):
        result = super().write(vals)
        if {"state", "date_planned"}.intersection(vals):
            self.order_line.mb_market_stock_plan_line_id._update_supply_readiness()
        return result


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    mb_market_stock_plan_line_id = fields.Many2one(
        "mb.market.stock.plan.line", check_company=True, copy=False, index=True,
    )

    def write(self, vals):
        result = super().write(vals)
        if {"product_qty", "date_planned"}.intersection(vals):
            self.mb_market_stock_plan_line_id._update_supply_readiness()
        return result
