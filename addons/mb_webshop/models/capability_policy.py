from odoo import models


class CapabilityPolicy(models.Model):
    _inherit = "mb.control.capability.policy"

    def _requires_owned_model_rules(self, module_key):
        if module_key == "webshop":
            return False
        return super()._requires_owned_model_rules(module_key)
