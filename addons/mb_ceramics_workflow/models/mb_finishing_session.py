from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class MbFinishingSession(models.Model):
    _name = "mb.finishing.session"
    _inherit = "mb.ceramics.session.mixin"
    _description = "Ceramics finishing session"
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
        check_company=True)
    finished_location_id = fields.Many2one(
        "stock.location", required=True, domain=[("usage", "=", "internal")],
        check_company=True)
    line_ids = fields.One2many(
        "mb.finishing.session.line", "session_id", string="Selected blanks", copy=True)
    production_ids = fields.One2many(
        "mrp.production", "mb_finishing_session_id", string="Manufacturing orders")
    state = fields.Selection(
        [("draft", "Draft"), ("progress", "In progress"), ("done", "Done")],
        required=True,
        default="draft",
    )
    company_id = fields.Many2one(
        "res.company", required=True, index=True,
        default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("name", _("New")) == _("New"):
                values["name"] = self.env["ir.sequence"].next_by_code(
                    "mb.finishing.session") or _("New")
        return super().create(vals_list)

    def action_start(self):
        for session in self:
            if session.state != "draft":
                continue
            if not session.line_ids:
                raise UserError(_("Select at least one damp-box blank."))
            for line in session.line_ids:
                line._start_finishing()
            session.state = "progress"
        return True


class MbFinishingSessionLine(models.Model):
    _name = "mb.finishing.session.line"
    _inherit = "mb.ceramics.session.line.mixin"
    _description = "Finishing session selection"
    _order = "id"
    _check_company_auto = True

    session_id = fields.Many2one(
        "mb.finishing.session", required=True, ondelete="cascade",
        check_company=True)
    blank_product_id = fields.Many2one(
        "product.product", required=True, domain=[("is_storable", "=", True)],
        check_company=True)
    blank_lot_id = fields.Many2one(
        "stock.lot", required=True, domain="[('product_id', '=', blank_product_id)]",
        check_company=True)
    quantity = fields.Float(required=True, digits="Product Unit", default=1.0)
    finished_product_id = fields.Many2one(
        "product.product", required=True, domain=[("is_storable", "=", True)],
        check_company=True)
    bom_id = fields.Many2one("mrp.bom", required=True, check_company=True)
    production_id = fields.Many2one(
        "mrp.production", readonly=True, copy=False, check_company=True)
    company_id = fields.Many2one(
        related="session_id.company_id", store=True, required=True, index=True,
        precompute=True)

    _positive_quantity = models.Constraint(
        "CHECK(quantity > 0)", "The selected blank quantity must be positive.")

    @api.constrains("blank_product_id", "blank_lot_id", "finished_product_id", "bom_id")
    def _check_selection(self):
        for line in self:
            if line.blank_lot_id.product_id != line.blank_product_id:
                raise ValidationError(_("The blank lot belongs to another product."))
            if line.finished_product_id not in (
                    line.bom_id.product_id | line.bom_id.product_tmpl_id.product_variant_ids):
                raise ValidationError(_("The bill of materials does not produce this article."))

    @api.onchange("blank_product_id")
    def _onchange_blank_product_id(self):
        location = self.session_id.source_location_id
        if not self.blank_product_id or not location:
            return
        if self.blank_lot_id.product_id == self.blank_product_id:
            return
        quants = self.env["stock.quant"].search([
            ("product_id", "=", self.blank_product_id.id),
            ("location_id", "=", location.id),
            ("lot_id", "!=", False),
            ("quantity", ">", 0),
        ])
        lots = quants.lot_id.sorted(key=lambda lot: (lot.create_date, lot.id))
        self.blank_lot_id = next((
            lot for lot in lots
            if self.env["stock.quant"]._get_available_quantity(
                self.blank_product_id,
                location,
                lot_id=lot,
                strict=True,
            ) > 0
        ), False)

    def _start_finishing(self):
        self.ensure_one()
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
            "mb_workflow_kind": "finishing",
            "mb_finishing_session_id": session.id,
        })
        production.action_confirm()
        blank_move = production.move_raw_ids.filtered(
            lambda move: move.product_id == self.blank_product_id)[:1]
        if not blank_move:
            raise UserError(_(
                "The bill of materials of %(product)s does not consume the "
                "selected blank.",
                product=self.finished_product_id.display_name,
            ))
        available = self.env["stock.quant"]._get_available_quantity(
            self.blank_product_id,
            session.source_location_id,
            lot_id=self.blank_lot_id,
            strict=True,
        )
        reserved_from_lot = sum(blank_move.move_line_ids.filtered(
            lambda move_line: move_line.lot_id == self.blank_lot_id
        ).mapped("quantity"))
        if available + reserved_from_lot < self.quantity:
            raise UserError(_("The selected blank lot does not have enough available stock."))
        production.action_assign()
        blank_move.lot_ids = self.blank_lot_id
        blank_move.quantity = self.quantity
        blank_move.picked = True
        blank_move._action_done(cancel_backorder=True)
        self.env["mb.board.content"].create({
            "board_id": session.board_id.id,
            "production_id": production.id,
            "quantity": self.quantity,
        })
        self.write({"production_id": production.id})
        return production
