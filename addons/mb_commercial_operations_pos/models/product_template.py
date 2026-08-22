from odoo import api, models
from odoo.fields import Domain


class ProductTemplate(models.Model):
    _inherit = "product.template"

    @api.model
    def _load_pos_data_domain(self, data, config):
        domain = Domain(super()._load_pos_data_domain(data, config))
        if config.mb_commercial_operation_id:
            allowed_templates = config.mb_market_product_ids.product_tmpl_id
            domain &= Domain("is_storable", "=", False) | Domain("id", "in", allowed_templates.ids)
        return domain
