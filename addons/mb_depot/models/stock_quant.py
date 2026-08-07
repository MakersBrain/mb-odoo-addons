from odoo import api, fields, models


class StockQuant(models.Model):
    _inherit = "stock.quant"

    depot_partner_id = fields.Many2one(
        related="location_id.depot_partner_id",
        string="Depositary",
        store=True,
    )
    depot_days = fields.Integer(
        string="Days held",
        compute="_compute_depot_days",
        help="Days since this piece arrived at its current location. A piece that "
             "has sat unsold for months is the thing worth chasing.",
    )

    @api.depends("in_date")
    def _compute_depot_days(self):
        now = fields.Datetime.now()
        for quant in self:
            quant.depot_days = (now - quant.in_date).days if quant.in_date else 0
