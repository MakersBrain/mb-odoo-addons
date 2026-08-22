from odoo import models


class AccountEdiXmlCii(models.AbstractModel):
    _inherit = "account.edi.xml.cii"

    def _export_invoice_constraints(self, invoice, vals):
        constraints = super()._export_invoice_constraints(invoice, vals)
        company = invoice.company_id
        if (
            company.l10n_fr_micro_tax_regime == "franchise"
            and not company.vat
            and company.company_registry
        ):
            # EN16931 BR-CO-26 accepts a seller identifier, legal registration
            # identifier, or VAT identifier. Native CII already exports
            # company_registry as BT-30, but its preflight checks only VAT.
            constraints["seller_identifier"] = None
        return constraints
