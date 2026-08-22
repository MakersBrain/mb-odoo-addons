from odoo import fields, models


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    mb_depot_sale_date = fields.Date(
        string="Sold on",
        index=True,
        help="The date the depositary reports the piece actually sold.\n\n"
        "The line's own date is when the transfer was validated here. A "
        "gallery that reports March's sales in April would otherwise have "
        "every one of them counted as April business.",
    )
    mb_depot_sale_report_line_id = fields.Many2one(
        "mb.depot.sale.report.line",
        string="Depot report line",
        copy=False,
        readonly=True,
        index=True,
    )
