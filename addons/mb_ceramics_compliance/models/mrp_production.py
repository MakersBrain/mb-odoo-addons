from odoo import _, models
from odoo.exceptions import UserError

# The families whose lots carry a migration test. Product categories rather than
# a material-type field of our own: a second taxonomy disagrees with the first
# the moment anyone edits either.
#
# The taxonomy is seed data in mb_ceramics_base, independent of any catalogue
# connector or external service, so the gate is always enforceable.
GLAZE_CATEGORY_REFS = (
    "mb_ceramics_base.categ_glaze",
    "mb_ceramics_base.categ_underglaze",
    "mb_ceramics_base.categ_engobe",
)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    def _mb_glaze_categories(self):
        """Categories whose products are surface materials."""
        categories = self.env["product.category"].browse()
        for ref in GLAZE_CATEGORY_REFS:
            categories |= self.env.ref(ref)
        return categories

    def _mb_consumed_glaze_lots(self):
        """Lots of surface material consumed by these orders."""
        categories = self._mb_glaze_categories()
        lots = self.move_raw_ids.move_line_ids.lot_id
        if not categories:
            return self.env["stock.lot"].browse()
        return lots.filtered(
            lambda lot: (
                lot.product_id.categ_id.id in categories.ids
                or lot.product_id.categ_id.parent_id.id in categories.ids
            )
        )

    def _mb_check_food_contact(self):
        for production in self:
            if not production.product_id.mb_food_contact:
                continue
            if production.qty_producing and not production.lot_producing_ids:
                raise UserError(
                    _(
                        "%s produces a food-contact article and needs a lot number "
                        "before it can be marked done.",
                        production.name,
                    )
                )
            untested = production._mb_consumed_glaze_lots().filtered(
                lambda lot: not lot.mb_migration_passed
            )
            if untested:
                raise UserError(
                    _(
                        "These glaze lots have no passing migration test, so %(order)s "
                        "cannot be released as food contact: %(lots)s",
                        order=production.name,
                        lots=", ".join(untested.mapped("name")),
                    )
                )

    def button_mark_done(self):
        self._mb_check_food_contact()
        return super().button_mark_done()
