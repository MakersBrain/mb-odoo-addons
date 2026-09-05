from odoo import api, models


class ResCompany(models.Model):
    _inherit = "res.company"

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        self.env["mb.label.template"]._ensure_company_seed_templates(companies)
        return companies
