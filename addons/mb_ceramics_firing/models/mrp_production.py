from odoo import _, models
from odoo.exceptions import UserError


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    def mb_assign_lot(self, lot):
        """Pin the lot at kiln loading, so it exists before cooling ends.

        This is the whole of what OCA's mrp_restrict_lot did, adapted to Odoo 19
        where `lot_producing_id` became the Many2many `lot_producing_ids`. The
        point is timing rather than mechanism: a label is printed when the load
        comes out of cooling, and the lot has to exist by then.
        """
        self.ensure_one()
        if lot.product_id != self.product_id:
            raise UserError(
                _(
                    "Lot %(lot)s belongs to %(other)s, not to %(wanted)s.",
                    lot=lot.name,
                    other=lot.product_id.display_name,
                    wanted=self.product_id.display_name,
                )
            )
        if lot not in self.lot_producing_ids:
            self.lot_producing_ids = [(4, lot.id)]
        return lot
