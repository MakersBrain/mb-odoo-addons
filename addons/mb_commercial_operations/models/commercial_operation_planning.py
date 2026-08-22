"""The planning and evidence surface of `mb.commercial.operation`.

Kept apart from `commercial_operation.py`, which owns the record's own
fields and lifecycle. This half is about producing a plan and freezing the
evidence for it, and it is the only part that holds the snapshot token.
"""

import base64
import hashlib
import json

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .snapshot_token import SNAPSHOT_TOKEN


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
                "id": self.id,
                "name": self.name,
                "type": self.operation_type,
                "state": self.state,
                "revision": self.planning_revision,
                "partner": self.partner_id.display_name,
                "planned_start": fields.Datetime.to_string(self.planned_start),
                "planned_end": fields.Datetime.to_string(self.planned_end),
                "expected_arrival": fields.Datetime.to_string(self.expected_arrival),
                "service_start": fields.Datetime.to_string(self.service_start),
                "service_end": fields.Datetime.to_string(self.service_end),
                "expected_return": fields.Datetime.to_string(self.expected_return),
                "responsible_user_ids": self.user_ids.ids,
            },
            "scenario": scenario
            and {
                "id": scenario.id,
                "name": scenario.name,
                "sales_excl_vat": scenario.sales_revenue_excl_vat,
                "receipts_incl_vat": scenario.customer_receipts_incl_vat,
                "fixed_cost": scenario.fixed_event_cost,
                "variable_cost": scenario.total_variable_cost,
                "break_even_units": scenario.break_even_units,
                "break_even_sales_excl_vat": scenario.break_even_sales_excl_vat,
                "break_even_receipts_incl_vat": scenario.break_even_customer_receipts_incl_vat,
                "projected_margin": scenario.projected_margin,
                "lines": [
                    {
                        "id": line.id,
                        "product_id": line.product_id.id,
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
                        "cost_source": line.cost_source,
                        "cost_date": line.cost_date,
                        "exclude_product_cost": line.exclude_product_cost,
                    }
                    for line in scenario.line_ids
                ],
                "costs": [
                    {
                        "id": cost.id,
                        "name": cost.name,
                        "category": cost.category,
                        "calculation": cost.calculation,
                        "quantity": cost.quantity,
                        "rate": cost.rate,
                        "percentage": cost.percentage,
                        "amount": cost.planned_amount,
                        "source_kind": cost.source_kind,
                        "assumption_date": cost.assumption_date,
                        "travel_estimate_id": cost.travel_estimate_id.id,
                        "source_reference": cost.source_reference,
                        "source_currency": cost.source_currency_id.name,
                        "source_amount": cost.source_amount,
                        "conversion_rate": cost.conversion_rate,
                        "conversion_date": cost.conversion_date,
                    }
                    for cost in scenario.cost_line_ids
                ],
            }
            or False,
            "travel": self.travel_estimate_id
            and {
                "id": self.travel_estimate_id.id,
                "revision": self.travel_estimate_id.revision,
                "state": self.travel_estimate_id.state,
                "distance_km": self.travel_estimate_id.distance_km,
                "duration_hours": self.travel_estimate_id.duration_hours,
                "total_operating_cost": self.travel_estimate_id.total_operating_cost,
                "incomplete": self.travel_estimate_id.incomplete,
            }
            or False,
            "stock_targets": [
                {
                    "id": target.id,
                    "type": target.target_type,
                    "product_id": target.product_id.id,
                    "category_id": target.category_id.id,
                    "required_qty": target.required_qty,
                    "expected_sold_qty": target.expected_sold_qty,
                    "expected_unit_price": target.expected_unit_price,
                    "expected_unit_cost": target.expected_unit_cost,
                    "cost_source": target.cost_source,
                    "cost_date": target.cost_date,
                    "supply_method": target.supply_method,
                    "readiness": target.readiness,
                }
                for target in self.stock_plan_line_ids
            ],
            "warnings": [
                {"code": code, "severity": severity, "message": message}
                for code, severity, message in self._get_planning_warnings(scenario)
            ],
            "actual": {
                "revenue": self.actual_revenue,
                "cost": self.actual_cost,
                "margin": self.actual_margin,
            }
            if kind == "outcome"
            else False,
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
        previous.with_context(mb_snapshot_token=SNAPSHOT_TOKEN).write({"state": "superseded"})
        snapshot = (
            self.env["mb.commercial.report.snapshot"]
            .with_context(mb_snapshot_token=SNAPSHOT_TOKEN)
            .create(
                {
                    "name": _(
                        "%(operation)s — %(kind)s r%(revision)s",
                        operation=self.name,
                        kind=_("Planning") if kind == "planning" else _("Outcome"),
                        revision=self.planning_revision,
                    ),
                    "operation_id": self.id,
                    "scenario_id": self.primary_scenario_id.id,
                    "report_kind": kind,
                    "revision": self.planning_revision,
                    "payload": payload,
                    "input_digest": digest,
                }
            )
        )
        report = self.env.ref(
            "mb_commercial_operations.action_report_commercial_operation"
            if kind == "planning"
            else "mb_commercial_operations.action_report_commercial_operation_outcome"
        )
        pdf, _content_type = report._render_qweb_pdf(
            report.report_name,
            self.ids,
            data={"report_kind": kind},
        )
        attachment = (
            self.env["ir.attachment"]
            .with_context(mb_snapshot_token=SNAPSHOT_TOKEN)
            .create(
                {
                    "name": f"{snapshot.name}.pdf",
                    "type": "binary",
                    "datas": base64.b64encode(pdf),
                    "mimetype": "application/pdf",
                    "res_model": self._name,
                    "res_id": self.id,
                    "mb_commercial_report_snapshot_id": snapshot.id,
                }
            )
        )
        snapshot.with_context(mb_snapshot_token=SNAPSHOT_TOKEN).write(
            {
                "attachment_id": attachment.id,
                "pdf_digest": hashlib.sha256(pdf).hexdigest(),
            }
        )
        self.message_post(
            body=Markup("%s <a href='/web/content/%s?download=true'>%s</a>")
            % (
                _("Frozen planning evidence created:"),
                attachment.id,
                snapshot.name,
            ),
            attachment_ids=[attachment.id],
        )
        return snapshot

    def action_complete_planning(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Complete Planning"),
            "res_model": "mb.commercial.operation.plan.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_operation_id": self.id},
        }

    def action_print_planning_pack(self):
        self.ensure_one()
        return self.env.ref(
            "mb_commercial_operations.action_report_commercial_operation"
        ).report_action(
            self,
            data={"report_kind": "planning"},
        )

    def action_print_outcome_pack(self):
        self.ensure_one()
        if self.state not in ("done", "financially_closed"):
            raise UserError(_("Complete the operation before printing its outcome report."))
        return self.env.ref(
            "mb_commercial_operations.action_report_commercial_operation_outcome"
        ).report_action(self)

    def action_freeze_replacement_copy(self):
        if not self.env.user.has_group(
            "mb_commercial_operations.group_commercial_operations_manager"
        ):
            raise AccessError(
                _("Only a Commercial Operations Manager can freeze a replacement copy.")
            )
        self.ensure_one()
        snapshot = self.report_snapshot_ids.filtered(
            lambda item: item.report_kind == "planning" and item.state == "current"
        )[:1]
        if not snapshot:
            raise UserError(_("No current planning snapshot exists."))
        if (
            self._planning_payload_digest(self._planning_payload("planning"))
            != snapshot.input_digest
        ):
            raise ValidationError(
                _("Approved planning inputs changed; reopen and approve a new revision instead.")
            )
        return self.with_context(mb_snapshot_creating=True)._create_report_snapshot("planning")
