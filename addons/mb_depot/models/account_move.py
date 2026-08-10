from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    mb_depot_sale_report_id = fields.Many2one(
        "mb.depot.sale.report", string="Depot sale report", copy=False,
        index=True, readonly=True,
    )
    mb_depot_sale_report_ids = fields.Many2many(
        "mb.depot.sale.report",
        "mb_depot_sale_report_account_move_rel",
        "move_id",
        "report_id",
        string="Depot sale reports",
        copy=False,
        readonly=True,
    )
    mb_depot_delivery_date_from = fields.Date(
        string="Depot delivery from", copy=False, readonly=True,
    )
    mb_depot_delivery_date_to = fields.Date(
        string="Depot delivery through", copy=False, readonly=True,
    )
