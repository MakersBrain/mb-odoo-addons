from odoo import _, api, models
from odoo.tools import formatLang


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.depends("name", "default_code", "product_tmpl_id")
    @api.depends_context(
        "display_default_code",
        "seller_id",
        "company_id",
        "partner_id",
        "formatted_display_name",
        "lang",
        "mb_depot_warehouse_id",
    )
    def _compute_display_name(self):
        super()._compute_display_name()
        depot_id = self.env.context.get("mb_depot_warehouse_id")
        depot = self.env["stock.warehouse"].browse(depot_id).exists()
        if not depot or not depot.is_depot:
            return

        available_by_product = {
            product.id: quantity - reserved
            for product, quantity, reserved in self.env["stock.quant"]._read_group(
                [
                    ("location_id", "child_of", depot.lot_stock_id.id),
                    ("product_id", "in", self.ids),
                ],
                ["product_id"],
                ["quantity:sum", "reserved_quantity:sum"],
            )
        }
        for product in self:
            quantity = formatLang(
                self.env,
                available_by_product.get(product.id, 0.0),
                dp="Product Unit",
            )
            product.display_name = _(
                "%(product)s — %(quantity)s %(uom)s available at %(depot)s",
                product=product.display_name,
                quantity=quantity,
                uom=product.uom_id.display_name,
                depot=depot.display_name,
            )
