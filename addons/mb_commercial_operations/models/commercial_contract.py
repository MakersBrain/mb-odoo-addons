from calendar import monthrange
from datetime import datetime, time, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class MbCommercialContract(models.Model):
    _name = "mb.commercial.contract"
    _description = "Commercial Contract"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_start desc, id desc"
    _check_company_auto = True

    name = fields.Char(required=True, default=lambda self: _("New"), copy=False, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
        index=True, tracking=True,
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    partner_id = fields.Many2one(
        "res.partner", string="Venue / Contract Partner", required=True,
        tracking=True, check_company=True,
    )
    project_id = fields.Many2one(
        "project.project", required=True, check_company=True, ondelete="restrict",
        tracking=True, index=True,
    )
    analytic_account_id = fields.Many2one(
        related="project_id.account_id", string="Analytic Account", store=True,
    )
    date_start = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    date_end = fields.Date(tracking=True)
    origin_partner_id = fields.Many2one(
        "res.partner", string="Default Travel Origin", check_company=True,
    )
    monthly_fixed_rent = fields.Monetary(tracking=True)
    rent_billing_method = fields.Selection(
        [
            ("vendor_bill", "Separate vendor bill"),
            ("settlement", "Included in settlement"),
            ("information", "Information only"),
        ],
        required=True,
        default="vendor_bill",
        tracking=True,
    )
    rent_product_id = fields.Many2one(
        "product.product", string="Rent Service", check_company=True,
        domain="[('type', '=', 'service')]",
    )
    notice_days = fields.Integer(default=30)
    review_date = fields.Date()
    attachment_ids = fields.Many2many(
        "ir.attachment", "mb_commercial_contract_attachment_rel",
        "contract_id", "attachment_id", string="Contract Documents",
    )
    obligation_ids = fields.One2many(
        "mb.commercial.obligation", "contract_id", string="Obligations",
    )
    operation_ids = fields.One2many(
        "mb.commercial.operation", "contract_id", string="Operations",
    )

    _date_order = models.Constraint(
        "CHECK(date_end IS NULL OR date_end >= date_start)",
        "The contract end date cannot be before its start date.",
    )
    _rent_nonnegative = models.Constraint(
        "CHECK(monthly_fixed_rent >= 0)",
        "The monthly rent cannot be negative.",
    )
    _notice_nonnegative = models.Constraint(
        "CHECK(notice_days >= 0)",
        "The notice period cannot be negative.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "mb.commercial.contract"
                ) or _("New")
            if not vals.get("project_id"):
                company = self.env["res.company"].browse(
                    vals.get("company_id") or self.env.company.id
                )
                partner = self.env["res.partner"].browse(vals.get("partner_id"))
                project = self.env["project.project"].with_company(company).create({
                    "name": vals.get("name") or partner.display_name or _("Commercial Contract"),
                    "company_id": company.id,
                    "partner_id": partner.id,
                    "allow_timesheets": True,
                    "mb_commercial_kind": "contract",
                    "date_start": vals.get("date_start"),
                    "date": vals.get("date_end"),
                })
                if not project.account_id:
                    project._create_analytic_account()
                vals["project_id"] = project.id
        return super().create(vals_list)

    @api.constrains("rent_billing_method", "monthly_fixed_rent", "rent_product_id")
    def _check_rent_configuration(self):
        for contract in self:
            if contract.rent_billing_method == "vendor_bill" \
                    and contract.monthly_fixed_rent and not contract.rent_product_id:
                raise ValidationError(_(
                    "Choose a rent service product before preparing vendor bills."
                ))

    def action_generate_occurrences(self):
        self.obligation_ids._generate_occurrences()
        return self.action_view_occurrences()

    def action_view_occurrences(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "mb_commercial_operations.action_commercial_occurrences"
        )
        action["domain"] = [("contract_id", "=", self.id)]
        action["context"] = {"default_contract_id": self.id}
        return action


class MbCommercialObligation(models.Model):
    _name = "mb.commercial.obligation"
    _description = "Commercial Contract Obligation"
    _order = "contract_id, sequence, id"
    _check_company_auto = True

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        related="contract_id.company_id", store=True, index=True,
    )
    contract_id = fields.Many2one(
        "mb.commercial.contract", required=True, check_company=True,
        ondelete="cascade", index=True,
    )
    obligation_type = fields.Selection(
        [("attendance", "Venue attendance"), ("visit", "Site visit")],
        required=True,
        default="attendance",
    )
    period_unit = fields.Selection(
        [("month", "Month"), ("week", "Week")],
        required=True,
        default="month",
    )
    required_occurrences = fields.Integer(required=True, default=1)
    required_hours = fields.Float(default=0.0)
    duration_hours = fields.Float(required=True, default=7.0)
    preferred_weekday = fields.Selection(
        [(str(day), label) for day, label in enumerate(
            ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"))],
        required=True,
        default="0",
    )
    start_hour = fields.Float(required=True, default=9.0)
    date_start = fields.Date(required=True)
    date_end = fields.Date()
    horizon_months = fields.Integer(required=True, default=6)
    user_ids = fields.Many2many(
        "res.users", "mb_commercial_obligation_user_rel", "obligation_id", "user_id",
        string="Default Assignees",
    )
    occurrence_ids = fields.One2many(
        "mb.commercial.obligation.occurrence", "obligation_id",
    )

    _date_order = models.Constraint(
        "CHECK(date_end IS NULL OR date_end >= date_start)",
        "The obligation end date cannot be before its start date.",
    )
    _counts_positive = models.Constraint(
        "CHECK(required_occurrences > 0 AND duration_hours > 0 AND horizon_months > 0)",
        "Occurrences, duration, and planning horizon must be positive.",
    )
    _hours_nonnegative = models.Constraint(
        "CHECK(required_hours >= 0)", "Required hours cannot be negative.",
    )
    _start_hour_range = models.Constraint(
        "CHECK(start_hour >= 0 AND start_hour < 24)",
        "The preferred start hour must be between 00:00 and 23:59.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("contract_id") and not vals.get("date_start"):
                vals["date_start"] = self.env["mb.commercial.contract"].browse(
                    vals["contract_id"]
                ).date_start
        records = super().create(vals_list)
        records._generate_occurrences()
        return records

    def write(self, vals):
        generation_fields = {
            "period_unit", "required_occurrences", "duration_hours",
            "preferred_weekday", "start_hour", "date_start", "date_end",
            "horizon_months", "active",
        }
        result = super().write(vals)
        if generation_fields.intersection(vals):
            self._regenerate_unapproved_occurrences()
        return result

    def _period_starts(self, today):
        self.ensure_one()
        start = max(self.date_start, today)
        if self.period_unit == "month":
            cursor = start.replace(day=1)
            horizon = (today + relativedelta(months=self.horizon_months)).replace(day=1)
            while cursor <= horizon:
                yield cursor
                cursor += relativedelta(months=1)
        else:
            cursor = start - timedelta(days=start.weekday())
            horizon = today + relativedelta(months=self.horizon_months)
            while cursor <= horizon:
                yield cursor
                cursor += timedelta(days=7)

    def _occurrence_date(self, period_start, sequence):
        self.ensure_one()
        weekday = int(self.preferred_weekday)
        first = period_start + timedelta(days=(weekday - period_start.weekday()) % 7)
        if self.period_unit == "week":
            return first
        candidate = first + timedelta(days=7 * (sequence - 1))
        last_day = monthrange(period_start.year, period_start.month)[1]
        if candidate.month != period_start.month:
            candidate = period_start.replace(day=last_day)
            candidate -= timedelta(days=(candidate.weekday() - weekday) % 7)
        return candidate

    def _local_datetime_to_utc(self, date_value):
        self.ensure_one()
        hour = int(self.start_hour)
        minute = round((self.start_hour - hour) * 60)
        if minute == 60:
            hour += 1
            minute = 0
        timezone = self.company_id.partner_id.tz or "UTC"
        local = pytz.timezone(timezone).localize(
            datetime.combine(date_value, time(hour % 24, minute))
        )
        return local.astimezone(pytz.UTC).replace(tzinfo=None)

    def _generate_occurrences(self):
        occurrence_model = self.env["mb.commercial.obligation.occurrence"]
        today = fields.Date.context_today(self)
        values = []
        for obligation in self.filtered("active"):
            for period_start in obligation._period_starts(today):
                for sequence in range(1, obligation.required_occurrences + 1):
                    occurrence_date = obligation._occurrence_date(period_start, sequence)
                    if occurrence_date < obligation.date_start:
                        continue
                    if obligation.date_end and occurrence_date > obligation.date_end:
                        continue
                    planned_start = obligation._local_datetime_to_utc(occurrence_date)
                    values.append({
                        "obligation_id": obligation.id,
                        "period_start": period_start,
                        "sequence": sequence,
                        "planned_start": planned_start,
                        "planned_end": planned_start + timedelta(hours=obligation.duration_hours),
                    })
        if values:
            for vals in values:
                existing = occurrence_model.search([
                    ("obligation_id", "=", vals["obligation_id"]),
                    ("period_start", "=", vals["period_start"]),
                    ("sequence", "=", vals["sequence"]),
                ], limit=1)
                if not existing:
                    occurrence_model.create(vals)
        return True

    def _regenerate_unapproved_occurrences(self):
        future = self.occurrence_ids.filtered(lambda occurrence: occurrence.state == "proposed")
        future.unlink()
        self._generate_occurrences()

    @api.model
    def _cron_generate_occurrences(self):
        obligations = self.search([("active", "=", True)])
        obligations._generate_occurrences()
        if self.env.context.get("cron_id"):
            self.env["ir.cron"]._commit_progress(len(obligations), remaining=0)


class MbCommercialObligationOccurrence(models.Model):
    _name = "mb.commercial.obligation.occurrence"
    _description = "Commercial Obligation Occurrence"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "planned_start, id"
    _check_company_auto = True

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one(
        related="obligation_id.company_id", store=True, index=True,
    )
    obligation_id = fields.Many2one(
        "mb.commercial.obligation", required=True, check_company=True,
        ondelete="cascade", index=True,
    )
    contract_id = fields.Many2one(
        related="obligation_id.contract_id", store=True, index=True,
    )
    period_start = fields.Date(required=True, index=True)
    sequence = fields.Integer(required=True)
    planned_start = fields.Datetime(required=True, tracking=True)
    planned_end = fields.Datetime(required=True, tracking=True)
    state = fields.Selection(
        [
            ("proposed", "Proposed"),
            ("approved", "Approved"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="proposed",
        copy=False,
        tracking=True,
        index=True,
    )
    operation_id = fields.Many2one(
        "mb.commercial.operation", check_company=True, copy=False,
        ondelete="restrict",
    )
    task_id = fields.Many2one(related="operation_id.task_id", store=True)
    actual_hours = fields.Float(compute="_compute_actual_hours")

    _occurrence_unique = models.Constraint(
        "unique(obligation_id, period_start, sequence)",
        "This contractual occurrence already exists.",
    )
    _date_order = models.Constraint(
        "CHECK(planned_end > planned_start)",
        "The occurrence end must be after its start.",
    )

    @api.depends("obligation_id.name", "period_start", "sequence")
    def _compute_name(self):
        for occurrence in self:
            occurrence.name = _("%(name)s — %(period)s #%(sequence)s",
                name=occurrence.obligation_id.name or _("Obligation"),
                period=occurrence.period_start or "",
                sequence=occurrence.sequence,
            )

    @api.depends("task_id.timesheet_ids.unit_amount")
    def _compute_actual_hours(self):
        for occurrence in self:
            occurrence.actual_hours = sum(occurrence.task_id.timesheet_ids.mapped("unit_amount"))

    def action_approve(self):
        for occurrence in self:
            if occurrence.state != "proposed":
                continue
            operation = self.env["mb.commercial.operation"].create(
                occurrence._prepare_operation_values()
            )
            operation.action_approve()
            occurrence.write({"operation_id": operation.id, "state": "approved"})
        return True

    def _prepare_operation_values(self):
        self.ensure_one()
        return {
            "name": self.name,
            "company_id": self.company_id.id,
            "operation_type": "attendance" if self.obligation_id.obligation_type == "attendance" else "visit",
            "contract_id": self.contract_id.id,
            "project_id": self.contract_id.project_id.id,
            "partner_id": self.contract_id.partner_id.id,
            "planned_start": self.planned_start,
            "planned_end": self.planned_end,
            "user_ids": [fields.Command.set(self.obligation_id.user_ids.ids)],
        }

    def action_done(self):
        for occurrence in self:
            if occurrence.state != "approved":
                raise UserError(_("Only approved occurrences can be completed."))
            occurrence.operation_id.action_done()
            occurrence.state = "done"
        return True

    def action_cancel(self):
        for occurrence in self:
            if occurrence.state == "done":
                raise UserError(_("A completed occurrence cannot be cancelled."))
            if occurrence.operation_id and occurrence.operation_id.state not in ("cancelled", "done", "financially_closed"):
                occurrence.operation_id.action_cancel()
            occurrence.state = "cancelled"
        return True

    def write(self, vals):
        protected = {"obligation_id", "period_start", "sequence", "planned_start", "planned_end"}
        if protected.intersection(vals) and self.filtered(lambda record: record.state != "proposed"):
            raise UserError(_("Approved or completed contractual occurrences cannot be rescheduled."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_proposed(self):
        if self.filtered(lambda occurrence: occurrence.state != "proposed"):
            raise UserError(_("Only proposed occurrences can be deleted."))
