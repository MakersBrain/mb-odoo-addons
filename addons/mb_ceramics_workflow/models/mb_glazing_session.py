from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


class MbGlazingSession(models.Model):
    _name = "mb.glazing.session"
    _description = "Ceramics glazing session"
    _order = "date desc, id desc"

    name = fields.Char(required=True, copy=False, default=lambda self: _("New"))
    date = fields.Date(required=True, default=fields.Date.context_today)
    board_id = fields.Many2one(
        "stock.package",
        required=True,
        domain="[('package_type_id.package_use', '=', 'reusable')]",
    )
    source_location_id = fields.Many2one(
        "stock.location",
        string="Bisque stock location",
        required=True,
        domain=[("usage", "=", "internal")],
    )
    material_location_id = fields.Many2one(
        "stock.location",
        string="Glaze/material location",
        required=True,
        domain=[("usage", "=", "internal")],
    )
    finished_location_id = fields.Many2one(
        "stock.location", required=True, domain=[("usage", "=", "internal")]
    )
    line_ids = fields.One2many(
        "mb.glazing.session.line", "session_id", string="Selected bisque ware", copy=True
    )
    production_ids = fields.One2many(
        "mrp.production", "mb_glazing_session_id", string="Manufacturing orders"
    )
    state = fields.Selection(
        [("draft", "Draft"), ("progress", "In progress"), ("done", "Done")],
        required=True,
        default="draft",
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("name", _("New")) == _("New"):
                values["name"] = self.env["ir.sequence"].next_by_code(
                    "mb.glazing.session"
                ) or _("New")
        return super().create(vals_list)

    @api.constrains(
        "board_id",
        "source_location_id",
        "material_location_id",
        "finished_location_id",
        "company_id",
    )
    def _check_company(self):
        for session in self:
            records = (
                session.board_id,
                session.source_location_id,
                session.material_location_id,
                session.finished_location_id,
            )
            if any(
                record.company_id and record.company_id != session.company_id
                for record in records
            ):
                raise ValidationError(
                    "The board, locations and glazing session must share a company."
                )

    def action_start(self):
        for session in self:
            if session.state != "draft":
                continue
            if not session.line_ids:
                raise UserError("Select at least one bisque lot.")
            for line in session.line_ids:
                line._start_glazing()
            session.state = "progress"
        return True


class MbGlazingSessionLine(models.Model):
    _name = "mb.glazing.session.line"
    _description = "Glazing session selection"
    _order = "id"

    session_id = fields.Many2one(
        "mb.glazing.session", required=True, ondelete="cascade"
    )
    bisque_product_id = fields.Many2one(
        "product.product",
        required=True,
        domain="[('product_tmpl_id.mb_ceramics_stage', '=', 'bisque')]",
    )
    bisque_lot_id = fields.Many2one(
        "stock.lot", required=True, domain="[('product_id', '=', bisque_product_id)]"
    )
    quantity = fields.Float(required=True, digits="Product Unit", default=1.0)
    available_quantity = fields.Float(
        compute="_compute_available_quantity", digits="Product Unit", readonly=True
    )
    finished_product_id = fields.Many2one(
        "product.product",
        required=True,
        domain="[('product_tmpl_id.mb_ceramics_stage', '=', 'finished')]",
    )
    bom_id = fields.Many2one("mrp.bom", required=True)
    allocation_ids = fields.One2many(
        "mb.glazing.material.allocation",
        "session_line_id",
        string="Tracked glaze and material lots",
        copy=True,
    )
    production_id = fields.Many2one("mrp.production", readonly=True, copy=False)

    _positive_quantity = models.Constraint(
        "CHECK(quantity > 0)", "The selected bisque quantity must be positive."
    )

    @api.depends(
        "bisque_product_id", "bisque_lot_id", "session_id.source_location_id"
    )
    def _compute_available_quantity(self):
        for line in self:
            if not (
                line.bisque_product_id
                and line.bisque_lot_id
                and line.session_id.source_location_id
            ):
                line.available_quantity = 0
                continue
            line.available_quantity = self.env[
                "stock.quant"
            ]._get_available_quantity(
                line.bisque_product_id,
                line.session_id.source_location_id,
                lot_id=line.bisque_lot_id,
                strict=True,
            )

    @api.constrains(
        "bisque_product_id", "bisque_lot_id", "finished_product_id", "bom_id"
    )
    def _check_selection(self):
        for line in self:
            if line.bisque_product_id.product_tmpl_id.mb_ceramics_stage != "bisque":
                raise ValidationError("The selected input must be bisque ware.")
            if line.finished_product_id.product_tmpl_id.mb_ceramics_stage != "finished":
                raise ValidationError("The selected output must be finished ware.")
            if line.bisque_lot_id.product_id != line.bisque_product_id:
                raise ValidationError("The bisque lot belongs to another product.")
            records = (
                line.bisque_lot_id,
                line.bisque_product_id,
                line.finished_product_id,
            )
            if any(
                record.company_id
                and record.company_id != line.session_id.company_id
                for record in records
            ):
                raise ValidationError(
                    "The selected products, lot and glazing session must share a company."
                )
            outputs = line.bom_id.product_id | line.bom_id.product_tmpl_id.product_variant_ids
            if line.finished_product_id not in outputs:
                raise ValidationError("The bill of materials does not produce this article.")
            if line.bisque_product_id not in line.bom_id.bom_line_ids.product_id:
                raise ValidationError("The glazing bill of materials does not consume the bisque ware.")

    @api.onchange("bisque_product_id")
    def _onchange_bisque_product_id(self):
        if self.bisque_lot_id.product_id != self.bisque_product_id:
            self.bisque_lot_id = False

    def _reserve_exact_move_lot(self, move, lot, quantity, location):
        product_quantity = move.product_uom._compute_quantity(
            quantity, move.product_id.uom_id, rounding_method="HALF-UP"
        )
        available = self.env["stock.quant"]._get_available_quantity(
            move.product_id,
            location,
            lot_id=lot,
            strict=True,
        )
        if float_compare(
            available,
            product_quantity,
            precision_rounding=move.product_id.uom_id.rounding,
        ) < 0:
            raise UserError(
                "%s lot %s does not have enough available stock."
                % (move.product_id.display_name, lot.name)
            )
        taken = move._update_reserved_quantity(
            quantity,
            location,
            lot_id=lot,
            strict=True,
        )
        if float_compare(
            taken,
            product_quantity,
            precision_rounding=move.product_id.uom_id.rounding,
        ) != 0:
            raise UserError(
                "The exact %s lot could not be reserved; no substitute was used."
                % move.product_id.display_name
            )

    def _reserve_tracked_materials(self, production, bisque_move):
        tracked_moves = production.move_raw_ids.filtered(
            lambda move: move != bisque_move and move.product_id.tracking != "none"
        )
        unexpected = self.allocation_ids.filtered(
            lambda allocation: allocation.product_id not in tracked_moves.product_id
        )
        if unexpected:
            raise UserError(
                "A material allocation does not match a tracked glazing component."
        )
        for move in tracked_moves:
            move.manual_consumption = True
            allocations = self.allocation_ids.filtered(
                lambda allocation, product=move.product_id:
                allocation.product_id == product
            )
            total = sum(
                allocation.uom_id._compute_quantity(
                    allocation.quantity, move.product_uom, rounding_method="HALF-UP"
                )
                for allocation in allocations
            )
            if float_compare(
                total,
                move.product_uom_qty,
                precision_rounding=move.product_uom.rounding,
            ) != 0:
                raise UserError(
                    "%s allocations must total exactly %s %s."
                    % (
                        move.product_id.display_name,
                        move.product_uom_qty,
                        move.product_uom.display_name,
                    )
                )
            for allocation in allocations:
                quantity = allocation.uom_id._compute_quantity(
                    allocation.quantity, move.product_uom, rounding_method="HALF-UP"
                )
                self._reserve_exact_move_lot(
                    move,
                    allocation.lot_id,
                    quantity,
                    self.session_id.material_location_id,
                )
                allocation.raw_move_id = move

    def _start_glazing(self):
        self.ensure_one()
        if self.production_id:
            return self.production_id
        session = self.session_id
        production = self.env["mrp.production"].create({
            "product_id": self.finished_product_id.id,
            "product_qty": self.quantity,
            "product_uom_id": self.finished_product_id.uom_id.id,
            "bom_id": self.bom_id.id,
            "location_src_id": session.source_location_id.id,
            "location_dest_id": session.finished_location_id.id,
            "origin": session.name,
            "company_id": session.company_id.id,
            "mb_workflow_kind": "glazing",
            "mb_glazing_session_id": session.id,
        })
        production.action_confirm()
        production.move_raw_ids.filtered(
            lambda move: move.state in ("assigned", "partially_available")
        )._do_unreserve()
        bisque_move = production.move_raw_ids.filtered(
            lambda move: move.product_id == self.bisque_product_id
        )[:1]
        if not bisque_move:
            raise UserError(
                "%s's bill of materials does not consume the selected bisque ware."
                % self.finished_product_id.display_name
            )
        (production.move_raw_ids - bisque_move).write({
            "location_id": session.material_location_id.id,
        })
        self._reserve_tracked_materials(production, bisque_move)
        self._reserve_exact_move_lot(
            bisque_move,
            self.bisque_lot_id,
            bisque_move.product_uom_qty,
            session.source_location_id,
        )
        production.move_raw_ids.filtered(
            lambda move: move != bisque_move and move.product_id.tracking == "none"
        )._action_assign()
        bisque_move.picked = True
        bisque_move._action_done(cancel_backorder=True)
        self.env["mb.board.content"].create({
            "board_id": session.board_id.id,
            "production_id": production.id,
            "quantity": self.quantity,
        })
        self.production_id = production
        return production
