from odoo import fields, models


class AccountTax(models.Model):
	_inherit = "account.tax"

	l10n_fr_micro_franchise_tax = fields.Boolean(
		string="Micro-enterprise franchise tax",
		readonly=True,
		copy=False,
		index=True,
		help="Technical marker for the franchise-en-base taxes managed by the micro-enterprise module.",
	)


class AccountTaxGroup(models.Model):
	_inherit = "account.tax.group"

	l10n_fr_micro_franchise_group = fields.Boolean(
		string="Micro-enterprise franchise group",
		readonly=True,
		copy=False,
		index=True,
	)
