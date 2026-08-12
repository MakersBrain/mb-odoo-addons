from odoo import api, fields, models
from odoo.fields import Command, Domain

# The one2many the picking form edits, and the one the catalog writes into.
CATALOG_LINES = "move_ids"


class StockPicking(models.Model):
    # A transfer has no catalog in Odoo: product.catalog.mixin is opt-in per
    # model and stock.picking does not take it, on the reasoning that a picking
    # is generated from a source document rather than typed. A depot placement
    # is the case that breaks that reasoning - it starts from nothing and names
    # a lot of individual pieces - so the mixin is added here.
    _name = "stock.picking"
    _inherit = ["stock.picking", "product.catalog.mixin"]

    depot_warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Depot",
        compute="_compute_depot_warehouse_id",
        store=True,
        help="Set when this transfer places pieces at a depot or brings them back.",
    )
    is_depot_placement = fields.Boolean(
        compute="_compute_depot_warehouse_id",
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
    mb_depot_sale_report_id = fields.Many2one(
        "mb.depot.sale.report", string="Depot sale report", copy=False,
        index=True, readonly=True,
    )
    mb_depot_effective_date = fields.Datetime(
        string="Effective depot sale date", copy=False, readonly=True,
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

    @api.depends("location_id.warehouse_id.is_depot",
                 "location_dest_id.warehouse_id.is_depot")
    def _compute_depot_warehouse_id(self):
        for picking in self:
            destination = picking.location_dest_id.warehouse_id
            source = picking.location_id.warehouse_id
            if destination.is_depot:
                picking.depot_warehouse_id = destination
                picking.is_depot_placement = True
            elif source.is_depot:
                picking.depot_warehouse_id = source
                picking.is_depot_placement = False
            else:
                picking.depot_warehouse_id = False
                picking.is_depot_placement = False

    # -------------------------------------------------------------------------
    # CATALOG
    #
    # The hooks product.catalog.mixin leaves abstract. mrp.production is the
    # shape followed here rather than sale.order: its components are the same
    # thing a placement is - a price-less list of stock.move records - and the
    # data method they both lean on, stock.move._get_product_catalog_lines_data,
    # already lives in stock.
    # -------------------------------------------------------------------------

    def action_add_from_catalog_depot(self):
        return self.with_context(child_field=CATALOG_LINES).action_add_from_catalog()

    def _get_action_add_from_catalog_extra_context(self):
        context = super()._get_action_add_from_catalog_extra_context()
        # Without this the on-hand badge counts every location in the company,
        # which for a placement is the wrong question: what matters is what is
        # at the source of this transfer and can actually be put in the van.
        if self.location_id:
            context["location"] = self.location_id.id
        return context

    def _default_order_line_values(self, child_field=False):
        return {
            **super()._default_order_line_values(child_field),
            **self.env["stock.move"]._get_product_catalog_lines_data(parent_record=self),
        }

    def _get_product_price_and_data(self, product):
        """Retail price, not cost.

        The consignment note and the statement both value a placement at list price,
        so a catalog quoting standard_price would contradict the paper the
        gallery signs.
        """
        return {"price": product.list_price}

    def _get_product_catalog_order_data(self, products, **kwargs):
        catalog = super()._get_product_catalog_order_data(products, **kwargs)
        for product in products:
            catalog[product.id] |= self._get_product_price_and_data(product)
        return catalog

    def _get_product_catalog_record_lines(self, product_ids, *, child_field=False, **kwargs):
        lines = self[child_field or CATALOG_LINES].filtered(
            lambda move: move.product_id.id in product_ids)
        return lines.grouped(lambda move: move.product_id)

    def _get_product_catalog_domain(self):
        # Storable only: a service or a consumable that is not tracked cannot be
        # standing on a gallery shelf, and the statement counts quants.
        return super()._get_product_catalog_domain() & Domain("is_storable", "=", True)

    def _update_order_line_info(self, product_id, quantity, *, child_field=False, **kwargs):
        field = child_field or CATALOG_LINES
        move = self[field].filtered(lambda m: m.product_id.id == product_id)
        if move:
            if quantity:
                move.product_uom_qty = quantity
            else:
                move.unlink()
        elif quantity > 0:
            self.write({field: [Command.create(
                self._get_new_catalog_line_values(product_id, quantity, **kwargs))]})
        return self.env["product.product"].browse(product_id).list_price

    def _get_new_catalog_line_values(self, product_id, quantity, **kwargs):
        return {
            "product_id": product_id,
            "product_uom_qty": quantity,
            "location_id": self.location_id.id,
            "location_dest_id": self.location_dest_id.id,
            "picking_type_id": self.picking_type_id.id,
            "company_id": self.company_id.id,
        }

    def _is_readonly(self):
        return self.state in ("done", "cancel")

    def _is_display_stock_in_catalog(self):
        return True
