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
        carriers = (
            self.env["delivery.carrier"]
            .sudo()
            .search([("company_id", "=", self.id), ("mb_provider_code", "=", provider_code)])
        )
        # Restriction blocks new purchases but intentionally retains the
        # credential path for cleanup and read-only repair of existing objects.
        # Deleting credentials remains a separate, explicit lifecycle action.
        carriers.with_context(mb_carrier_lifecycle_write=True).write(
            {
                "mb_provider_restricted": True,
            }
        )
        return {
            **evidence,
            "adapter": "odoo_carrier_mutation_gate",
            "provider": provider_code,
            "carriers_restricted": carriers.ids,
            "historical_read_retained": True,
        }

    def _mb_remove_capability_restriction(self, module_key):
        result = super()._mb_remove_capability_restriction(module_key)
        provider_code = self._mb_shipping_provider_code(module_key)
        if provider_code:
            carriers = (
                self.env["delivery.carrier"]
                .sudo()
                .search([("company_id", "=", self.id), ("mb_provider_code", "=", provider_code)])
            )
            carriers.with_context(mb_carrier_lifecycle_write=True).write(
                {
                    "mb_provider_restricted": False,
                    "mb_provider_enabled": True,
                }
            )
        return result
