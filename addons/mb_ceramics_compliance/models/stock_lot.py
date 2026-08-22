from collections import defaultdict

from odoo import api, fields, models


class StockLot(models.Model):
    _inherit = "stock.lot"

    mb_food_contact = fields.Boolean(related="product_id.mb_food_contact", store=True)
    mb_glaze_lot_ids = fields.Many2many(
        comodel_name="stock.lot",
        relation="mb_lot_glaze_lot_rel",
        column1="lot_id",
        column2="glaze_lot_id",
        string="Glaze lots consumed",
        compute="_compute_mb_glaze_lot_ids",
        help="Derived from the manufacturing order's consumed components. Not "
        "stored: Odoo already keeps this on the move lines, and a copy "
        "would be a second answer to the one question a regulator asks.",
    )
    mb_migration_passed = fields.Boolean(
        string="Migration test passed",
        compute="_compute_mb_migration_passed",
        store=True,
        help="For a glaze lot, whether it has a passing lead and cadmium test.",
    )
    mb_migration_test_ids = fields.One2many(
        comodel_name="mb.migration.test",
        inverse_name="lot_id",
        string="Migration tests",
    )

    @api.depends("mb_migration_test_ids.passed")
    def _compute_mb_migration_passed(self):
        for lot in self:
            lot.mb_migration_passed = any(lot.mb_migration_test_ids.mapped("passed"))

    def _compute_mb_glaze_lot_ids(self):
        glazes_by_lot = defaultdict(lambda: self.env["stock.lot"])
        if self.ids:
            productions = self.env["mrp.production"].search([("lot_producing_ids", "in", self.ids)])
            for production in productions:
                consumed = production._mb_consumed_glaze_lots()
                for lot in production.lot_producing_ids & self:
                    glazes_by_lot[lot.id] |= consumed
        for lot in self:
            lot.mb_glaze_lot_ids = glazes_by_lot.get(lot.id, self.env["stock.lot"])
