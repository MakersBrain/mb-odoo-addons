from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .internal import internal_context, is_internal


class ResCompany(models.Model):
	_inherit = "res.company"

	l10n_fr_micro_activity_start_date = fields.Date(string="Micro-enterprise activity start")
	l10n_fr_micro_urssaf_tracking_start_date = fields.Date(
		string="URSSAF ledger tracking starts",
		help="Receipts before this period boundary were filed outside Odoo and are not claimed.",
	)
	l10n_fr_micro_urssaf_tracking_start_confirmed = fields.Boolean(
		string="URSSAF tracking boundary confirmed",
		copy=False,
		help="An Accounting Administrator explicitly confirmed the first receipt date covered by Odoo.",
	)
	l10n_fr_micro_urssaf_periodicity = fields.Selection(
		selection=[("monthly", "Monthly"), ("quarterly", "Quarterly")],
		string="URSSAF periodicity",
		default="monthly",
		required=True,
	)
	l10n_fr_micro_versement_from = fields.Date(string="Versement libératoire from")
	l10n_fr_micro_versement_to = fields.Date(string="Versement libératoire through")
	l10n_fr_micro_acre_granted = fields.Boolean(string="ACRE granted")
	l10n_fr_micro_acre_from = fields.Date(string="ACRE from")
	l10n_fr_micro_acre_to = fields.Date(string="ACRE through")
	l10n_fr_micro_acre_coefficient = fields.Float(
		string="ACRE payable coefficient", digits=(5, 4), default=1.0,
		help="Share of the normal social contribution rate that remains payable.",
	)
	l10n_fr_micro_cfp_kind = fields.Selection(
		selection=[
			("artisan", "Artisan"),
			("merchant", "Merchant"),
			("liberal", "Liberal profession"),
		],
		string="Professional training contribution status",
		default="artisan",
	)
	l10n_fr_micro_chamber_kind = fields.Selection(
		selection=[("cma", "CMA"), ("cci", "CCI"), ("none", "Not registered")],
		string="Consular chamber",
		default="cma",
	)
	l10n_fr_micro_chamber_zone = fields.Selection(
		selection=[
			("general", "Metropolitan France — general"),
			("alsace", "Bas-Rhin / Haut-Rhin"),
			("moselle", "Moselle"),
		],
		string="Chamber-tax zone",
		default="general",
	)
	l10n_fr_micro_accounting_responsible_id = fields.Many2one(
		"res.users", string="URSSAF accounting responsible",
		domain=[("share", "=", False)],
	)
	l10n_fr_micro_depot_sale_closed_through = fields.Date(
		string="Depot sales permanently closed through",
		copy=False,
		help="Monotonic horizon advanced whenever an URSSAF declaration is filed. "
			"Depot reports cannot be backdated on or before this date, even if the "
			"declaration is later reset to draft.",
	)
	l10n_fr_micro_depot_sale_horizon_confirmed = fields.Boolean(
		string="Depot sale closing horizon confirmed",
		copy=False,
		help="Accounting has checked that the permanent horizon includes any "
			"historical declarations that were filed and later reopened.",
	)

	_urssaf_configuration_fields = {
		"l10n_fr_micro_activity_start_date", "l10n_fr_micro_urssaf_tracking_start_date",
		"l10n_fr_micro_urssaf_periodicity", "l10n_fr_micro_versement_from",
		"l10n_fr_micro_versement_to", "l10n_fr_micro_acre_granted",
		"l10n_fr_micro_acre_from", "l10n_fr_micro_acre_to",
		"l10n_fr_micro_acre_coefficient", "l10n_fr_micro_cfp_kind",
		"l10n_fr_micro_chamber_kind", "l10n_fr_micro_chamber_zone",
		"l10n_fr_micro_accounting_responsible_id",
		"l10n_fr_micro_urssaf_tracking_start_confirmed",
		"l10n_fr_micro_depot_sale_closed_through",
		"l10n_fr_micro_depot_sale_horizon_confirmed",
	}

	def write(self, values):
		if "l10n_fr_micro_urssaf_tracking_start_date" in values \
				and "l10n_fr_micro_urssaf_tracking_start_confirmed" not in values \
				and not is_internal(self.env):
			values["l10n_fr_micro_urssaf_tracking_start_confirmed"] = False
		if "l10n_fr_micro_depot_sale_closed_through" in values:
			self.env.cr.execute(
				"SELECT id FROM res_company WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
				[self.ids],
			)
			self.invalidate_recordset(["l10n_fr_micro_depot_sale_closed_through"])
			new_horizon = fields.Date.to_date(
				values["l10n_fr_micro_depot_sale_closed_through"]
			) if values["l10n_fr_micro_depot_sale_closed_through"] else False
			for company in self:
				if company.l10n_fr_micro_depot_sale_closed_through and (
					not new_horizon
					or new_horizon < company.l10n_fr_micro_depot_sale_closed_through
				):
					raise ValidationError(_(
						"The permanent URSSAF depot-sale horizon cannot be reduced."
					))
		if self._urssaf_configuration_fields.intersection(values) \
				and not self.env.is_superuser() \
				and not is_internal(self.env) \
				and not self.env.user.has_group("account.group_account_manager"):
			raise AccessError(_("Only an Accounting Administrator can change URSSAF configuration."))
		return super().write(values)

	def _l10n_fr_micro_advance_depot_sale_horizon(self, horizon):
		"""Atomically advance the permanent horizon and never move it backwards."""
		for company in self.sorted("id"):
			company.env.cr.execute(
				"SELECT id FROM res_company WHERE id = %s FOR UPDATE", [company.id]
			)
			company.invalidate_recordset([
				"l10n_fr_micro_depot_sale_closed_through",
			])
			if not company.l10n_fr_micro_depot_sale_closed_through \
					or horizon > company.l10n_fr_micro_depot_sale_closed_through:
				company.with_context(**internal_context()).write({
					"l10n_fr_micro_depot_sale_closed_through": horizon,
				})
		return True

	def action_l10n_fr_micro_confirm_depot_sale_horizon(self):
		if not self.env.user.has_group("account.group_account_manager"):
			raise AccessError(_(
				"Only an Accounting Administrator can confirm the depot-sale horizon."
			))
		self.with_context(**internal_context()).write({
			"l10n_fr_micro_depot_sale_horizon_confirmed": True,
		})
		return True

	@api.constrains(
		"l10n_fr_micro_activity_start_date",
		"l10n_fr_micro_urssaf_tracking_start_date",
		"l10n_fr_micro_versement_from",
		"l10n_fr_micro_versement_to",
		"l10n_fr_micro_acre_granted",
		"l10n_fr_micro_acre_from",
		"l10n_fr_micro_acre_to",
		"l10n_fr_micro_acre_coefficient",
	)
	def _check_urssaf_configuration(self):
		for company in self:
			if company.l10n_fr_micro_activity_start_date and company.l10n_fr_micro_urssaf_tracking_start_date \
					and company.l10n_fr_micro_urssaf_tracking_start_date < company.l10n_fr_micro_activity_start_date:
				raise ValidationError(_("URSSAF tracking cannot start before the activity."))
			for date_from, date_to, label in (
				(company.l10n_fr_micro_versement_from, company.l10n_fr_micro_versement_to, _("Versement libératoire")),
				(company.l10n_fr_micro_acre_from, company.l10n_fr_micro_acre_to, _("ACRE")),
			):
				if date_from and date_to and date_to < date_from:
					raise ValidationError(_("%(label)s end date precedes its start date.", label=label))
			if company.l10n_fr_micro_acre_granted:
				if not company.l10n_fr_micro_acre_from or not company.l10n_fr_micro_acre_to:
					raise ValidationError(_("An ACRE grant requires start and end dates."))
				if not 0 < company.l10n_fr_micro_acre_coefficient <= 1:
					raise ValidationError(_("The ACRE payable coefficient must be above 0 and at most 1."))

	def _l10n_fr_micro_acre_coefficient_on(self, date):
		self.ensure_one()
		if self.l10n_fr_micro_acre_granted \
				and self.l10n_fr_micro_acre_from <= date <= self.l10n_fr_micro_acre_to:
			return self.l10n_fr_micro_acre_coefficient
		return 1.0

	def _l10n_fr_micro_has_versement_on(self, date):
		self.ensure_one()
		return bool(
			self.l10n_fr_micro_versement_from
			and self.l10n_fr_micro_versement_from <= date
			and (not self.l10n_fr_micro_versement_to or date <= self.l10n_fr_micro_versement_to)
		)

	def action_l10n_fr_micro_apply_acre_rule(self):
		for company in self:
			if not company.l10n_fr_micro_activity_start_date:
				raise ValidationError(_("Enter the activity start date before deriving ACRE."))
			rule = self.env["l10n.fr.micro.urssaf.acre.rule"].search([
				("creation_date_from", "<=", company.l10n_fr_micro_activity_start_date),
				"|", ("creation_date_to", "=", False),
				("creation_date_to", ">=", company.l10n_fr_micro_activity_start_date),
			], order="creation_date_from desc", limit=1)
			if not rule:
				raise ValidationError(_("No ACRE creation-date rule applies to this activity start date."))
			start = company.l10n_fr_micro_activity_start_date
			quarter_start = start.replace(month=((start.month - 1) // 3) * 3 + 1, day=1)
			company.write({
				"l10n_fr_micro_acre_granted": True,
				"l10n_fr_micro_acre_from": start,
				"l10n_fr_micro_acre_to": quarter_start + relativedelta(months=12, days=-1),
				"l10n_fr_micro_acre_coefficient": rule.payable_coefficient,
			})
		return True
