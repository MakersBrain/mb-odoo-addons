import base64
import hashlib
import json

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


_SNAPSHOT_TOKEN = object()


class AccountAnalyticLine(models.Model):
    _inherit = "account.analytic.line"

    mb_commercial_operation_id = fields.Many2one(
        "mb.commercial.operation", check_company=True, copy=False, index=True,
        ondelete="restrict",
    )


class AccountMove(models.Model):
    _inherit = "account.move"

    mb_commercial_operation_id = fields.Many2one(
        "mb.commercial.operation", check_company=True, copy=False, index=True,
        ondelete="restrict",
    )


class MbCommercialPlanTemplate(models.Model):
    _name = "mb.commercial.plan.template"
    _description = "Commercial Planning Template"
    _order = "name"
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True,
    )
    operation_type = fields.Selection(
        selection=lambda self: self.env["mb.commercial.operation"]._fields["operation_type"].selection,
        required=True, default="market",
    )
    calculation_mode = fields.Selection(
        [("product_mix", "Product Mix"), ("average_basket", "Average Basket")],
        required=True, default="product_mix",
    )
    default_duration_hours = fields.Float(default=7.0)
    default_setup_hours = fields.Float(string="Default Setup / Loading Hours")
    default_service_hours = fields.Float(string="Default Service / Public Hours", default=6.0)
    default_teardown_hours = fields.Float(string="Default Teardown / Unloading Hours")
    default_labour_hourly_cost = fields.Monetary()
    default_travel_hourly_cost = fields.Monetary()
    default_fuel_consumption_l_per_100km = fields.Float(default=7.0)
    default_fuel_price_eur_per_l = fields.Monetary(default=1.80)
    warning_age_days = fields.Integer(default=90)
    currency_id = fields.Many2one(related="company_id.currency_id")
    cost_line_ids = fields.One2many("mb.commercial.plan.template.cost", "template_id")
    product_line_ids = fields.One2many("mb.commercial.plan.template.product", "template_id")


class MbCommercialPlanTemplateCost(models.Model):
    _name = "mb.commercial.plan.template.cost"
    _description = "Commercial Planning Template Cost"
    _order = "sequence, id"
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    template_id = fields.Many2one("mb.commercial.plan.template", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="template_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    name = fields.Char(required=True)
    category = fields.Selection(
        selection=lambda self: self.env["mb.commercial.cost.line"]._fields["category"].selection,
        required=True, default="other",
    )
    calculation = fields.Selection(
        selection=lambda self: self.env["mb.commercial.cost.line"]._fields["calculation"].selection,
        required=True, default="fixed",
    )
    quantity = fields.Float(default=1.0)
    rate = fields.Monetary()
    percentage = fields.Float(digits=(16, 4))


class MbCommercialPlanTemplateProduct(models.Model):
    _name = "mb.commercial.plan.template.product"
    _description = "Commercial Planning Template Product"
    _order = "sequence, id"
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    template_id = fields.Many2one("mb.commercial.plan.template", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="template_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    product_id = fields.Many2one("product.product", required=True, check_company=True)
    expected_sold_qty = fields.Float(default=1.0)
    desired_opening_qty = fields.Float(default=1.0)
    safety_qty = fields.Float()
    sale_price_excluded_tax = fields.Monetary()
    product_unit_cost = fields.Monetary()


class MbCommercialReportSnapshot(models.Model):
    _name = "mb.commercial.report.snapshot"
    _description = "Frozen Commercial Planning Report"
    _inherit = ["mail.thread"]
    _order = "generated_at desc, id desc"
    _check_company_auto = True

    name = fields.Char(required=True, readonly=True)
    operation_id = fields.Many2one(
        "mb.commercial.operation", required=True, ondelete="restrict",
        check_company=True, index=True, readonly=True,
    )
    scenario_id = fields.Many2one(
        "mb.commercial.profitability.scenario", ondelete="restrict",
        check_company=True, readonly=True,
    )
    company_id = fields.Many2one(related="operation_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    report_kind = fields.Selection(
        [("planning", "Planning Pack"), ("outcome", "Outcome Pack")],
        required=True, readonly=True,
    )
    revision = fields.Integer(required=True, readonly=True)
    state = fields.Selection(
        [("current", "Current"), ("superseded", "Superseded"), ("void", "Void")],
        required=True, default="current", readonly=True, tracking=True,
    )
    generated_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    generated_by_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user, readonly=True)
    payload = fields.Json(required=True, readonly=True)
    input_digest = fields.Char(required=True, readonly=True, index=True)
    pdf_digest = fields.Char(readonly=True)
    attachment_id = fields.Many2one("ir.attachment", ondelete="restrict", readonly=True)
    void_reason = fields.Text(tracking=True)
    voided_at = fields.Datetime(readonly=True)
    voided_by_id = fields.Many2one("res.users", readonly=True)

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("mb_snapshot_token") is not _SNAPSHOT_TOKEN:
            raise AccessError(_("Snapshots can only be created by the controlled approval workflow."))
        return super().create(values_list)

    @api.constrains("operation_id", "scenario_id")
    def _check_scenario_operation(self):
        for snapshot in self.filtered("scenario_id"):
            if snapshot.scenario_id.operation_id != snapshot.operation_id:
                raise ValidationError(_("The frozen scenario must belong to the operation."))

    def action_open_attachment(self):
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_("This snapshot has no PDF attachment."))
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{self.attachment_id.id}?download=true",
            "target": "self",
        }

    def action_void(self):
        if not self.env.user.has_group("mb_commercial_operations.group_commercial_operations_manager"):
            raise AccessError(_("Only a Commercial Operations Manager can void a snapshot."))
        for snapshot in self.filtered(lambda item: item.state != "void"):
            if not snapshot.void_reason:
                raise ValidationError(_("Enter a void reason before voiding this frozen report."))
            snapshot.with_context(mb_snapshot_token=_SNAPSHOT_TOKEN).write({
                "state": "void", "voided_at": fields.Datetime.now(),
                "voided_by_id": self.env.user.id,
            })
            message = _("Frozen report voided: %(reason)s", reason=snapshot.void_reason)
            snapshot.message_post(body=message)
            snapshot.operation_id.message_post(body=message)
        return True

    def write(self, vals):
        allowed = {"state", "void_reason", "voided_at", "voided_by_id", "attachment_id", "pdf_digest"}
        reason_only = set(vals) <= {"void_reason"} and self.env.user.has_group(
            "mb_commercial_operations.group_commercial_operations_manager"
        ) and not self.filtered(lambda snapshot: snapshot.state == "void")
        if not reason_only and (
            self.env.context.get("mb_snapshot_token") is not _SNAPSHOT_TOKEN or set(vals) - allowed
        ):
            raise UserError(_("Frozen report snapshots are immutable."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_never(self):
        raise UserError(_("Frozen report snapshots cannot be deleted; void them instead."))


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    mb_commercial_report_snapshot_id = fields.Many2one(
        "mb.commercial.report.snapshot", copy=False, index=True, ondelete="restrict",
    )

    def write(self, vals):
        if self.filtered("mb_commercial_report_snapshot_id") \
                and self.env.context.get("mb_snapshot_token") is not _SNAPSHOT_TOKEN:
            raise UserError(_("A frozen commercial report attachment cannot be changed."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_commercial_snapshot_attachment(self):
        if self.filtered("mb_commercial_report_snapshot_id") \
                and self.env.context.get("mb_snapshot_token") is not _SNAPSHOT_TOKEN:
            raise UserError(_("A frozen commercial report attachment cannot be deleted."))


class MbCommercialOperation(models.Model):
    _inherit = "mb.commercial.operation"

    @api.constrains("primary_scenario_id")
    def _check_primary_scenario(self):
        for operation in self.filtered("primary_scenario_id"):
            if operation.primary_scenario_id.operation_id != operation:
                raise ValidationError(_("The primary scenario must belong to this operation."))

    def _planning_payload(self, kind):
        self.ensure_one()
        scenario = self.primary_scenario_id
        return {
            "schema": 1,
            "kind": kind,
            "operation": {
                "id": self.id, "name": self.name, "type": self.operation_type,
                "state": self.state, "revision": self.planning_revision,
                "partner": self.partner_id.display_name,
                "planned_start": fields.Datetime.to_string(self.planned_start),
                "planned_end": fields.Datetime.to_string(self.planned_end),
                "expected_arrival": fields.Datetime.to_string(self.expected_arrival),
                "service_start": fields.Datetime.to_string(self.service_start),
                "service_end": fields.Datetime.to_string(self.service_end),
                "expected_return": fields.Datetime.to_string(self.expected_return),
                "responsible_user_ids": self.user_ids.ids,
            },
            "scenario": scenario and {
                "id": scenario.id, "name": scenario.name,
                "sales_excl_vat": scenario.sales_revenue_excl_vat,
                "receipts_incl_vat": scenario.customer_receipts_incl_vat,
                "fixed_cost": scenario.fixed_event_cost,
                "variable_cost": scenario.total_variable_cost,
                "break_even_units": scenario.break_even_units,
                "break_even_sales_excl_vat": scenario.break_even_sales_excl_vat,
                "break_even_receipts_incl_vat": scenario.break_even_customer_receipts_incl_vat,
                "projected_margin": scenario.projected_margin,
                "lines": [{
                    "id": line.id, "product_id": line.product_id.id,
                    "stock_target_id": line.source_stock_plan_line_id.id,
                    "expected_sold_qty": line.expected_sold_qty,
                    "sales_price_excl_vat": line.sale_price_excluded_tax,
                    "vat_rate": line.vat_rate,
                    "customer_price_incl_vat": line.customer_price_incl_vat,
                    "channel_fee_rate": line.channel_fee_rate,
                    "turnover_levy_rate": line.turnover_levy_rate,
                    "eligible_turnover_basis": line.eligible_turnover_basis,
                    "product_unit_cost": line.product_unit_cost,
                    "product_cost_mode": line.product_cost_mode,
                    "product_cost_rate": line.product_cost_rate,
                    "other_variable_unit_cost": line.other_variable_unit_cost,
                    "cost_source": line.cost_source, "cost_date": line.cost_date,
                    "exclude_product_cost": line.exclude_product_cost,
                } for line in scenario.line_ids],
                "costs": [{
                    "id": cost.id, "name": cost.name, "category": cost.category,
                    "calculation": cost.calculation, "quantity": cost.quantity,
                    "rate": cost.rate, "percentage": cost.percentage,
                    "amount": cost.planned_amount, "source_kind": cost.source_kind,
                    "assumption_date": cost.assumption_date,
                    "travel_estimate_id": cost.travel_estimate_id.id,
                    "source_reference": cost.source_reference,
                    "source_currency": cost.source_currency_id.name,
                    "source_amount": cost.source_amount,
                    "conversion_rate": cost.conversion_rate,
                    "conversion_date": cost.conversion_date,
                } for cost in scenario.cost_line_ids],
            } or False,
            "travel": self.travel_estimate_id and {
                "id": self.travel_estimate_id.id,
                "revision": self.travel_estimate_id.revision,
                "state": self.travel_estimate_id.state,
                "distance_km": self.travel_estimate_id.distance_km,
                "duration_hours": self.travel_estimate_id.duration_hours,
                "total_operating_cost": self.travel_estimate_id.total_operating_cost,
                "incomplete": self.travel_estimate_id.incomplete,
            } or False,
            "stock_targets": [{
                "id": target.id, "type": target.target_type,
                "product_id": target.product_id.id, "category_id": target.category_id.id,
                "required_qty": target.required_qty,
                "expected_sold_qty": target.expected_sold_qty,
                "expected_unit_price": target.expected_unit_price,
                "expected_unit_cost": target.expected_unit_cost,
                "cost_source": target.cost_source, "cost_date": target.cost_date,
                "supply_method": target.supply_method, "readiness": target.readiness,
            } for target in self.stock_plan_line_ids],
            "warnings": [
                {"code": code, "severity": severity, "message": message}
                for code, severity, message in self._get_planning_warnings(scenario)
            ],
            "actual": {
                "revenue": self.actual_revenue, "cost": self.actual_cost,
                "margin": self.actual_margin,
            } if kind == "outcome" else False,
        }

    def _planning_payload_digest(self, payload):
        digest_payload = json.loads(json.dumps(payload, default=str))
        digest_payload.get("operation", {}).pop("state", None)
        if digest_payload.get("kind") == "outcome":
            digest_payload.pop("actual", None)
        canonical = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _create_report_snapshot(self, kind):
        self.ensure_one()
        payload = self._planning_payload(kind)
        digest = self._planning_payload_digest(payload)
        previous = self.report_snapshot_ids.filtered(
            lambda snapshot: snapshot.report_kind == kind and snapshot.state == "current"
        )
        previous.with_context(mb_snapshot_token=_SNAPSHOT_TOKEN).write({"state": "superseded"})
        snapshot = self.env["mb.commercial.report.snapshot"].with_context(
            mb_snapshot_token=_SNAPSHOT_TOKEN
        ).create({
            "name": _("%(operation)s — %(kind)s r%(revision)s", operation=self.name,
                      kind=_("Planning") if kind == "planning" else _("Outcome"),
                      revision=self.planning_revision),
            "operation_id": self.id, "scenario_id": self.primary_scenario_id.id,
            "report_kind": kind, "revision": self.planning_revision,
            "payload": payload, "input_digest": digest,
        })
        report = self.env.ref(
            "mb_commercial_operations.action_report_commercial_operation"
            if kind == "planning"
            else "mb_commercial_operations.action_report_commercial_operation_outcome"
        )
        pdf, _content_type = report._render_qweb_pdf(
            report.report_name, self.ids, data={"report_kind": kind},
        )
        attachment = self.env["ir.attachment"].with_context(
            mb_snapshot_token=_SNAPSHOT_TOKEN
        ).create({
            "name": f"{snapshot.name}.pdf", "type": "binary", "datas": base64.b64encode(pdf),
            "mimetype": "application/pdf", "res_model": self._name,
            "res_id": self.id, "mb_commercial_report_snapshot_id": snapshot.id,
        })
        snapshot.with_context(mb_snapshot_token=_SNAPSHOT_TOKEN).write({
            "attachment_id": attachment.id, "pdf_digest": hashlib.sha256(pdf).hexdigest(),
        })
        self.message_post(
            body=Markup("%s <a href='/web/content/%s?download=true'>%s</a>") % (
                _("Frozen planning evidence created:"), attachment.id, snapshot.name,
            ),
            attachment_ids=[attachment.id],
        )
        return snapshot

    def action_complete_planning(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Complete Planning"),
            "res_model": "mb.commercial.operation.plan.wizard", "view_mode": "form",
            "target": "new", "context": {"default_operation_id": self.id},
        }

    def action_print_planning_pack(self):
        self.ensure_one()
        return self.env.ref("mb_commercial_operations.action_report_commercial_operation").report_action(
            self, data={"report_kind": "planning"},
        )

    def action_print_outcome_pack(self):
        self.ensure_one()
        if self.state not in ("done", "financially_closed"):
            raise UserError(_("Complete the operation before printing its outcome report."))
        return self.env.ref("mb_commercial_operations.action_report_commercial_operation_outcome").report_action(self)

    def action_freeze_replacement_copy(self):
        if not self.env.user.has_group("mb_commercial_operations.group_commercial_operations_manager"):
            raise AccessError(_("Only a Commercial Operations Manager can freeze a replacement copy."))
        self.ensure_one()
        snapshot = self.report_snapshot_ids.filtered(
            lambda item: item.report_kind == "planning" and item.state == "current"
        )[:1]
        if not snapshot:
            raise UserError(_("No current planning snapshot exists."))
        if self._planning_payload_digest(self._planning_payload("planning")) != snapshot.input_digest:
            raise ValidationError(_("Approved planning inputs changed; reopen and approve a new revision instead."))
        return self.with_context(mb_snapshot_creating=True)._create_report_snapshot("planning")


class MbCommercialPlanningWizard(models.TransientModel):
    _name = "mb.commercial.operation.plan.wizard"
    _description = "Complete Commercial Operation Planning"
    _check_company_auto = True

    operation_id = fields.Many2one("mb.commercial.operation", check_company=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    name = fields.Char(required=True, default=lambda self: _("New planned operation"))
    operation_type = fields.Selection(
        selection=lambda self: self.env["mb.commercial.operation"]._fields["operation_type"].selection,
        required=True, default="market",
    )
    partner_id = fields.Many2one("res.partner", required=True, check_company=True)
    organizer_id = fields.Many2one("res.partner", check_company=True)
    contract_id = fields.Many2one("mb.commercial.contract", check_company=True)
    user_ids = fields.Many2many("res.users")
    departure = fields.Datetime(required=True, default=fields.Datetime.now)
    expected_arrival = fields.Datetime()
    setup_duration_hours = fields.Float()
    service_start = fields.Datetime()
    service_end = fields.Datetime()
    teardown_duration_hours = fields.Float()
    expected_return = fields.Datetime()
    application_deadline = fields.Datetime()
    payment_deadline = fields.Datetime()
    template_id = fields.Many2one("mb.commercial.plan.template", check_company=True)
    scenario_name = fields.Char(required=True, default=lambda self: _("Planning scenario"))
    calculation_mode = fields.Selection(
        [("product_mix", "Product Mix"), ("average_basket", "Average Basket")],
        required=True, default="product_mix",
    )
    travel_estimate_id = fields.Many2one("mb.travel.estimate", check_company=True)
    connector_id = fields.Many2one("mb.tollquote.connector", check_company=True)
    origin_latitude = fields.Float(digits=(10, 7))
    origin_longitude = fields.Float(digits=(10, 7))
    destination_latitude = fields.Float(digits=(10, 7))
    destination_longitude = fields.Float(digits=(10, 7))
    round_trip = fields.Boolean(default=True)
    vehicle_class = fields.Integer(default=1)
    payment_option = fields.Integer(default=1)
    fuel_consumption_l_per_100km = fields.Float(default=7.0)
    fuel_price_eur_per_l = fields.Monetary(default=1.80)
    driver_cost_eur_per_hour = fields.Monetary()
    quote_calculated = fields.Boolean(readonly=True)
    quote_request_id = fields.Char(readonly=True)
    quote_provider_version = fields.Char(readonly=True)
    quote_distance_km = fields.Float(readonly=True)
    quote_duration_hours = fields.Float(readonly=True)
    quote_toll_cost = fields.Monetary(readonly=True)
    quote_fuel_cost = fields.Monetary(readonly=True)
    quote_driver_cost = fields.Monetary(readonly=True)
    quote_total_operating_cost = fields.Monetary(readonly=True)
    quote_reporting_currency = fields.Char(readonly=True)
    quote_incomplete = fields.Boolean(readonly=True)
    quote_warning_text = fields.Text(readonly=True)
    quote_request_snapshot = fields.Json(readonly=True)
    quote_response_snapshot = fields.Json(readonly=True)
    quote_conversion_rate = fields.Float(readonly=True, digits=(12, 6))
    quote_conversion_date = fields.Date(readonly=True)
    accept_quote = fields.Boolean()
    incomplete_quote_acknowledged = fields.Boolean()
    line_ids = fields.One2many("mb.commercial.operation.plan.wizard.line", "wizard_id")
    cost_ids = fields.One2many("mb.commercial.operation.plan.wizard.cost", "wizard_id")
    warning_summary = fields.Text(compute="_compute_warning_summary")
    preview_units = fields.Float(compute="_compute_preview", string="Planned Units / Baskets")
    preview_sales_excl_vat = fields.Monetary(
        compute="_compute_preview", string="Sales Excluding VAT",
    )
    preview_receipts_incl_vat = fields.Monetary(
        compute="_compute_preview", string="Customer Receipts Including VAT",
    )
    preview_fixed_cost = fields.Monetary(compute="_compute_preview", string="Known Fixed Cost")
    preview_variable_cost = fields.Monetary(
        compute="_compute_preview", string="Estimated Variable Cost",
    )
    preview_contribution = fields.Monetary(compute="_compute_preview", string="Contribution")
    preview_break_even_units = fields.Integer(
        compute="_compute_preview", string="Break-even Units / Baskets",
    )
    preview_break_even_sales = fields.Monetary(
        compute="_compute_preview", string="Break-even Sales Excluding VAT",
    )
    preview_break_even_receipts = fields.Monetary(
        compute="_compute_preview", string="Break-even Receipts Including VAT",
    )
    preview_projected_margin = fields.Monetary(
        compute="_compute_preview", string="Projected Margin",
    )
    preview_blocked = fields.Boolean(compute="_compute_preview")
    preview_note = fields.Char(compute="_compute_preview")

    @api.model
    def default_get(self, field_list):
        values = super().default_get(field_list)
        operation = self.env["mb.commercial.operation"].browse(values.get("operation_id"))
        if operation:
            values.update({
                "company_id": operation.company_id.id, "name": operation.name,
                "operation_type": operation.operation_type,
                "partner_id": operation.partner_id.id,
                "organizer_id": operation.organizer_id.id,
                "contract_id": operation.contract_id.id,
                "user_ids": [fields.Command.set(operation.user_ids.ids)],
                "departure": operation.planned_start,
                "expected_arrival": operation.expected_arrival,
                "setup_duration_hours": operation.setup_duration_hours,
                "service_start": operation.service_start,
                "service_end": operation.service_end,
                "teardown_duration_hours": operation.teardown_duration_hours,
                "expected_return": operation.expected_return or operation.planned_end,
                "application_deadline": operation.application_deadline,
                "payment_deadline": operation.payment_deadline,
            })
            values.setdefault("travel_estimate_id", operation.travel_estimate_id.id)
            estimate = operation.travel_estimate_id
            if estimate:
                values.update({
                    "connector_id": estimate.connector_id.id,
                    "origin_latitude": estimate.origin_latitude,
                    "origin_longitude": estimate.origin_longitude,
                    "destination_latitude": estimate.destination_latitude,
                    "destination_longitude": estimate.destination_longitude,
                    "round_trip": estimate.round_trip,
                    "vehicle_class": estimate.vehicle_class,
                    "payment_option": estimate.payment_option,
                    "fuel_consumption_l_per_100km": estimate.fuel_consumption_l_per_100km,
                    "fuel_price_eur_per_l": estimate.fuel_price_eur_per_l,
                    "driver_cost_eur_per_hour": estimate.driver_cost_eur_per_hour,
                })
            scenario = operation.primary_scenario_id
            if scenario:
                values.update({
                    "scenario_name": _("Revision of %s", scenario.name),
                    "calculation_mode": scenario.calculation_mode,
                    "line_ids": [fields.Command.create({
                        "product_id": line.product_id.id,
                        "source_stock_plan_line_id": line.source_stock_plan_line_id.id,
                        "expected_sold_qty": line.expected_sold_qty,
                        "sale_price_excluded_tax": line.sale_price_excluded_tax,
                        "vat_rate": line.vat_rate, "channel_fee_rate": line.channel_fee_rate,
                        "turnover_levy_rate": line.turnover_levy_rate,
                        "product_unit_cost": line.product_unit_cost,
                        "product_cost_mode": line.product_cost_mode,
                        "product_cost_rate": line.product_cost_rate,
                        "other_variable_unit_cost": line.other_variable_unit_cost,
                        "exclude_product_cost": line.exclude_product_cost,
                        "desired_opening_qty": line.source_stock_plan_line_id.desired_opening_qty,
                        "safety_qty": line.source_stock_plan_line_id.safety_qty,
                    }) for line in scenario.line_ids],
                    "cost_ids": [fields.Command.create({
                        "name": line.name, "category": line.category,
                        "calculation": line.calculation, "quantity": line.quantity,
                        "rate": line.rate, "percentage": line.percentage,
                        "source_kind": line.source_kind,
                    }) for line in scenario.cost_line_ids],
                })
            elif operation.stock_plan_line_ids:
                values["line_ids"] = [fields.Command.create({
                    "product_id": target.product_id.id,
                    "source_stock_plan_line_id": target.id,
                    "expected_sold_qty": target.expected_sold_qty,
                    "sale_price_excluded_tax": target.expected_unit_price,
                    "product_unit_cost": target.expected_unit_cost,
                    "desired_opening_qty": target.desired_opening_qty,
                    "safety_qty": target.safety_qty,
                }) for target in operation.stock_plan_line_ids.filtered(
                    lambda target: target.target_type == "product"
                )]
        return values

    def _new_preview_scenario(self):
        """Build an in-memory scenario so preview and saved records use one engine."""
        self.ensure_one()
        operation = self.operation_id or self.env["mb.commercial.operation"].new({
            "company_id": self.company_id,
        })
        scenario = self.env["mb.commercial.profitability.scenario"].new({
            "operation_id": operation,
            "calculation_mode": self.calculation_mode,
            "travel_estimate_id": self.travel_estimate_id,
            "line_ids": [
                fields.Command.create(line._scenario_values()) for line in self.line_ids
            ],
        })
        scenario.cost_line_ids = [fields.Command.create({
            **line._cost_values(operation),
            "scenario_id": scenario,
        }) for line in self.cost_ids]
        scenario.cost_line_ids._compute_planned_amount()
        scenario._compute_results()
        scenario.cost_line_ids._compute_planned_amount()
        scenario._compute_results()
        return scenario

    @api.depends(
        "company_id", "operation_id", "calculation_mode", "travel_estimate_id",
        "line_ids.expected_sold_qty", "line_ids.sale_price_excluded_tax",
        "line_ids.vat_rate", "line_ids.channel_fee_rate",
        "line_ids.turnover_levy_rate", "line_ids.product_unit_cost",
        "line_ids.product_cost_mode", "line_ids.product_cost_rate",
        "line_ids.other_variable_unit_cost", "line_ids.exclude_product_cost",
        "cost_ids.calculation", "cost_ids.quantity", "cost_ids.rate",
        "cost_ids.percentage",
    )
    def _compute_preview(self):
        for wizard in self:
            scenario = wizard._new_preview_scenario()
            wizard.preview_units = scenario.planned_units
            wizard.preview_sales_excl_vat = scenario.sales_revenue_excl_vat
            wizard.preview_receipts_incl_vat = scenario.customer_receipts_incl_vat
            wizard.preview_fixed_cost = scenario.fixed_event_cost
            wizard.preview_variable_cost = scenario.total_variable_cost
            wizard.preview_contribution = scenario.projected_contribution
            wizard.preview_break_even_units = scenario.break_even_units
            wizard.preview_break_even_sales = scenario.break_even_sales_excl_vat
            wizard.preview_break_even_receipts = scenario.break_even_customer_receipts_incl_vat
            wizard.preview_projected_margin = scenario.projected_margin
            wizard.preview_blocked = scenario.calculation_blocked
            wizard.preview_note = scenario.calculation_note

    @api.depends("operation_id", "preview_blocked", "preview_note")
    def _compute_warning_summary(self):
        for wizard in self:
            messages = []
            if wizard.preview_blocked and wizard.preview_note:
                messages.append(_("BLOCKING — %s", wizard.preview_note))
            if wizard.operation_id.planning_warning_summary:
                messages.append(wizard.operation_id.planning_warning_summary)
            wizard.warning_summary = "\n".join(messages)

    @api.onchange("template_id")
    def _onchange_template_id(self):
        if not self.template_id:
            return
        self.calculation_mode = self.template_id.calculation_mode
        self.setup_duration_hours = self.template_id.default_setup_hours
        self.teardown_duration_hours = self.template_id.default_teardown_hours
        self.driver_cost_eur_per_hour = self.template_id.default_travel_hourly_cost
        self.fuel_consumption_l_per_100km = (
            self.template_id.default_fuel_consumption_l_per_100km
        )
        self.fuel_price_eur_per_l = self.template_id.default_fuel_price_eur_per_l
        if self.service_start and self.template_id.default_service_hours:
            self.service_end = fields.Datetime.add(
                self.service_start, hours=self.template_id.default_service_hours,
            )
        if self.departure and self.template_id.default_duration_hours:
            self.expected_return = fields.Datetime.add(
                self.departure, hours=self.template_id.default_duration_hours,
            )
        self.line_ids = [fields.Command.clear()] + [fields.Command.create({
            "product_id": line.product_id.id, "expected_sold_qty": line.expected_sold_qty,
            "sale_price_excluded_tax": line.sale_price_excluded_tax or line.product_id.lst_price,
            "product_unit_cost": line.product_unit_cost or line.product_id.standard_price,
            "desired_opening_qty": line.desired_opening_qty,
            "safety_qty": line.safety_qty,
        }) for line in self.template_id.product_line_ids]
        self.cost_ids = [fields.Command.clear()] + [fields.Command.create({
            "name": line.name, "category": line.category, "calculation": line.calculation,
            "quantity": line.quantity, "rate": line.rate, "percentage": line.percentage,
            "source_kind": "template",
        }) for line in self.template_id.cost_line_ids]
        if self.template_id.default_labour_hourly_cost and not self.template_id.cost_line_ids.filtered(
            lambda line: line.category == "labour"
        ):
            self.cost_ids = [fields.Command.create({
                "name": _("Planned labour"), "category": "labour",
                "calculation": "hour",
                "quantity": self.template_id.default_duration_hours,
                "rate": self.template_id.default_labour_hourly_cost,
                "source_kind": "template",
            })]

    def action_save_draft(self):
        self.ensure_one()
        operation = self.operation_id
        if operation and operation.state not in ("draft", "quoted"):
            raise UserError(_("Reopen the operation before changing its planning baseline."))
        operation_values = self._operation_values()
        if operation:
            operation.write(operation_values)
        else:
            operation = self.env["mb.commercial.operation"].with_company(self.company_id).create(operation_values)
            self.operation_id = operation
        scenario_line_values = []
        for line in self.line_ids:
            target = line.source_stock_plan_line_id
            if self.calculation_mode == "product_mix" and line.product_id:
                target_values = {
                    "operation_id": operation.id, "target_type": "product",
                    "product_id": line.product_id.id,
                    "desired_opening_qty": line.desired_opening_qty,
                    "safety_qty": line.safety_qty,
                    "expected_sold_qty": line.expected_sold_qty,
                    "expected_unit_price": line.sale_price_excluded_tax,
                    "expected_unit_cost": line.product_unit_cost,
                    "cost_source": "product", "cost_date": fields.Date.context_today(self),
                }
                if target and target.operation_id == operation:
                    target.write(target_values)
                else:
                    target = self.env["mb.market.stock.plan.line"].create(target_values)
                line.source_stock_plan_line_id = target
            values = line._scenario_values()
            values["source_stock_plan_line_id"] = target.id
            scenario_line_values.append(fields.Command.create(values))
        scenario = self.env["mb.commercial.profitability.scenario"].create({
            "name": self.scenario_name, "operation_id": operation.id,
            "calculation_mode": self.calculation_mode,
            "travel_estimate_id": self.travel_estimate_id.id,
            "line_ids": scenario_line_values,
        })
        scenario.cost_line_ids = [fields.Command.create(line._cost_values(operation)) for line in self.cost_ids]
        operation.write({
            "primary_scenario_id": scenario.id,
            "travel_estimate_id": self.travel_estimate_id.id,
            "expected_revenue": scenario.sales_revenue_excl_vat,
        })
        self._after_operation_saved(operation, scenario)
        return {
            "type": "ir.actions.act_window", "res_model": operation._name,
            "res_id": operation.id, "view_mode": "form", "target": "current",
        }

    def _operation_values(self):
        self.ensure_one()
        return {
            "name": self.name, "company_id": self.company_id.id,
            "operation_type": self.operation_type, "partner_id": self.partner_id.id,
            "organizer_id": self.organizer_id.id, "contract_id": self.contract_id.id,
            "user_ids": [fields.Command.set(self.user_ids.ids)],
            "planned_start": self.departure,
            "planned_end": self.expected_return or self.service_end or fields.Datetime.add(self.departure, hours=7),
            "expected_arrival": self.expected_arrival,
            "setup_duration_hours": self.setup_duration_hours,
            "service_start": self.service_start, "service_end": self.service_end,
            "teardown_duration_hours": self.teardown_duration_hours,
            "expected_return": self.expected_return,
            "application_deadline": self.application_deadline,
            "payment_deadline": self.payment_deadline,
            "profitability_required": self.operation_type == "market",
        }

    def _after_operation_saved(self, operation, scenario):
        if self.quote_calculated:
            estimate = self._persist_transient_quote(operation)
            scenario.travel_estimate_id = estimate
            if self.accept_quote:
                if estimate.incomplete and not self.incomplete_quote_acknowledged:
                    raise ValidationError(_("Acknowledge incomplete TollQuote pricing before accepting it."))
                estimate.incomplete_acknowledged = self.incomplete_quote_acknowledged
                estimate.action_accept()
                if not scenario.cost_line_ids.filtered(lambda line: line.category == "travel"):
                    self.env["mb.commercial.cost.line"].create({
                        "operation_id": operation.id, "scenario_id": scenario.id,
                        "name": _("Accepted TollQuote travel total"), "category": "travel",
                        "calculation": "fixed", "quantity": 1,
                        "rate": estimate.total_operating_cost,
                        "source_kind": "travel", "travel_estimate_id": estimate.id,
                        "assumption_date": estimate.conversion_date,
                        "source_reference": estimate.request_id,
                        "source_currency_id": estimate.currency_id.id,
                        "source_amount": estimate.total_operating_cost,
                        "conversion_rate": estimate.conversion_rate or 1.0,
                        "conversion_date": estimate.conversion_date,
                    })
        self._sync_deadline_activity(operation, _("Commercial application deadline"), self.application_deadline)
        self._sync_deadline_activity(operation, _("Commercial payment deadline"), self.payment_deadline)
        return None

    def action_calculate_travel(self):
        self.ensure_one()
        if not self.connector_id:
            raise ValidationError(_("Choose a TollQuote connector."))
        if (not self.origin_latitude and not self.origin_longitude) or (
            not self.destination_latitude and not self.destination_longitude
        ):
            raise ValidationError(_("Enter usable origin and destination coordinates."))
        estimate = self.env["mb.travel.estimate"].new({
            "company_id": self.company_id.id, "connector_id": self.connector_id.id,
            "origin_latitude": self.origin_latitude, "origin_longitude": self.origin_longitude,
            "destination_latitude": self.destination_latitude,
            "destination_longitude": self.destination_longitude,
            "round_trip": self.round_trip, "departure_at": self.departure,
            "vehicle_class": self.vehicle_class, "payment_option": self.payment_option,
            "fuel_consumption_l_per_100km": self.fuel_consumption_l_per_100km,
            "fuel_price_eur_per_l": self.fuel_price_eur_per_l,
            "driver_cost_eur_per_hour": self.driver_cost_eur_per_hour,
        })
        estimate._calculate_current_revision()
        self.write({
            "quote_calculated": True, "quote_request_id": estimate.request_id,
            "quote_provider_version": estimate.provider_version,
            "quote_distance_km": estimate.distance_km,
            "quote_duration_hours": estimate.duration_hours,
            "quote_toll_cost": estimate.toll_cost, "quote_fuel_cost": estimate.fuel_cost,
            "quote_driver_cost": estimate.driver_cost,
            "quote_total_operating_cost": estimate.total_operating_cost,
            "quote_reporting_currency": estimate.reporting_currency,
            "quote_incomplete": estimate.incomplete,
            "quote_warning_text": estimate.warning_text,
            "quote_request_snapshot": estimate.request_snapshot,
            "quote_response_snapshot": estimate.response_snapshot,
            "quote_conversion_rate": estimate.conversion_rate,
            "quote_conversion_date": estimate.conversion_date,
            "accept_quote": False, "incomplete_quote_acknowledged": False,
        })
        return {
            "type": "ir.actions.act_window", "name": _("Complete Planning"),
            "res_model": self._name, "res_id": self.id, "view_mode": "form", "target": "new",
        }

    def _persist_transient_quote(self, operation):
        self.ensure_one()
        previous = operation.travel_estimate_id
        values = {
            "company_id": self.company_id.id, "connector_id": self.connector_id.id,
            "operation_id": operation.id, "origin_partner_id": operation.company_id.partner_id.id,
            "destination_partner_id": operation.partner_id.id,
            "origin_latitude": self.origin_latitude, "origin_longitude": self.origin_longitude,
            "destination_latitude": self.destination_latitude,
            "destination_longitude": self.destination_longitude,
            "round_trip": self.round_trip, "departure_at": self.departure,
            "vehicle_class": self.vehicle_class, "payment_option": self.payment_option,
            "fuel_consumption_l_per_100km": self.fuel_consumption_l_per_100km,
            "fuel_price_eur_per_l": self.fuel_price_eur_per_l,
            "driver_cost_eur_per_hour": self.driver_cost_eur_per_hour,
            "state": "quoted", "revision": previous.revision + 1 if previous else 1,
            "previous_revision_id": previous.id,
            "request_id": self.quote_request_id,
            "provider_version": self.quote_provider_version,
            "calculated_at": fields.Datetime.now(),
            "distance_km": self.quote_distance_km,
            "duration_hours": self.quote_duration_hours,
            "toll_cost": self.quote_toll_cost, "fuel_cost": self.quote_fuel_cost,
            "driver_cost": self.quote_driver_cost,
            "total_operating_cost": self.quote_total_operating_cost,
            "reporting_currency": self.quote_reporting_currency,
            "incomplete": self.quote_incomplete,
            "warning_text": self.quote_warning_text,
            "request_snapshot": self.quote_request_snapshot,
            "response_snapshot": self.quote_response_snapshot,
            "conversion_rate": self.quote_conversion_rate,
            "conversion_date": self.quote_conversion_date,
        }
        return self.env["mb.travel.estimate"].create(values)

    def _sync_deadline_activity(self, operation, summary, deadline):
        activity_type = self.env.ref("mail.mail_activity_data_todo")
        existing = operation.activity_ids.filtered(
            lambda activity: activity.activity_type_id == activity_type and activity.summary == summary
        )
        if not deadline:
            existing.unlink()
            return
        values = {
            "date_deadline": fields.Date.to_date(deadline),
            "user_id": operation.user_ids[:1].id or self.env.user.id,
            "summary": summary,
        }
        if existing:
            existing.write(values)
        else:
            operation.activity_schedule(activity_type.id, **values)

    def action_save_and_approve(self):
        action = self.action_save_draft()
        self.operation_id.action_approve()
        return action


class MbCommercialPlanningWizardLine(models.TransientModel):
    _name = "mb.commercial.operation.plan.wizard.line"
    _description = "Commercial Planning Product Assumption"

    wizard_id = fields.Many2one("mb.commercial.operation.plan.wizard", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    product_id = fields.Many2one("product.product")
    source_stock_plan_line_id = fields.Many2one("mb.market.stock.plan.line")
    expected_sold_qty = fields.Float(default=1.0)
    sale_price_excluded_tax = fields.Monetary()
    vat_rate = fields.Float()
    channel_fee_rate = fields.Float()
    turnover_levy_rate = fields.Float()
    product_unit_cost = fields.Monetary()
    product_cost_mode = fields.Selection(
        [("amount", "Amount"), ("sales_percent", "% of sales excluding VAT")],
        required=True, default="amount",
    )
    product_cost_rate = fields.Float()
    other_variable_unit_cost = fields.Monetary()
    exclude_product_cost = fields.Boolean()
    desired_opening_qty = fields.Float(default=1.0)
    safety_qty = fields.Float()

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.sale_price_excluded_tax = self.product_id.lst_price
            self.product_unit_cost = self.product_id.standard_price

    def _scenario_values(self):
        self.ensure_one()
        return {
            "product_id": self.product_id.id,
            "source_stock_plan_line_id": self.source_stock_plan_line_id.id,
            "expected_sold_qty": self.expected_sold_qty,
            "sale_price_excluded_tax": self.sale_price_excluded_tax,
            "vat_rate": self.vat_rate, "channel_fee_rate": self.channel_fee_rate,
            "turnover_levy_rate": self.turnover_levy_rate,
            "product_unit_cost": self.product_unit_cost,
            "product_cost_mode": self.product_cost_mode,
            "product_cost_rate": self.product_cost_rate,
            "other_variable_unit_cost": self.other_variable_unit_cost,
            "exclude_product_cost": self.exclude_product_cost,
            "eligible_turnover_basis": self.sale_price_excluded_tax,
            "cost_source": "product", "cost_date": fields.Date.context_today(self),
        }


class MbCommercialPlanningWizardCost(models.TransientModel):
    _name = "mb.commercial.operation.plan.wizard.cost"
    _description = "Commercial Planning Cost Assumption"

    wizard_id = fields.Many2one("mb.commercial.operation.plan.wizard", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    name = fields.Char(required=True)
    category = fields.Selection(selection=lambda self: self.env["mb.commercial.cost.line"]._fields["category"].selection, required=True)
    calculation = fields.Selection(selection=lambda self: self.env["mb.commercial.cost.line"]._fields["calculation"].selection, required=True)
    quantity = fields.Float(default=1.0)
    rate = fields.Monetary()
    percentage = fields.Float()
    source_kind = fields.Selection(selection=lambda self: self.env["mb.commercial.cost.line"]._fields["source_kind"].selection, default="manual")

    def _cost_values(self, operation):
        self.ensure_one()
        return {
            "operation_id": operation.id, "name": self.name, "category": self.category,
            "calculation": self.calculation, "quantity": self.quantity, "rate": self.rate,
            "percentage": self.percentage, "source_kind": self.source_kind,
            "assumption_date": fields.Date.context_today(self),
        }


class CommercialOperationReport(models.AbstractModel):
    _name = "report.mb_commercial_operations.report_commercial_operation"
    _description = "Commercial Operation Report Values"

    @api.model
    def _get_report_values(self, docids, data=None):
        operations = self.env["mb.commercial.operation"].browse(docids)
        kind = (data or {}).get("report_kind", "planning")
        return {"doc_ids": docids, "doc_model": operations._name, "docs": operations, "report_kind": kind}


class CommercialOperationOutcomeReport(models.AbstractModel):
    _name = "report.mb_commercial_operations.operation_outcome"
    _description = "Commercial Operation Outcome Report Values"

    @api.model
    def _get_report_values(self, docids, data=None):
        operations = self.env["mb.commercial.operation"].browse(docids)
        return {"doc_ids": docids, "doc_model": operations._name, "docs": operations, "report_kind": "outcome"}
