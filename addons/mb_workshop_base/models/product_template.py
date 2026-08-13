from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    mb_supplier_lot_required = fields.Boolean(
        string="Supplier lot required",
        help="Require this purchased material to retain the supplier's physical "
             "batch in Odoo lot traceability. This is independent from whether a "
             "finished article is intended for food contact.",
    )

    @api.onchange("mb_supplier_lot_required")
    def _onchange_mb_supplier_lot_required(self):
        # A default, not the rule. The constraint below is what actually holds,
        # because an import or an RPC write never fires an onchange.
        if self.mb_supplier_lot_required and self.tracking == "none":
            self.tracking = "lot"

    @api.constrains("mb_supplier_lot_required", "tracking")
    def _check_supplier_lot_tracking(self):
        for template in self:
            if template.mb_supplier_lot_required and template.tracking == "none":
                raise ValidationError(_(
                    "%s requires its supplier batch to be retained and must be "
                    "tracked by lot or serial number.",
                    template.display_name,
                ))
