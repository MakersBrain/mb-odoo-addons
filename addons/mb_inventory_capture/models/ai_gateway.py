from odoo import api, models


class InventoryCaptureAiGateway(models.AbstractModel):
    _inherit = "mb.ai.gateway"

    @api.model
    def _task_contracts(self):
        contracts = dict(super()._task_contracts())
        contracts["inventory_label"] = {
            "path": "internal/v1/workshops/{workshop_id}/inventory-captures",
            "connect_timeout": 3.05,
            "read_timeout": 10,
        }
        contracts["inventory_product_lookup"] = {
            "path": "internal/v1/workshops/{workshop_id}/inventory-product-lookups",
            "mode": "request",
            "connect_timeout": 3.05,
            "read_timeout": 15,
        }
        return contracts
