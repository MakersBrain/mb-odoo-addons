from odoo import _, fields, models
from odoo.exceptions import AccessError


class AccountTax(models.Model):
	_inherit = "account.tax"

	l10n_fr_micro_urssaf_category = fields.Selection(
		selection=[
			("bic_goods", "BIC — sales of goods"),
			("bic_service", "BIC — commercial or craft services"),
			("bnc", "BNC — liberal activity"),
		],
		string="URSSAF turnover category",
		copy=False,
		index=True,
		help="Micro-social turnover box carried by sale lines using this tax.",
	)

	l10n_fr_micro_franchise_tax = fields.Boolean(
		string="Micro-enterprise franchise tax",
		readonly=True,
		copy=False,
		index=True,
		help="Technical marker for the franchise-en-base taxes managed by the micro-enterprise module.",
	)

	def write(self, values):
		if "l10n_fr_micro_urssaf_category" in values and not self.env.is_superuser() \
				and not self.env.user.has_group("account.group_account_manager"):
			raise AccessError(_("Only an Accounting Administrator can classify URSSAF taxes."))
		return super().write(values)


class AccountTaxGroup(models.Model):
	_inherit = "account.tax.group"

	l10n_fr_micro_franchise_group = fields.Boolean(
		string="Micro-enterprise franchise group",
		readonly=True,
		copy=False,
		index=True,
	)
