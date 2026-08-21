from odoo import _, models
from odoo.exceptions import AccessError, UserError


class InventoryCaptureCatalogueCandidate(models.Model):
    _inherit = "mb.inventory.capture.candidate"

    def action_import_reviewed_product(self):
        self.ensure_one()
        if not self.env.user.has_group("stock.group_stock_manager"):
            raise AccessError(_("Only an inventory manager can import a reviewed product."))
        if self.kind != "product" or not self.normalized_value.startswith("catalogue:"):
            raise UserError(_("Only a MakersBrain catalogue candidate can be imported."))
        if self.capture_id.state != "review":
            raise UserError(_("The capture must be in review before importing a product."))
        service = self.env["mb.catalogue.service"].search([("active", "=", True)], limit=1)
        if not service:
            raise UserError(_("No catalogue service is configured."))
        canonical_id = self.normalized_value.removeprefix("catalogue:")
        service.action_import([canonical_id])
        template = self.env["product.template"]._mb_find_by_canonical(canonical_id)
        product = template.product_variant_ids[:1]
        if not product:
            raise UserError(_("The catalogue product was imported without an inventory variant."))
        self.mapped_product_id = product
        self.action_map_reviewed_product()
        return {
            "type": "ir.actions.act_window",
            "res_model": "product.product",
            "res_id": product.id,
            "view_mode": "form",
            "target": "current",
        }
