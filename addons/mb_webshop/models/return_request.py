from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WebshopReturn(models.Model):
    _name = "mb.webshop.return"
    _description = "Webshop customer return"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "request_date desc, id desc"

    name = fields.Char(required=True, readonly=True, copy=False, default="New", index=True)
    order_id = fields.Many2one(
        "sale.order", required=True, readonly=True, index=True, ondelete="restrict", tracking=True
    )
    partner_id = fields.Many2one(
        related="order_id.partner_id", store=True, readonly=True, index=True
    )
    company_id = fields.Many2one(
        related="order_id.company_id", store=True, readonly=True, index=True
    )
    website_id = fields.Many2one(
        related="order_id.website_id", store=True, readonly=True, index=True
    )
    request_date = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)
    reason = fields.Text(required=True, readonly=True)
    state = fields.Selection(
        [
            ("requested", "Requested"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("received", "Received"),
            ("resolved", "Resolved"),
        ],
        required=True,
        default="requested",
        readonly=True,
        tracking=True,
        index=True,
    )
    resolution = fields.Selection(
        [
            ("refund", "Refund"),
            ("replacement", "Replacement order"),
            ("no_refund", "No refund"),
        ],
        tracking=True,
    )
    decision_note = fields.Text(tracking=True)
    line_ids = fields.One2many(
        "mb.webshop.return.line", "return_id", required=True, copy=False
    )
    return_picking_ids = fields.Many2many(
        "stock.picking", "mb_webshop_return_picking_rel", readonly=True, copy=False
    )
    replacement_order_id = fields.Many2one(
        "sale.order", readonly=True, copy=False, ondelete="restrict"
    )
    refund_move_ids = fields.Many2many(
        "account.move", compute="_compute_refund_move_ids"
    )

    @api.depends("order_id.invoice_ids", "order_id.invoice_ids.state")
    def _compute_refund_move_ids(self):
        for request_record in self:
            invoices = request_record.order_id.invoice_ids
            request_record.refund_move_ids = invoices.filtered(
                lambda move, invoices=invoices: move.move_type == "out_refund"
                and move.state == "posted"
                and move.reversed_entry_id in invoices
            )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("name", "New") == "New":
                values["name"] = self.env["ir.sequence"].next_by_code(
                    "mb.webshop.return"
                ) or "New"
        return super().create(vals_list)

    @api.model
    def create_from_portal(self, order, quantities, reason):
        order.ensure_one()
        self.env.cr.execute("SELECT id FROM sale_order WHERE id = %s FOR UPDATE", [order.id])
        if not order.website_id or order.state not in ("sale", "done"):
            raise ValidationError(_("This order is not eligible for a webshop return."))
        if not reason or not reason.strip():
            raise ValidationError(_("Please tell the workshop why you are returning the item."))
        if len(reason.strip()) > 2000:
            raise ValidationError(_("The return reason is too long."))

        commands = []
        returnable = order._mb_returnable_lines()
        for line_id, quantity in quantities.items():
            line_id = int(line_id)
            line = returnable.filtered(
                lambda candidate, line_id=line_id: candidate.id == line_id
            )
            if not line or quantity <= 0:
                raise ValidationError(_("A return quantity is invalid."))
            available = order._mb_returnable_quantity(line)
            if line.product_uom_id.compare(quantity, available) > 0:
                raise ValidationError(_(
                    "Only %(quantity)s of %(product)s can be returned.",
                    quantity=available,
                    product=line.product_id.display_name,
                ))
            commands.append(fields.Command.create({
                "order_line_id": line.id,
                "quantity": quantity,
            }))
        if not commands:
            raise ValidationError(_("Select at least one item to return."))
        request_record = self.create({
            "order_id": order.id,
            "reason": reason.strip(),
            "line_ids": commands,
        })
        request_record._mb_queue_customer_update()
        return request_record

    def _mb_queue_customer_update(self):
        template = self.env.ref("mb_webshop.mail_template_return_status")
        for request_record in self.filtered("partner_id.email"):
            template.send_mail(
                request_record.id, force_send=False, raise_exception=False
            )

    def action_approve(self):
        for request_record in self:
            if request_record.state != "requested":
                raise ValidationError(_("Only a requested return can be approved."))
            remaining = {
                line.order_line_id.id: line.quantity for line in request_record.line_ids
            }
            pickings = self.env["stock.picking"]
            outbound = request_record.order_id.picking_ids.filtered(
                lambda picking: picking.state == "done"
                and picking.picking_type_code == "outgoing"
            ).sorted("date_done")
            for picking in outbound:
                wizard = self.env["stock.return.picking"].with_context(
                    active_model="stock.picking",
                    active_id=picking.id,
                    active_ids=[picking.id],
                ).create({"picking_id": picking.id})
                selected = False
                for wizard_line in wizard.product_return_moves:
                    sale_line = wizard_line.move_id.sale_line_id
                    wanted = remaining.get(sale_line.id, 0)
                    if wanted <= 0:
                        wizard_line.quantity = 0
                        continue
                    already_returned = sum(
                        returned.product_uom._compute_quantity(
                            returned.product_uom_qty, wizard_line.uom_id
                        )
                        for returned in wizard_line.move_id.returned_move_ids.filtered(
                            lambda move: move.state != "cancel"
                        )
                    )
                    available = max(wizard_line.move_quantity - already_returned, 0)
                    quantity = min(
                        sale_line.product_uom_id._compute_quantity(
                            wanted, wizard_line.uom_id, round=False
                        ),
                        available,
                    )
                    wizard_line.quantity = quantity
                    if quantity > 0:
                        selected = True
                        remaining[sale_line.id] -= wizard_line.uom_id._compute_quantity(
                            quantity, sale_line.product_uom_id, round=False
                        )
                if selected:
                    action = wizard.action_create_returns()
                    return_picking = self.env["stock.picking"].browse(action["res_id"])
                    return_picking.origin = request_record.name
                    pickings |= return_picking

            missing = request_record.line_ids.filtered(
                lambda line, remaining=remaining: line.order_line_id.product_uom_id.compare(
                    remaining[line.order_line_id.id], 0
                ) > 0
            )
            if missing:
                raise ValidationError(_(
                    "The delivered quantity is no longer available for this return."
                ))
            request_record.write({
                "state": "approved",
                "return_picking_ids": [fields.Command.set(pickings.ids)],
            })
            request_record._mb_queue_customer_update()
        return True

    def action_reject(self):
        for request_record in self:
            if request_record.state != "requested":
                raise ValidationError(_("Only a requested return can be rejected."))
            if not request_record.decision_note:
                raise ValidationError(_("Add a decision note before rejecting the return."))
            request_record.state = "rejected"
            request_record._mb_queue_customer_update()
        return True

    def action_mark_received(self):
        for request_record in self:
            if request_record.state != "approved" or not request_record.return_picking_ids:
                raise ValidationError(_("Approve the return before receiving it."))
            if any(picking.state != "done" for picking in request_record.return_picking_ids):
                raise ValidationError(_("Validate every return transfer before marking it received."))
            request_record.state = "received"
            request_record._mb_queue_customer_update()
        return True

    def action_open_credit_note(self):
        self.ensure_one()
        invoices = self.order_id.invoice_ids.filtered(
            lambda move: move.move_type == "out_invoice" and move.state == "posted"
        )
        if not invoices:
            raise ValidationError(_("This order has no posted invoice to refund."))
        action = self.env["ir.actions.actions"]._for_xml_id(
            "account.action_view_account_move_reversal"
        )
        action["context"] = {
            "active_model": "account.move",
            "active_ids": invoices.ids,
            "default_journal_id": invoices[:1].journal_id.id,
        }
        return action

    def action_create_replacement(self):
        self.ensure_one()
        if self.state != "received" or self.resolution != "replacement":
            raise ValidationError(_("Receive the return and select replacement first."))
        if self.replacement_order_id:
            return self.replacement_order_id.get_formview_action()
        replacement = self.order_id.copy({
            "website_id": False,
            "origin": _("Replacement for %(return_name)s", return_name=self.name),
            "order_line": [fields.Command.clear()],
        })
        for line in self.line_ids:
            line.order_line_id.copy({
                "order_id": replacement.id,
                "product_uom_qty": line.quantity,
            })
        self.replacement_order_id = replacement
        return replacement.get_formview_action()

    def action_resolve(self):
        for request_record in self:
            if request_record.state != "received" or not request_record.resolution:
                raise ValidationError(_("Receive the return and choose a resolution first."))
            if request_record.resolution == "refund" and not request_record.refund_move_ids:
                raise ValidationError(_("Post the native credit note before resolving the refund."))
            if request_record.resolution == "replacement" and not request_record.replacement_order_id:
                raise ValidationError(_("Create the replacement order before resolving the return."))
            if request_record.resolution == "no_refund" and not request_record.decision_note:
                raise ValidationError(_("Document why no refund is due."))
            request_record.state = "resolved"
            request_record._mb_queue_customer_update()
        return True


class WebshopReturnLine(models.Model):
    _name = "mb.webshop.return.line"
    _description = "Webshop customer return line"
    _order = "id"

    return_id = fields.Many2one(
        "mb.webshop.return", required=True, ondelete="cascade", index=True
    )
    order_line_id = fields.Many2one(
        "sale.order.line", required=True, readonly=True, ondelete="restrict"
    )
    product_id = fields.Many2one(
        related="order_line_id.product_id", store=True, readonly=True
    )
    quantity = fields.Float(required=True, readonly=True)
    product_uom_id = fields.Many2one(
        related="order_line_id.product_uom_id", store=True, readonly=True
    )

    _return_order_line_unique = models.Constraint(
        "UNIQUE(return_id, order_line_id)",
        "An order line can appear only once in a return request.",
    )

    @api.constrains("quantity")
    def _check_quantity(self):
        for line in self:
            if line.product_uom_id.compare(line.quantity, 0) <= 0:
                raise ValidationError(_("A return quantity must be positive."))

    @api.constrains("order_line_id", "return_id")
    def _check_order_line_matches_return(self):
        for line in self:
            if line.order_line_id.order_id != line.return_id.order_id:
                raise ValidationError(_(
                    "Every return line must belong to the return's sales order."
                ))
