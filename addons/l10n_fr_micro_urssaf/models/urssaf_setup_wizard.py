from odoo import fields, models


class L10nFrMicroUrssafSetupWizard(models.TransientModel):
	_name = "l10n.fr.micro.urssaf.setup.wizard"
	_description = "French micro-enterprise URSSAF setup"

	company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
	activity_start_date = fields.Date(required=True)
	tracking_start_date = fields.Date(required=True)
	periodicity = fields.Selection(
		selection=[("monthly", "Monthly"), ("quarterly", "Quarterly")],
		required=True, default="monthly",
	)
	accounting_responsible_id = fields.Many2one("res.users", required=True, domain=[("share", "=", False)])
	acre_granted = fields.Boolean(string="ACRE granted")

	def action_apply(self):
		self.ensure_one()
		self.company_id.write({
			"l10n_fr_micro_activity_start_date": self.activity_start_date,
			"l10n_fr_micro_urssaf_tracking_start_date": self.tracking_start_date,
			"l10n_fr_micro_urssaf_periodicity": self.periodicity,
			"l10n_fr_micro_accounting_responsible_id": self.accounting_responsible_id.id,
		})
		if self.acre_granted:
			self.company_id.action_l10n_fr_micro_apply_acre_rule()
		else:
			self.company_id.write({
				"l10n_fr_micro_acre_granted": False,
				"l10n_fr_micro_acre_from": False,
				"l10n_fr_micro_acre_to": False,
				"l10n_fr_micro_acre_coefficient": 1.0,
			})
		return {"type": "ir.actions.act_window_close"}
