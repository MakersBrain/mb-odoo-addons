from odoo import _, api, models
from odoo.exceptions import ValidationError


class ShopImportBatch(models.Model):
    _inherit = "mb.shop.import.batch"

    @api.constrains("target_location_id")
    def _reject_depot_snapshot_target(self):
        depot_roots = self.env["stock.warehouse"].search([
            ("is_depot", "=", True),
        ]).mapped("view_location_id")
        for batch in self.filtered("target_location_id"):
            if depot_roots and self.env["stock.location"].search_count([
                ("id", "=", batch.target_location_id.id),
                ("id", "child_of", depot_roots.ids),
            ]):
                raise ValidationError(_(
                    "A scraper stock snapshot cannot target a depot warehouse. "
                    "Import into atelier stock, then use a placement transfer."
                ))

    def _create_or_update_product(self, line):
        product = super()._create_or_update_product(line)
        if not line.is_service and (
            not product.is_storable
            or not product.sale_ok
            or product.purchase_ok
            or product.invoice_policy != "delivery"
        ):
            raise ValidationError(_(
                "Imported physical products must remain storable, saleable, "
                "not purchasable, and invoiceable on delivery for depot sales."
            ))
        return product
