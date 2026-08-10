from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    mb_clay_body_id = fields.Many2one(
        comodel_name="product.product",
        string="Clay body",
        help="The body this piece is made from, as the material product itself "
             "rather than a code, so it joins to the master catalogue.",
    )

    mb_food_contact = fields.Boolean(
        string="Food contact",
        help="Intended to come into contact with foodstuffs. This is the only "
             "reason an article is tracked, and it is what brings 84/500/EEC "
             "migration limits and a declaration of compliance into scope.",
    )
    mb_supplier_lot_required = fields.Boolean(
        string="Supplier lot required",
        help="Require this purchased material to retain the supplier's physical "
             "batch in Odoo lot traceability. This is independent from whether a "
             "finished article is intended for food contact.",
    )
    mb_migration_limit_class = fields.Selection(
        selection=[
            ("cat1", "Non-fillable, or fillable with internal depth up to 25 mm"),
            ("cat2", "Other fillable articles"),
            ("cat3", "Cooking ware; storage vessels over 3 litres"),
        ],
        string="Migration limit class",
        help="Which set of lead and cadmium limits applies under 84/500/EEC. "
             "Named a class rather than a category because categ_id already "
             "means something else, and the two are unrelated.",
    )
    mb_tableware_form = fields.Boolean(
        string="Tableware form",
        help="Shaped like an article for food use. A decorative plate is still "
             "a plate to whoever buys it, so the label has to say what it is not.",
    )
    mb_label_food_warning = fields.Boolean(
        string="Label carries food warning",
        compute="_compute_mb_label_food_warning",
        store=True,
    )

    @api.depends("mb_food_contact", "mb_tableware_form")
    def _compute_mb_label_food_warning(self):
        for template in self:
            template.mb_label_food_warning = (
                template.mb_tableware_form and not template.mb_food_contact)

    @api.onchange("mb_food_contact")
    def _onchange_mb_food_contact(self):
        # A default, not the rule. The constraint below is what actually holds,
        # because an import or an RPC write never fires an onchange.
        if self.mb_food_contact and self.tracking == "none":
            self.tracking = "lot"

    @api.onchange("mb_supplier_lot_required")
    def _onchange_mb_supplier_lot_required(self):
        if self.mb_supplier_lot_required and self.tracking == "none":
            self.tracking = "lot"

    @api.constrains("mb_food_contact", "tracking")
    def _check_food_contact_tracking(self):
        for template in self:
            if template.mb_food_contact and template.tracking == "none":
                raise ValidationError(_(
                    "%s is a food-contact article and must be tracked by lot or "
                    "serial number. Article 17 of Regulation 1935/2004 requires "
                    "the business it was supplied to be identifiable, and an "
                    "untracked product cannot answer that.",
                    template.display_name,
                ))

    @api.constrains("mb_supplier_lot_required", "tracking")
    def _check_supplier_lot_tracking(self):
        for template in self:
            if template.mb_supplier_lot_required and template.tracking == "none":
                raise ValidationError(_(
                    "%s requires its supplier batch to be retained and must be "
                    "tracked by lot or serial number.",
                    template.display_name,
                ))

    @api.constrains("mb_food_contact", "mb_migration_limit_class")
    def _check_migration_limit_class_scope(self):
        for template in self:
            if template.mb_migration_limit_class and not template.mb_food_contact:
                raise ValidationError(_(
                    "%s is not intended for food contact, so 84/500/EEC does not "
                    "reach it and it has no migration limit class.",
                    template.display_name,
                ))
