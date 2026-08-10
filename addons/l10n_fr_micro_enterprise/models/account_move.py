from odoo import fields, models


class AccountMove(models.Model):
	_inherit = "account.move"

	l10n_fr_micro_franchise_invoice = fields.Boolean(
		string="Franchise-en-base invoice",
		copy=False,
		readonly=True,
		help="Snapshot used to preserve the legally required Article 293 B mention when the invoice is reprinted.",
	)

	def _l10n_fr_micro_is_franchise_invoice(self):
		"""Derive the legal snapshot from the taxes actually posted on the invoice."""
		self.ensure_one()
		if not self.is_sale_document(include_receipts=True):
			return False
		invoice_taxes = self.invoice_line_ids.filtered(
			lambda line: line.display_type == "product"
		).tax_ids
		return any(invoice_taxes.mapped("l10n_fr_micro_franchise_tax"))

	def _post(self, soft=True):
		posted = super()._post(soft=soft)
		for move in posted.filtered(lambda candidate: candidate.state == "posted"):
			# Write both outcomes. A draft may have been prepared under a different
			# regime or date; only final posting evidence is legally relevant.
			move.l10n_fr_micro_franchise_invoice = move._l10n_fr_micro_is_franchise_invoice()
		return posted
