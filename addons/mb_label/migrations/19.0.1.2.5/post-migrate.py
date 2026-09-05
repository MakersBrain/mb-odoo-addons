from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["mb.label.template"]._ensure_company_seed_templates(env["res.company"].search([]))
