from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    depot_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Depot",
        compute="_compute_depot_location_id",
        store=True,
        help="Set when this transfer places pieces at a depot or brings them back.",
    )
    is_depot_placement = fields.Boolean(
        compute="_compute_depot_location_id",
        store=True,
    )
    mb_depot_sale_date = fields.Date(
        string="Sold on",
        compute="_compute_mb_depot_sale_date",
        inverse="_inverse_mb_depot_sale_date",
        help="Reported sale date for the whole transfer. The date itself lives on "
             "the move lines, so a sheet of reported sales can date each piece "
             "separately; this is the shortcut for the ordinary case where one "
             "transfer stands for one reported sale.",
    )

    @api.depends("move_line_ids.mb_depot_sale_date")
    def _compute_mb_depot_sale_date(self):
        for picking in self:
            dates = set(picking.move_line_ids.mapped("mb_depot_sale_date"))
            # Blank rather than arbitrary when the lines disagree: the transfer
            # has no single sale date to show, and the lines keep theirs.
            picking.mb_depot_sale_date = dates.pop() if len(dates) == 1 else False

    def _inverse_mb_depot_sale_date(self):
        for picking in self:
            picking.move_line_ids.mb_depot_sale_date = picking.mb_depot_sale_date

    @api.depends("location_id.is_depot", "location_dest_id.is_depot")
    def _compute_depot_location_id(self):
        for picking in self:
            if picking.location_dest_id.is_depot:
                picking.depot_location_id = picking.location_dest_id
                picking.is_depot_placement = True
            elif picking.location_id.is_depot:
                picking.depot_location_id = picking.location_id
                picking.is_depot_placement = False
            else:
                picking.depot_location_id = False
                picking.is_depot_placement = False
