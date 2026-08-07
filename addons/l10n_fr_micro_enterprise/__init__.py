from . import models
from . import wizards


def post_init_hook(env):
	companies = env["res.company"].search([]).filtered(
		lambda company: (company.account_fiscal_country_id or company.country_id).code == "FR"
	)
	companies._l10n_fr_micro_prepare_tax_setup()
