from collections import defaultdict

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare

from .internal import internal_context, is_internal


class MbDepotSaleReport(models.Model):
    _name = "mb.depot.sale.report"
    _description = "Depositary sale report"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "report_received_on desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
        index=True, tracking=True,
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    depot_warehouse_id = fields.Many2one(
        "stock.warehouse", string="Depot", required=True, tracking=True,
        domain="[('is_depot', '=', True), ('company_id', '=', company_id)]",
    )
    external_reference = fields.Char(
        string="Depot report reference", required=True, index=True, tracking=True,
    )
    report_received_on = fields.Date(
        required=True, default=fields.Date.context_today, tracking=True,
    )
    note = fields.Text()
    create_draft_invoice = fields.Boolean(tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("processed", "Processed"),
            ("reversal_required", "Reversal required"),
            ("reversed", "Reversed"),
        ],
        required=True, default="draft", copy=False, index=True, tracking=True,
    )
    line_ids = fields.One2many(
        "mb.depot.sale.report.line", "report_id", string="Reported sales", copy=True,
    )
    available_product_ids = fields.Many2many(
        "product.product",
        string="Available Products at the Depot",
        compute="_compute_available_product_ids",
        help="Products currently on hand and unreserved at the selected depot.",
    )
    sale_order_ids = fields.One2many("sale.order", "mb_depot_sale_report_id")
    picking_ids = fields.One2many("stock.picking", "mb_depot_sale_report_id")
    invoice_ids = fields.Many2many(
        "account.move",
        "mb_depot_sale_report_account_move_rel",
        "report_id",
        "move_id",
        string="Invoices",
    )
    return_picking_ids = fields.Many2many(
        "stock.picking", compute="_compute_correction_documents",
    )
    credit_note_ids = fields.Many2many(
        "account.move", compute="_compute_correction_documents",
    )
    sale_order_count = fields.Integer(compute="_compute_document_counts")
    picking_count = fields.Integer(compute="_compute_document_counts")
    invoice_count = fields.Integer(compute="_compute_document_counts")
    return_picking_count = fields.Integer(compute="_compute_correction_documents")
    credit_note_count = fields.Integer(compute="_compute_correction_documents")
    closed_through = fields.Date(compute="_compute_closed_period")
    closed_through_source = fields.Char(compute="_compute_closed_period")
    processed_at = fields.Datetime(readonly=True, copy=False)
    processed_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    reversal_reason = fields.Text(
        string="Correction/reversal reason", copy=False, tracking=True,
    )
    allow_partial_reversal = fields.Boolean(
        string="Reason documents a partial correction", copy=False, tracking=True,
    )

    _reference_unique = models.Constraint(
        "unique(company_id, depot_warehouse_id, external_reference)",
        "This depot report reference has already been recorded for this depot.",
    )

    @api.depends("depot_warehouse_id", "external_reference")
    def _compute_name(self):
        for report in self:
            report.name = " / ".join(filter(None, (
                report.depot_warehouse_id.name,
                report.external_reference,
            ))) or _("New depot sale report")

    @api.depends("depot_warehouse_id")
    def _compute_available_product_ids(self):
        for report in self:
            depot = report.depot_warehouse_id
            if not depot:
                report.available_product_ids = False
                continue
            available = [
                product.id
                for product, quantity, reserved in self.env["stock.quant"]._read_group(
                    [("location_id", "child_of", depot.lot_stock_id.id)],
                    ["product_id"],
                    ["quantity:sum", "reserved_quantity:sum"],
                )
                if quantity - reserved > 0
            ]
            report.available_product_ids = [fields.Command.set(available)]

    @api.depends("sale_order_ids", "picking_ids", "invoice_ids")
    def _compute_document_counts(self):
        for report in self:
            report.sale_order_count = len(report.sale_order_ids)
            report.picking_count = len(report.picking_ids)
            report.invoice_count = len(report.invoice_ids)

    @api.depends("picking_ids.move_ids.returned_move_ids", "invoice_ids.reversal_move_ids")
    def _compute_correction_documents(self):
        for report in self:
            report.return_picking_ids = report.picking_ids.move_ids.returned_move_ids.picking_id
            report.credit_note_ids = report.invoice_ids.reversal_move_ids
            report.return_picking_count = len(report.return_picking_ids)
            report.credit_note_count = len(report.credit_note_ids)

    def _get_closed_period_barriers(self):
        """Return irreversible or policy barriers; localisation modules extend it."""
        self.ensure_one()
        company = self.company_id
        barriers = {}
        for field_name, label in (
            ("fiscalyear_lock_date", _("global accounting lock")),
            ("tax_lock_date", _("tax return lock")),
            ("sale_lock_date", _("sales lock")),
            ("hard_lock_date", _("hard accounting lock")),
        ):
            value = company[field_name]
            if value:
                barriers[label] = value
        if company.mb_depot_stock_closed_through:
            barriers[_('depot inventory closing')] = company.mb_depot_stock_closed_through
        return barriers

    @api.depends("company_id")
    def _compute_closed_period(self):
        for report in self:
            barriers = report._get_closed_period_barriers()
            if barriers:
                source, value = max(barriers.items(), key=lambda item: item[1])
                report.closed_through = value
                report.closed_through_source = source
            else:
                report.closed_through = False
                report.closed_through_source = False

    def _company_local_date(self, value):
        self.ensure_one()
        timezone = self.company_id.partner_id.tz or self.env.user.tz or "UTC"
        instant = fields.Datetime.to_datetime(value).replace(tzinfo=pytz.UTC)
        return instant.astimezone(pytz.timezone(timezone)).date()

    def _check_processing_access(self):
        if not self.env.user.has_group("mb_depot.group_depot_sale_manager"):
            raise AccessError(_("Only a Depot Sale Manager can process depot reports."))
        if self.create_draft_invoice and not self.env.user.has_group(
            "account.group_account_invoice"
        ):
            raise AccessError(_("Invoicing access is required to create the draft invoice."))

    def _validate_configuration(self):
        self.ensure_one()
        depot = self.depot_warehouse_id
        if not depot.active or not depot.is_depot:
            raise ValidationError(_("Choose an active depot warehouse."))
        if depot.company_id != self.company_id:
            raise ValidationError(_("The depot must belong to the report company."))
        if depot.mb_depot_legal_structure != "resale":
            raise ValidationError(_(
                "Depot %(depot)s is not configured as Purchase-resale on sale.",
                depot=depot.display_name,
            ))
        if not depot.depot_partner_id or not depot.depot_pricelist_id:
            raise ValidationError(_(
                "Configure the depositary and commission pricelist on %(depot)s.",
                depot=depot.display_name,
            ))
        if not self.line_ids:
            raise ValidationError(_("Add at least one reported sale line."))
        self._validate_closed_period_configuration()

    def _validate_closed_period_configuration(self):
        """Optional compliance modules can require closure setup before processing."""
        self.ensure_one()
        return True

    def _validate_dates(self):
        self.ensure_one()
        today = fields.Date.context_today(self.with_company(self.company_id))
        barriers = self._get_closed_period_barriers()
        barrier_label, barrier = (max(barriers.items(), key=lambda item: item[1])
                                  if barriers else (False, False))
        for line in self.line_ids:
            local_date = self._company_local_date(line.sold_at)
            if local_date > today:
                raise ValidationError(_(
                    "%(product)s is dated %(date)s, which is in the future.",
                    product=line.product_id.display_name, date=local_date,
                ))
            if barrier and local_date <= barrier:
                raise ValidationError(_(
                    "%(product)s is dated %(date)s. Depot sales are permanently "
                    "closed through %(barrier)s (%(source)s).",
                    product=line.product_id.display_name, date=local_date,
                    barrier=barrier, source=barrier_label,
                ))

    def _lock_report_and_quants(self):
        self.ensure_one()
        # Filing URSSAF locks the same company row while advancing its
        # permanent horizon. Whichever transaction gets this lock first has a
        # deterministic order: an already-filed horizon blocks this report,
        # while a report already in progress completes before filing closes it.
        self.env.cr.execute(
            "SELECT id FROM res_company WHERE id = %s FOR UPDATE",
            [self.company_id.id],
        )
        self.company_id.invalidate_recordset()
        self.env.cr.execute(
            "SELECT id FROM mb_depot_sale_report WHERE id = %s FOR UPDATE", [self.id]
        )
        location_ids = self.env["stock.location"].search([
            ("id", "child_of", self.depot_warehouse_id.lot_stock_id.id),
        ]).ids
        self.env.cr.execute(
            """
                SELECT id FROM stock_quant
                 WHERE company_id = %s
                   AND location_id = ANY(%s)
                   AND product_id = ANY(%s)
                 ORDER BY id
                 FOR UPDATE
            """,
            [self.company_id.id, location_ids, self.line_ids.product_id.ids],
        )

    def _validate_historical_stock(self, requested_lines):
        """Apply all reported sales to reconstructed balances at every boundary."""
        depot_location = self.depot_warehouse_id.lot_stock_id
        product = requested_lines.product_id.ensure_one()
        lot = requested_lines[0].lot_id if product.tracking != "none" else False
        quant_domain = [
            ("product_id", "=", product.id),
            ("location_id", "child_of", depot_location.id),
        ]
        if lot:
            quant_domain.append(("lot_id", "=", lot.id))
        current = sum(self.env["stock.quant"].search(quant_domain).mapped("quantity"))
        earliest = min(requested_lines.mapped("sold_at"))
        domain = [
            ("move_id.state", "=", "done"),
            ("product_id", "=", product.id),
            ("date", ">", earliest),
            "|",
            ("location_id", "child_of", depot_location.id),
            ("location_dest_id", "child_of", depot_location.id),
        ]
        if lot:
            domain.append(("lot_id", "=", lot.id))
        move_lines = self.env["stock.move.line"].search(domain)
        boundaries = sorted(set(move_lines.mapped("date") + requested_lines.mapped("sold_at")))
        boundaries.append(fields.Datetime.now())
        for boundary in boundaries:
            later_net_movement = 0.0
            for move_line in move_lines.filtered(
                lambda item, at=boundary: item.date > at
            ):
                incoming = move_line.location_dest_id._child_of(depot_location)
                outgoing = move_line.location_id._child_of(depot_location)
                later_net_movement += (move_line.quantity if incoming else 0.0) - (
                    move_line.quantity if outgoing else 0.0
                )
            reported_outgoing = sum(
                requested_lines.filtered(
                    lambda item, at=boundary: item.sold_at <= at
                ).mapped("quantity")
            )
            balance = current - later_net_movement - reported_outgoing
            if float_compare(balance, 0.0, precision_rounding=product.uom_id.rounding) < 0:
                detail = lot.name if lot else product.display_name
                raise ValidationError(_(
                    "%(item)s was not available at stock boundary %(date)s after "
                    "applying every sale in this report.",
                    item=detail, date=boundary,
                ))

    def _validate_serial_crossing_history(self, line):
        """Require one uninterrupted entry of the exact serial before its sale."""
        depot_location = self.depot_warehouse_id.lot_stock_id
        movements = self.env["stock.move.line"].search([
            ("move_id.state", "=", "done"),
            ("product_id", "=", line.product_id.id),
            ("lot_id", "=", line.lot_id.id),
            ("date", "<=", line.sold_at),
            "|",
            ("location_id", "child_of", depot_location.id),
            ("location_dest_id", "child_of", depot_location.id),
        ], order="date, id")
        entered = False
        balance = 0.0
        for movement in movements:
            incoming = movement.location_dest_id._child_of(depot_location)
            outgoing = movement.location_id._child_of(depot_location)
            if incoming and not outgoing:
                entered = True
                balance += movement.quantity
            elif outgoing and not incoming:
                raise ValidationError(_(
                    "Serial number %(serial)s left %(depot)s before its reported "
                    "sale at %(date)s.",
                    serial=line.lot_id.name,
                    depot=self.depot_warehouse_id.display_name,
                    date=line.sold_at,
                ))
        if not entered or float_compare(
            balance, 1.0, precision_rounding=line.product_uom_id.rounding,
        ) < 0:
            raise ValidationError(_(
                "Serial number %(serial)s had not entered %(depot)s by its "
                "reported sale at %(date)s.",
                serial=line.lot_id.name,
                depot=self.depot_warehouse_id.display_name,
                date=line.sold_at,
            ))

    def _validate_stock(self):
        self.ensure_one()
        depot_location = self.depot_warehouse_id.lot_stock_id
        requested = defaultdict(float)
        serial_ids = set()
        for line in self.line_ids:
            product = line.product_id
            if not product.is_storable or not product.sale_ok:
                raise ValidationError(_(
                    "%(product)s must be a saleable storable product.",
                    product=product.display_name,
                ))
            if product.invoice_policy != "delivery":
                raise ValidationError(_(
                    "%(product)s must invoice Delivered quantities.",
                    product=product.display_name,
                ))
            if product.tracking != "none" and not line.lot_id:
                raise ValidationError(_("Select a lot or serial number for %s.", product.display_name))
            if product.tracking == "none" and line.lot_id:
                raise ValidationError(_("Do not select a lot for untracked product %s.", product.display_name))
            if line.lot_id and line.lot_id.product_id != product:
                raise ValidationError(_("The selected lot does not belong to %s.", product.display_name))
            if product.tracking == "serial":
                if float_compare(line.quantity, 1.0, precision_rounding=line.product_uom_id.rounding):
                    raise ValidationError(_("Serial-tracked product %s must have quantity one.", product.display_name))
                if line.lot_id.id in serial_ids:
                    raise ValidationError(_("Serial number %s appears more than once.", line.lot_id.name))
                serial_ids.add(line.lot_id.id)
                self._validate_serial_crossing_history(line)
            key = (product, line.lot_id if product.tracking != "none" else False)
            requested[key] += line.quantity

        for (product, lot), quantity in requested.items():
            available = self.env["stock.quant"]._get_available_quantity(
                product, depot_location, lot_id=lot, strict=False,
                allow_negative=True,
            )
            if float_compare(available, quantity, precision_rounding=product.uom_id.rounding) < 0:
                detail = lot.name if lot else product.display_name
                raise ValidationError(_(
                    "Only %(available)s of %(item)s is currently unreserved at this depot; %(requested)s was reported.",
                    available=available, item=detail, requested=quantity,
                ))
        historical_groups = defaultdict(lambda: self.env["mb.depot.sale.report.line"])
        for line in self.line_ids:
            key = (
                line.product_id,
                line.lot_id if line.product_id.tracking != "none" else False,
            )
            historical_groups[key] |= line
        for lines in historical_groups.values():
            self._validate_historical_stock(lines)

    def _preflight(self):
        self._validate_configuration()
        self._validate_dates()
        self.line_ids._validate_commercial_evidence()
        self._validate_stock()

    def _order_values(self, sold_at, lines):
        depot = self.depot_warehouse_id
        return {
            "partner_id": depot.depot_partner_id.id,
            "warehouse_id": depot.id,
            "pricelist_id": depot.depot_pricelist_id.id,
            "date_order": sold_at,
            "client_order_ref": self.external_reference,
            "mb_depot_sale_report_id": self.id,
            "mb_depot_effective_date": sold_at,
            "mb_depot_reported_public_total": sum(
                line.reported_public_unit_price * line.quantity for line in lines
            ),
            "mb_depot_reported_net_total": sum(lines.mapped("net_line_amount")),
            "order_line": [fields.Command.create({
                "product_id": line.product_id.id,
                "product_uom_qty": line.quantity,
                "product_uom_id": line.product_uom_id.id,
                "price_unit": line.reported_public_unit_price,
                "discount": line.reported_commission_percentage,
                "mb_depot_sale_report_line_id": line.id,
            }) for line in lines],
        }

    def _assign_exact_report_lines(self, order, report_lines):
        picking = order.picking_ids.filtered(lambda record: record.state != "cancel")
        if len(picking) != 1:
            raise UserError(_("Depot sale %(order)s did not produce exactly one delivery.", order=order.name))
        picking.mb_depot_sale_report_id = self
        picking.mb_depot_effective_date = order.mb_depot_effective_date
        if picking.picking_type_id.warehouse_id != self.depot_warehouse_id \
                or picking.location_id != self.depot_warehouse_id.lot_stock_id \
                or picking.location_dest_id.usage != "customer":
            raise UserError(_("Delivery %s was not sourced from the selected depot.", picking.name))

        picking.action_assign()
        by_report_line = {line.id: line for line in report_lines}
        for sale_line in order.order_line:
            report_line = by_report_line[sale_line.mb_depot_sale_report_line_id.id]
            moves = sale_line.move_ids.filtered(lambda move: move.state != "cancel")
            if not moves:
                raise UserError(_("No stock move was created for %s.", report_line.product_id.display_name))
            moves._do_unreserve()
            moves.move_line_ids.unlink()
            remaining = report_line.quantity
            for move in moves:
                quantity = min(remaining, move.product_uom_qty)
                if quantity <= 0:
                    continue
                previous_lines = move.move_line_ids
                reserved = move._update_reserved_quantity(
                    quantity,
                    picking.location_id,
                    lot_id=report_line.lot_id,
                    strict=False,
                )
                if float_compare(
                    reserved, quantity,
                    precision_rounding=report_line.product_uom_id.rounding,
                ):
                    raise ValidationError(_(
                        "The exact available stock for %(product)s changed while "
                        "the depot report was being processed.",
                        product=report_line.product_id.display_name,
                    ))
                assigned_lines = move.move_line_ids - previous_lines
                assigned_lines.write({
                    "picked": True,
                    "mb_depot_sale_date": self._company_local_date(report_line.sold_at),
                    "mb_depot_sale_report_line_id": report_line.id,
                })
                remaining -= quantity
            if float_compare(remaining, 0.0, precision_rounding=report_line.product_uom_id.rounding):
                raise UserError(_("Could not assign the full reported quantity of %s.", report_line.product_id.display_name))

        self._validate_dates()
        for report_line in report_lines:
            assigned = picking.move_line_ids.filtered(
                lambda item, line=report_line: item.mb_depot_sale_report_line_id == line
            )
            assigned_quantity = sum(assigned.mapped("quantity"))
            if float_compare(
                assigned_quantity, report_line.quantity,
                precision_rounding=report_line.product_uom_id.rounding,
            ) or any(item.lot_id != report_line.lot_id for item in assigned):
                raise UserError(_(
                    "The reserved quantity or lot for %(product)s changed before validation.",
                    product=report_line.product_id.display_name,
                ))
        sold_on = self._company_local_date(order.mb_depot_effective_date)
        result = picking.with_context(
            skip_backorder=True,
            cancel_backorder=True,
            # Odoo 19's stock-account hook uses this date while `_action_done`
            # creates the valuation journal entry. Backdating only `date_done`
            # afterwards would leave accounting in today's period.
            force_period_date=sold_on,
        ).button_validate()
        if isinstance(result, dict):
            raise UserError(_("Delivery %s still requires an interactive validation choice.", picking.name))
        if picking.state != "done":
            raise UserError(_("Delivery %s was not completed.", picking.name))
        # Odoo 19 propagates date_done to done moves and their move lines. Keep
        # that standard propagation, then restore each report line's own time
        # when several timestamps share the same company-local sale date.
        picking.write({"date_done": order.mb_depot_effective_date})
        for move_line in picking.move_line_ids:
            report_line = move_line.mb_depot_sale_report_line_id
            move_line.write({
                "date": report_line.sold_at,
                "mb_depot_sale_date": self._company_local_date(report_line.sold_at),
            })
        return picking

    def action_process(self):
        self.ensure_one()
        self._check_processing_access()
        self._lock_report_and_quants()
        self.invalidate_recordset()
        if self.state != "draft":
            raise UserError(_("Only a draft depot report can be processed."))
        self._preflight()

        grouped = defaultdict(lambda: self.env["mb.depot.sale.report.line"])
        for line in self.line_ids.sorted(lambda record: (record.sold_at, record.id)):
            grouped[self._company_local_date(line.sold_at)] |= line

        orders = self.env["sale.order"]
        pickings = self.env["stock.picking"]
        for _sold_on, lines in grouped.items():
            sold_at = max(lines.mapped("sold_at"))
            order = self.env["sale.order"].create(self._order_values(sold_at, lines))
            order.action_confirm()
            picking = self._assign_exact_report_lines(order, lines)
            orders |= order
            pickings |= picking
            order.message_post(body=_(
                "Created from depot report %(reference)s for %(depot)s, effective %(date)s.",
                reference=self.external_reference, depot=self.depot_warehouse_id.display_name,
                date=sold_at,
            ))
            picking.message_post(body=_(
                "Completed from depot report %(reference)s, effective %(date)s.",
                reference=self.external_reference, date=sold_at,
            ))

        invoice = self.env["account.move"]
        if self.create_draft_invoice:
            invoice = orders._create_invoices(grouped=False)
            if len(invoice) != 1:
                raise UserError(_("The generated depot orders could not be consolidated into one invoice."))
            today = fields.Date.context_today(self.with_company(self.company_id))
            barriers = self._get_closed_period_barriers()
            if barriers and today <= max(barriers.values()):
                raise UserError(_("Today's invoice date is in a closed period."))
            invoice.write({
                "invoice_date": today,
                "mb_depot_sale_report_id": self.id,
                "mb_depot_delivery_date_from": min(
                    self._company_local_date(line.sold_at) for line in self.line_ids
                ),
                "mb_depot_delivery_date_to": max(
                    self._company_local_date(line.sold_at) for line in self.line_ids
                ),
                "ref": self.external_reference,
            })

        self.with_context(**internal_context()).write({
            "state": "processed",
            "processed_at": fields.Datetime.now(),
            "processed_by_id": self.env.user.id,
        })
        return self.action_view_sale_orders()

    def action_start_reversal(self):
        self.ensure_one()
        self._check_processing_access()
        if self.state != "processed":
            raise UserError(_("Only a processed report can start reversal."))
        if not self.reversal_reason:
            raise UserError(_("Document the correction or reversal reason first."))
        self.with_context(**internal_context()).state = "reversal_required"
        return {
            "type": "ir.actions.act_window",
            "name": _("Return depot sale deliveries"),
            "res_model": "stock.picking",
            "view_mode": "list,form",
            "domain": [("id", "in", self.picking_ids.ids)],
        }

    def action_mark_reversed(self):
        self.ensure_one()
        self._check_processing_access()
        if self.state != "reversal_required":
            raise UserError(_("Start the reversal workflow first."))
        draft_invoices = self.invoice_ids.filtered(lambda move: move.state == "draft")
        if draft_invoices:
            raise UserError(_("Cancel every draft invoice before completing the reversal."))
        for invoice in self.invoice_ids.filtered(lambda move: move.state == "posted"):
            posted_credits = invoice.reversal_move_ids.filtered(lambda move: move.state == "posted")
            credited = sum(abs(posted_credits.mapped("amount_total_signed")))
            if not posted_credits or (not self.allow_partial_reversal and float_compare(
                credited, abs(invoice.amount_total_signed),
                precision_rounding=invoice.currency_id.rounding,
            ) < 0):
                raise UserError(_("Post a complete linked credit note for %s first.", invoice.name))
        returned_moves = self.env["stock.move"].search([
            ("origin_returned_move_id", "in", self.picking_ids.move_ids.ids),
            ("state", "=", "done"),
        ])
        total_returned = sum(returned_moves.mapped("quantity"))
        if not total_returned:
            raise UserError(_("Complete at least one linked stock return first."))
        for move in self.picking_ids.move_ids.filtered(lambda item: item.state == "done"):
            move_returns = returned_moves.filtered(
                lambda item, original=move: item.origin_returned_move_id == original
            )
            returned = sum(move_returns.mapped("quantity"))
            if float_compare(returned, move.quantity, precision_rounding=move.product_uom.rounding) > 0:
                raise UserError(_("Returned quantity exceeds the original sale of %s.", move.product_id.display_name))
            if not self.allow_partial_reversal and float_compare(
                returned, move.quantity, precision_rounding=move.product_uom.rounding,
            ) < 0:
                raise UserError(_("Complete the return of %s first.", move.product_id.display_name))
            original_by_lot = defaultdict(float)
            returned_by_lot = defaultdict(float)
            for move_line in move.move_line_ids:
                original_by_lot[move_line.lot_id.id] += move_line.quantity
            for move_line in move_returns.move_line_ids:
                returned_by_lot[move_line.lot_id.id] += move_line.quantity
            for lot_id, quantity in returned_by_lot.items():
                if lot_id not in original_by_lot or float_compare(
                    quantity,
                    original_by_lot[lot_id],
                    precision_rounding=move.product_uom.rounding,
                ) > 0:
                    lot = self.env["stock.lot"].browse(lot_id)
                    raise UserError(_(
                        "Return the original lot or serial for %(product)s; "
                        "%(lot)s was not sold by this report.",
                        product=move.product_id.display_name,
                        lot=lot.display_name if lot else _("untracked stock"),
                    ))
            if not self.allow_partial_reversal:
                for lot_id, quantity in original_by_lot.items():
                    if float_compare(
                        returned_by_lot[lot_id],
                        quantity,
                        precision_rounding=move.product_uom.rounding,
                    ) < 0:
                        lot = self.env["stock.lot"].browse(lot_id)
                        raise UserError(_(
                            "Complete the return of lot or serial %(lot)s for %(product)s.",
                            lot=lot.display_name if lot else _("untracked stock"),
                            product=move.product_id.display_name,
                        ))
        barriers = self._get_closed_period_barriers()
        if barriers:
            source, barrier = max(barriers.items(), key=lambda item: item[1])
            for picking in returned_moves.picking_id:
                if self._company_local_date(picking.date_done) <= barrier:
                    raise UserError(_(
                        "Return %(picking)s is inside the permanent closing horizon "
                        "through %(date)s (%(source)s).",
                        picking=picking.name, date=barrier, source=source,
                    ))
            for credit in self.credit_note_ids.filtered(lambda move: move.state == "posted"):
                if credit.date <= barrier:
                    raise UserError(_(
                        "Credit note %(credit)s is inside the permanent closing horizon "
                        "through %(date)s (%(source)s).",
                        credit=credit.name, date=barrier, source=source,
                    ))
        self.with_context(**internal_context()).state = "reversed"
        return True

    def _document_action(self, model, records, name):
        self.ensure_one()
        action = {
            "type": "ir.actions.act_window", "name": name,
            "res_model": model, "view_mode": "list,form",
            "domain": [("id", "in", records.ids)],
        }
        if len(records) == 1:
            action.update({"view_mode": "form", "res_id": records.id})
        return action

    def action_view_sale_orders(self):
        return self._document_action("sale.order", self.sale_order_ids, _("Sales Orders"))

    def action_view_pickings(self):
        return self._document_action("stock.picking", self.picking_ids, _("Deliveries"))

    def action_view_invoices(self):
        self._check_accounting_document_access()
        return self._document_action("account.move", self.invoice_ids, _("Invoices"))

    def action_view_returns(self):
        return self._document_action("stock.picking", self.return_picking_ids, _("Returns"))

    def action_view_credit_notes(self):
        self._check_accounting_document_access()
        return self._document_action("account.move", self.credit_note_ids, _("Credit Notes"))

    def _check_accounting_document_access(self):
        if not self.env.user.has_group("account.group_account_invoice"):
            raise AccessError(_(
                "Invoicing access is required to open invoices and credit notes."
            ))

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if values.get("state", "draft") != "draft":
                raise UserError(_("A depot report must be created in Draft state."))
            if values.get("create_draft_invoice") and not self.env.user.has_group(
                "account.group_account_invoice"
            ):
                raise AccessError(_(
                    "Invoicing access is required to enable draft invoice creation."
                ))
            if values.get("external_reference"):
                values["external_reference"] = values["external_reference"].strip()
                existing = self.search([
                    ("company_id", "=", values.get("company_id") or self.env.company.id),
                    ("depot_warehouse_id", "=", values.get("depot_warehouse_id")),
                    ("external_reference", "=", values["external_reference"]),
                ], limit=1)
                if existing:
                    raise UserError(_(
                        "Depot report reference %(reference)s already belongs to %(report)s.",
                        reference=values["external_reference"],
                        report=existing._get_html_link(),
                    ))
        return super().create(values_list)

    def write(self, values):
        internal = is_internal(self.env)
        if "state" in values and not internal:
            raise UserError(_("Use the depot report workflow buttons to change its state."))
        if values.get("external_reference"):
            values["external_reference"] = values["external_reference"].strip()
        correction_fields = {"reversal_reason", "allow_partial_reversal"}
        forbidden = set(values) - correction_fields
        if forbidden and self.filtered(lambda report: report.state != "draft") and not internal:
            raise UserError(_("Processed depot reports are immutable; use the reversal workflow."))
        if set(values).intersection(correction_fields) and self.filtered(
            lambda report: report.state == "reversed"
        ) and not internal:
            raise UserError(_("Reversed depot reports are immutable."))
        if "create_draft_invoice" in values and values["create_draft_invoice"] \
                and not self.env.user.has_group("account.group_account_invoice"):
            raise AccessError(_("Invoicing access is required to enable draft invoice creation."))
        return super().write(values)

    def unlink(self):
        if self.filtered(lambda report: report.state != "draft"):
            raise UserError(_("Processed depot reports cannot be deleted."))
        return super().unlink()


class MbDepotSaleReportLine(models.Model):
    _name = "mb.depot.sale.report.line"
    _description = "Depositary sale report line"
    _order = "sold_at, id"

    report_id = fields.Many2one(
        "mb.depot.sale.report", required=True, ondelete="cascade", index=True,
    )
    depot_warehouse_id = fields.Many2one(related="report_id.depot_warehouse_id")
    company_id = fields.Many2one(related="report_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="report_id.currency_id")
    sold_at = fields.Datetime(required=True, index=True)
    product_id = fields.Many2one(
        "product.product", required=True,
        domain="[('id', 'in', available_product_ids), ('sale_ok', '=', True), ('is_storable', '=', True)]",
    )
    available_product_ids = fields.Many2many(
        related="report_id.available_product_ids",
        string="Available Products at the Depot",
    )
    product_uom_id = fields.Many2one(
        "uom.uom", related="product_id.uom_id", store=True, readonly=True,
    )
    lot_id = fields.Many2one(
        "stock.lot", string="Lot/Serial number",
        domain="[('id', 'in', available_lot_ids)]",
    )
    available_lot_ids = fields.Many2many(
        "stock.lot",
        string="Available Lots/Serial Numbers at the Depot",
        compute="_compute_available_lot_ids",
    )
    quantity = fields.Float(required=True, default=1.0, digits="Product Unit of Measure")
    reported_public_unit_price = fields.Monetary(required=True)
    reported_commission_percentage = fields.Float(required=True, digits="Discount")
    net_unit_price = fields.Monetary(compute="_compute_net_amount", store=True)
    net_line_amount = fields.Monetary(compute="_compute_net_amount", store=True)
    external_line_reference = fields.Char(string="Depositary line reference")

    @api.onchange("product_id")
    def _onchange_product_id_commercial_values(self):
        for line in self:
            if not line.product_id:
                continue
            line.reported_public_unit_price = line.product_id.list_price
            line.reported_commission_percentage = (
                line.report_id.depot_warehouse_id.depot_commission
            )

    @api.depends("report_id.depot_warehouse_id", "product_id")
    def _compute_available_lot_ids(self):
        for line in self:
            depot = line.report_id.depot_warehouse_id
            if not depot or not line.product_id:
                line.available_lot_ids = False
                continue
            quants = self.env["stock.quant"].search([
                ("location_id", "child_of", depot.lot_stock_id.id),
                ("product_id", "=", line.product_id.id),
                ("lot_id", "!=", False),
                ("quantity", ">", 0),
            ])
            line.available_lot_ids = quants.filtered(
                lambda quant: quant.quantity - quant.reserved_quantity > 0
            ).lot_id

    @api.depends(
        "quantity", "reported_public_unit_price", "reported_commission_percentage",
    )
    def _compute_net_amount(self):
        for line in self:
            line.net_unit_price = line.reported_public_unit_price * (
                1.0 - line.reported_commission_percentage / 100.0
            )
            line.net_line_amount = line.net_unit_price * line.quantity

    @api.constrains(
        "quantity", "reported_public_unit_price", "reported_commission_percentage",
    )
    def _validate_commercial_evidence(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("Reported quantities must be positive."))
            if line.reported_public_unit_price < 0:
                raise ValidationError(_("Reported public prices cannot be negative."))
            if not 0 <= line.reported_commission_percentage <= 100:
                raise ValidationError(_("Reported commission must be between 0 and 100 percent."))

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            product = self.env["product.product"].browse(values.get("product_id"))
            report = self.env["mb.depot.sale.report"].browse(values.get("report_id"))
            if product:
                values.setdefault("reported_public_unit_price", product.list_price)
            if report:
                values.setdefault(
                    "reported_commission_percentage",
                    report.depot_warehouse_id.depot_commission,
                )
        reports = self.env["mb.depot.sale.report"].browse([
            values.get("report_id") for values in values_list if values.get("report_id")
        ])
        if reports.filtered(lambda report: report.state != "draft"):
            raise UserError(_("Lines can only be added to a draft depot report."))
        return super().create(values_list)

    def write(self, values):
        if self.filtered(lambda line: line.report_id.state != "draft"):
            raise UserError(_("Processed depot report lines are immutable."))
        if values.get("report_id"):
            target = self.env["mb.depot.sale.report"].browse(values["report_id"])
            if target.state != "draft":
                raise UserError(_("Lines can only be moved to a draft depot report."))
        return super().write(values)

    def unlink(self):
        if self.filtered(lambda line: line.report_id.state != "draft"):
            raise UserError(_("Processed depot report lines cannot be deleted."))
        return super().unlink()
