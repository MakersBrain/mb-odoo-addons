from odoo import _, fields, models
from odoo.exceptions import AccessError


class AccountJournal(models.Model):
	_inherit = "account.journal"

	l10n_fr_micro_receipt_method = fields.Selection(
		selection=[
			("transfer", "Bank transfer"),
			("card", "Card"),
			("cash", "Cash"),
			("cheque", "Cheque"),
			("other", "Other / manual"),
		],
		string="Micro receipt method",
		help="Explicit payment-method classification used by the micro-enterprise receipt book.",
	)

	def write(self, values):
		if "l10n_fr_micro_receipt_method" in values and not self.env.is_superuser() \
				and not self.env.user.has_group("account.group_account_manager"):
			raise AccessError(_("Only an Accounting Administrator can classify receipt journals."))
		return super().write(values)
