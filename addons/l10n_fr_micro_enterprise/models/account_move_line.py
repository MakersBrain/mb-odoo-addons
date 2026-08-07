from odoo import models


class AccountMoveLine(models.Model):
	_inherit = "account.move.line"

	def _get_computed_taxes(self):
		taxes = super()._get_computed_taxes()
		self.ensure_one()
		move = self.move_id
		company = move.company_id
		if (
			company.l10n_fr_micro_tax_regime != "franchise"
			or not move.is_sale_document(include_receipts=True)
		):
			return taxes
		partner_country = move.commercial_partner_id.country_id
		company_country = company.account_fiscal_country_id or company.country_id
		if partner_country and partner_country != company_country:
			return taxes
		if taxes:
			return company.l10n_fr_micro_fiscal_position_id.map_tax(taxes)
		if self.product_id.type == "service":
			return company.l10n_fr_micro_service_tax_id
		return company.l10n_fr_micro_goods_tax_id
