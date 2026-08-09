from odoo import _, fields, models


class L10nFrMicroVatSwitchWizard(models.TransientModel):
	_name = "l10n.fr.micro.vat.switch.wizard"
	_description = "Apply a dated micro-enterprise VAT-regime switch"

	company_id = fields.Many2one(
		"res.company", required=True, default=lambda self: self.env.company,
	)
	effective_date = fields.Date(
		required=True, default=fields.Date.context_today,
		help="Actual date on which the VAT franchise ceased to apply.",
	)

	def action_apply(self):
		self.ensure_one()
		self.company_id.action_l10n_fr_micro_activate_vat(effective_date=self.effective_date)
		return {"type": "ir.actions.client", "tag": "display_notification", "params": {
			"title": _("VAT-liable mode activated"),
			"message": _("The VAT regime is recorded as effective from %s.", self.effective_date),
			"type": "warning", "sticky": True,
		}}
