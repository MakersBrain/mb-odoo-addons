from odoo import fields, models


class AccountFiscalPosition(models.Model):
    _inherit = "account.fiscal.position"

    l10n_fr_micro_franchise_position = fields.Boolean(
        string="Micro-enterprise franchise position",
        readonly=True,
        copy=False,
        index=True,
        help="Technical marker for the domestic franchise-en-base fiscal position.",
    )
