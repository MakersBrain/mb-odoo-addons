from odoo import models


class CapabilityPolicy(models.Model):
    _inherit = "mb.control.capability.policy"

    def _requires_owned_model_rules(self, module_key):
        if module_key.startswith("shipping-"):
            # Historical shipment journals, labels and tracking remain readable;
            # restriction is an explicit provider mutation gate instead.
            return False
        return super()._requires_owned_model_rules(module_key)


class ResCompany(models.Model):
    _inherit = "res.company"

    @staticmethod
    def _mb_shipping_provider_code(module_key):
        return module_key.removeprefix("shipping-") if module_key.startswith("shipping-") else ""

    def _mb_apply_capability_restriction(self, module_key, reason):
        evidence = super()._mb_apply_capability_restriction(module_key, reason)
        provider_code = self._mb_shipping_provider_code(module_key)
        if not provider_code:
            return evidence
        carriers = self.env["delivery.carrier"].sudo().search([
            ("company_id", "=", self.id), ("mb_provider_code", "=", provider_code)
        ])
        carriers._mb_suspend_webhooks()
        carriers.write({"mb_provider_enabled": False})
        return {
            **evidence,
            "adapter": "odoo_carrier_mutation_gate",
            "provider": provider_code,
            "carriers_disabled": carriers.ids,
            "historical_read_retained": True,
        }

    def _mb_remove_capability_restriction(self, module_key):
        result = super()._mb_remove_capability_restriction(module_key)
        provider_code = self._mb_shipping_provider_code(module_key)
        if provider_code:
            carriers = self.env["delivery.carrier"].sudo().search([
                ("company_id", "=", self.id), ("mb_provider_code", "=", provider_code)
            ])
            carriers.write({"mb_provider_enabled": True})
            resume = getattr(carriers, "_mb_resume_webhooks", None)
            if resume:
                resume()
        return result
