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
