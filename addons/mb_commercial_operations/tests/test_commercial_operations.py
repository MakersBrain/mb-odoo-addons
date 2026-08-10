from datetime import datetime, timedelta
from unittest.mock import patch

import requests

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCommercialOperations(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env["res.partner"].create({
            "name": "Market Hall",
            "company_id": cls.company.id,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Stoneware Mug",
            "list_price": 40.0,
            "standard_price": 10.0,
        })
        cls.manager = cls.env["res.users"].create({
            "name": "Operations Manager",
            "login": "commercial-manager",
            "group_ids": [fields.Command.set([
                cls.env.ref("base.group_user").id,
                cls.env.ref("mb_commercial_operations.group_commercial_operations_manager").id,
                cls.env.ref("account.group_account_manager").id,
            ])],
        })

    def _operation(self, **values):
        start = fields.Datetime.now() + timedelta(days=30)
        return self.env["mb.commercial.operation"].create({
            "name": "Autumn Market",
            "company_id": self.company.id,
            "partner_id": self.partner.id,
            "planned_start": start,
            "planned_end": start + timedelta(hours=8),
            **values,
        })

    def test_operation_creates_native_project_account_and_task(self):
        operation = self._operation()
        self.assertTrue(operation.project_id)
        self.assertTrue(operation.project_id.account_id)
        self.assertTrue(operation.task_id)
        self.assertEqual(operation.task_id.mb_commercial_operation_id, operation)
        self.assertEqual(operation.task_id.date_deadline, operation.planned_end)

    def test_unsaved_operation_has_zero_actual_profit(self):
        operation = self.env["mb.commercial.operation"].new({})

        self.assertEqual(operation.actual_revenue, 0.0)
        self.assertEqual(operation.actual_cost, 0.0)
        self.assertEqual(operation.actual_margin, 0.0)

    def test_contract_occurrences_are_generated_ahead_and_idempotent(self):
        contract = self.env["mb.commercial.contract"].create({
            "partner_id": self.partner.id,
            "company_id": self.company.id,
            "date_start": fields.Date.today().replace(day=1),
            "rent_billing_method": "information",
        })
        obligation = self.env["mb.commercial.obligation"].create({
            "name": "Two permanence days",
            "contract_id": contract.id,
            "date_start": contract.date_start,
            "required_occurrences": 2,
            "horizon_months": 6,
            "preferred_weekday": "5",
        })
        before = len(obligation.occurrence_ids)
        self.assertGreaterEqual(before, 12)
        obligation._generate_occurrences()
        self.assertEqual(len(obligation.occurrence_ids), before)
        first = obligation.occurrence_ids.sorted("planned_start")[0]
        first.action_approve()
        self.assertEqual(first.state, "approved")
        self.assertTrue(first.operation_id)
        self.assertTrue(first.task_id)

    def test_approved_occurrence_is_immutable(self):
        contract = self.env["mb.commercial.contract"].create({
            "partner_id": self.partner.id,
            "company_id": self.company.id,
            "date_start": fields.Date.today(),
            "rent_billing_method": "information",
        })
        obligation = self.env["mb.commercial.obligation"].create({
            "name": "Visit",
            "contract_id": contract.id,
            "date_start": contract.date_start,
        })
        occurrence = obligation.occurrence_ids[:1]
        occurrence.action_approve()
        with self.assertRaises(UserError):
            occurrence.planned_start += timedelta(days=1)

    def test_break_even_uses_percentage_and_hourly_amounts_once(self):
        operation = self._operation()
        scenario = self.env["mb.commercial.profitability.scenario"].create({
            "operation_id": operation.id,
            "route_cost_mode": "components",
            "toll_cost": 20.0,
            "fuel_cost": 30.0,
            "planned_travel_hours": 2.0,
            "travel_hourly_cost": 15.0,
            "planned_work_hours": 8.0,
            "work_hourly_cost": 20.0,
            "stall_rent": 60.0,
            "line_ids": [fields.Command.create({
                "product_id": self.product.id,
                "mix_share": 100.0,
                "sale_price_excluded_tax": 40.0,
                "channel_fee_rate": 2.5,
                "product_unit_cost": 10.0,
                "other_variable_unit_cost": 1.0,
                "cost_source": "product",
                "cost_date": fields.Date.today(),
            })],
        })
        self.assertEqual(scenario.accepted_travel_cost, 80.0)
        self.assertEqual(scenario.fixed_event_cost, 300.0)
        self.assertEqual(scenario.line_ids.channel_fee_amount, 1.0)
        self.assertEqual(scenario.weighted_unit_contribution, 28.0)
        self.assertEqual(scenario.break_even_units, 11)
        scenario.action_approve()
        with self.assertRaises(UserError):
            scenario.stall_rent = 70.0

    def test_invalid_mix_and_nonpositive_contribution_block_approval(self):
        operation = self._operation()
        scenario = self.env["mb.commercial.profitability.scenario"].create({
            "operation_id": operation.id,
            "manual_travel_total": 20.0,
            "line_ids": [fields.Command.create({
                "product_id": self.product.id,
                "mix_share": 50.0,
                "sale_price_excluded_tax": 10.0,
                "product_unit_cost": 10.0,
                "cost_source": "product",
                "cost_date": fields.Date.today(),
            })],
        })
        self.assertTrue(scenario.calculation_blocked)
        with self.assertRaises(ValidationError):
            scenario.action_approve()

    def test_overlapping_stock_targets_must_be_allocated(self):
        operation = self._operation()
        bucket = self.env["mb.market.stock.plan.line"].create({
            "operation_id": operation.id,
            "target_type": "bucket",
            "category_id": self.product.categ_id.id,
            "price_min": 20,
            "price_max": 50,
            "expected_unit_price": 35,
        })
        exact = self.env["mb.market.stock.plan.line"].create({
            "operation_id": operation.id,
            "target_type": "product",
            "product_id": self.product.id,
            "expected_unit_price": 40,
        })
        with self.assertRaises(ValidationError):
            operation.action_approve()
        exact.bucket_line_id = bucket
        operation.action_approve()
        self.assertEqual(operation.state, "approved")

    def test_user_conflict_requires_acknowledgement(self):
        start = fields.Datetime.now() + timedelta(days=10)
        self._operation(
            user_ids=[fields.Command.set([self.manager.id])],
            planned_start=start,
            planned_end=start + timedelta(hours=4),
        ).action_approve()
        conflict = self._operation(
            name="Conflicting market",
            user_ids=[fields.Command.set([self.manager.id])],
            planned_start=start + timedelta(hours=2),
            planned_end=start + timedelta(hours=5),
        )
        with self.assertRaises(ValidationError):
            conflict.action_approve()
        conflict.conflict_acknowledged = True
        conflict.action_approve()

    def test_financial_close_does_not_freeze_later_document_payment_state(self):
        operation = self._operation(documents_expected=False)
        operation.action_approve()
        operation.action_done()
        operation.with_user(self.manager).action_financial_close()
        self.assertEqual(operation.state, "financially_closed")
        self.assertTrue(operation.documents_complete)
        with self.assertRaises(UserError):
            operation.planned_end += timedelta(days=1)

    def test_travel_quote_incomplete_requires_acknowledgement_and_revisions(self):
        connector = self.env["mb.tollquote.connector"].create({
            "name": "Stage",
            "company_id": self.company.id,
            "api_token": "secret",
        })
        operation = self._operation()
        estimate = self.env["mb.travel.estimate"].create({
            "connector_id": connector.id,
            "operation_id": operation.id,
            "origin_latitude": 48.8566,
            "origin_longitude": 2.3522,
            "destination_latitude": 49.2583,
            "destination_longitude": 4.0317,
        })
        route = {"response": {"trip": {
            "summary": {"length": 100.0, "time": 3600},
            "legs": [{"shape": "encoded-polyline6"}],
        }}}
        quote = {
            "request_id": "00000000-0000-0000-0000-000000000001",
            "reporting_currency": "EUR",
            "totals": {"gross": {"value": "12.50", "currency": "EUR"}},
            "warnings": ["partial"],
            "unpriced": [{"gate": "unknown"}],
        }
        with patch.object(type(connector), "_request", autospec=True, side_effect=[route, quote, route, quote]):
            estimate.action_calculate()
        self.assertEqual(estimate.state, "quoted")
        self.assertTrue(estimate.incomplete)
        self.assertEqual(estimate.distance_km, 200.0)
        with self.assertRaises(ValidationError):
            estimate.action_accept()
        estimate.incomplete_acknowledged = True
        estimate.action_accept()
        self.assertEqual(operation.travel_estimate_id, estimate)
        with patch.object(type(connector), "_request", autospec=True, side_effect=[route, quote, route, quote]):
            action = estimate.action_calculate()
        revision = self.env["mb.travel.estimate"].browse(action["res_id"])
        self.assertEqual(revision.revision, 2)
        self.assertEqual(estimate.state, "accepted")

    def test_tollquote_errors_are_sanitized_and_user_readable(self):
        connector = self.env["mb.tollquote.connector"].create({
            "name": "Stage error cases",
            "company_id": self.company.id,
            "api_token": "never-leak-this-token",
        })
        cases = [
            (requests.Timeout(), "timed out"),
            (requests.HTTPError(response=type("Response", (), {"status_code": 401})()), "credential"),
            (requests.HTTPError(response=type("Response", (), {"status_code": 429})()), "quota"),
            (requests.HTTPError(response=type("Response", (), {"status_code": 503})()), "503"),
            (ValueError("malformed"), "invalid response"),
        ]
        for error, expected in cases:
            response = type("FakeResponse", (), {
                "raise_for_status": lambda self, issue=error: (_ for _ in ()).throw(issue),
                "json": lambda self: {},
            })()
            with self.subTest(expected=expected), patch(
                "odoo.addons.mb_commercial_operations.models.travel_estimate.requests.request",
                return_value=response,
            ), self.assertRaises(UserError) as raised:
                connector._request("GET", "/ready")
            message = str(raised.exception)
            self.assertIn(expected, message)
            self.assertNotIn("never-leak-this-token", message)

    def test_staging_connector_bootstraps_anonymous_session_without_token(self):
        connector = self.env["mb.tollquote.connector"].create({
            "name": "Anonymous staging",
            "company_id": self.company.id,
        })
        with patch(
            "odoo.addons.mb_commercial_operations.models.travel_estimate.requests.Session"
        ) as session_class:
            session = session_class.return_value.__enter__.return_value
            session.request.return_value.json.return_value = {"status": "ok"}

            result = connector._request("GET", "/ready")

        self.assertEqual(result, {"status": "ok"})
        session.get.assert_called_once_with(
            "https://api.stage.tollquote.com/v1/client/bootstrap",
            timeout=15,
        )
        session.request.assert_called_once()
        self.assertNotIn(
            "Authorization", session.request.call_args.kwargs["headers"],
        )

    def test_quote_uses_route_polyline_required_by_live_api(self):
        connector = self.env["mb.tollquote.connector"].create({
            "name": "Polyline quote",
            "company_id": self.company.id,
            "api_token": "secret",
        })
        estimate = self.env["mb.travel.estimate"].create({
            "connector_id": connector.id,
            "origin_latitude": 43.1954811,
            "origin_longitude": 5.7539553,
            "destination_latitude": 43.7425854,
            "destination_longitude": 3.7041228,
        })
        with patch.object(
            type(connector), "_request", autospec=True,
            return_value={"totals": {}},
        ) as request:
            estimate._price_route({
                "trip": {"legs": [{"shape": "encoded-polyline6"}]},
            })

        payload = request.call_args.kwargs["payload"]
        self.assertEqual(payload["route"], {"polyline6": "encoded-polyline6"})

    def test_unvalidated_api_revision_and_missing_totals_are_incomplete(self):
        connector = self.env["mb.tollquote.connector"].create({
            "name": "Stage revision",
            "company_id": self.company.id,
            "api_token": "secret",
        })
        estimate = self.env["mb.travel.estimate"].create({
            "connector_id": connector.id,
            "origin_latitude": 48.8,
            "origin_longitude": 2.3,
            "destination_latitude": 49.2,
            "destination_longitude": 4.0,
            "round_trip": False,
        })
        route = {"response": {"trip": {
            "summary": {"length": 100, "time": 3600},
            "legs": [{"shape": "encoded-polyline6"}],
        }}}
        quote = {"api_version": "0.2.0", "reporting_currency": "EUR", "totals": {}}
        with patch.object(type(connector), "_request", autospec=True, side_effect=[route, quote]):
            estimate.action_calculate()
        self.assertTrue(estimate.incomplete)
        self.assertIn("0.2.0", estimate.warning_text)
        self.assertEqual(estimate.provider_version, "0.2.0")

    def test_profitability_report_reads_live_analytic_evidence(self):
        operation = self._operation(expected_revenue=200)
        self.env["account.analytic.line"].create({
            "name": "Market revenue",
            "account_id": operation.analytic_account_id.id,
            "amount": 150,
        })
        self.env["account.analytic.line"].create({
            "name": "Market cost",
            "account_id": operation.analytic_account_id.id,
            "amount": -40,
        })
        report = self.env["mb.commercial.profitability.report"].search([
            ("operation_id", "=", operation.id),
        ])
        self.assertEqual(report.actual_revenue, 150)
        self.assertEqual(report.actual_cost, 40)
        self.assertEqual(report.actual_margin, 110)

    def test_company_rules_keep_other_company_records_out(self):
        other = self.env["res.company"].create({"name": "Other Workshop"})
        other_partner = self.partner.copy({"company_id": other.id})
        operation = self.env["mb.commercial.operation"].with_company(other).create({
            "name": "Other market",
            "company_id": other.id,
            "partner_id": other_partner.id,
            "planned_start": datetime(2026, 9, 1, 8),
            "planned_end": datetime(2026, 9, 1, 18),
        })
        user = self.env["res.users"].create({
            "name": "Single company user",
            "login": "single-company-commercial",
            "company_id": self.company.id,
            "company_ids": [fields.Command.set([self.company.id])],
            "group_ids": [fields.Command.set([
                self.env.ref("base.group_user").id,
                self.env.ref("mb_commercial_operations.group_commercial_operations_user").id,
            ])],
        })
        self.assertFalse(self.env["mb.commercial.operation"].with_user(user).search([("id", "=", operation.id)]))
