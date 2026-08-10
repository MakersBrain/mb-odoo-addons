from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    mb_commercial_operation_id = fields.Many2one(
        "mb.commercial.operation", check_company=True, copy=False, index=True,
    )
