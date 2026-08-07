from odoo import api, fields, models


class AccountMove(models.Model):
	_inherit = "account.move"

	l10n_fr_micro_franchise_invoice = fields.Boolean(
		string="Franchise-en-base invoice",
		copy=False,
		readonly=True,
		help="Snapshot used to preserve the legally required Article 293 B mention when the invoice is reprinted.",
	)

	@api.model
	def _l10n_fr_micro_values_are_franchise_invoice(self, values):
		if values.get("move_type") not in ("out_invoice", "out_refund", "out_receipt"):
			return False
		company = self.env["res.company"].browse(values.get("company_id")) or self.env.company
		if company.l10n_fr_micro_tax_regime != "franchise":
			return False
		invoice_date = fields.Date.to_date(values.get("invoice_date")) or fields.Date.context_today(company)
		return not company.l10n_fr_micro_tax_switch_date or invoice_date >= company.l10n_fr_micro_tax_switch_date

	@api.model_create_multi
	def create(self, values_list):
		for values in values_list:
			if "l10n_fr_micro_franchise_invoice" not in values:
				values["l10n_fr_micro_franchise_invoice"] = self._l10n_fr_micro_values_are_franchise_invoice(values)
		return super().create(values_list)

	def _post(self, soft=True):
		for move in self.filtered(lambda candidate: candidate.state == "draft"):
			if self._l10n_fr_micro_values_are_franchise_invoice({
				"move_type": move.move_type,
				"company_id": move.company_id.id,
				"invoice_date": move.invoice_date,
			}):
				move.l10n_fr_micro_franchise_invoice = True
		return super()._post(soft=soft)
