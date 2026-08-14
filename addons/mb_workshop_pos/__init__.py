from . import models


def post_init_hook(env):
    """Seed a counter for companies whose accounting already exists.

    New workshops get theirs when the chart of accounts is loaded, through the
    `account.chart.template.try_loading` extension. This covers the other
    direction: an existing database that installs the addon after the fact.
    """
    for company in env["res.company"].search([]):
        env["pos.config"]._mb_ensure_default_counter(company)
