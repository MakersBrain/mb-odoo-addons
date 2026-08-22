from . import models


def post_init_hook(env):
    companies = (
        env["res.company"]
        .search([])
        .filtered(
            lambda company: (
                (company.account_fiscal_country_id or company.country_id).code == "FR"
                and company.l10n_fr_micro_tax_regime != "unchanged"
            )
        )
    )
    for company in companies:
        latest_filed = env["l10n.fr.micro.urssaf.declaration"].search(
            [
                ("company_id", "=", company.id),
                ("state", "=", "filed"),
            ],
            order="date_to desc",
            limit=1,
        )
        if latest_filed and (
            not company.l10n_fr_micro_depot_sale_closed_through
            or latest_filed.date_to > company.l10n_fr_micro_depot_sale_closed_through
        ):
            company._l10n_fr_micro_advance_depot_sale_horizon(latest_filed.date_to)
