from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    mb_market_target_margin_per_hour = fields.Monetary(
        related="company_id.mb_market_target_margin_per_hour", readonly=False,
    )
