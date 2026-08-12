from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


class MbBisqueSession(models.Model):
    _name = "mb.bisque.session"
    _inherit = "mb.ceramics.session.mixin"
    _description = "Ceramics bisque preparation session"
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char(required=True, copy=False, default=lambda self: _("New"))
    date = fields.Date(required=True, default=fields.Date.context_today)
    board_id = fields.Many2one(
        "stock.package",
        required=True,
        domain="[('package_type_id.package_use', '=', 'reusable')]",
        check_company=True,
    )
    source_location_id = fields.Many2one(
        "stock.location", required=True, domain=[("usage", "=", "internal")],
        check_company=True,
    )
    bisque_location_id = fields.Many2one(
        "stock.location",
        string="Accepted bisque location",
        required=True,
        domain=[("usage", "=", "internal")],
        check_company=True,
    )
    line_ids = fields.One2many(
        "mb.bisque.session.line", "session_id", string="Selected green ware", copy=True
    )
    production_ids = fields.One2many(
        "mrp.production", "mb_bisque_session_id", string="Manufacturing orders"
    )
    state = fields.Selection(
        [("draft", "Draft"), ("progress", "In progress"), ("done", "Done")],
        required=True,
        default="draft",
    )
    company_id = fields.Many2one(
        "res.company", required=True, index=True,
        default=lambda self: self.env.company
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("name", _("New")) == _("New"):
                values["name"] = self.env["ir.sequence"].next_by_code(
                    "mb.bisque.session"
                ) or _("New")
        return super().create(vals_list)

    @api.constrains(
        "board_id", "source_location_id", "bisque_location_id", "company_id"
    )
    def _check_company_and_locations(self):
        for session in self:
            if session.source_location_id == session.bisque_location_id:
                raise ValidationError(_("Green stock and accepted bisque stock need different locations."))
            records = (
                session.board_id,
                session.source_location_id,
                session.bisque_location_id,
            )
            if any(
                record.company_id and record.company_id != session.company_id
                for record in records
            ):
                raise ValidationError(_("The board, locations and bisque session must share a company."))

    def action_start(self):
        for session in self:
            if session.state != "draft":
                continue
            if not session.line_ids:
                raise UserError(_("Select at least one green-ware lot."))
            for line in session.line_ids:
                line._start_bisque()
            session.state = "progress"
        return True


class MbBisqueSessionLine(models.Model):
    _name = "mb.bisque.session.line"
    _inherit = "mb.ceramics.session.line.mixin"
    _description = "Bisque session selection"
    _order = "id"
    _check_company_auto = True

    session_id = fields.Many2one(
        "mb.bisque.session", required=True, ondelete="cascade",
        check_company=True,
    )
    green_product_id = fields.Many2one(
        "product.product",
        required=True,
        domain="[('product_tmpl_id.mb_ceramics_stage', '=', 'green')]",
        check_company=True,
    )
    green_lot_id = fields.Many2one(
        "stock.lot", required=True, domain="[('product_id', '=', green_product_id)]",
        check_company=True,
    )
    quantity = fields.Float(required=True, digits="Product Unit", default=1.0)
    available_quantity = fields.Float(
        compute="_compute_available_quantity", digits="Product Unit", readonly=True
    )
    bisque_product_id = fields.Many2one(
        "product.product",
        required=True,
        domain="[('product_tmpl_id.mb_ceramics_stage', '=', 'bisque')]",
        check_company=True,
    )
    bom_id = fields.Many2one("mrp.bom", required=True, check_company=True)
    production_id = fields.Many2one(
        "mrp.production", readonly=True, copy=False, check_company=True)
    company_id = fields.Many2one(
        related="session_id.company_id", store=True, required=True, index=True,
        precompute=True)

    _positive_quantity = models.Constraint(
        "CHECK(quantity > 0)", "The selected green-ware quantity must be positive."
    )

    @api.depends(
        "green_product_id", "green_lot_id", "session_id.source_location_id"
    )
    def _compute_available_quantity(self):
        for line in self:
            if not (
                line.green_product_id
                and line.green_lot_id
                and line.session_id.source_location_id
            ):
                line.available_quantity = 0
                continue
            line.available_quantity = self.env[
                "stock.quant"
            ]._get_available_quantity(
                line.green_product_id,
                line.session_id.source_location_id,
                lot_id=line.green_lot_id,
                strict=True,
            )

    @api.constrains(
        "green_product_id", "green_lot_id", "bisque_product_id", "bom_id"
    )
    def _check_selection(self):
        for line in self:
            if line.green_product_id.product_tmpl_id.mb_ceramics_stage != "green":
                raise ValidationError(_("The selected input must be green ware."))
            if line.bisque_product_id.product_tmpl_id.mb_ceramics_stage != "bisque":
                raise ValidationError(_("The selected output must be bisque ware."))
            if line.green_lot_id.product_id != line.green_product_id:
                raise ValidationError(_("The green lot belongs to another product."))
            records = (
                line.green_lot_id,
                line.green_product_id,
                line.bisque_product_id,
            )
            if any(
                record.company_id
                and record.company_id != line.session_id.company_id
                for record in records
            ):
                raise ValidationError(_("The selected products, lot and bisque session must share a company."))
            outputs = line.bom_id.product_id | line.bom_id.product_tmpl_id.product_variant_ids
            if line.bisque_product_id not in outputs:
                raise ValidationError(_("The bill of materials does not produce this bisque ware."))
            if line.green_product_id not in line.bom_id.bom_line_ids.product_id:
                raise ValidationError(_("The bisque bill of materials does not consume the green ware."))

    @api.onchange("green_product_id")
    def _onchange_green_product_id(self):
        if self.green_lot_id.product_id != self.green_product_id:
            self.green_lot_id = False

    def _start_bisque(self):
        self.ensure_one()
        if self.production_id:
            return self.production_id
        session = self.session_id
        production = self.env["mrp.production"].create({
            "product_id": self.bisque_product_id.id,
            "product_qty": self.quantity,
            "product_uom_id": self.bisque_product_id.uom_id.id,
            "bom_id": self.bom_id.id,
            "location_src_id": session.source_location_id.id,
            "location_dest_id": session.bisque_location_id.id,
            "origin": session.name,
            "company_id": session.company_id.id,
            "mb_workflow_kind": "bisque",
            "mb_bisque_session_id": session.id,
        })
        production.action_confirm()
        production.move_raw_ids.filtered(
            lambda move: move.state in ("assigned", "partially_available")
        )._do_unreserve()
        green_move = production.move_raw_ids.filtered(
            lambda move: move.product_id == self.green_product_id
        )[:1]
        if not green_move:
            raise UserError(_(
                "The bill of materials of %(product)s does not consume the "
                "selected green ware.",
                product=self.bisque_product_id.display_name,
            ))
        required = green_move.product_uom_qty
        required_product_uom = green_move.product_uom._compute_quantity(
            required, self.green_product_id.uom_id, rounding_method="HALF-UP"
        )
        available = self.env["stock.quant"]._get_available_quantity(
            self.green_product_id,
            session.source_location_id,
            lot_id=self.green_lot_id,
            strict=True,
        )
        if float_compare(
            available,
            required_product_uom,
            precision_rounding=self.green_product_id.uom_id.rounding,
        ) < 0:
            raise UserError(_("The selected green lot does not have enough available stock."))
        taken = green_move._update_reserved_quantity(
            required,
            session.source_location_id,
            lot_id=self.green_lot_id,
            strict=True,
        )
        if float_compare(
            taken,
            required_product_uom,
            precision_rounding=self.green_product_id.uom_id.rounding,
        ) != 0:
            raise UserError(_("The exact selected green lot could not be reserved."))
        (production.move_raw_ids - green_move)._action_assign()
        green_move.picked = True
        green_move._action_done(cancel_backorder=True)
        self.env["mb.board.content"].create({
            "board_id": session.board_id.id,
            "production_id": production.id,
            "quantity": self.quantity,
        })
        self.production_id = production
        return production
