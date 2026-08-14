import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class PosConfig(models.Model):
    _inherit = "pos.config"

    @api.model
    def _mb_ensure_default_counter(self, company):
        """Give `company` one counter if it has none and can have one.

        Returns the counter that now exists, or an empty recordset when the
        company already had one or the accounting it needs is not there yet.
        The caller is never asked to distinguish the two: both mean there is
        nothing left to do.
        """
        company = company.sudo()
        if self.sudo().search_count(self._check_company_domain(company), limit=1):
            return self.browse()
        if not company.chart_template:
            # No chart, no journals. The kanban says as much: its scenario
            # cards are disabled until a chart of accounts is installed.
            return self.browse()
        bank_journal = self.env["account.journal"].sudo().search([
            ("type", "=", "bank"),
            ("company_id", "in", company.parent_ids.ids),
        ], limit=1)
        if not bank_journal:
            # load_onboarding_retail_scenario raises UserError without one.
            _logger.info(
                "no bank journal for %s; POS counter not seeded", company.display_name
            )
            return self.browse()
        result = (
            self.sudo()
            .with_company(company)
            .with_context(allowed_company_ids=company.ids)
            .load_onboarding_retail_scenario(with_demo_data=False)
        )
        counter = self.browse(result["config_id"])
        _logger.info("seeded POS counter %s for %s", counter.id, company.display_name)
        return counter
