from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

OPEN_MOVE_STATES = ("waiting", "confirmed", "partially_available", "assigned")


class MbCommercialOperation(models.Model):
    _inherit = "mb.commercial.operation"

    source_warehouse_id = fields.Many2one(
        "stock.warehouse",
        check_company=True,
        tracking=True,
    )
    source_location_id = fields.Many2one(
        "stock.location",
        check_company=True,
        domain="[('usage', '=', 'internal'), ('company_id', '=', company_id)]",
        tracking=True,
    )
    market_location_id = fields.Many2one(
        "stock.location",
        check_company=True,
        copy=False,
        domain="[('usage', '=', 'internal'), ('company_id', '=', company_id)]",
        tracking=True,
    )
    preparation_picking_id = fields.Many2one(
        "stock.picking",
        check_company=True,
        copy=False,
        ondelete="restrict",
    )
    return_picking_ids = fields.One2many(
        "stock.picking",
        "mb_commercial_operation_id",
        domain=[("mb_commercial_stock_role", "=", "return")],
        string="Return Transfers",
    )
    stock_reconciled = fields.Boolean(compute="_compute_stock_status")
    stock_discrepancy_count = fields.Integer(compute="_compute_stock_status")
    stock_reconciliation_note = fields.Text(compute="_compute_stock_status")
    stock_closed = fields.Boolean(copy=False, tracking=True)
    stock_close_date = fields.Date(copy=False, readonly=True)
    stock_close_user_id = fields.Many2one("res.users", copy=False, readonly=True)
    has_supply_plan = fields.Boolean(compute="_compute_has_supply_plan")
    stock_required_qty = fields.Float(compute="_compute_stock_overview")
    stock_forecast_qty = fields.Float(compute="_compute_stock_overview")
    stock_shortage_qty = fields.Float(compute="_compute_stock_overview")
    stock_readiness = fields.Selection(
        [("not_checked", "Not Checked"), ("shortage", "Shortage"), ("ready", "Ready")],
        compute="_compute_stock_overview",
    )

    def _get_operation_profitability_items(self):
        self.ensure_one()
        items = super()._get_operation_profitability_items()
        if not self.id:
            return items
        pickings = self.env["stock.picking"].search(
            [
                ("mb_commercial_operation_id", "=", self.id),
                ("state", "=", "done"),
            ]
        )
        for line in pickings.move_ids.analytic_account_line_ids:
            items.append(
                {
                    "model": line._name,
                    "res_id": line.id,
                    "component": "cost",
                    "date": line.date,
                    "amount": -line.amount,
                    "currency": self.currency_id,
                }
            )
        return items

    @api.depends("stock_plan_line_ids.supply_method")
    def _compute_has_supply_plan(self):
        for operation in self:
            operation.has_supply_plan = any(
                method not in ("manual", "stock")
                for method in operation.stock_plan_line_ids.mapped("supply_method")
            )

    @api.depends(
        "stock_plan_line_ids.required_qty",
        "stock_plan_line_ids.forecast_available",
        "stock_plan_line_ids.shortage_qty",
        "stock_plan_line_ids.availability_calculated_at",
    )
    def _compute_stock_overview(self):
        for operation in self:
            targets = operation.stock_plan_line_ids.filtered(
                lambda line: line.target_type == "product"
            )
            operation.stock_required_qty = sum(targets.mapped("required_qty"))
            operation.stock_forecast_qty = sum(targets.mapped("forecast_available"))
            operation.stock_shortage_qty = sum(targets.mapped("shortage_qty"))
            if not targets or not all(targets.mapped("availability_calculated_at")):
                operation.stock_readiness = "not_checked"
            elif operation.stock_shortage_qty:
                operation.stock_readiness = "shortage"
            else:
                operation.stock_readiness = "ready"

    def write(self, vals):
        allocation_fields = {
            "source_warehouse_id",
            "source_location_id",
            "market_location_id",
            "preparation_picking_id",
        }
        if allocation_fields.intersection(vals) and self.filtered("stock_closed"):
            raise UserError(_("Reopen stock reconciliation before changing stock evidence links."))
        return super().write(vals)

    @api.depends(
        "preparation_picking_id.state",
        "preparation_picking_id.move_ids.quantity",
        "return_picking_ids.state",
        "return_picking_ids.move_ids.quantity",
        "market_location_id",
    )
    def _compute_stock_status(self):
        for operation in self:
            discrepancies = operation._stock_discrepancies()
            operation.stock_discrepancy_count = len(discrepancies)
            operation.stock_reconciled = (
                bool(operation.preparation_picking_id) and not discrepancies
            )
            operation.stock_reconciliation_note = "\n".join(discrepancies) or _(
                "Prepared, sold, scrapped, returned, and remaining stock reconcile."
            )

    def _move_line_buckets(self, move_lines):
        buckets = defaultdict(float)
        for line in move_lines:
            key = (line.product_id.id, line.lot_id.id or 0)
            buckets[key] += line.quantity_product_uom
        return buckets

    def _stock_discrepancies(self):
        self.ensure_one()
        if not self.preparation_picking_id or self.preparation_picking_id.state != "done":
            return [_("The preparation transfer is not completed.")]
        if not self.market_location_id:
            return [_("No market stock location is configured.")]

        market_domain = [("location_id", "child_of", self.market_location_id.id)]
        prepared = self._move_line_buckets(
            self.preparation_picking_id.move_line_ids.filtered(
                lambda line: line.move_id.state == "done"
            )
        )
        returned = self._move_line_buckets(
            self.return_picking_ids.filtered(lambda picking: picking.state == "done").move_line_ids
        )
        outbound_lines = self.env["stock.move.line"].search(
            [
                *market_domain,
                ("state", "=", "done"),
                ("picking_id", "not in", self.return_picking_ids.ids),
            ]
        )
        sold = self._move_line_buckets(
            outbound_lines.filtered(lambda line: line.location_dest_id.usage == "customer")
        )
        scrapped = self._move_line_buckets(
            outbound_lines.filtered(lambda line: line.move_id.scrap_id)
        )

        remaining = defaultdict(float)
        quants = self.env["stock.quant"].search(
            [
                ("location_id", "child_of", self.market_location_id.id),
                ("quantity", "!=", 0),
            ]
        )
        for quant in quants:
            remaining[(quant.product_id.id, quant.lot_id.id or 0)] += quant.quantity

        messages = []
        keys = set(prepared) | set(returned) | set(sold) | set(scrapped) | set(remaining)
        for product_id, lot_id in sorted(keys):
            difference = prepared[(product_id, lot_id)] - (
                returned[(product_id, lot_id)]
                + sold[(product_id, lot_id)]
                + scrapped[(product_id, lot_id)]
                + remaining[(product_id, lot_id)]
            )
            product = self.env["product.product"].browse(product_id)
            if not float_is_zero(difference, precision_rounding=product.uom_id.rounding):
                lot = self.env["stock.lot"].browse(lot_id)
                messages.append(
                    _(
                        "%(product)s%(lot)s differs by %(quantity)s %(uom)s.",
                        product=product.display_name,
                        lot=(" / " + lot.name) if lot else "",
                        quantity=difference,
                        uom=product.uom_id.display_name,
                    )
                )
        return messages

    def _ensure_market_location(self):
        self.ensure_one()
        if self.market_location_id:
            return self.market_location_id
        warehouse = self.source_warehouse_id
        if not warehouse:
            raise ValidationError(_("Choose a source warehouse first."))
        location = self.env["stock.location"].create(
            {
                "name": self.name,
                "location_id": warehouse.lot_stock_id.id,
                "usage": "internal",
                "company_id": self.company_id.id,
            }
        )
        self.market_location_id = location
        return location

    def action_check_stock_availability(self):
        lines = self.stock_plan_line_ids.filtered(lambda line: line.target_type == "product")
        if not lines:
            raise UserError(_("Add at least one exact-product stock target."))
        lines._refresh_availability()
        return True

    def action_prepare_supply(self):
        for operation in self:
            if operation.state not in ("approved", "scheduled"):
                raise UserError(_("Approve the operation before preparing supply."))
            for line in operation.stock_plan_line_ids:
                line._prepare_supply()
        return True

    def action_refresh_supply_status(self):
        self.stock_plan_line_ids._update_supply_readiness()
        return True

    def action_view_stock_pickings(self):
        self.ensure_one()
        pickings = self.preparation_picking_id | self.return_picking_ids
        action = self.env["ir.actions.actions"]._for_xml_id("stock.action_picking_tree_all")
        action["domain"] = [("id", "in", pickings.ids)]
        action["context"] = {"create": False}
        return action

    def action_prepare_market_stock(self):
        self.ensure_one()
        if self.state not in ("approved", "scheduled"):
            raise UserError(_("Approve the operation before preparing market stock."))
        if self.preparation_picking_id:
            return self._picking_action(self.preparation_picking_id)
        warehouse = self.source_warehouse_id
        if not warehouse:
            raise ValidationError(_("Choose a source warehouse first."))
        source = self.source_location_id or warehouse.lot_stock_id
        destination = self._ensure_market_location()
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": warehouse.int_type_id.id,
                "location_id": source.id,
                "location_dest_id": destination.id,
                "scheduled_date": self.stock_preparation_deadline or self.planned_start,
                "origin": self.name,
                "mb_commercial_operation_id": self.id,
                "mb_commercial_stock_role": "preparation",
            }
        )
        move_model = self.env["stock.move"]
        for line in self.stock_plan_line_ids.sorted("priority"):
            allocations = line.allocation_ids
            if line.target_type == "product":
                if line.product_id.tracking != "none":
                    allocated = sum(allocations.mapped("quantity"))
                    if (
                        float_compare(
                            allocated,
                            line.required_qty,
                            precision_rounding=line.product_id.uom_id.rounding,
                        )
                        != 0
                    ):
                        raise ValidationError(
                            _(
                                "Select exactly %(quantity)s tracked units for %(product)s.",
                                quantity=line.required_qty,
                                product=line.product_id.display_name,
                            )
                        )
                products_and_quantities = (
                    [(line.product_id, line.required_qty)]
                    if not allocations
                    else [
                        (allocation.product_id, allocation.quantity) for allocation in allocations
                    ]
                )
            else:
                products_and_quantities = [
                    (allocation.product_id, allocation.quantity) for allocation in allocations
                ]
            for product, quantity in products_and_quantities:
                move = move_model.create(
                    {
                        "product_id": product.id,
                        "product_uom_qty": quantity,
                        "product_uom": product.uom_id.id,
                        "location_id": source.id,
                        "location_dest_id": destination.id,
                        "picking_id": picking.id,
                        "date": self.stock_preparation_deadline or self.planned_start,
                        "mb_market_stock_plan_line_id": line.id,
                    }
                )
                matching = allocations.filtered(
                    lambda allocation, p=product: allocation.product_id == p
                )
                if matching:
                    move.lot_ids = matching.lot_id
        if not picking.move_ids:
            picking.unlink()
            raise ValidationError(_("No concrete stock is selected for preparation."))
        picking.action_confirm()
        picking.action_assign()
        fully_reserved = all(
            float_compare(
                move.quantity,
                move.product_uom._compute_quantity(move.product_uom_qty, move.product_id.uom_id),
                precision_rounding=move.product_id.uom_id.rounding,
            )
            >= 0
            for move in picking.move_ids
        )
        if not fully_reserved:
            raise ValidationError(
                _(
                    "The selected market stock is not fully available. Resolve existing reservations or reduce the selection."
                )
            )
        self.preparation_picking_id = picking
        return self._picking_action(picking)

    def action_prepare_market_return(self):
        self.ensure_one()
        if not self.market_location_id or not self.preparation_picking_id:
            raise UserError(_("Prepare market stock before creating a return transfer."))
        existing = self.return_picking_ids.filtered(
            lambda picking: picking.state not in ("done", "cancel")
        )[:1]
        if existing:
            return self._picking_action(existing)
        warehouse = self.source_warehouse_id
        destination = self.source_location_id or warehouse.lot_stock_id
        quants = self.env["stock.quant"].search(
            [
                ("location_id", "child_of", self.market_location_id.id),
                ("quantity", ">", 0),
            ]
        )
        if not quants:
            raise UserError(_("There is no stock left at the market location to return."))
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": warehouse.int_type_id.id,
                "location_id": self.market_location_id.id,
                "location_dest_id": destination.id,
                "scheduled_date": self.actual_end or fields.Datetime.now(),
                "origin": _("Return: %(operation)s", operation=self.name),
                "mb_commercial_operation_id": self.id,
                "mb_commercial_stock_role": "return",
            }
        )
        for quant in quants:
            move = self.env["stock.move"].create(
                {
                    "product_id": quant.product_id.id,
                    "product_uom_qty": quant.quantity,
                    "product_uom": quant.product_id.uom_id.id,
                    "location_id": quant.location_id.id,
                    "location_dest_id": destination.id,
                    "picking_id": picking.id,
                }
            )
            if quant.lot_id:
                move.lot_ids = quant.lot_id
        picking.action_confirm()
        picking.action_assign()
        return self._picking_action(picking)

    def action_stock_close(self):
        for operation in self:
            if operation.state not in ("done", "financially_closed"):
                raise UserError(_("Complete the operation before closing its stock."))
            discrepancies = operation._stock_discrepancies()
            if discrepancies:
                discrepancy_message = "\n".join(discrepancies)
                raise ValidationError(discrepancy_message)
            operation.write(
                {
                    "stock_closed": True,
                    "stock_close_date": fields.Date.context_today(operation),
                    "stock_close_user_id": self.env.user.id,
                }
            )
        return True

    def action_reopen_stock(self):
        if not self.env.user.has_group(
            "mb_commercial_operations.group_commercial_operations_manager"
        ):
            raise UserError(
                _("Only a Commercial Operations Manager can reopen stock reconciliation.")
            )
        self.write({"stock_closed": False, "stock_close_date": False, "stock_close_user_id": False})
        return True

    def _picking_action(self, picking):
        return {
            "type": "ir.actions.act_window",
            "name": picking.display_name,
            "res_model": "stock.picking",
            "view_mode": "form",
            "res_id": picking.id,
        }

    def action_cancel(self):
        for picking in (self.preparation_picking_id | self.return_picking_ids).filtered(
            lambda record: record.state not in ("done", "cancel")
        ):
            picking.action_cancel()
        return super().action_cancel()


class MbMarketStockPlanLine(models.Model):
    _inherit = "mb.market.stock.plan.line"

    supply_method = fields.Selection(
        selection_add=[("stock", "Take From Stock")], ondelete={"stock": "set default"}
    )
    source_warehouse_id = fields.Many2one(
        "stock.warehouse",
        check_company=True,
        related="operation_id.source_warehouse_id",
        readonly=True,
    )
    source_location_id = fields.Many2one(
        "stock.location",
        check_company=True,
        related="operation_id.source_location_id",
        readonly=True,
    )
    allocation_ids = fields.One2many(
        "mb.market.stock.allocation",
        "plan_line_id",
        string="Concrete Stock",
    )
    stock_closed = fields.Boolean(related="operation_id.stock_closed")
    on_hand_now = fields.Float(readonly=True, copy=False)
    reserved_now = fields.Float(readonly=True, copy=False)
    incoming_before_cutoff = fields.Float(readonly=True, copy=False)
    outgoing_before_cutoff = fields.Float(readonly=True, copy=False)
    forecast_available = fields.Float(readonly=True, copy=False)
    shortage_qty = fields.Float(readonly=True, copy=False)
    availability_calculated_at = fields.Datetime(readonly=True, copy=False)

    def _refresh_availability(self):
        for line in self:
            if line.target_type != "product" or not line.product_id:
                continue
            operation = line.operation_id
            warehouse = operation.source_warehouse_id
            if not warehouse:
                raise ValidationError(
                    _(
                        "Choose a source warehouse on %(operation)s.",
                        operation=operation.display_name,
                    )
                )
            location = operation.source_location_id or warehouse.lot_stock_id
            cutoff = operation.stock_preparation_deadline or operation.planned_start
            quants = self.env["stock.quant"].search(
                [
                    ("product_id", "=", line.product_id.id),
                    ("location_id", "child_of", location.id),
                ]
            )
            on_hand = sum(quants.mapped("quantity"))
            reserved = sum(quants.mapped("reserved_quantity"))
            candidates = self.env["stock.move"].search(
                [
                    ("product_id", "=", line.product_id.id),
                    ("company_id", "=", operation.company_id.id),
                    ("state", "in", OPEN_MOVE_STATES),
                    ("date", "<=", cutoff),
                    "|",
                    ("location_id", "child_of", location.id),
                    ("location_dest_id", "child_of", location.id),
                ]
            )
            incoming = sum(
                move.product_uom._compute_quantity(move.product_uom_qty, line.product_id.uom_id)
                for move in candidates
                if move.location_dest_id._child_of(location)
                and not move.location_id._child_of(location)
            )
            outgoing = sum(
                move.product_uom._compute_quantity(move.product_uom_qty, line.product_id.uom_id)
                for move in candidates
                if move.location_id._child_of(location)
                and not move.location_dest_id._child_of(location)
            )
            forecast = on_hand + incoming - outgoing
            line.with_context(mb_stock_refresh=True).write(
                {
                    "on_hand_now": on_hand,
                    "reserved_now": reserved,
                    "incoming_before_cutoff": incoming,
                    "outgoing_before_cutoff": outgoing,
                    "forecast_available": forecast,
                    "shortage_qty": max(0.0, line.required_qty - forecast),
                    "availability_calculated_at": fields.Datetime.now(),
                    "readiness": "planned" if forecast >= line.required_qty else "unplanned",
                    "blocking_note": False
                    if forecast >= line.required_qty
                    else _(
                        "Stock shortage: %(quantity)s",
                        quantity=max(0.0, line.required_qty - forecast),
                    ),
                }
            )
            line._update_supply_readiness()
        return True

    def _prepare_supply(self):
        return True

    def _update_supply_readiness(self):
        return True

    def write(self, vals):
        refresh_fields = {
            "on_hand_now",
            "reserved_now",
            "incoming_before_cutoff",
            "outgoing_before_cutoff",
            "forecast_available",
            "shortage_qty",
            "availability_calculated_at",
            "readiness",
            "blocking_note",
        }
        if refresh_fields.intersection(vals) and (
            self.env.context.get("mb_stock_refresh") or self.env.context.get("mb_supply_refresh")
        ):
            return models.Model.write(self, vals)
        if self.operation_id.filtered("stock_closed"):
            raise UserError(_("Stock allocations are closed for this operation."))
        return super().write(vals)


class MbMarketStockAllocation(models.Model):
    _name = "mb.market.stock.allocation"
    _description = "Concrete Market Stock Allocation"
    _order = "plan_line_id, product_id, lot_id"
    _check_company_auto = True

    plan_line_id = fields.Many2one(
        "mb.market.stock.plan.line",
        required=True,
        check_company=True,
        ondelete="cascade",
        index=True,
    )
    operation_id = fields.Many2one(
        related="plan_line_id.operation_id",
        store=True,
        precompute=True,
        index=True,
    )
    company_id = fields.Many2one(related="plan_line_id.company_id", store=True, index=True)
    product_id = fields.Many2one(
        "product.product",
        required=True,
        check_company=True,
        domain="[('is_storable', '=', True)]",
    )
    lot_id = fields.Many2one(
        "stock.lot",
        check_company=True,
        domain="[('product_id', '=', product_id)]",
    )
    quantity = fields.Float(required=True, default=1.0)

    _positive_quantity = models.Constraint(
        "CHECK(quantity > 0)",
        "Allocated quantity must be positive.",
    )
    _unique_operation_lot = models.Constraint(
        "UNIQUE(operation_id, lot_id)",
        "A lot or serial number can satisfy only one target in an operation.",
    )

    @api.constrains("plan_line_id", "product_id", "lot_id")
    def _check_allocation(self):
        for allocation in self:
            line = allocation.plan_line_id
            if line.target_type == "product" and line.product_id != allocation.product_id:
                raise ValidationError(
                    _("The allocated product must match the exact-product target.")
                )
            if allocation.product_id.tracking != "none" and not allocation.lot_id:
                raise ValidationError(_("Select a lot or serial number for tracked products."))
            if allocation.lot_id and allocation.lot_id.product_id != allocation.product_id:
                raise ValidationError(_("The lot does not belong to the allocated product."))

    def write(self, vals):
        if self.operation_id.filtered("stock_closed"):
            raise UserError(_("Stock allocations are closed for this operation."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_unlocked(self):
        if self.operation_id.filtered("stock_closed"):
            raise UserError(_("Stock allocations are closed for this operation."))
