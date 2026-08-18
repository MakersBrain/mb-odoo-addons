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
    expected_arrival = fields.Datetime(tracking=True)
    setup_duration_hours = fields.Float(tracking=True)
    service_start = fields.Datetime(tracking=True)
    service_end = fields.Datetime(tracking=True)
    teardown_duration_hours = fields.Float(tracking=True)
    expected_return = fields.Datetime(tracking=True)
    application_deadline = fields.Datetime(tracking=True)
    payment_deadline = fields.Datetime(tracking=True)
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
    primary_scenario_id = fields.Many2one(
        "mb.commercial.profitability.scenario", string="Primary Scenario",
        check_company=True, copy=False, tracking=True,
        domain="[('operation_id', '=', id), ('state', 'in', ('draft', 'approved'))]",
    )
    profitability_required = fields.Boolean(
        default=False, tracking=True,
        help="Enable for operations whose planning baseline must include break-even profitability.",
    )
    profitability_opt_out_reason = fields.Text(tracking=True)
    planning_revision = fields.Integer(default=1, copy=False, readonly=True)
    planning_approved_by_id = fields.Many2one("res.users", copy=False, readonly=True)
    planning_approved_at = fields.Datetime(copy=False, readonly=True)
    planning_warning_count = fields.Integer(compute="_compute_planning_warnings")
    planning_blocking_warning_count = fields.Integer(compute="_compute_planning_warnings")
    planning_warning_summary = fields.Text(compute="_compute_planning_warnings")
    report_snapshot_ids = fields.One2many(
        "mb.commercial.report.snapshot", "operation_id", string="Frozen Reports",
    )
    planned_cost = fields.Monetary(compute="_compute_planned_profit", store=True)
    planned_margin = fields.Monetary(compute="_compute_planned_profit", store=True)
    planning_units = fields.Float(
        related="primary_scenario_id.planned_units", string="Planned Units / Baskets",
    )
    planning_sales_excl_vat = fields.Monetary(
        related="primary_scenario_id.sales_revenue_excl_vat",
        string="Planned Sales Excluding VAT",
    )
    planning_receipts_incl_vat = fields.Monetary(
        related="primary_scenario_id.customer_receipts_incl_vat",
        string="Planned Customer Receipts Including VAT",
    )
    planning_fixed_cost = fields.Monetary(
        related="primary_scenario_id.fixed_event_cost", string="Known Fixed Cost",
    )
    planning_variable_cost = fields.Monetary(
        related="primary_scenario_id.total_variable_cost",
        string="Estimated Variable Cost",
    )
    planning_break_even_units = fields.Integer(
        related="primary_scenario_id.break_even_units",
        string="Break-even Units / Baskets",
    )
    planning_break_even_sales = fields.Monetary(
        related="primary_scenario_id.break_even_sales_excl_vat",
        string="Break-even Sales Excluding VAT",
    )
    planning_break_even_receipts = fields.Monetary(
        related="primary_scenario_id.break_even_customer_receipts_incl_vat",
        string="Break-even Receipts Including VAT",
    )
    planning_break_even_headroom = fields.Float(
        related="primary_scenario_id.break_even_headroom_ratio",
        string="Break-even Headroom",
    )
    planning_recommendation = fields.Selection(
        related="primary_scenario_id.recommendation", string="Profitability Verdict",
        store=True, index=True,
    )
    planning_recommendation_note = fields.Char(
        related="primary_scenario_id.recommendation_note", string="Verdict Explanation",
    )
    planning_effort_hours = fields.Float(
        related="primary_scenario_id.effort_hours", string="Planned Work + Travel Hours",
    )
    planning_margin_per_hour = fields.Monetary(
        related="primary_scenario_id.margin_per_effort_hour",
        string="Planned Margin per Hour", store=True,
    )
    planning_travel_distance_km = fields.Float(
        related="primary_scenario_id.travel_distance_km",
        string="Planned Travel Distance (km)",
    )
    planning_travel_distance_known = fields.Boolean(
        related="primary_scenario_id.travel_distance_known",
    )
    planning_margin_per_km = fields.Monetary(
        related="primary_scenario_id.margin_per_travel_km",
        string="Planned Margin per Kilometre", store=True,
    )
    accepted_travel_cost = fields.Monetary(
        related="travel_estimate_id.total_operating_cost", string="Accepted Travel Cost",
    )
    accepted_travel_distance_km = fields.Float(
        related="travel_estimate_id.distance_km", string="Travel Distance (km)",
    )
    accepted_travel_duration_hours = fields.Float(
        related="travel_estimate_id.duration_hours", string="Travel Duration (hours)",
    )
    actual_revenue = fields.Monetary(compute="_compute_actual_profit")
    actual_cost = fields.Monetary(compute="_compute_actual_profit")
    actual_margin = fields.Monetary(compute="_compute_actual_profit")
    actual_work_hours = fields.Float(compute="_compute_actual_work_hours")
    account_move_ids = fields.Many2many(
        "account.move", "mb_commercial_operation_account_move_rel",
        "operation_id", "move_id", string="Accounting Documents", copy=False,
        check_company=True,
    )
    direct_account_move_ids = fields.One2many(
        "account.move", "mb_commercial_operation_id", string="Direct Accounting Evidence",
    )
    analytic_evidence_ids = fields.One2many(
        "account.analytic.line", "mb_commercial_operation_id",
        string="Operation Analytic Evidence", copy=False,
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
        prepared_vals = []
        project_indexes = []
        project_vals = []
        for original_vals in vals_list:
            vals = dict(original_vals)
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "mb.commercial.operation"
                ) or _("New")
            company = self.env["res.company"].browse(
                vals.get("company_id") or self.env.company.id
            )
            vals["planned_start"] = vals.get("planned_start") or fields.Datetime.now()
            if not vals.get("planned_end"):
                vals["planned_end"] = fields.Datetime.add(
                    vals["planned_start"], hours=7,
                )
            if not vals.get("project_id"):
                project_indexes.append(len(prepared_vals))
                project_vals.append({
                    "name": vals["name"],
                    "company_id": company.id,
                    "partner_id": vals.get("partner_id"),
                    "allow_timesheets": True,
                    "mb_commercial_kind": "market" if vals.get("operation_type", "market") == "market" else "venue",
                    "date_start": fields.Datetime.to_datetime(vals["planned_start"]).date(),
                    "date": fields.Datetime.to_datetime(vals["planned_end"]).date(),
                })
            prepared_vals.append(vals)

        if project_vals:
            projects = self.env["project.project"].create(project_vals)
            for index, project in zip(project_indexes, projects, strict=True):
                if not project.account_id:
                    project.with_company(project.company_id)._create_analytic_account()
                prepared_vals[index]["project_id"] = project.id

        records = super().create(prepared_vals)
        operations_without_tasks = records.filtered(lambda operation: not operation.task_id)
        if operations_without_tasks:
            tasks = self.env["project.task"].create([
                {
                    "name": record.name,
                    "project_id": record.project_id.id,
                    "company_id": record.company_id.id,
                    "partner_id": record.partner_id.id,
                    "user_ids": [fields.Command.set(record.user_ids.ids)],
                    "date_deadline": record.planned_end,
                    "allocated_hours": record.planned_work_hours,
                    "mb_commercial_operation_id": record.id,
                }
                for record in operations_without_tasks
            ])
            for record, task in zip(operations_without_tasks, tasks, strict=True):
                record.with_context(mb_operation_sync=True).task_id = task
        return records

    def write(self, vals):
        plan_fields = {
            "operation_type", "partner_id", "organizer_id", "contract_id",
            "project_id", "user_ids", "planned_start", "planned_end", "all_day",
            "expected_arrival", "setup_duration_hours", "service_start", "service_end",
            "teardown_duration_hours", "expected_return", "application_deadline",
            "payment_deadline",
            "travel_estimate_id", "stock_preparation_deadline", "expected_visitors",
            "expected_revenue", "primary_scenario_id", "profitability_required",
            "profitability_opt_out_reason",
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

    @api.depends(
        "expected_revenue", "cost_line_ids.planned_amount", "primary_scenario_id",
        "primary_scenario_id.sales_revenue_excl_vat",
        "primary_scenario_id.fixed_event_cost",
        "primary_scenario_id.projected_margin",
    )
    def _compute_planned_profit(self):
        for operation in self:
            scenario = operation.primary_scenario_id
            if scenario:
                operation.planned_cost = scenario.fixed_event_cost + scenario.total_variable_cost
                operation.planned_margin = scenario.projected_margin
            else:
                operation.planned_cost = sum(operation.cost_line_ids.filtered(
                    lambda line: not line.scenario_id
                ).mapped("planned_amount"))
                operation.planned_margin = operation.expected_revenue - operation.planned_cost

    @api.depends(
        "task_id.timesheet_ids.amount", "analytic_evidence_ids.amount",
        "account_move_ids.state", "account_move_ids.amount_untaxed_signed",
        "account_move_ids.line_ids.balance", "direct_account_move_ids.state",
        "direct_account_move_ids.amount_untaxed_signed",
        "direct_account_move_ids.line_ids.balance",
    )
    def _compute_actual_profit(self):
        for operation in self:
            items = operation._get_operation_profitability_items()
            seen = set()
            revenue = cost = 0.0
            for item in items:
                key = (item["model"], item["res_id"], item["component"])
                if key in seen:
                    continue
                seen.add(key)
                amount = operation._profitability_amount_company_currency(item)
                if item["component"] == "revenue":
                    revenue += amount
                else:
                    cost += amount
            operation.actual_revenue = operation.currency_id.round(revenue)
            operation.actual_cost = operation.currency_id.round(cost)
            operation.actual_margin = operation.actual_revenue - operation.actual_cost

    @api.depends("task_id.timesheet_ids.unit_amount", "actual_start", "actual_end")
    def _compute_actual_work_hours(self):
        for operation in self:
            timesheet_hours = sum(operation.task_id.timesheet_ids.mapped("unit_amount"))
            if timesheet_hours:
                operation.actual_work_hours = timesheet_hours
            elif operation.actual_start and operation.actual_end:
                operation.actual_work_hours = max(
                    0.0,
                    (operation.actual_end - operation.actual_start).total_seconds() / 3600.0,
                )
            else:
                operation.actual_work_hours = 0.0

    def _profitability_amount_company_currency(self, item):
        self.ensure_one()
        currency = item.get("currency") or self.currency_id
        amount = item.get("amount", 0.0)
        if currency != self.currency_id:
            amount = currency._convert(
                amount, self.currency_id, self.company_id,
                item.get("date") or fields.Date.context_today(self),
            )
        return amount

    def _get_operation_profitability_items(self):
        """Return normalized, operation-scoped native evidence.

        Optional bridge addons extend this registry.  Never fall back to the
        operation's whole analytic account: depot operations intentionally share
        a long-lived project with their contract.
        """
        self.ensure_one()
        items = []
        for line in self.analytic_evidence_ids:
            items.append({
                "model": line._name, "res_id": line.id,
                "component": "revenue" if line.amount > 0 else "cost",
                "date": line.date,
                "amount": line.amount if line.amount > 0 else -line.amount,
                "currency": self.currency_id,
            })
        for line in self.task_id.timesheet_ids:
            if line.mb_commercial_operation_id:
                continue
            if line.amount:
                items.append({
                    "model": line._name, "res_id": line.id,
                    "component": "cost", "date": line.date,
                    "amount": -line.amount, "currency": self.currency_id,
                })
        for move in (self.account_move_ids | self.direct_account_move_ids).filtered(
            lambda record: record.state == "posted"
        ):
            revenue_move = move.move_type in ("out_invoice", "out_refund")
            component = "revenue" if revenue_move else "cost"
            sign = -1 if move.move_type in ("out_refund", "in_refund") else 1
            items.append({
                "model": move._name, "res_id": move.id, "component": component,
                "date": move.date, "amount": sign * abs(move.amount_untaxed_signed),
                "currency": self.currency_id,
            })
        return items

    def _get_operation_profitability_report_items(self):
        """Return the same deduplicated evidence used by the actual KPI totals."""
        self.ensure_one()
        rows = []
        seen = set()
        for item in self._get_operation_profitability_items():
            key = (item["model"], item["res_id"], item["component"])
            if key in seen:
                continue
            seen.add(key)
            record = self.env[item["model"]].browse(item["res_id"]).exists()
            rows.append({
                "model": item["model"],
                "res_id": item["res_id"],
                "source": record.display_name if record else _("Deleted source"),
                "component": item["component"],
                "date": item.get("date"),
                "amount": self.currency_id.round(
                    self._profitability_amount_company_currency(item)
                ),
            })
        return sorted(
            rows,
            key=lambda row: (str(row["date"] or ""), row["model"], row["res_id"]),
        )

    def _get_planning_warnings(self, scenario=None):
        self.ensure_one()
        scenario = scenario or self.primary_scenario_id
        warnings = []
        if self.profitability_required and not scenario:
            warnings.append(("missing_primary_scenario", "blocking", _("Choose a primary profitability scenario.")))
        if not self.profitability_required and self.profitability_opt_out_reason:
            warnings.append(("cost_plan_only", "info", self.profitability_opt_out_reason))
        if scenario and scenario.calculation_blocked:
            warnings.append(("scenario_blocked", "blocking", scenario.calculation_note or _("The primary scenario is incomplete.")))
        if scenario:
            legacy_operation_cost = sum(self.cost_line_ids.filtered(
                lambda line: not line.scenario_id
            ).mapped("planned_amount"))
            legacy_scenario_cost = (
                scenario.accepted_travel_cost
                + scenario.planned_work_hours * scenario.work_hourly_cost
                + scenario.stall_rent + scenario.parking_cost
                + scenario.accommodation_cost + scenario.other_fixed_cost
            )
            scenario_cost = sum(scenario.cost_line_ids.mapped("planned_amount"))
            if (
                scenario_cost and legacy_scenario_cost
                and not self.currency_id.is_zero(scenario_cost - legacy_scenario_cost)
            ) or (
                scenario_cost and legacy_operation_cost
                and not self.currency_id.is_zero(scenario_cost - legacy_operation_cost)
            ) or (
                not scenario_cost and legacy_scenario_cost and legacy_operation_cost
                and not self.currency_id.is_zero(legacy_scenario_cost - legacy_operation_cost)
            ):
                warnings.append((
                    "legacy_cost_reconciliation", "blocking",
                    _("Legacy and scenario-owned fixed costs differ; review the baseline explicitly."),
                ))
        if scenario and scenario.line_ids.filtered("exclude_product_cost"):
            warnings.append((
                "product_cost_excluded", "warning",
                _("One or more sales assumptions explicitly exclude product cost."),
            ))
        if scenario and scenario.line_ids.filtered(lambda line: line.cost_source == "proxy"):
            warnings.append(("product_cost_proxy", "warning", _("A product cost uses a documented sale-price proxy.")))
        old_date = fields.Date.subtract(fields.Date.context_today(self), days=90)
        if scenario and scenario.line_ids.filtered(lambda line: line.cost_date and line.cost_date < old_date):
            warnings.append(("product_cost_outdated", "warning", _("A product cost assumption is more than 90 days old.")))
        if scenario and scenario.state == "draft" and scenario.line_ids.filtered(
            lambda line: line.source_stock_plan_line_id and (
                line.expected_sold_qty != line.source_stock_plan_line_id.expected_sold_qty
                or line.sale_price_excluded_tax != line.source_stock_plan_line_id.expected_unit_price
                or line.product_unit_cost != line.source_stock_plan_line_id.expected_unit_cost
            )
        ):
            warnings.append(("stock_scenario_out_of_sync", "warning", _("Draft sales assumptions differ from their stock-plan snapshot.")))
        if scenario and not scenario.calculation_blocked \
                and scenario.break_even_units > scenario.planned_units:
            warnings.append(("break_even_above_plan", "warning", _("Break-even exceeds planned units or baskets.")))
        if self.expected_arrival and self.service_start and self.expected_arrival > self.service_start:
            warnings.append(("arrival_after_service_start", "blocking", _("Expected arrival is after the service starts.")))
        if self.application_deadline and self.application_deadline < fields.Datetime.now():
            warnings.append(("application_deadline_overdue", "warning", _("The application deadline is overdue.")))
        if self.activity_ids.filtered(
            lambda activity: activity.date_deadline < fields.Date.context_today(self)
        ):
            warnings.append(("activity_overdue", "warning", _("One or more operation activities are overdue.")))
        accepted = self.travel_estimate_id
        if accepted and (accepted.state != "accepted" or accepted.incomplete and not accepted.incomplete_acknowledged):
            warnings.append(("travel_not_accepted", "blocking", _("Accept or acknowledge the selected travel quote.")))
        if scenario and scenario.travel_estimate_id and scenario.travel_estimate_id.state != "accepted":
            warnings.append(("scenario_travel_not_accepted", "blocking", _("The scenario travel quote is not accepted.")))
        if self.operation_type == "market" and not self.stock_plan_line_ids:
            warnings.append(("missing_stock_targets", "warning", _("No stock targets are planned.")))
        for line in self.stock_plan_line_ids.filtered(lambda target: target.blocking_note):
            warnings.append(("stock_target_blocked", "blocking", line.blocking_note))
        prefetched_conflicts = self.env.context.get("mb_user_conflicts")
        conflict = (
            self.browse(prefetched_conflicts.get(self.id))
            if prefetched_conflicts is not None
            else self._get_user_conflict()
        )
        if conflict and not self.conflict_acknowledged:
            warnings.append((
                "responsible_user_conflict", "blocking",
                _("A responsible person is assigned to an overlapping operation."),
            ))
        if self.state in ("done", "financially_closed") and not self.documents_complete:
            warnings.append(("actual_documents_incomplete", "warning", _("Actual accounting documents are incomplete.")))
        if not self.env.context.get("mb_snapshot_creating") \
                and self.state in ("approved", "scheduled", "in_progress", "done", "financially_closed") \
                and not self.report_snapshot_ids.filtered(
                    lambda snapshot: snapshot.report_kind == "planning" and snapshot.revision == self.planning_revision
                ):
            warnings.append(("approved_snapshot_missing", "blocking", _("The approved revision has no frozen planning report.")))
        return warnings

    @api.depends(
        "primary_scenario_id", "primary_scenario_id.calculation_blocked",
        "travel_estimate_id.state", "travel_estimate_id.incomplete",
        "travel_estimate_id.incomplete_acknowledged", "stock_plan_line_ids.blocking_note",
        "documents_complete", "state", "profitability_required",
        "profitability_opt_out_reason", "expected_arrival", "service_start",
        "user_ids", "planned_start", "planned_end", "conflict_acknowledged",
        "application_deadline", "report_snapshot_ids.state", "report_snapshot_ids.revision",
        "primary_scenario_id.line_ids.cost_source", "primary_scenario_id.line_ids.cost_date",
        "primary_scenario_id.line_ids.exclude_product_cost",
        "primary_scenario_id.line_ids.source_stock_plan_line_id",
        "primary_scenario_id.line_ids.expected_sold_qty",
        "primary_scenario_id.break_even_units", "primary_scenario_id.planned_units",
        "activity_ids.date_deadline",
        "cost_line_ids.planned_amount", "primary_scenario_id.cost_line_ids.planned_amount",
        "primary_scenario_id.accepted_travel_cost", "primary_scenario_id.stall_rent",
        "primary_scenario_id.other_fixed_cost",
        "primary_scenario_id.travel_estimate_id.state",
    )
    def _compute_planning_warnings(self):
        conflicts = self._get_user_conflicts()
        conflict_ids = {
            record_id: conflict.id or False
            for record_id, conflict in conflicts.items()
        }
        for operation in self:
            warnings = operation.with_context(
                mb_user_conflicts=conflict_ids
            )._get_planning_warnings()
            operation.planning_warning_count = len(warnings)
            operation.planning_blocking_warning_count = len([
                warning for warning in warnings if warning[1] == "blocking"
            ])
            operation.planning_warning_summary = "\n".join(
                f"[{severity.upper()}] {message}" for _code, severity, message in warnings
            )

    @api.depends(
        "documents_expected", "account_move_ids.state", "account_move_ids.payment_state",
        "direct_account_move_ids.state", "direct_account_move_ids.payment_state",
    )
    def _compute_financial_status(self):
        settled_states = {"paid", "in_payment", "reversed"}
        for operation in self:
            documents = operation.account_move_ids | operation.direct_account_move_ids
            operation.documents_complete = (
                not operation.documents_expected
                or bool(documents) and all(move.state == "posted" for move in documents)
            )
            operation.accounting_reconciled = (
                operation.documents_complete
                and all(move.payment_state in settled_states for move in documents)
            )

    def _get_user_conflict(self):
        self.ensure_one()
        return self._get_user_conflicts().get(self.id, self.browse())

    def _get_user_conflicts(self):
        """Return one overlapping operation per record with a single search."""
        conflicts = {operation.id: self.browse() for operation in self}
        operations = self.filtered(
            lambda operation: operation.user_ids
            and operation.planned_start and operation.planned_end
        )
        if not operations:
            return conflicts
        candidates = self.sudo().search([
            ("company_id", "in", operations.company_id.ids),
            ("state", "not in", ["cancelled", "financially_closed"]),
            ("user_ids", "in", operations.user_ids.ids),
            ("planned_start", "<", max(operations.mapped("planned_end"))),
            ("planned_end", ">", min(operations.mapped("planned_start"))),
        ])
        for operation in operations:
            operation_user_ids = set(operation.user_ids.ids)
            conflict = candidates.filtered(lambda candidate,
                    current=operation, current_user_ids=operation_user_ids: (
                candidate.id != current.id
                and candidate.company_id.id == current.company_id.id
                and candidate.planned_start < current.planned_end
                and candidate.planned_end > current.planned_start
                and current_user_ids.intersection(candidate.user_ids.ids)
            ))[:1]
            conflicts[operation.id] = conflict
        return conflicts

    def _find_comparable_operation(self):
        """Return the last comparable operation whose plan can seed this one."""
        self.ensure_one()
        if not self.partner_id or not self.planned_start:
            return self.browse()
        base = [
            ("id", "not in", self.ids),
            ("company_id", "=", self.company_id.id),
            ("operation_type", "=", self.operation_type),
            ("planned_start", "<", self.planned_start),
            ("primary_scenario_id.line_ids", "!=", False),
        ]
        committed = [("state", "in", ("done", "financially_closed"))]
        still_open = [("state", "in", ("approved", "scheduled", "in_progress"))]
        subjects = []
        if self.contract_id:
            subjects.append([("contract_id", "=", self.contract_id.id)])
        subjects.append([("partner_id", "=", self.partner_id.id)])
        for subject in subjects:
            for state_domain in (committed, still_open):
                # Deliberately not sudoed: seeding may only carry data the planner
                # is allowed to read. _order already sorts the most recent first.
                match = self.search(base + subject + state_domain, limit=1)
                if match:
                    return match
        return self.browse()

    def _check_user_conflicts(self):
        conflicts_by_operation = self._get_user_conflicts()
        for operation in self.filtered("user_ids"):
            conflicts = conflicts_by_operation.get(operation.id, self.browse())
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
            blocking = [warning[2] for warning in operation._get_planning_warnings() if warning[1] == "blocking"]
            if blocking:
                blocking_message = "\n".join(blocking)
                raise ValidationError(blocking_message)
            scenario = operation.primary_scenario_id
            if scenario and scenario.state == "draft":
                scenario._approve_as_primary()
            operation.with_context(mb_approve_baseline=True).write({
                "state": "approved",
                "planning_approved_by_id": self.env.user.id,
                "planning_approved_at": fields.Datetime.now(),
            })
            operation.with_context(mb_snapshot_creating=True)._create_report_snapshot("planning")
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
            project = operation.project_id
            open_siblings = project.mb_commercial_operation_ids.filtered(
                lambda sibling: sibling.state not in ("financially_closed", "cancelled")
            )
            if project.mb_commercial_kind != "contract" and not open_siblings:
                project.active = False
        return True

    def action_reopen(self):
        if not self.env.user.has_group("mb_commercial_operations.group_commercial_operations_manager"):
            raise AccessError(_("Only a Commercial Operations Manager can reopen operations."))
        for operation in self:
            if operation.state not in ("approved", "scheduled", "done", "financially_closed"):
                raise UserError(_("This operation is not in a reopenable state."))
            previous_scenario = operation.primary_scenario_id
            operation.with_context(mb_reopen=True).write({
                "state": "draft",
                "planning_revision": operation.planning_revision + 1,
                "planning_approved_by_id": False,
                "planning_approved_at": False,
                "financial_close_date": False,
                "financial_close_user_id": False,
            })
            if previous_scenario and previous_scenario.state != "draft":
                revision_scenario = previous_scenario.copy({
                    "name": _("Revision %(revision)s of %(name)s",
                              revision=operation.planning_revision,
                              name=previous_scenario.name),
                    "state": "draft", "approved_by_id": False, "approved_at": False,
                })
                operation.write({"primary_scenario_id": revision_scenario.id})
            if operation.project_id.mb_commercial_kind != "contract":
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
    scenario_id = fields.Many2one(
        "mb.commercial.profitability.scenario", ondelete="cascade",
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
            ("day", "Per day"), ("revenue_percent", "Percentage of revenue"), ("unit", "Per unit"),
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

    source_kind = fields.Selection([
        ("manual", "Manual"), ("travel", "Travel Quote"),
        ("contract", "Contract"), ("template", "Template"),
        ("migration", "Legacy Migration"),
    ], required=True, default="manual")
    travel_estimate_id = fields.Many2one("mb.travel.estimate", check_company=True, ondelete="restrict")
    assumption_date = fields.Date(default=fields.Date.context_today)
    source_reference = fields.Char()
    source_currency_id = fields.Many2one("res.currency")
    source_amount = fields.Monetary(currency_field="source_currency_id")
    conversion_rate = fields.Float(digits=(12, 6))
    conversion_date = fields.Date()

    @api.depends(
        "calculation", "quantity", "rate", "percentage",
        "operation_id.expected_revenue", "scenario_id.sales_revenue_excl_vat",
    )
    def _compute_planned_amount(self):
        for line in self:
            if line.calculation == "revenue_percent":
                revenue = line.scenario_id.sales_revenue_excl_vat or line.operation_id.expected_revenue
                amount = revenue * line.percentage / 100.0
            else:
                amount = line.quantity * line.rate
            line.planned_amount = line.currency_id.round(amount) if line.currency_id else amount

    @api.model_create_multi
    def create(self, vals_list):
        scenarios = self.env["mb.commercial.profitability.scenario"].browse(
            [vals.get("scenario_id") for vals in vals_list if vals.get("scenario_id")]
        )
        if not self.env.context.get("mb_planning_migration") and scenarios.filtered(
            lambda scenario: scenario.state != "draft"
        ):
            raise UserError(_("Approved scenario costs are immutable; create a revision."))
        for vals in vals_list:
            scenario = self.env["mb.commercial.profitability.scenario"].browse(vals.get("scenario_id"))
            if scenario:
                vals.setdefault("operation_id", scenario.operation_id.id)
        operations = self.env["mb.commercial.operation"].browse(
            [vals.get("operation_id") for vals in vals_list if vals.get("operation_id")]
        )
        if not self.env.context.get("mb_planning_migration") and operations.filtered(
            lambda operation: operation.state not in ("draft", "quoted")
        ):
            raise UserError(_("Reopen the operation before adding planned costs."))
        return super().create(vals_list)

    def write(self, vals):
        if self.scenario_id.filtered(lambda scenario: scenario.state != "draft"):
            raise UserError(_("Approved scenario costs are immutable; create a revision."))
        if self.operation_id.filtered(lambda operation: operation.state not in ("draft", "quoted")):
            raise UserError(_("Reopen the operation before changing its approved cost baseline."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_unlocked(self):
        if self.scenario_id.filtered(lambda scenario: scenario.state != "draft"):
            raise UserError(_("Approved scenario costs cannot be deleted."))
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
