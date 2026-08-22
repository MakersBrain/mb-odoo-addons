from ast import literal_eval
from datetime import datetime, timedelta
from unittest.mock import patch

import requests
from lxml import etree

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import datetime as safe_datetime
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestCommercialOperations(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Market Hall",
                "company_id": cls.company.id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Stoneware Mug",
                "list_price": 40.0,
                "standard_price": 10.0,
            }
        )
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Operations Manager",
                "login": "commercial-manager",
                "group_ids": [
                    fields.Command.set(
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref(
                                "mb_commercial_operations.group_commercial_operations_manager"
                            ).id,
                            cls.env.ref("account.group_account_manager").id,
                        ]
                    )
                ],
            }
        )
        cls.employee = cls.env["hr.employee"].create(
            {
                "name": "Commercial test worker",
                "company_id": cls.company.id,
            }
        )

    def _operation(self, **values):
        start = fields.Datetime.now() + timedelta(days=30)
        return self.env["mb.commercial.operation"].create(
            {
                "name": "Autumn Market",
                "company_id": self.company.id,
                "partner_id": self.partner.id,
                "planned_start": start,
                "planned_end": start + timedelta(hours=8),
                **values,
            }
        )

    def test_operation_creates_native_project_account_and_task(self):
        operation = self._operation()
        self.assertTrue(operation.project_id)
        self.assertTrue(operation.project_id.account_id)
        self.assertTrue(operation.task_id)
        self.assertEqual(operation.task_id.mb_commercial_operation_id, operation)
        self.assertEqual(operation.task_id.date_deadline, operation.planned_end)

    def test_batched_operation_create_applies_datetime_defaults(self):
        operations = self.env["mb.commercial.operation"].create(
            [
                {"name": "Defaulted A", "partner_id": self.partner.id},
                {"name": "Defaulted B", "partner_id": self.partner.id},
            ]
        )

        self.assertEqual(len(operations), 2)
        self.assertTrue(all(operations.mapped("planned_start")))
        self.assertTrue(all(operations.mapped("planned_end")))
        self.assertTrue(all(operations.mapped("project_id")))
        self.assertTrue(all(operations.mapped("task_id")))
        for operation in operations:
            self.assertEqual(
                operation.planned_end - operation.planned_start,
                timedelta(hours=7),
            )

    def test_unsaved_operation_has_zero_actual_profit(self):
        operation = self.env["mb.commercial.operation"].new({})

        self.assertEqual(operation.actual_revenue, 0.0)
        self.assertEqual(operation.actual_cost, 0.0)
        self.assertEqual(operation.actual_margin, 0.0)

    def test_contract_occurrences_are_generated_ahead_and_idempotent(self):
        contract = self.env["mb.commercial.contract"].create(
            {
                "partner_id": self.partner.id,
                "company_id": self.company.id,
                "date_start": fields.Date.today().replace(day=1),
                "rent_billing_method": "information",
            }
        )
        obligation = self.env["mb.commercial.obligation"].create(
            {
                "name": "Two permanence days",
                "contract_id": contract.id,
                "date_start": contract.date_start,
                "required_occurrences": 2,
                "horizon_months": 6,
                "preferred_weekday": "5",
            }
        )
        before = len(obligation.occurrence_ids)
        self.assertGreaterEqual(before, 12)
        obligation._generate_occurrences()
        self.assertEqual(len(obligation.occurrence_ids), before)
        first = obligation.occurrence_ids.sorted("planned_start")[0]
        first.action_approve()
        self.assertEqual(first.state, "approved")
        self.assertTrue(first.operation_id)
        self.assertTrue(first.task_id)

    def test_closing_contract_occurrence_keeps_shared_project_active(self):
        contract = self.env["mb.commercial.contract"].create(
            {
                "partner_id": self.partner.id,
                "company_id": self.company.id,
                "date_start": fields.Date.today(),
                "rent_billing_method": "information",
            }
        )
        obligation = self.env["mb.commercial.obligation"].create(
            {
                "name": "Shared-project visit",
                "contract_id": contract.id,
                "date_start": contract.date_start,
            }
        )
        occurrence = obligation.occurrence_ids[:1]
        occurrence.action_approve()
        occurrence.operation_id.action_done()
        occurrence.operation_id.with_user(self.manager).action_financial_close()

        self.assertTrue(contract.project_id.active)

    def test_approved_occurrence_is_immutable(self):
        contract = self.env["mb.commercial.contract"].create(
            {
                "partner_id": self.partner.id,
                "company_id": self.company.id,
                "date_start": fields.Date.today(),
                "rent_billing_method": "information",
            }
        )
        obligation = self.env["mb.commercial.obligation"].create(
            {
                "name": "Visit",
                "contract_id": contract.id,
                "date_start": contract.date_start,
            }
        )
        occurrence = obligation.occurrence_ids[:1]
        occurrence.action_approve()
        with self.assertRaises(UserError):
            occurrence.planned_start += timedelta(days=1)

    def test_break_even_uses_percentage_and_hourly_amounts_once(self):
        operation = self._operation()
        scenario = self.env["mb.commercial.profitability.scenario"].create(
            {
                "operation_id": operation.id,
                "cost_line_ids": [
                    fields.Command.create(
                        {
                            "operation_id": operation.id,
                            "name": "Travel",
                            "category": "travel",
                            "calculation": "fixed",
                            "quantity": 1.0,
                            "rate": 80.0,
                        }
                    ),
                    fields.Command.create(
                        {
                            "operation_id": operation.id,
                            "name": "Stand work",
                            "category": "labour",
                            "calculation": "hour",
                            "quantity": 8.0,
                            "rate": 20.0,
                        }
                    ),
                    fields.Command.create(
                        {
                            "operation_id": operation.id,
                            "name": "Stall",
                            "category": "venue",
                            "calculation": "fixed",
                            "quantity": 1.0,
                            "rate": 60.0,
                        }
                    ),
                ],
                "line_ids": [
                    fields.Command.create(
                        {
                            "product_id": self.product.id,
                            "expected_sold_qty": 20.0,
                            "sale_price_excluded_tax": 40.0,
                            "channel_fee_rate": 2.5,
                            "product_unit_cost": 10.0,
                            "other_variable_unit_cost": 1.0,
                            "cost_source": "product",
                            "cost_date": fields.Date.today(),
                        }
                    )
                ],
            }
        )
        self.assertEqual(scenario.accepted_travel_cost, 80.0)
        self.assertEqual(scenario.fixed_event_cost, 300.0)
        self.assertEqual(scenario.line_ids.channel_fee_amount, 1.0)
        self.assertEqual(scenario.weighted_unit_contribution, 28.0)
        self.assertEqual(scenario.break_even_units, 11)
        scenario.action_approve()
        with self.assertRaises(UserError):
            scenario.cost_line_ids.filtered(lambda line: line.category == "venue").rate = 70.0

    def test_invalid_mix_and_nonpositive_contribution_block_approval(self):
        operation = self._operation()
        scenario = self.env["mb.commercial.profitability.scenario"].create(
            {
                "operation_id": operation.id,
                "cost_line_ids": [
                    fields.Command.create(
                        {
                            "operation_id": operation.id,
                            "name": "Travel",
                            "category": "travel",
                            "calculation": "fixed",
                            "quantity": 1.0,
                            "rate": 20.0,
                        }
                    )
                ],
                "line_ids": [
                    fields.Command.create(
                        {
                            "product_id": self.product.id,
                            "sale_price_excluded_tax": 10.0,
                            "product_unit_cost": 10.0,
                            "cost_source": "product",
                            "cost_date": fields.Date.today(),
                        }
                    )
                ],
            }
        )
        self.assertTrue(scenario.calculation_blocked)
        with self.assertRaises(ValidationError):
            scenario.action_approve()

    def test_product_plan_aggregates_unrounded_levies_and_freezes_pdf(self):
        operation = self._operation(profitability_required=True)
        scenario = self.env["mb.commercial.profitability.scenario"].create(
            {
                "operation_id": operation.id,
                "calculation_mode": "product_mix",
                "line_ids": [
                    fields.Command.create(
                        {
                            "product_id": self.product.id,
                            "expected_sold_qty": 10,
                            "sale_price_excluded_tax": 40.0,
                            "vat_rate": 20.0,
                            "channel_fee_rate": 2.5,
                            "turnover_levy_rate": 12.3,
                            "product_unit_cost": 10.0,
                            "other_variable_unit_cost": 1.0,
                            "cost_source": "product",
                            "cost_date": fields.Date.today(),
                        }
                    )
                ],
                "cost_line_ids": [
                    fields.Command.create(
                        {
                            "operation_id": operation.id,
                            "name": "Stall",
                            "category": "venue",
                            "calculation": "fixed",
                            "quantity": 1,
                            "rate": 100,
                        }
                    )
                ],
            }
        )
        operation.primary_scenario_id = scenario
        self.assertEqual(scenario.sales_revenue_excl_vat, 400)
        self.assertEqual(scenario.customer_receipts_incl_vat, 480)
        self.assertEqual(scenario.total_variable_cost, 169.2)
        self.assertEqual(scenario.projected_margin, 130.8)
        self.assertEqual(scenario.break_even_units, 5)

        operation.action_approve()
        snapshot = operation.report_snapshot_ids
        self.assertEqual(len(snapshot), 1)
        self.assertTrue(snapshot.attachment_id.datas)
        self.assertEqual(snapshot.input_digest, snapshot.input_digest.lower())
        with self.assertRaises(UserError):
            snapshot.payload = {"forged": True}
        with self.assertRaises(UserError):
            snapshot.attachment_id.datas = b"forged"

    def test_zero_product_cost_requires_explicit_assumption(self):
        operation = self._operation(profitability_required=True)
        scenario = self.env["mb.commercial.profitability.scenario"].create(
            {
                "operation_id": operation.id,
                "line_ids": [
                    fields.Command.create(
                        {
                            "product_id": self.product.id,
                            "expected_sold_qty": 2,
                            "sale_price_excluded_tax": 40,
                            "product_unit_cost": 0,
                            "cost_source": "planning",
                            "cost_date": fields.Date.today(),
                        }
                    )
                ],
            }
        )
        operation.primary_scenario_id = scenario
        self.assertTrue(scenario.calculation_blocked)
        scenario.line_ids.exclude_product_cost = True
        self.assertFalse(scenario.calculation_blocked)
        self.assertIn("exclude product cost", operation.planning_warning_summary.lower())

    def test_average_basket_matches_equivalent_product_plan(self):
        product_operation = self._operation(name="Product economics")
        basket_operation = self._operation(name="Basket economics")
        product_scenario = self.env["mb.commercial.profitability.scenario"].create(
            {
                "operation_id": product_operation.id,
                "line_ids": [
                    fields.Command.create(
                        {
                            "product_id": self.product.id,
                            "expected_sold_qty": 10,
                            "sale_price_excluded_tax": 40,
                            "vat_rate": 20,
                            "channel_fee_rate": 2.5,
                            "turnover_levy_rate": 12.3,
                            "product_unit_cost": 10,
                            "cost_source": "product",
                            "cost_date": fields.Date.today(),
                        }
                    )
                ],
            }
        )
        basket_scenario = self.env["mb.commercial.profitability.scenario"].create(
            {
                "operation_id": basket_operation.id,
                "calculation_mode": "average_basket",
                "line_ids": [
                    fields.Command.create(
                        {
                            "expected_sold_qty": 10,
                            "sale_price_excluded_tax": 40,
                            "vat_rate": 20,
                            "channel_fee_rate": 2.5,
                            "turnover_levy_rate": 12.3,
                            "product_cost_mode": "sales_percent",
                            "product_cost_rate": 25,
                            "cost_source": "planning",
                            "cost_date": fields.Date.today(),
                        }
                    )
                ],
            }
        )
        self.assertEqual(
            basket_scenario.sales_revenue_excl_vat,
            product_scenario.sales_revenue_excl_vat,
        )
        self.assertEqual(
            basket_scenario.customer_receipts_incl_vat,
            product_scenario.customer_receipts_incl_vat,
        )
        self.assertEqual(
            basket_scenario.projected_contribution,
            product_scenario.projected_contribution,
        )

    def _verdict_scenario(self, operation, **values):
        """A market selling 20 mugs at 40 with 10 of product cost, over 8 + 2 hours."""
        line = values.pop("line", {})
        travel_cost = values.pop("travel_cost", 50.0)
        venue_cost = values.pop("venue_cost", 50.0)
        work_hours = values.pop("work_hours", 8.0)
        travel_hours = values.pop("travel_hours", 2.0)
        travel_km = values.pop("travel_km", 0.0)
        cost_line_ids = values.pop("cost_line_ids", None)
        if cost_line_ids is None:
            cost_line_ids = [
                fields.Command.create(
                    {
                        "operation_id": operation.id,
                        "name": "Travel",
                        "category": "travel",
                        "calculation": "fixed",
                        "quantity": 1.0,
                        "rate": travel_cost,
                    }
                ),
                fields.Command.create(
                    {
                        "operation_id": operation.id,
                        "name": "Travel time",
                        "category": "travel",
                        "calculation": "hour",
                        "quantity": travel_hours,
                        "rate": 0.0,
                    }
                ),
                fields.Command.create(
                    {
                        "operation_id": operation.id,
                        "name": "Stand work",
                        "category": "labour",
                        "calculation": "hour",
                        "quantity": work_hours,
                        "rate": 0.0,
                    }
                ),
                fields.Command.create(
                    {
                        "operation_id": operation.id,
                        "name": "Stall",
                        "category": "venue",
                        "calculation": "fixed",
                        "quantity": 1.0,
                        "rate": venue_cost,
                    }
                ),
            ]
            if travel_km:
                cost_line_ids.append(
                    fields.Command.create(
                        {
                            "operation_id": operation.id,
                            "name": "Travel distance",
                            "category": "travel",
                            "calculation": "kilometre",
                            "quantity": travel_km,
                            "rate": 0.0,
                        }
                    )
                )
        return self.env["mb.commercial.profitability.scenario"].create(
            {
                "operation_id": operation.id,
                "cost_line_ids": cost_line_ids,
                "line_ids": [
                    fields.Command.create(
                        {
                            "product_id": self.product.id,
                            "expected_sold_qty": 20,
                            "sale_price_excluded_tax": 40.0,
                            "product_unit_cost": 10.0,
                            "cost_source": "product",
                            "cost_date": fields.Date.today(),
                            **line,
                        }
                    )
                ],
                **values,
            }
        )

    def test_hourly_margin_counts_work_and_travel_and_recommends_the_market(self):
        operation = self._operation()
        scenario = self._verdict_scenario(operation)
        self.assertEqual(scenario.fixed_event_cost, 100.0)
        self.assertEqual(scenario.projected_margin, 500.0)
        self.assertEqual(scenario.break_even_units, 4)
        self.assertEqual(scenario.effort_hours, 10.0)
        self.assertEqual(scenario.margin_per_effort_hour, 50.0)
        self.assertEqual(scenario.margin_per_work_hour, 62.5)
        self.assertEqual(scenario.break_even_headroom_ratio, 4.0)
        self.assertEqual(scenario.recommendation, "go")
        self.assertIn("above break-even", scenario.recommendation_note)
        operation.primary_scenario_id = scenario
        self.assertEqual(operation.planning_recommendation, "go")
        self.assertEqual(operation.planning_margin_per_hour, 50.0)
        self.assertEqual(operation.planning_effort_hours, 10.0)

    def test_hourly_target_from_company_policy_downgrades_the_verdict(self):
        self.company.mb_market_target_margin_per_hour = 60.0
        operation = self._operation()
        scenario = self._verdict_scenario(operation)
        self.assertEqual(scenario.target_margin_per_hour, 60.0)
        self.assertEqual(scenario.margin_per_effort_hour, 50.0)
        self.assertEqual(scenario.recommendation, "marginal")
        self.assertIn("below the", scenario.recommendation_note)

    def test_market_below_break_even_is_not_worth_attending(self):
        operation = self._operation()
        scenario = self._verdict_scenario(operation, venue_cost=900.0)
        self.assertEqual(scenario.break_even_units, 32)
        self.assertEqual(scenario.projected_margin, -350.0)
        self.assertEqual(scenario.recommendation, "no_go")
        self.assertIn("32", scenario.recommendation_note)

    def test_thin_break_even_headroom_is_only_marginal(self):
        operation = self._operation()
        scenario = self._verdict_scenario(operation, venue_cost=480.0)
        self.assertEqual(scenario.break_even_units, 18)
        self.assertEqual(scenario.projected_margin, 70.0)
        self.assertAlmostEqual(scenario.break_even_headroom_ratio, 2 / 18, places=6)
        self.assertEqual(scenario.recommendation, "marginal")
        self.assertIn("slow day", scenario.recommendation_note)

    def test_profitable_market_without_fixed_costs_clears_break_even_headroom(self):
        operation = self._operation()
        scenario = self._verdict_scenario(
            operation,
            travel_cost=0.0,
            venue_cost=0.0,
        )
        self.assertEqual(scenario.fixed_event_cost, 0.0)
        self.assertEqual(scenario.break_even_units, 0)
        self.assertGreater(scenario.projected_margin, 0.0)
        self.assertEqual(scenario.break_even_headroom_ratio, 1.0)
        self.assertEqual(scenario.recommendation, "go")

    def test_sales_without_quantities_are_blocked(self):
        operation = self._operation()
        scenario = self._verdict_scenario(
            operation,
            line={"expected_sold_qty": 0},
        )
        self.assertTrue(scenario.calculation_blocked)
        self.assertEqual(scenario.recommendation, "unknown")
        self.assertIn("positive", scenario.recommendation_note)

    def test_effort_hours_fall_back_to_hourly_labour_cost_lines(self):
        operation = self._operation()
        scenario = self._verdict_scenario(
            operation,
            cost_line_ids=[
                fields.Command.create(
                    {
                        "operation_id": operation.id,
                        "name": "Stand crew",
                        "category": "labour",
                        "calculation": "hour",
                        "quantity": 6.0,
                        "rate": 10.0,
                    }
                ),
                fields.Command.create(
                    {
                        "operation_id": operation.id,
                        "name": "Stall",
                        "category": "venue",
                        "calculation": "fixed",
                        "quantity": 1.0,
                        "rate": 100.0,
                    }
                ),
            ],
        )
        self.assertEqual(scenario.fixed_event_cost, 160.0)
        self.assertEqual(scenario.effort_hours, 6.0)
        self.assertEqual(scenario.projected_margin, 440.0)
        self.assertAlmostEqual(scenario.margin_per_effort_hour, 73.33, places=2)
        self.assertEqual(scenario.recommendation, "go")

    def test_margin_per_kilometre_uses_the_scenario_cost_line_distance(self):
        operation = self._operation()
        scenario = self._verdict_scenario(operation, travel_km=120.0)
        self.assertEqual(scenario.travel_distance_km, 120.0)
        self.assertTrue(scenario.travel_distance_known)
        self.assertEqual(scenario.margin_per_travel_km, 4.17)
        self.assertEqual(scenario.margin_per_effort_hour, 50.0)
        self.assertEqual(scenario.recommendation, "go")

    def test_margin_per_kilometre_is_unknown_without_a_quote_or_typed_distance(self):
        operation = self._operation()
        scenario = self._verdict_scenario(operation)
        self.assertFalse(scenario.travel_distance_known)
        self.assertEqual(scenario.travel_distance_km, 0.0)
        self.assertEqual(scenario.margin_per_travel_km, 0.0)
        self.assertEqual(scenario.recommendation, "go")
        self.assertIn("above break-even", scenario.recommendation_note)

    def test_margin_per_kilometre_reads_the_accepted_quote_in_provider_total_mode(self):
        connector = self.env["mb.tollquote.connector"].create(
            {
                "name": "Stage kilometres",
                "company_id": self.company.id,
                "api_token": "secret",
            }
        )
        operation = self._operation()
        estimate = self.env["mb.travel.estimate"].create(
            {
                "connector_id": connector.id,
                "operation_id": operation.id,
                "origin_latitude": 48.8566,
                "origin_longitude": 2.3522,
                "destination_latitude": 49.2583,
                "destination_longitude": 4.0317,
            }
        )
        route = {
            "response": {
                "trip": {
                    "summary": {"length": 100.0, "time": 3600},
                    "legs": [{"shape": "encoded-polyline6"}],
                }
            }
        }
        quote = {
            "request_id": "00000000-0000-0000-0000-000000000002",
            "reporting_currency": "EUR",
            "totals": {"gross": {"value": "12.50", "currency": "EUR"}},
        }
        with patch.object(
            type(connector), "_request", autospec=True, side_effect=[route, quote, route, quote]
        ):
            estimate.action_calculate()
        estimate.incomplete_acknowledged = True
        estimate.action_accept()
        self.assertEqual(estimate.distance_km, 200.0)
        scenario = self._verdict_scenario(
            operation,
            travel_estimate_id=estimate.id,
        )
        self.assertFalse(scenario.calculation_blocked)
        self.assertEqual(scenario.travel_distance_km, 200.0)
        self.assertEqual(
            scenario.margin_per_travel_km,
            scenario.currency_id.round(scenario.projected_margin / 200.0),
        )

    def test_travel_kilometres_fall_back_to_per_kilometre_cost_lines(self):
        operation = self._operation()
        scenario = self._verdict_scenario(
            operation,
            cost_line_ids=[
                fields.Command.create(
                    {
                        "operation_id": operation.id,
                        "name": "Mileage allowance",
                        "category": "travel",
                        "calculation": "kilometre",
                        "quantity": 150.0,
                        "rate": 0.35,
                    }
                ),
            ],
        )
        self.assertEqual(scenario.travel_distance_km, 150.0)
        self.assertTrue(scenario.travel_distance_known)
        self.assertEqual(scenario.fixed_event_cost, 52.5)
        self.assertEqual(scenario.projected_margin, 547.5)
        self.assertEqual(scenario.margin_per_travel_km, 3.65)

    def test_operation_mirrors_margin_per_kilometre_from_the_primary_scenario(self):
        operation = self._operation()
        scenario = self._verdict_scenario(operation, travel_km=120.0)
        operation.primary_scenario_id = scenario
        self.assertEqual(operation.planning_margin_per_km, 4.17)
        self.assertEqual(operation.planning_travel_distance_km, 120.0)
        self.assertTrue(operation.planning_travel_distance_known)
        self.assertEqual(operation.accepted_travel_distance_km, 0.0)

    def test_approved_scenario_keeps_its_kilometre_kpi(self):
        operation = self._operation(profitability_required=True)
        scenario = self._verdict_scenario(operation, travel_km=120.0)
        scenario.action_approve()
        self.assertEqual(scenario.state, "approved")
        with self.assertRaises(UserError):
            scenario.cost_line_ids.filtered(
                lambda line: line.calculation == "kilometre"
            ).quantity = 999.0
        self.assertEqual(scenario.travel_distance_km, 120.0)
        self.assertEqual(scenario.margin_per_travel_km, 4.17)

    def test_planning_snapshot_digest_is_unchanged_by_the_kilometre_kpi(self):
        operation = self._operation(profitability_required=True)
        scenario = self._verdict_scenario(operation, travel_km=120.0)
        scenario.action_approve()
        snapshot = operation.report_snapshot_ids.filtered(
            lambda item: item.report_kind == "planning" and item.state == "current"
        )
        self.assertEqual(len(snapshot), 1)
        digest = snapshot.input_digest
        operation.with_user(self.manager).action_freeze_replacement_copy()
        replacement = operation.report_snapshot_ids.filtered(
            lambda item: item.report_kind == "planning" and item.state == "current"
        )
        self.assertEqual(len(replacement), 1)
        self.assertNotEqual(replacement, snapshot)
        self.assertEqual(replacement.input_digest, digest)

    def test_new_operation_wizard_saves_one_authoritative_plan_only(self):
        before_operations = self.env["mb.commercial.operation"].search_count([])
        before_moves = self.env["account.move"].search_count([])
        start = fields.Datetime.now() + timedelta(days=45)
        wizard = self.env["mb.commercial.operation.plan.wizard"].create(
            {
                "name": "Winter ceramics fair",
                "operation_type": "market",
                "company_id": self.company.id,
                "partner_id": self.partner.id,
                "departure": start,
                "service_start": start + timedelta(hours=1),
                "service_end": start + timedelta(hours=7),
                "expected_return": start + timedelta(hours=8),
                "scenario_name": "Expected sales",
                "line_ids": [
                    fields.Command.create(
                        {
                            "product_id": self.product.id,
                            "desired_opening_qty": 20,
                            "expected_sold_qty": 10,
                            "sale_price_excluded_tax": 40,
                            "product_unit_cost": 10,
                        }
                    )
                ],
                "cost_ids": [
                    fields.Command.create(
                        {
                            "name": "Stand",
                            "category": "venue",
                            "calculation": "fixed",
                            "quantity": 1,
                            "rate": 75,
                        }
                    )
                ],
            }
        )
        self.assertEqual(self.env["mb.commercial.operation"].search_count([]), before_operations)
        self.assertEqual(wizard.preview_units, 10)
        self.assertEqual(wizard.preview_sales_excl_vat, 400)
        self.assertEqual(wizard.preview_fixed_cost, 75)
        self.assertEqual(wizard.preview_projected_margin, 225)
        self.assertFalse(wizard.preview_blocked)
        action = wizard.action_save_draft()
        operation = self.env["mb.commercial.operation"].browse(action["res_id"])
        self.assertEqual(
            self.env["mb.commercial.operation"].search_count([]), before_operations + 1
        )
        self.assertEqual(operation.primary_scenario_id.cost_line_ids.planned_amount, 75)
        self.assertEqual(operation.stock_plan_line_ids.desired_opening_qty, 20)
        self.assertEqual(
            operation.primary_scenario_id.line_ids.source_stock_plan_line_id,
            operation.stock_plan_line_ids,
        )
        self.assertEqual(self.env["account.move"].search_count([]), before_moves)

    def test_planning_template_copies_time_travel_and_labour_assumptions(self):
        template = self.env["mb.commercial.plan.template"].create(
            {
                "name": "Full market day",
                "company_id": self.company.id,
                "operation_type": "market",
                "default_duration_hours": 9,
                "default_setup_hours": 1,
                "default_service_hours": 6,
                "default_teardown_hours": 1,
                "default_labour_hourly_cost": 20,
                "default_travel_hourly_cost": 15,
                "default_fuel_consumption_l_per_100km": 8,
                "default_fuel_price_eur_per_l": 2,
            }
        )
        start = fields.Datetime.now() + timedelta(days=20)
        wizard = self.env["mb.commercial.operation.plan.wizard"].create(
            {
                "name": "Template preview",
                "company_id": self.company.id,
                "partner_id": self.partner.id,
                "departure": start,
                "service_start": start + timedelta(hours=2),
            }
        )
        wizard.template_id = template
        wizard._onchange_template_id()
        self.assertEqual(wizard.setup_duration_hours, 1)
        self.assertEqual(wizard.service_end, wizard.service_start + timedelta(hours=6))
        self.assertEqual(wizard.teardown_duration_hours, 1)
        self.assertEqual(wizard.driver_cost_eur_per_hour, 15)
        self.assertEqual(wizard.fuel_consumption_l_per_100km, 8)
        labour = wizard.cost_ids.filtered(lambda line: line.category == "labour")
        self.assertEqual(labour.quantity, 9)
        self.assertEqual(labour.rate, 20)

    def test_new_operation_quote_stays_transient_until_explicit_save_and_accept(self):
        connector = self.env["mb.tollquote.connector"].create(
            {
                "name": "Transient quote",
                "company_id": self.company.id,
                "api_token": "secret",
            }
        )
        start = fields.Datetime.now() + timedelta(days=60)
        wizard = self.env["mb.commercial.operation.plan.wizard"].create(
            {
                "name": "Quoted market",
                "operation_type": "market",
                "company_id": self.company.id,
                "partner_id": self.partner.id,
                "departure": start,
                "expected_return": start + timedelta(hours=8),
                "connector_id": connector.id,
                "origin_latitude": 43.30,
                "origin_longitude": 3.50,
                "destination_latitude": 43.55,
                "destination_longitude": 3.85,
                "line_ids": [
                    fields.Command.create(
                        {
                            "product_id": self.product.id,
                            "expected_sold_qty": 10,
                            "sale_price_excluded_tax": 40,
                            "product_unit_cost": 10,
                        }
                    )
                ],
            }
        )
        route = {
            "response": {
                "trip": {
                    "summary": {"length": 50, "time": 1800},
                    "legs": [{"shape": "encoded-polyline6"}],
                }
            }
        }
        quote = {
            "api_version": "0.1.0",
            "reporting_currency": "EUR",
            "totals": {"gross": {"value": "5.00", "currency": "EUR"}},
        }
        before = self.env["mb.travel.estimate"].search_count([])
        with patch.object(
            type(connector),
            "_request",
            autospec=True,
            side_effect=[route, quote, route, quote],
        ):
            wizard.action_calculate_travel()
        self.assertTrue(wizard.quote_calculated)
        self.assertEqual(self.env["mb.travel.estimate"].search_count([]), before)
        wizard.accept_quote = True
        wizard.incomplete_quote_acknowledged = wizard.quote_incomplete
        operation = self.env["mb.commercial.operation"].browse(wizard.action_save_draft()["res_id"])
        self.assertEqual(operation.travel_estimate_id.state, "accepted")
        self.assertEqual(operation.travel_estimate_id.distance_km, 100)
        travel_cost = operation.primary_scenario_id.cost_line_ids.filtered(
            lambda line: line.category == "travel"
        )
        self.assertEqual(travel_cost.travel_estimate_id, operation.travel_estimate_id)
        self.assertEqual(
            travel_cost.planned_amount, operation.travel_estimate_id.total_operating_cost
        )

    def test_live_planning_and_outcome_reports_render_through_native_qweb(self):
        operation = self._operation(name="Printable operation")
        planning = self.env.ref("mb_commercial_operations.action_report_commercial_operation")
        html, _kind = planning._render_qweb_html(planning.report_name, operation.ids)
        self.assertIn(b"DRAFT / SIMULATION", html)
        self.assertIn(b"Cost plan only", html)

        operation.action_approve()
        operation.action_done()
        snapshot_count = len(operation.report_snapshot_ids)
        operation.action_print_outcome_pack()
        self.assertEqual(len(operation.report_snapshot_ids), snapshot_count)
        outcome = self.env.ref(
            "mb_commercial_operations.action_report_commercial_operation_outcome"
        )
        html, _kind = outcome._render_qweb_html(outcome.report_name, operation.ids)
        self.assertIn(b"Outcome", html)
        self.assertIn(b"operation-linked native evidence only", html)

    def test_overlapping_stock_targets_must_be_allocated(self):
        operation = self._operation()
        bucket = self.env["mb.market.stock.plan.line"].create(
            {
                "operation_id": operation.id,
                "target_type": "bucket",
                "category_id": self.product.categ_id.id,
                "price_min": 20,
                "price_max": 50,
                "expected_unit_price": 35,
            }
        )
        exact = self.env["mb.market.stock.plan.line"].create(
            {
                "operation_id": operation.id,
                "target_type": "product",
                "product_id": self.product.id,
                "expected_unit_price": 40,
            }
        )
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
        self.assertFalse(operation.project_id.active)
        with self.assertRaises(UserError):
            operation.planned_end += timedelta(days=1)
        operation.with_user(self.manager).action_reopen()
        self.assertTrue(operation.project_id.active)

    def test_travel_quote_incomplete_requires_acknowledgement_and_revisions(self):
        connector = self.env["mb.tollquote.connector"].create(
            {
                "name": "Stage",
                "company_id": self.company.id,
                "api_token": "secret",
            }
        )
        operation = self._operation()
        estimate = self.env["mb.travel.estimate"].create(
            {
                "connector_id": connector.id,
                "operation_id": operation.id,
                "origin_latitude": 48.8566,
                "origin_longitude": 2.3522,
                "destination_latitude": 49.2583,
                "destination_longitude": 4.0317,
            }
        )
        route = {
            "response": {
                "trip": {
                    "summary": {"length": 100.0, "time": 3600},
                    "legs": [{"shape": "encoded-polyline6"}],
                }
            }
        }
        quote = {
            "request_id": "00000000-0000-0000-0000-000000000001",
            "reporting_currency": "EUR",
            "totals": {"gross": {"value": "12.50", "currency": "EUR"}},
            "warnings": ["partial"],
            "unpriced": [{"gate": "unknown"}],
        }
        with patch.object(
            type(connector), "_request", autospec=True, side_effect=[route, quote, route, quote]
        ):
            estimate.action_calculate()
        self.assertEqual(estimate.state, "quoted")
        self.assertTrue(estimate.incomplete)
        self.assertEqual(estimate.distance_km, 200.0)
        with self.assertRaises(ValidationError):
            estimate.action_accept()
        estimate.incomplete_acknowledged = True
        estimate.action_accept()
        self.assertEqual(operation.travel_estimate_id, estimate)
        with patch.object(
            type(connector), "_request", autospec=True, side_effect=[route, quote, route, quote]
        ):
            action = estimate.action_calculate()
        revision = self.env["mb.travel.estimate"].browse(action["res_id"])
        self.assertEqual(revision.revision, 2)
        self.assertEqual(estimate.state, "accepted")

    def test_tollquote_errors_are_sanitized_and_user_readable(self):
        connector = self.env["mb.tollquote.connector"].create(
            {
                "name": "Stage error cases",
                "company_id": self.company.id,
                "api_token": "never-leak-this-token",
            }
        )
        cases = [
            (requests.Timeout(), "timed out"),
            (
                requests.HTTPError(response=type("Response", (), {"status_code": 401})()),
                "credential",
            ),
            (requests.HTTPError(response=type("Response", (), {"status_code": 429})()), "quota"),
            (requests.HTTPError(response=type("Response", (), {"status_code": 503})()), "503"),
            (ValueError("malformed"), "invalid response"),
        ]
        for error, expected in cases:
            response = type(
                "FakeResponse",
                (),
                {
                    "raise_for_status": lambda self, issue=error: (_ for _ in ()).throw(issue),
                    "json": lambda self: {},
                },
            )()
            with (
                self.subTest(expected=expected),
                patch(
                    "odoo.addons.mb_commercial_operations.models.travel_estimate.requests.request",
                    return_value=response,
                ),
                self.assertRaises(UserError) as raised,
            ):
                connector._request("GET", "/ready")
            message = str(raised.exception)
            self.assertIn(expected, message)
            self.assertNotIn("never-leak-this-token", message)

    def test_staging_connector_bootstraps_anonymous_session_without_token(self):
        connector = self.env["mb.tollquote.connector"].create(
            {
                "name": "Anonymous staging",
                "company_id": self.company.id,
            }
        )
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
            "Authorization",
            session.request.call_args.kwargs["headers"],
        )

    def test_quote_uses_route_polyline_required_by_live_api(self):
        connector = self.env["mb.tollquote.connector"].create(
            {
                "name": "Polyline quote",
                "company_id": self.company.id,
                "api_token": "secret",
            }
        )
        estimate = self.env["mb.travel.estimate"].create(
            {
                "connector_id": connector.id,
                "origin_latitude": 43.1954811,
                "origin_longitude": 5.7539553,
                "destination_latitude": 43.7425854,
                "destination_longitude": 3.7041228,
            }
        )
        with patch.object(
            type(connector),
            "_request",
            autospec=True,
            return_value={"totals": {}},
        ) as request:
            estimate._price_route(
                {
                    "trip": {"legs": [{"shape": "encoded-polyline6"}]},
                }
            )

        payload = request.call_args.kwargs["payload"]
        self.assertEqual(payload["route"], {"polyline6": "encoded-polyline6"})

    def test_unvalidated_api_revision_and_missing_totals_are_incomplete(self):
        connector = self.env["mb.tollquote.connector"].create(
            {
                "name": "Stage revision",
                "company_id": self.company.id,
                "api_token": "secret",
            }
        )
        estimate = self.env["mb.travel.estimate"].create(
            {
                "connector_id": connector.id,
                "origin_latitude": 48.8,
                "origin_longitude": 2.3,
                "destination_latitude": 49.2,
                "destination_longitude": 4.0,
                "round_trip": False,
            }
        )
        route = {
            "response": {
                "trip": {
                    "summary": {"length": 100, "time": 3600},
                    "legs": [{"shape": "encoded-polyline6"}],
                }
            }
        }
        quote = {"api_version": "0.2.0", "reporting_currency": "EUR", "totals": {}}
        with patch.object(type(connector), "_request", autospec=True, side_effect=[route, quote]):
            estimate.action_calculate()
        self.assertTrue(estimate.incomplete)
        self.assertIn("0.2.0", estimate.warning_text)
        self.assertEqual(estimate.provider_version, "0.2.0")

    def test_profitability_report_reads_only_operation_task_evidence(self):
        operation = self._operation()
        self.env["account.analytic.line"].create(
            {
                "name": "Market revenue",
                "account_id": operation.analytic_account_id.id,
                "mb_commercial_operation_id": operation.id,
                "amount": 150,
            }
        )
        self.env["account.analytic.line"].create(
            {
                "name": "Market cost",
                "account_id": operation.analytic_account_id.id,
                "mb_commercial_operation_id": operation.id,
                "amount": -40,
            }
        )
        self.env["account.analytic.line"].create(
            {
                "name": "Other operation on shared project",
                "account_id": operation.analytic_account_id.id,
                "amount": 999,
            }
        )
        report = self.env["mb.commercial.profitability.report"].search(
            [
                ("operation_id", "=", operation.id),
            ]
        )
        self.assertEqual(report.actual_revenue, 150)
        self.assertEqual(report.actual_cost, 40)
        self.assertEqual(report.actual_margin, 110)

    def test_company_rules_keep_other_company_records_out(self):
        other = self.env["res.company"].create({"name": "Other Workshop"})
        other_partner = self.partner.copy({"company_id": other.id})
        operation = (
            self.env["mb.commercial.operation"]
            .with_company(other)
            .create(
                {
                    "name": "Other market",
                    "company_id": other.id,
                    "partner_id": other_partner.id,
                    "planned_start": datetime(2026, 9, 1, 8),
                    "planned_end": datetime(2026, 9, 1, 18),
                }
            )
        )
        user = self.env["res.users"].create(
            {
                "name": "Single company user",
                "login": "single-company-commercial",
                "company_id": self.company.id,
                "company_ids": [fields.Command.set([self.company.id])],
                "group_ids": [
                    fields.Command.set(
                        [
                            self.env.ref("base.group_user").id,
                            self.env.ref(
                                "mb_commercial_operations.group_commercial_operations_user"
                            ).id,
                        ]
                    )
                ],
            }
        )
        self.assertFalse(
            self.env["mb.commercial.operation"].with_user(user).search([("id", "=", operation.id)])
        )

    def _candidate_domain(self):
        action = self.env.ref("mb_commercial_operations.action_commercial_market_candidates")
        return literal_eval(action.domain)

    def test_market_candidates_rank_by_planned_margin_per_hour(self):
        strong = self._operation(name="Strong fair")
        strong.primary_scenario_id = self._verdict_scenario(strong)
        weak = self._operation(name="Weak fair")
        weak.primary_scenario_id = self._verdict_scenario(weak, venue_cost=480.0)
        loss = self._operation(name="Loss-making fair")
        loss.primary_scenario_id = self._verdict_scenario(loss, venue_cost=900.0)
        uncosted = self._operation(name="Uncosted fair")
        self.assertEqual(weak.planning_recommendation, "marginal")
        self.assertEqual(loss.planning_recommendation, "no_go")

        candidates = self.env["mb.commercial.operation"].search(
            [*self._candidate_domain(), ("id", "in", (strong + weak + loss + uncosted).ids)],
            order="planning_margin_per_hour desc",
        )
        self.assertEqual(candidates.ids, [strong.id, weak.id, uncosted.id, loss.id])

    def test_uncosted_market_ranks_at_zero_not_null(self):
        uncosted = self._operation()
        self.assertFalse(uncosted.primary_scenario_id)
        self.assertEqual(uncosted.planning_margin_per_hour, 0.0)
        self.assertFalse(uncosted.planning_recommendation)
        self.assertIn(
            uncosted, self.env["mb.commercial.operation"].search(self._candidate_domain())
        )

    def test_market_candidate_domain_excludes_replanned_and_non_market_operations(self):
        draft = self._operation()
        quoted = self._operation()
        quoted.state = "quoted"
        approved = self._operation()
        approved.state = "approved"
        visit = self._operation(operation_type="visit")

        candidates = self.env["mb.commercial.operation"].search(
            [
                *self._candidate_domain(),
                ("id", "in", (draft + quoted + approved + visit).ids),
            ]
        )
        self.assertEqual(set(candidates.ids), {draft.id, quoted.id})

    def test_open_application_filter_hides_markets_whose_deadline_passed(self):
        view = self.env.ref("mb_commercial_operations.view_commercial_operation_search")
        arch = etree.fromstring(view.arch.encode())
        domain = arch.xpath("//filter[@name='open_application']")[0].get("domain")

        undated = self._operation()
        open_call = self._operation(application_deadline=fields.Datetime.now() + timedelta(days=7))
        closed_call = self._operation(
            application_deadline=fields.Datetime.now() - timedelta(days=7)
        )
        evaluated = safe_eval(
            domain,
            {
                "context_today": lambda: fields.Date.context_today(undated),
                # A search domain sees datetime as a namespace, not as the class, so
                # bind the same wrapper Odoo evaluates domains with; binding the class
                # would make this test pass on an expression the client cannot run.
                "datetime": safe_datetime,
            },
        )

        matches = self.env["mb.commercial.operation"].search(
            [
                *evaluated,
                ("id", "in", (undated + open_call + closed_call).ids),
            ]
        )
        self.assertEqual(set(matches.ids), {undated.id, open_call.id})

    def test_break_even_headroom_is_readable_on_the_operation(self):
        operation = self._operation()
        scenario = self._verdict_scenario(operation)
        self.assertEqual(operation.planning_break_even_headroom, 0.0)
        operation.primary_scenario_id = scenario
        self.assertEqual(operation.planning_break_even_headroom, scenario.break_even_headroom_ratio)
        self.assertEqual(operation.planning_break_even_headroom, 4.0)

    def _past_market(self, state="done", **values):
        """A market held last year at the same venue, with a costed plan."""
        start = values.pop("planned_start", fields.Datetime.now() - timedelta(days=330))
        operation = self._operation(
            **{
                "name": "Last Autumn Market",
                "planned_start": start,
                "planned_end": start + timedelta(hours=8),
                **values,
            }
        )
        operation.primary_scenario_id = self.env["mb.commercial.profitability.scenario"].create(
            {
                "name": "Last year's plan",
                "operation_id": operation.id,
                "line_ids": [
                    fields.Command.create(
                        {
                            "product_id": self.product.id,
                            "expected_sold_qty": 20,
                            "sale_price_excluded_tax": 40.0,
                            "vat_rate": 20.0,
                            "channel_fee_rate": 2.5,
                            "turnover_levy_rate": 12.3,
                            "product_unit_cost": 10.0,
                            "cost_source": "product",
                            "cost_date": fields.Date.today() - timedelta(days=330),
                        }
                    )
                ],
                "cost_line_ids": [
                    fields.Command.create(
                        {
                            "operation_id": operation.id,
                            "name": "Stall",
                            "category": "venue",
                            "calculation": "fixed",
                            "quantity": 1,
                            "rate": 100,
                        }
                    )
                ],
            }
        )
        operation.state = state
        return operation

    def _plan_wizard(self, operation):
        return (
            self.env["mb.commercial.operation.plan.wizard"]
            .with_context(
                default_operation_id=operation.id,
            )
            .create({})
        )

    def test_new_market_seeds_its_draft_scenario_from_the_last_comparable_operation(self):
        source = self._past_market()
        wizard = self._plan_wizard(self._operation(name="This Autumn Market"))

        self.assertEqual(wizard.source_operation_id, source)
        self.assertEqual(len(wizard.line_ids), 1)
        self.assertEqual(wizard.line_ids.product_id, self.product)
        self.assertEqual(wizard.line_ids.sale_price_excluded_tax, 40.0)
        self.assertEqual(wizard.line_ids.vat_rate, 20.0)
        self.assertEqual(wizard.line_ids.channel_fee_rate, 2.5)
        self.assertEqual(wizard.line_ids.turnover_levy_rate, 12.3)
        self.assertEqual(wizard.line_ids.product_unit_cost, 10.0)
        self.assertEqual(wizard.cost_ids.rate, 100)
        self.assertEqual(wizard.source_actual_revenue, source.actual_revenue)

    def test_seeded_scenario_is_draft_and_not_the_approved_baseline(self):
        self._past_market()
        operation = self._operation(name="This Autumn Market")
        self._plan_wizard(operation).action_save_draft()

        scenario = operation.primary_scenario_id
        self.assertEqual(scenario.state, "draft")
        self.assertFalse(scenario.approved_by_id)
        self.assertFalse(scenario.approved_at)
        self.assertEqual(operation.state, "draft")
        self.assertFalse(operation.report_snapshot_ids)

    def test_seeding_drops_travel_quote_and_stock_target_links(self):
        source = self._past_market(state="draft")
        connector = self.env["mb.tollquote.connector"].create(
            {
                "name": "Last year connector",
                "company_id": self.company.id,
                "api_token": "secret",
            }
        )
        estimate = self.env["mb.travel.estimate"].create(
            {
                "company_id": self.company.id,
                "connector_id": connector.id,
                "operation_id": source.id,
                "origin_latitude": 43.30,
                "origin_longitude": 3.50,
                "destination_latitude": 43.55,
                "destination_longitude": 3.85,
                "state": "quoted",
                "total_operating_cost": 60.0,
            }
        )
        estimate.action_accept()
        target = self.env["mb.market.stock.plan.line"].create(
            {
                "operation_id": source.id,
                "target_type": "product",
                "product_id": self.product.id,
                "expected_sold_qty": 20,
            }
        )
        source.primary_scenario_id.line_ids.source_stock_plan_line_id = target
        source.state = "done"

        operation = self._operation(name="This Autumn Market")
        wizard = self._plan_wizard(operation)
        self.assertEqual(wizard.source_operation_id, source)
        self.assertFalse(wizard.line_ids.source_stock_plan_line_id)
        self.assertFalse(wizard.travel_estimate_id)

        wizard.action_save_draft()
        seeded_targets = operation.primary_scenario_id.line_ids.source_stock_plan_line_id
        self.assertTrue(seeded_targets)
        self.assertEqual(seeded_targets.operation_id, operation)
        self.assertFalse(operation.travel_estimate_id)
        self.assertEqual(source.primary_scenario_id.line_ids.source_stock_plan_line_id, target)

    def test_seeded_lines_keep_the_default_opening_quantity(self):
        # The source line has no stock target, so nothing should overwrite the
        # field's own default with a zero.
        source = self._past_market()
        self.assertFalse(source.primary_scenario_id.line_ids.source_stock_plan_line_id)

        wizard = self._plan_wizard(self._operation(name="This Autumn Market"))

        self.assertEqual(wizard.line_ids.desired_opening_qty, 1.0)

    def test_prior_actuals_stay_hidden_until_the_source_market_has_happened(self):
        source = self._past_market(state="approved")

        wizard = self._plan_wizard(self._operation(name="This Autumn Market"))

        self.assertEqual(wizard.source_operation_id, source)
        self.assertFalse(wizard.source_actuals_known)
        source.state = "done"
        wizard.invalidate_recordset()
        self.assertTrue(wizard.source_actuals_known)

    def test_approved_scenario_keeps_its_hourly_and_per_km_figures(self):
        # These are stored computes, which are written by _write() and so never
        # meet the immutability guard; the operation's dates and quote stay
        # editable long after a scenario is approved.
        operation = self._operation()
        scenario = self._verdict_scenario(operation, travel_km=100.0)
        scenario.action_approve()
        margin_per_hour = scenario.margin_per_effort_hour
        margin_per_km = scenario.margin_per_travel_km

        operation.with_user(self.manager).action_reopen()
        operation.planned_end = operation.planned_start + timedelta(hours=40)
        scenario.invalidate_recordset()

        self.assertEqual(scenario.margin_per_effort_hour, margin_per_hour)
        self.assertEqual(scenario.margin_per_travel_km, margin_per_km)

    def test_seeded_fixed_costs_lose_their_travel_provenance(self):
        source = self._past_market(state="draft")
        connector = self.env["mb.tollquote.connector"].create(
            {
                "name": "Provenance connector",
                "company_id": self.company.id,
                "api_token": "secret",
            }
        )
        estimate = self.env["mb.travel.estimate"].create(
            {
                "company_id": self.company.id,
                "connector_id": connector.id,
                "operation_id": source.id,
                "origin_latitude": 43.30,
                "origin_longitude": 3.50,
                "destination_latitude": 43.55,
                "destination_longitude": 3.85,
                "state": "quoted",
                "total_operating_cost": 60.0,
            }
        )
        self.env["mb.commercial.cost.line"].create(
            {
                "operation_id": source.id,
                "scenario_id": source.primary_scenario_id.id,
                "name": "Accepted TollQuote travel total",
                "category": "travel",
                "calculation": "fixed",
                "quantity": 1,
                "rate": 60.0,
                "source_kind": "travel",
                "travel_estimate_id": estimate.id,
                "source_reference": "quote-42",
            }
        )
        source.state = "done"

        operation = self._operation(name="This Autumn Market")
        self._plan_wizard(operation).action_save_draft()

        seeded = operation.primary_scenario_id.cost_line_ids.filtered(
            lambda line: line.category == "travel"
        )
        self.assertEqual(len(seeded), 1)
        self.assertEqual(seeded.name, "Accepted TollQuote travel total")
        self.assertEqual(seeded.rate, 60.0)
        self.assertEqual(seeded.source_kind, "manual")
        self.assertFalse(seeded.travel_estimate_id)
        self.assertFalse(seeded.source_reference)
        self.assertEqual(seeded.assumption_date, fields.Date.context_today(seeded))

    def test_seeding_ignores_financial_and_evidence_data(self):
        source = self._past_market()
        self.env["account.analytic.line"].create(
            {
                "name": "Last year's takings",
                "account_id": source.analytic_account_id.id,
                "mb_commercial_operation_id": source.id,
                "amount": 900,
            }
        )
        source.close_note = "Rain kept half the visitors away."

        operation = self._operation(name="This Autumn Market")
        wizard = self._plan_wizard(operation)
        self.assertEqual(wizard.source_actual_revenue, 900)
        self.assertEqual(wizard.source_actual_margin, source.actual_margin)

        wizard.action_save_draft()
        self.assertFalse(operation.analytic_evidence_ids)
        self.assertFalse(operation.account_move_ids)
        self.assertFalse(operation.financial_close_date)
        self.assertFalse(operation.close_note)

    def test_comparable_operation_prefers_same_contract_then_most_recent(self):
        contract = self.env["mb.commercial.contract"].create(
            {
                "partner_id": self.partner.id,
                "company_id": self.company.id,
                "date_start": fields.Date.today() - timedelta(days=700),
                "rent_billing_method": "information",
            }
        )
        contracted = self._past_market(
            name="Contracted market",
            contract_id=contract.id,
            planned_start=fields.Datetime.now() - timedelta(days=600),
        )
        recent = self._past_market(name="Recent market")
        other_partner = self.env["res.partner"].create(
            {
                "name": "Other Hall",
                "company_id": self.company.id,
            }
        )
        self._past_market(name="Other venue market", partner_id=other_partner.id)

        operation = self._operation(name="This Autumn Market", contract_id=contract.id)
        self.assertEqual(operation._find_comparable_operation(), contracted)

        operation.contract_id = False
        self.assertEqual(operation._find_comparable_operation(), recent)

    def test_comparable_operation_ignores_draft_cancelled_and_scenarioless_operations(self):
        operation = self._operation(name="This Autumn Market")
        self.assertFalse(operation._find_comparable_operation())

        self._past_market(state="draft")
        self._past_market(state="cancelled")
        start = fields.Datetime.now() - timedelta(days=200)
        self._operation(
            name="Scenarioless market",
            planned_start=start,
            planned_end=start + timedelta(hours=8),
            state="done",
        )
        self.assertFalse(operation._find_comparable_operation())

        wizard = self._plan_wizard(operation)
        self.assertFalse(wizard.source_operation_id)
        self.assertFalse(wizard.line_ids)

    def test_seeded_stale_cost_dates_raise_the_outdated_warning(self):
        self._past_market()
        operation = self._operation(name="This Autumn Market")
        self._plan_wizard(operation).action_save_draft()

        self.assertEqual(
            operation.primary_scenario_id.line_ids.cost_date,
            fields.Date.today() - timedelta(days=330),
        )
        outdated = [
            warning
            for warning in operation._get_planning_warnings()
            if warning[0] == "product_cost_outdated"
        ]
        self.assertEqual(len(outdated), 1)
        self.assertEqual(outdated[0][1], "warning")

    def test_seeding_never_reads_or_creates_snapshots(self):
        source = self._past_market(state="draft", profitability_required=True)
        source.action_approve()
        source.state = "done"
        self.assertEqual(len(source.report_snapshot_ids), 1)

        operation = self._operation(name="This Autumn Market")
        self._plan_wizard(operation).action_save_draft()

        self.assertEqual(len(source.report_snapshot_ids), 1)
        self.assertFalse(
            source.report_snapshot_ids.filtered(lambda snapshot: snapshot.report_kind == "outcome")
        )
        self.assertFalse(operation.report_snapshot_ids)
        source.with_user(self.manager).action_freeze_replacement_copy()

    def test_seeding_respects_company_isolation(self):
        other = self.env["res.company"].create({"name": "Other Workshop"})
        other_partner = self.partner.copy({"company_id": other.id})
        foreign = (
            self.env["mb.commercial.operation"]
            .with_company(other)
            .create(
                {
                    "name": "Other company market",
                    "company_id": other.id,
                    "partner_id": other_partner.id,
                    "planned_start": fields.Datetime.now() - timedelta(days=300),
                    "planned_end": fields.Datetime.now() - timedelta(days=300) + timedelta(hours=8),
                }
            )
        )
        foreign.primary_scenario_id = (
            self.env["mb.commercial.profitability.scenario"]
            .with_company(other)
            .create(
                {
                    "name": "Foreign plan",
                    "operation_id": foreign.id,
                    "line_ids": [
                        fields.Command.create(
                            {
                                "expected_sold_qty": 10,
                                "sale_price_excluded_tax": 40.0,
                                "product_cost_mode": "sales_percent",
                                "product_cost_rate": 25,
                                "cost_source": "planning",
                                "cost_date": fields.Date.today(),
                            }
                        )
                    ],
                }
            )
        )
        foreign.state = "done"

        operation = self._operation(name="This Autumn Market")
        self.assertFalse(operation._find_comparable_operation())
        self.assertFalse(self._plan_wizard(operation).source_operation_id)
