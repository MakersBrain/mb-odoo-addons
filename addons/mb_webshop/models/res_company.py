from odoo import models


class ResCompany(models.Model):
    _inherit = "res.company"

    def _mb_apply_capability_restriction(self, module_key, reason):
        evidence = super()._mb_apply_capability_restriction(module_key, reason)
        if module_key != "webshop":
            return evidence
        websites = self.env["website"].sudo().search([("company_id", "in", self.ids)])
        websites.write({"mb_webshop_enabled": False})
        return {
            "adapter": "odoo_storefront_gate",
            "storefront_blocked": True,
            "checkout_blocked": True,
            "historical_read_retained": True,
        }

    def _mb_remove_capability_restriction(self, module_key):
        result = super()._mb_remove_capability_restriction(module_key)
        if module_key == "webshop":
            self.env["website"].sudo().search(
                [
                    ("company_id", "in", self.ids),
                ]
            ).write({"mb_webshop_enabled": True})
        return result
