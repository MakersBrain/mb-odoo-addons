from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    mb_market_target_margin_per_hour = fields.Monetary(
        string="Target Market Margin per Hour",
        help="Minimum planned margin per hour of effort (work plus travel) below which a "
             "market is only worth attending for reasons other than money. Leave at zero "
             "to judge markets on break-even headroom alone.",
    )

    _mb_market_target_margin_nonnegative = models.Constraint(
        "CHECK(mb_market_target_margin_per_hour >= 0)",
        "The target market margin per hour cannot be negative.",
    )
