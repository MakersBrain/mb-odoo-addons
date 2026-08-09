from odoo import fields

from . import models


def post_init_hook(env):
	companies = env["res.company"].search([]).filtered(
		lambda company: (company.account_fiscal_country_id or company.country_id).code == "FR"
		and company.l10n_fr_micro_tax_regime != "unchanged"
	)
	for company in companies:
		if not company.l10n_fr_micro_urssaf_tracking_start_date:
			company.l10n_fr_micro_urssaf_tracking_start_date = env.context.get(
				"l10n_fr_micro_urssaf_tracking_start_date"
			) or fields.Date.context_today(company)
