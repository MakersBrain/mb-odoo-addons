from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    mb_second_product_tmpl_id = fields.Many2one(
        "product.template",
        string="Seconds product",
        domain="[('is_storable', '=', True), ('id', '!=', id)]",
        help="Sellable product used when inspection downgrades this article.",
    )
    mb_firing_min_temperature = fields.Float(string="Minimum firing temperature")
    mb_firing_max_temperature = fields.Float(string="Maximum firing temperature")
    mb_ceramics_stage = fields.Selection(
        [
            ("green", "Green ware"),
            ("bisque", "Bisque ware"),
            ("finished", "Finished ware"),
        ],
        string="Ceramics stage",
        copy=False,
        index=True,
    )

    @api.constrains("mb_ceramics_stage", "is_storable", "tracking")
    def _check_ceramics_stage_stock_policy(self):
        for product in self.filtered(
            lambda template: template.mb_ceramics_stage in ("green", "bisque")
        ):
            if not product.is_storable:
                raise ValidationError("Green and bisque ware must be storable products.")
            if product.tracking == "none":
                raise ValidationError("Green and bisque ware must be tracked by lot or serial.")

    @api.constrains("mb_second_product_tmpl_id", "tracking")
    def _check_second_tracking(self):
        for product in self.filtered("mb_second_product_tmpl_id"):
            if product.mb_second_product_tmpl_id == product:
                raise ValidationError("A product cannot be its own seconds product.")
            if product.mb_second_product_tmpl_id.tracking != product.tracking:
                raise ValidationError(
                    "The first-quality and seconds products must use the same tracking policy."
                )

    @api.constrains("mb_firing_min_temperature", "mb_firing_max_temperature")
    def _check_firing_range(self):
        for product in self:
            if (product.mb_firing_min_temperature and product.mb_firing_max_temperature
                    and product.mb_firing_min_temperature
                    > product.mb_firing_max_temperature):
                raise ValidationError(
                    "The minimum firing temperature cannot exceed the maximum."
                )
