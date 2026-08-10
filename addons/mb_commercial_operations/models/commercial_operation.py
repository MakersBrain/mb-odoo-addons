from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


LOCKED_OPERATION_STATES = {"done", "financially_closed", "cancelled"}


class MbCommercialOperation(models.Model):
    _name = "mb.commercial.operation"
    _description = "Commercial Operation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "planned_start desc, id desc"
    _check_company_auto = True

    name = fields.Char(required=True, default=lambda self: _("New"), copy=False, tracking=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
        index=True, tracking=True,
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    operation_type = fields.Selection(
        [("market", "Market / Fair"), ("attendance", "Venue Attendance"), ("visit", "Site Visit")],
        required=True,
        default="market",
        ondelete={"market": "set default", "attendance": "set default", "visit": "set default"},
        tracking=True,
        index=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("quoted", "Costed"),
            ("approved", "Approved"),
            ("scheduled", "Scheduled"),
            ("in_progress", "In Progress"),
            ("done", "Operationally Done"),
            ("financially_closed", "Financially Closed"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="draft",
        copy=False,
        tracking=True,
        index=True,
    )
    color = fields.Integer(compute="_compute_color")
    partner_id = fields.Many2one(
        "res.partner", string="Venue", required=True, check_company=True,
        tracking=True,
    )
    organizer_id = fields.Many2one(
        "res.partner", string="Organizer", check_company=True,
    )
    contract_id = fields.Many2one(
        "mb.commercial.contract", check_company=True, ondelete="restrict",
        tracking=True, index=True,
    )
    project_id = fields.Many2one(
        "project.project", required=True, check_company=True, ondelete="restrict",
        tracking=True, index=True,
    )
    analytic_account_id = fields.Many2one(
        related="project_id.account_id", store=True,
    )
    task_id = fields.Many2one(
        "project.task", check_company=True, copy=False, ondelete="set null",
        tracking=True,
    )
    user_ids = fields.Many2many(
        "res.users", "mb_commercial_operation_user_rel", "operation_id", "user_id",
        string="Responsible People", tracking=True,
    )
    planned_start = fields.Datetime(required=True, default=fields.Datetime.now, tracking=True)
    planned_end = fields.Datetime(required=True, tracking=True)
    all_day = fields.Boolean()
    actual_start = fields.Datetime(copy=False, tracking=True)
    actual_end = fields.Datetime(copy=False, tracking=True)
    planned_work_hours = fields.Float(compute="_compute_planned_hours", store=True)
    travel_estimate_id = fields.Many2one(
        "mb.travel.estimate", check_company=True, copy=False, ondelete="set null",
    )
    stock_preparation_deadline = fields.Datetime(tracking=True)
    expected_visitors = fields.Integer()
    expected_revenue = fields.Monetary(tracking=True)
    cost_line_ids = fields.One2many(
        "mb.commercial.cost.line", "operation_id", string="Planned Costs",
    )
    stock_plan_line_ids = fields.One2many(
        "mb.market.stock.plan.line", "operation_id", string="Stock Targets",
    )
    scenario_ids = fields.One2many(
        "mb.commercial.profitability.scenario", "operation_id",
    )
    planned_cost = fields.Monetary(compute="_compute_planned_profit", store=True)
    planned_margin = fields.Monetary(compute="_compute_planned_profit", store=True)
    actual_revenue = fields.Monetary(compute="_compute_actual_profit")
    actual_cost = fields.Monetary(compute="_compute_actual_profit")
    actual_margin = fields.Monetary(compute="_compute_actual_profit")
    account_move_ids = fields.Many2many(
        "account.move", "mb_commercial_operation_account_move_rel",
        "operation_id", "move_id", string="Accounting Documents", copy=False,
        check_company=True,
    )
    documents_expected = fields.Boolean(default=False)
    documents_complete = fields.Boolean(compute="_compute_financial_status")
    accounting_reconciled = fields.Boolean(compute="_compute_financial_status")
    conflict_acknowledged = fields.Boolean(copy=False, tracking=True)
    financial_close_date = fields.Date(copy=False, readonly=True)
    financial_close_user_id = fields.Many2one(
        "res.users", copy=False, readonly=True,
    )
    close_note = fields.Text(copy=False, tracking=True)

    _date_order = models.Constraint(
        "CHECK(planned_end > planned_start)",
        "The operation end must be after its start.",
    )
    _visitor_nonnegative = models.Constraint(
        "CHECK(expected_visitors >= 0)", "Expected visitors cannot be negative.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = self.browse()
        for original_vals in vals_list:
            vals = dict(original_vals)
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "mb.commercial.operation"
                ) or _("New")
            company = self.env["res.company"].browse(
                vals.get("company_id") or self.env.company.id
            )
            if not vals.get("planned_end"):
                vals["planned_end"] = fields.Datetime.add(
                    vals.get("planned_start") or fields.Datetime.now(), hours=7,
                )
            if not vals.get("project_id"):
                project = self.env["project.project"].with_company(company).create({
                    "name": vals["name"],
                    "company_id": company.id,
                    "partner_id": vals.get("partner_id"),
                    "allow_timesheets": True,
                    "mb_commercial_kind": "market" if vals.get("operation_type", "market") == "market" else "venue",
                    "date_start": fields.Datetime.to_datetime(vals["planned_start"]).date(),
                    "date": fields.Datetime.to_datetime(vals["planned_end"]).date(),
                })
                if not project.account_id:
                    project._create_analytic_account()
                vals["project_id"] = project.id
            record = super().create([vals])
            if not record.task_id:
                task = self.env["project.task"].with_company(record.company_id).create({
                    "name": record.name,
                    "project_id": record.project_id.id,
                    "company_id": record.company_id.id,
                    "partner_id": record.partner_id.id,
                    "user_ids": [fields.Command.set(record.user_ids.ids)],
                    "date_deadline": record.planned_end,
                    "allocated_hours": record.planned_work_hours,
                    "mb_commercial_operation_id": record.id,
                })
                record.with_context(mb_operation_sync=True).task_id = task
            records |= record
        return records

    def write(self, vals):
        plan_fields = {
            "operation_type", "partner_id", "organizer_id", "contract_id",
            "project_id", "user_ids", "planned_start", "planned_end", "all_day",
            "travel_estimate_id", "stock_preparation_deadline", "expected_visitors",
            "expected_revenue",
        }
        if plan_fields.intersection(vals):
            locked = self.filtered(lambda operation: operation.state in LOCKED_OPERATION_STATES)
            if locked:
                raise UserError(_(
                    "Completed, financially closed, or cancelled operations cannot be rescheduled or replanned."
                ))
            approved = self.filtered(lambda operation: operation.state not in ("draft", "quoted"))
            if approved:
                raise UserError(_("Reopen the approved operation before changing its planning baseline."))
        result = super().write(vals)
        if not self.env.context.get("mb_operation_sync") and {
            "name", "planned_end", "user_ids", "planned_start",
        }.intersection(vals):
            for operation in self.filtered("task_id"):
                operation.task_id.with_context(mb_operation_sync=True).write({
                    "name": operation.name,
                    "date_deadline": operation.planned_end,
                    "allocated_hours": operation.planned_work_hours,
                    "user_ids": [fields.Command.set(operation.user_ids.ids)],
                })
        return result

    @api.depends("operation_type", "state")
    def _compute_color(self):
        colors = {"market": 2, "attendance": 4, "visit": 7}
        for operation in self:
            operation.color = 1 if operation.state in ("cancelled", "financially_closed") else colors.get(operation.operation_type, 0)

    @api.depends("planned_start", "planned_end")
    def _compute_planned_hours(self):
        for operation in self:
            if operation.planned_start and operation.planned_end:
                operation.planned_work_hours = max(
                    0.0, (operation.planned_end - operation.planned_start).total_seconds() / 3600,
                )
            else:
                operation.planned_work_hours = 0.0

    @api.depends("expected_revenue", "cost_line_ids.planned_amount")
    def _compute_planned_profit(self):
        for operation in self:
            operation.planned_cost = sum(operation.cost_line_ids.mapped("planned_amount"))
            operation.planned_margin = operation.expected_revenue - operation.planned_cost

    @api.depends("analytic_account_id.line_ids.amount")
    def _compute_actual_profit(self):
        for operation in self:
            account = operation.analytic_account_id
            if not account or not account.plan_id:
                operation.actual_revenue = 0.0
                operation.actual_cost = 0.0
                operation.actual_margin = 0.0
                continue
            # Odoo 19's analytic account ``line_ids`` uses the contextual
            # ``auto_account_id`` bridge to the dynamic column of its plan.
            # Without the plan context the one2many is intentionally empty.
            plan_column = account.plan_id._column_name()
            lines = self.env["account.analytic.line"].search([
                (plan_column, "=", account.id),
            ])
            amounts = lines.mapped("amount")
            operation.actual_revenue = sum(amount for amount in amounts if amount > 0)
            operation.actual_cost = -sum(amount for amount in amounts if amount < 0)
            operation.actual_margin = operation.actual_revenue - operation.actual_cost

    @api.depends("documents_expected", "account_move_ids.state", "account_move_ids.payment_state")
    def _compute_financial_status(self):
        settled_states = {"paid", "in_payment", "reversed"}
        for operation in self:
            documents = operation.account_move_ids
            operation.documents_complete = (
                not operation.documents_expected
                or bool(documents) and all(move.state == "posted" for move in documents)
            )
            operation.accounting_reconciled = (
                operation.documents_complete
                and all(move.payment_state in settled_states for move in documents)
            )

    def _check_user_conflicts(self):
        for operation in self.filtered("user_ids"):
            conflicts = self.search([
                ("id", "!=", operation.id),
                ("company_id", "=", operation.company_id.id),
                ("state", "not in", ["cancelled", "financially_closed"]),
                ("user_ids", "in", operation.user_ids.ids),
                ("planned_start", "<", operation.planned_end),
                ("planned_end", ">", operation.planned_start),
            ], limit=1)
            if conflicts and not operation.conflict_acknowledged:
                raise ValidationError(_(
                    "%(operation)s overlaps %(conflict)s for an assigned person. "
                    "Resolve the conflict or acknowledge it before approval.",
                    operation=operation.display_name,
                    conflict=conflicts.display_name,
                ))

    def _check_stock_plan_allocations(self):
        for operation in self:
            exact_lines = operation.stock_plan_line_ids.filtered(
                lambda line: line.target_type == "product"
            )
            seen_products = set()
            for line in exact_lines:
                if line.product_id.id in seen_products:
                    raise ValidationError(_(
                        "Product %(product)s is targeted more than once.",
                        product=line.product_id.display_name,
                    ))
                seen_products.add(line.product_id.id)
            bucket_lines = operation.stock_plan_line_ids.filtered(
                lambda line: line.target_type == "bucket"
            )
            for line in exact_lines:
                matching = bucket_lines.filtered(
                    lambda bucket, exact=line:
                    (not bucket.category_id or exact.product_id.categ_id == bucket.category_id)
                    and exact.expected_unit_price >= bucket.price_min
                    and (not bucket.price_max or exact.expected_unit_price <= bucket.price_max)
                )
                if len(matching) > 1 or matching and line.bucket_line_id != matching:
                    raise ValidationError(_(
                        "Allocate exact product %(product)s to its single matching assortment bucket before approval.",
                        product=line.product_id.display_name,
                    ))
            ordered = bucket_lines.sorted("priority")
            for index, left in enumerate(ordered):
                for right in ordered[index + 1:]:
                    same_category = not left.category_id or not right.category_id or left.category_id == right.category_id
                    overlap = left.price_min <= (right.price_max or float("inf")) and right.price_min <= (left.price_max or float("inf"))
                    if same_category and overlap and left.priority == right.priority:
                        raise ValidationError(_(
                            "Overlapping assortment buckets need different priorities or non-overlapping definitions."
                        ))

    def action_mark_costed(self):
        for operation in self:
            if operation.state != "draft":
                raise UserError(_("Only draft operations can be marked costed."))
            operation.state = "quoted"
        return True

    def action_view_travel_estimates(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "mb_commercial_operations.action_travel_estimates"
        )
        action["domain"] = [("operation_id", "=", self.id)]
        action["context"] = {
            "default_operation_id": self.id,
            "default_company_id": self.company_id.id,
            "default_destination_partner_id": self.partner_id.id,
            "default_departure_at": self.planned_start,
        }
        return action

    def action_approve(self):
        self._check_user_conflicts()
        self._check_stock_plan_allocations()
        for operation in self:
            if operation.state not in ("draft", "quoted"):
                raise UserError(_("Only draft or costed operations can be approved."))
            accepted = operation.travel_estimate_id
            if accepted and (accepted.state != "accepted" or accepted.incomplete and not accepted.incomplete_acknowledged):
                raise ValidationError(_(
                    "Accept the travel estimate and acknowledge incomplete pricing before approval."
                ))
            operation.state = "approved"
        return True

    def action_schedule(self):
        for operation in self:
            if operation.state != "approved":
                raise UserError(_("Only approved operations can be scheduled."))
            operation.state = "scheduled"
        return True

    def action_start(self):
        for operation in self:
            if operation.state not in ("approved", "scheduled"):
                raise UserError(_("Only approved or scheduled operations can start."))
            operation.write({"state": "in_progress", "actual_start": fields.Datetime.now()})
        return True

    def action_done(self):
        for operation in self:
            if operation.state not in ("approved", "scheduled", "in_progress"):
                raise UserError(_("Only an active operation can be completed."))
            operation.write({
                "state": "done",
                "actual_start": operation.actual_start or operation.planned_start,
                "actual_end": fields.Datetime.now(),
            })
            if operation.task_id:
                operation.task_id.state = "1_done"
        return True

    def action_financial_close(self):
        if not self.env.user.has_group("account.group_account_manager"):
            raise AccessError(_("Only an Accounting Administrator can financially close operations."))
        for operation in self:
            if operation.state != "done":
                raise UserError(_("Complete the operation before financial close."))
            if not operation.documents_complete:
                raise UserError(_("Complete and post the expected accounting documents first."))
            operation.write({
                "state": "financially_closed",
                "financial_close_date": fields.Date.context_today(operation),
                "financial_close_user_id": self.env.user.id,
            })
            operation.project_id.active = False
        return True

    def action_reopen(self):
        if not self.env.user.has_group("mb_commercial_operations.group_commercial_operations_manager"):
            raise AccessError(_("Only a Commercial Operations Manager can reopen operations."))
        for operation in self:
            if operation.state not in ("approved", "scheduled", "done", "financially_closed"):
                raise UserError(_("This operation is not in a reopenable state."))
            operation.with_context(mb_reopen=True).write({
                "state": "draft",
                "financial_close_date": False,
                "financial_close_user_id": False,
            })
            operation.project_id.active = True
            operation.message_post(body=_("Operation reopened by %(user)s.", user=self.env.user.display_name))
        return True

    def action_cancel(self):
        for operation in self:
            if operation.state in ("done", "financially_closed"):
                raise UserError(_("Completed operations require correction/reversal, not cancellation."))
            operation.state = "cancelled"
        return True

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if self.filtered(lambda operation: operation.state != "draft"):
            raise UserError(_("Only draft operations can be deleted."))


class MbCommercialCostLine(models.Model):
    _name = "mb.commercial.cost.line"
    _description = "Commercial Planned Cost"
    _order = "sequence, id"
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    operation_id = fields.Many2one(
        "mb.commercial.operation", required=True, ondelete="cascade",
        check_company=True, index=True,
    )
    company_id = fields.Many2one(related="operation_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    name = fields.Char(required=True)
    category = fields.Selection(
        [
            ("travel", "Travel"), ("labour", "Labour"), ("rent", "Rent"),
            ("venue", "Venue / Stall"), ("accommodation", "Accommodation"),
            ("parking", "Parking"), ("fee", "Fee / Commission"), ("other", "Other"),
        ],
        required=True,
        default="other",
    )
    calculation = fields.Selection(
        [
            ("fixed", "Fixed"), ("hour", "Per hour"), ("kilometre", "Per kilometre"),
            ("day", "Per day"), ("revenue_percent", "% of revenue"), ("unit", "Per unit"),
        ],
        required=True,
        default="fixed",
    )
    quantity = fields.Float(default=1.0)
    rate = fields.Monetary()
    percentage = fields.Float(digits=(16, 4))
    planned_amount = fields.Monetary(compute="_compute_planned_amount", store=True)
    analytic_line_id = fields.Many2one("account.analytic.line", copy=False, ondelete="set null")
    account_move_line_id = fields.Many2one("account.move.line", copy=False, ondelete="set null")

    _quantity_nonnegative = models.Constraint(
        "CHECK(quantity >= 0 AND rate >= 0 AND percentage >= 0)",
        "Cost quantities, rates, and percentages cannot be negative.",
    )

    @api.depends("calculation", "quantity", "rate", "percentage", "operation_id.expected_revenue")
    def _compute_planned_amount(self):
        for line in self:
            if line.calculation == "revenue_percent":
                amount = line.operation_id.expected_revenue * line.percentage / 100.0
            else:
                amount = line.quantity * line.rate
            line.planned_amount = line.currency_id.round(amount) if line.currency_id else amount

    @api.model_create_multi
    def create(self, vals_list):
        operations = self.env["mb.commercial.operation"].browse(
            [vals.get("operation_id") for vals in vals_list if vals.get("operation_id")]
        )
        if operations.filtered(lambda operation: operation.state not in ("draft", "quoted")):
            raise UserError(_("Reopen the operation before adding planned costs."))
        return super().create(vals_list)

    def write(self, vals):
        if self.operation_id.filtered(lambda operation: operation.state not in ("draft", "quoted")):
            raise UserError(_("Reopen the operation before changing its approved cost baseline."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_unlocked(self):
        if self.operation_id.filtered(lambda operation: operation.state not in ("draft", "quoted")):
            raise UserError(_("Approved cost lines cannot be deleted."))


class MbMarketStockPlanLine(models.Model):
    _name = "mb.market.stock.plan.line"
    _description = "Market Stock Target"
    _order = "priority, id"
    _check_company_auto = True

    operation_id = fields.Many2one(
        "mb.commercial.operation", required=True, ondelete="cascade",
        check_company=True, index=True,
    )
    company_id = fields.Many2one(related="operation_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    target_type = fields.Selection(
        [("product", "Exact Product"), ("bucket", "Assortment Bucket")],
        required=True,
        default="product",
    )
    product_id = fields.Many2one("product.product", check_company=True)
    category_id = fields.Many2one("product.category")
    price_min = fields.Monetary()
    price_max = fields.Monetary()
    priority = fields.Integer(default=10)
    desired_opening_qty = fields.Float(required=True, default=1.0)
    safety_qty = fields.Float(default=0.0)
    required_qty = fields.Float(compute="_compute_required_qty", store=True)
    expected_sold_qty = fields.Float(default=0.0)
    expected_unit_price = fields.Monetary()
    expected_unit_cost = fields.Monetary()
    cost_source = fields.Selection(
        [("product", "Odoo product cost"), ("planning", "Explicit planning cost"), ("proxy", "Sale-price proxy")],
        default="product",
    )
    cost_date = fields.Date(default=fields.Date.context_today)
    supply_method = fields.Selection(
        [("manual", "Manual Selection")], required=True, default="manual",
        ondelete={"manual": "set default"},
    )
    bucket_line_id = fields.Many2one(
        "mb.market.stock.plan.line", string="Allocated Assortment Bucket",
        domain="[('operation_id', '=', operation_id), ('target_type', '=', 'bucket')]",
        ondelete="set null",
    )
    allocated_exact_line_ids = fields.One2many(
        "mb.market.stock.plan.line", "bucket_line_id", string="Allocated Exact Products",
    )
    allocated_quantity = fields.Float(compute="_compute_allocated_quantity")
    remaining_bucket_qty = fields.Float(compute="_compute_allocated_quantity")
    readiness = fields.Selection(
        [("unplanned", "Unplanned"), ("planned", "Planned")],
        required=True,
        default="planned",
    )
    blocking_note = fields.Text()

    _quantities_nonnegative = models.Constraint(
        "CHECK(desired_opening_qty >= 0 AND safety_qty >= 0 AND expected_sold_qty >= 0)",
        "Stock target quantities cannot be negative.",
    )
    _prices_nonnegative = models.Constraint(
        "CHECK(price_min >= 0 AND price_max >= 0 AND expected_unit_price >= 0 AND expected_unit_cost >= 0)",
        "Stock target prices and costs cannot be negative.",
    )
    _price_order = models.Constraint(
        "CHECK(price_max = 0 OR price_max >= price_min)",
        "The maximum assortment price cannot be below the minimum.",
    )
    _not_own_bucket = models.Constraint(
        "CHECK(bucket_line_id IS NULL OR bucket_line_id != id)",
        "A stock target cannot allocate itself.",
    )

    @api.depends("desired_opening_qty", "safety_qty")
    def _compute_required_qty(self):
        for line in self:
            line.required_qty = line.desired_opening_qty + line.safety_qty

    @api.model_create_multi
    def create(self, vals_list):
        operations = self.env["mb.commercial.operation"].browse(
            [vals.get("operation_id") for vals in vals_list if vals.get("operation_id")]
        )
        if operations.filtered(lambda operation: operation.state not in ("draft", "quoted")):
            raise UserError(_("Reopen the operation before adding a stock target."))
        return super().create(vals_list)

    @api.depends("allocated_exact_line_ids.required_qty", "required_qty")
    def _compute_allocated_quantity(self):
        for line in self:
            line.allocated_quantity = sum(line.allocated_exact_line_ids.mapped("required_qty"))
            line.remaining_bucket_qty = max(0.0, line.required_qty - line.allocated_quantity)

    @api.constrains("target_type", "product_id", "category_id", "bucket_line_id", "operation_id")
    def _check_target_configuration(self):
        for line in self:
            if line.target_type == "product" and not line.product_id:
                raise ValidationError(_("Choose a product for an exact-product target."))
            if line.target_type == "bucket" and line.product_id:
                raise ValidationError(_("An assortment bucket cannot also select an exact product."))
            if line.bucket_line_id and (
                line.target_type != "product"
                or line.bucket_line_id.target_type != "bucket"
                or line.bucket_line_id.operation_id != line.operation_id
            ):
                raise ValidationError(_("Exact-product allocation must point to a bucket in the same operation."))

    def write(self, vals):
        if self.operation_id.filtered(lambda operation: operation.state not in ("draft", "quoted")):
            raise UserError(_("Reopen the operation before changing its approved stock target."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_unlocked(self):
        if self.operation_id.filtered(lambda operation: operation.state not in ("draft", "quoted")):
            raise UserError(_("Approved stock targets cannot be deleted."))
