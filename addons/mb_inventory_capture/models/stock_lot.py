from odoo import fields, models


class StockLot(models.Model):
    _inherit = "stock.lot"

    mb_supplier_lot_origin = fields.Selection(
        [("supplier", "Supplier package"), ("opening_balance", "Opening balance")],
        string="Supplier-lot origin",
        copy=False,
        index=True,
    )
