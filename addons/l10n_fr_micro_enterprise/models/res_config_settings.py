from odoo import fields, models


class ResConfigSettings(models.TransientModel):
	_inherit = "res.config.settings"

	l10n_fr_micro_tax_regime = fields.Selection(
		related="company_id.l10n_fr_micro_tax_regime", readonly=True,
	)
	l10n_fr_micro_goods_tax_id = fields.Many2one(
		related="company_id.l10n_fr_micro_goods_tax_id", readonly=True,
	)
	l10n_fr_micro_service_tax_id = fields.Many2one(
		related="company_id.l10n_fr_micro_service_tax_id", readonly=True,
	)
	l10n_fr_micro_bnc_enabled = fields.Boolean(
		related="company_id.l10n_fr_micro_bnc_enabled", readonly=False,
	)
	l10n_fr_micro_bnc_tax_id = fields.Many2one(
		related="company_id.l10n_fr_micro_bnc_tax_id", readonly=True,
	)
	l10n_fr_micro_bnc_economic_tax_id = fields.Many2one(
		related="company_id.l10n_fr_micro_bnc_economic_tax_id", readonly=True,
	)
	l10n_fr_micro_purchase_tax_id = fields.Many2one(
		related="company_id.l10n_fr_micro_purchase_tax_id", readonly=True,
	)
	l10n_fr_micro_fiscal_position_id = fields.Many2one(
		related="company_id.l10n_fr_micro_fiscal_position_id", readonly=True,
	)
	l10n_fr_micro_tax_switch_date = fields.Date(
		related="company_id.l10n_fr_micro_tax_switch_date", readonly=True,
	)

	def action_l10n_fr_micro_prepare_tax_setup(self):
		self.ensure_one()
		return self.company_id.action_l10n_fr_micro_prepare_tax_setup()

	def action_l10n_fr_micro_activate_franchise(self):
		self.ensure_one()
		return self.company_id.action_l10n_fr_micro_activate_franchise()

	def action_l10n_fr_micro_activate_vat(self, effective_date=None):
		self.ensure_one()
		return self.company_id.action_l10n_fr_micro_activate_vat(effective_date=effective_date)
