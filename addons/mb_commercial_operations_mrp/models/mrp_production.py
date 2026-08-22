from odoo import fields, models


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    mb_market_stock_plan_line_id = fields.Many2one(
        "mb.market.stock.plan.line",
        check_company=True,
        copy=False,
        index=True,
    )
    mb_commercial_operation_id = fields.Many2one(
        "mb.commercial.operation",
        check_company=True,
        copy=False,
        index=True,
    )

    def write(self, vals):
        result = super().write(vals)
        if {"state", "date_start", "date_finished", "date_deadline"}.intersection(vals):
            self.mb_market_stock_plan_line_id._update_supply_readiness()
        return result
