from odoo import _, models
from odoo.exceptions import ValidationError


class MbDepotSaleReport(models.Model):
	_inherit = "mb.depot.sale.report"

	def _get_closed_period_barriers(self):
		barriers = super()._get_closed_period_barriers()
		self.ensure_one()
		if self.company_id.l10n_fr_micro_depot_sale_closed_through:
			barriers[_("filed URSSAF horizon")] = (
				self.company_id.l10n_fr_micro_depot_sale_closed_through
			)
		return barriers

	def _validate_closed_period_configuration(self):
		super()._validate_closed_period_configuration()
		self.ensure_one()
		if not self.company_id.l10n_fr_micro_depot_sale_horizon_confirmed:
			raise ValidationError(_(
				"An Accounting Administrator must confirm the permanent URSSAF "
				"depot-sale closing horizon for this company before a depot sale "
				"can be processed."
			))
		return True
