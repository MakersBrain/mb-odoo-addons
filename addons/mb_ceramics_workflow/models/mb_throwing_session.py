from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class MbThrowingSession(models.Model):
    _name = "mb.throwing.session"
    _description = "Ceramics throwing session"
    _order = "date desc, id desc"

    name = fields.Char(required=True, copy=False, default=lambda self: _("New"))
    date = fields.Date(required=True, default=fields.Date.context_today)
    clay_product_id = fields.Many2one(
        "product.product", required=True, domain=[("is_storable", "=", True)])
    clay_lot_id = fields.Many2one(
        "stock.lot", required=True, domain="[('product_id', '=', clay_product_id)]")
    source_location_id = fields.Many2one(
        "stock.location", required=True, domain=[("usage", "=", "internal")])
    damp_location_id = fields.Many2one(
        "stock.location", required=True, domain=[("usage", "=", "internal")])
    board_id = fields.Many2one(
        "stock.package",
        domain="[('package_type_id.package_use', '=', 'reusable')]",
    )
    note = fields.Text()
    line_ids = fields.One2many(
        "mb.throwing.session.line", "session_id", string="Outputs", copy=True)
    production_ids = fields.One2many(
        "mrp.production", "mb_throwing_session_id", string="Manufacturing orders")
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Recorded"), ("cancel", "Cancelled")],
        required=True,
        default="draft",
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("name", _("New")) == _("New"):
                values["name"] = self.env["ir.sequence"].next_by_code(
                    "mb.throwing.session") or _("New")
        return super().create(vals_list)

    @api.constrains("clay_product_id", "clay_lot_id")
    def _check_clay_lot(self):
        for session in self:
            if session.clay_product_id.tracking != "lot":
                raise ValidationError("Clay used for throwing must be tracked by lot.")
            if session.clay_lot_id.product_id != session.clay_product_id:
                raise ValidationError("The clay lot must belong to the selected clay product.")

    @api.onchange("clay_product_id", "source_location_id")
    def _onchange_clay_product_id(self):
        if not self.clay_product_id or not self.source_location_id:
            return
        if self.clay_lot_id.product_id == self.clay_product_id:
            return
        quants = self.env["stock.quant"].search([
            ("product_id", "=", self.clay_product_id.id),
            ("location_id", "=", self.source_location_id.id),
            ("lot_id", "!=", False),
            ("quantity", ">", 0),
        ])
        lots = quants.lot_id.sorted(key=lambda lot: (lot.create_date, lot.id))
        self.clay_lot_id = next((
            lot for lot in lots
            if self.env["stock.quant"]._get_available_quantity(
                self.clay_product_id,
                self.source_location_id,
                lot_id=lot,
                strict=True,
            ) > 0
        ), False)

    def action_confirm(self):
        for session in self:
            if session.state != "draft":
                continue
            if not session.line_ids:
                raise UserError("Add at least one blank output.")
            for line in session.line_ids:
                line._produce_blank()
            session.state = "done"
        return True


class MbThrowingSessionLine(models.Model):
    _name = "mb.throwing.session.line"
    _description = "Throwing session output"
    _order = "id"

    session_id = fields.Many2one(
        "mb.throwing.session", required=True, ondelete="cascade")
    blank_product_id = fields.Many2one(
        "product.product", required=True, domain=[("is_storable", "=", True)])
    quantity = fields.Float(required=True, digits="Product Unit", default=1.0)
    clay_quantity = fields.Float(required=True, digits="Product Unit", default=1.0)
    bom_id = fields.Many2one("mrp.bom", required=True)
    production_id = fields.Many2one("mrp.production", readonly=True, copy=False)
    blank_lot_id = fields.Many2one("stock.lot", readonly=True, copy=False)

    _positive_quantity = models.Constraint(
        "CHECK(quantity > 0 AND clay_quantity > 0)",
        "Blank and clay quantities must be positive.",
    )

    @api.constrains("blank_product_id", "bom_id")
    def _check_bom_product(self):
        for line in self:
            if line.blank_product_id not in (
                    line.bom_id.product_id | line.bom_id.product_tmpl_id.product_variant_ids):
                raise ValidationError("The bill of materials does not produce this blank.")
            if line.blank_product_id.tracking != "lot":
                raise ValidationError("Reusable blank products must be tracked by lot.")

    def action_print_wip_label(self):
        self.ensure_one()
        if not self.blank_lot_id:
            raise UserError("Record the throwing output before printing its label.")
        return self.blank_lot_id.with_context(
            mb_wip_quantity=self.quantity,
        ).action_mb_print_wip_label()

    def _produce_blank(self):
        self.ensure_one()
        session = self.session_id
        production = self.env["mrp.production"].create({
            "product_id": self.blank_product_id.id,
            "product_qty": self.quantity,
            "product_uom_id": self.blank_product_id.uom_id.id,
            "bom_id": self.bom_id.id,
            "location_src_id": session.source_location_id.id,
            "location_dest_id": session.damp_location_id.id,
            "origin": session.name,
            "company_id": session.company_id.id,
            "mb_workflow_kind": "throwing",
            "mb_throwing_session_id": session.id,
        })
        production.action_confirm()
        clay_move = production.move_raw_ids.filtered(
            lambda move: move.product_id == session.clay_product_id)[:1]
        if not clay_move:
            raise UserError(
                "%s's bill of materials does not consume the selected clay."
                % self.blank_product_id.display_name)
        available = self.env["stock.quant"]._get_available_quantity(
            session.clay_product_id,
            session.source_location_id,
            lot_id=session.clay_lot_id,
            strict=True,
        )
        reserved_from_lot = sum(clay_move.move_line_ids.filtered(
            lambda move_line: move_line.lot_id == session.clay_lot_id
        ).mapped("quantity"))
        if available + reserved_from_lot < self.clay_quantity:
            raise UserError("The selected clay lot does not have enough available stock.")
        production.action_assign()
        clay_move.lot_ids = session.clay_lot_id
        clay_move.quantity = self.clay_quantity
        clay_move.picked = True
        lot = self.env["stock.lot"].create({
            "name": self.env["ir.sequence"].next_by_code("mb.blank.lot"),
            "product_id": self.blank_product_id.id,
            "company_id": session.company_id.id,
        })
        production.lot_producing_ids = [fields.Command.set(lot.ids)]
        production.qty_producing = self.quantity
        production._set_qty_producing()
        production.with_context(
            skip_backorder=True, skip_redirection=True).button_mark_done()
        if production.state != "done":
            raise UserError("The throwing order needs manual manufacturing review.")
        self.write({"production_id": production.id, "blank_lot_id": lot.id})
        return production
