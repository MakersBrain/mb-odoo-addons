from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    mb_commercial_operation_id = fields.Many2one(
        "mb.commercial.operation",
        string="Commercial Operation",
        check_company=True,
        copy=False,
        index=True,
    )
    mb_commercial_stock_role = fields.Selection(
        [("preparation", "Market Preparation"), ("return", "Market Return")],
        copy=False,
        index=True,
    )


class StockMove(models.Model):
    _inherit = "stock.move"

    mb_market_stock_plan_line_id = fields.Many2one(
        "mb.market.stock.plan.line",
        string="Market Stock Target",
        check_company=True,
        copy=False,
        index=True,
    )

    def _prepare_analytic_line_values(self, account_field_values, amount, unit_amount):
        values = super()._prepare_analytic_line_values(
            account_field_values,
            amount,
            unit_amount,
        )
        if self.picking_id.mb_commercial_operation_id:
            values["mb_commercial_operation_id"] = self.picking_id.mb_commercial_operation_id.id
        return values
