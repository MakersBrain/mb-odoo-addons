import logging

from odoo import models

_logger = logging.getLogger(__name__)


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def try_loading(self, template_code, company, install_demo=False, force_create=True):
        """Seed the workshop counter once the company has journals to book to.

        This is the seam every caller in this repository goes through:
        `res.company._mb_bootstrap_french_accounting` when the control plane
        provisions a workshop, and the `l10n_fr_micro_enterprise` setup wizard
        when someone sets a company up by hand.

        A failure here is swallowed deliberately. The counter is convenience -
        without it the artisan sees Odoo's shop-type screen - while the chart of
        accounts it rides on is not, and must not be rolled back by it.
        """
        result = super().try_loading(
            template_code, company, install_demo=install_demo, force_create=force_create
        )
        if not company:
            return result
        try:
            company_id = company if isinstance(company, int) else company.id
            self.env["pos.config"]._mb_ensure_default_counter(
                self.env["res.company"].browse(company_id)
            )
        except Exception:  # noqa: BLE001 - see the docstring
            _logger.warning("could not seed the POS counter", exc_info=True)
        return result
