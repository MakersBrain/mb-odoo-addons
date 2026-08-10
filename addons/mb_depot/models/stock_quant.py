from odoo import api, fields, models


class StockQuant(models.Model):
    _inherit = "stock.quant"

    depot_partner_id = fields.Many2one(
        related="location_id.warehouse_id.depot_partner_id",
        string="Depositary",
        store=True,
    )
    depot_days = fields.Integer(
        string="Days held",
        compute="_compute_depot_days",
        help="Days since this piece arrived at its current location. A piece that "
             "has sat unsold for months is the thing worth chasing.",
    )
    company_currency_id = fields.Many2one(
        related="company_id.currency_id",
        string="Company currency",
        readonly=True,
    )
    depot_retail_unit_price = fields.Monetary(
        string="Retail unit price",
        currency_field="company_currency_id",
        compute="_compute_depot_commercial_values",
        store=True,
        help="Public sales price. This is commercial information, not inventory cost.",
    )
    depot_retail_value = fields.Monetary(
        string="Retail value",
        currency_field="company_currency_id",
        compute="_compute_depot_commercial_values",
        store=True,
        help="On-hand quantity valued at the public sales price, independently "
             "from Odoo's accounting inventory valuation.",
    )
    depot_expected_net_value = fields.Monetary(
        string="Expected net",
        currency_field="company_currency_id",
        compute="_compute_depot_commercial_values",
        store=True,
        help="Expected proceeds if the on-hand quantity sells at the public "
             "price, after the depot's recorded commission.",
    )

    @api.depends(
        "quantity",
        "product_id.list_price",
        "location_id.warehouse_id.depot_commission",
    )
    def _compute_depot_commercial_values(self):
        for quant in self:
            unit_price = quant.product_id.list_price
            retail_value = quant.quantity * unit_price
            commission = quant.location_id.warehouse_id.depot_commission
            quant.depot_retail_unit_price = unit_price
            quant.depot_retail_value = retail_value
            quant.depot_expected_net_value = retail_value * (1.0 - commission / 100.0)

    @api.depends("in_date")
    def _compute_depot_days(self):
        now = fields.Datetime.now()
        for quant in self:
            quant.depot_days = (now - quant.in_date).days if quant.in_date else 0
