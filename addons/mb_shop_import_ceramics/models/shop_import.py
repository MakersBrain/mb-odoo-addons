from odoo import api, models


class ShopImportBatch(models.Model):
    _inherit = "mb.shop.import.batch"

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if "product_category_id" in fields_list and not values.get("product_category_id"):
            category = self.env.ref("mb_ceramics_base.categ_finished_ceramics")
            values["product_category_id"] = category.id
        return values
