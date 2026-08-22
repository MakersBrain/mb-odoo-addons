from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    l10n_fr_micro_vat_operation_date = fields.Date(
        string="VAT threshold operation date",
        copy=False,
        help="Delivery/taxable-event date used for the VAT-franchise threshold when it cannot be derived from stock or POS.",
    )
