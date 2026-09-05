from calendar import monthrange
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestCommercialDepot(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref("mb_depot.group_depot_sale_manager")
        cls.env.user.group_ids |= cls.env.ref("account.group_account_invoice")
        if "l10n_fr_micro_depot_sale_horizon_confirmed" in cls.env.company._fields:
            cls.env.company.sudo().l10n_fr_micro_depot_sale_horizon_confirmed = True
        if not cls.env["account.journal"].search_count(
            [
                ("company_id", "=", cls.env.company.id),
                ("type", "=", "sale"),
            ]
        ):
            cls.env["account.chart.template"].sudo().try_loading(
                "generic_coa",
                company=cls.env.company,
                install_demo=False,
            )
        cls.home = cls.env["stock.warehouse"].search(
            [
                ("company_id", "=", cls.env.company.id),
                ("is_depot", "=", False),
            ],
            limit=1,
        )
        cls.gallery = cls.env["res.partner"].create(
            {
                "name": "Commercial Gallery",
                "is_company": True,
            }
        )
        cls.env["mb.depot.create"].create(
            {
                "partner_id": cls.gallery.id,
                "commission": 35.0,
                "legal_structure": "resale",
            }
        ).action_create()
        cls.depot = (
            cls.env["stock.warehouse"]
            .search(
                [
                    ("is_depot", "=", True),
                    ("depot_partner_id", "=", cls.gallery.id),
                ]
            )
            .ensure_one()
        )
        cls.depot.out_type_id.analytic_costs = True
        cls.product = cls.env["product.product"].create(
            {
                "name": "Forecast Bowl",
                "type": "consu",
                "is_storable": True,
                "sale_ok": True,
                "invoice_policy": "delivery",
                "list_price": 100.0,
                "standard_price": 20.0,
            }
        )
        cls.rent_product = cls.env["product.product"].create(
            {
                "name": "Depot Rent",
                "type": "service",
                "purchase_ok": True,
                "sale_ok": False,
            }
        )
        today = fields.Date.today()
        cls.contract = cls.env["mb.commercial.contract"].create(
            {
                "name": "Gallery Contract",
                "partner_id": cls.gallery.id,
                "depot_warehouse_id": cls.depot.id,
                "source_warehouse_id": cls.home.id,
                "date_start": today.replace(day=10),
                "monthly_fixed_rent": 310.0,
                "rent_billing_method": "vendor_bill",
                "rent_product_id": cls.rent_product.id,
                "refill_review_date": today,
            }
        )
        cls.rule = cls.env["mb.depot.assortment.rule"].create(
            {
                "name": "Bowl display",
                "contract_id": cls.contract.id,
                "product_id": cls.product.id,
                "minimum_quantity": 2,
                "target_quantity": 6,
                "demand_window_days": 30,
            }
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product,
            cls.home.lot_stock_id,
            20,
        )

    def _place(self, quantity, when):
        move = self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_qty": quantity,
                "location_id": self.home.lot_stock_id.id,
                "location_dest_id": self.depot.lot_stock_id.id,
            }
        )
        move._action_confirm()
        move.move_line_ids = [
            fields.Command.create(
                {
                    "product_id": self.product.id,
                    "location_id": self.home.lot_stock_id.id,
                    "location_dest_id": self.depot.lot_stock_id.id,
                    "quantity": quantity,
                    "picked": True,
                }
            )
        ]
        move.picked = True
        move._action_done()
        move.date = when
        move.move_line_ids.date = when

    def _sale_report(self, quantity=2, invoice=False):
        sold_at = fields.Datetime.now() - timedelta(days=2)
        report = self.env["mb.depot.sale.report"].create(
            {
                "depot_warehouse_id": self.depot.id,
                "external_reference": "COMMERCIAL-DEPOT-001"
                if not invoice
                else "COMMERCIAL-DEPOT-INV",
                "create_draft_invoice": invoice,
                "line_ids": [
                    fields.Command.create(
                        {
                            "sold_at": sold_at,
                            "product_id": self.product.id,
                            "quantity": quantity,
                            "reported_public_unit_price": 100.0,
                            "reported_commission_percentage": 35.0,
                        }
                    )
                ],
            }
        )
        report.action_process()
        return report

    def test_accounting_user_cannot_read_other_company_rent_period(self):
        own_period = self.env["mb.commercial.rent.period"].create(
            {
                "contract_id": self.contract.id,
                "period_start": fields.Date.today().replace(day=1),
            }
        )
        other_company = self.env["res.company"].create({"name": "Other Rent Workshop"})
        other_partner = (
            self.env["res.partner"]
            .with_company(other_company)
            .create(
                {
                    "name": "Other Gallery",
                    "company_id": other_company.id,
                }
            )
        )
        other_contract = (
            self.env["mb.commercial.contract"]
            .with_company(other_company)
            .create(
                {
                    "name": "Other Gallery Contract",
                    "company_id": other_company.id,
                    "partner_id": other_partner.id,
                    "date_start": fields.Date.today(),
                }
            )
        )
        other_period = (
            self.env["mb.commercial.rent.period"]
            .with_company(other_company)
            .create(
                {
                    "contract_id": other_contract.id,
                    "period_start": fields.Date.today().replace(day=1),
                }
            )
        )
        accountant = new_test_user(
            self.env,
            login="single-company-rent-accountant",
            groups="account.group_account_invoice",
            company_id=self.env.company.id,
        )
        periods = self.env["mb.commercial.rent.period"].with_user(accountant)

        self.assertEqual(
            periods.search([("id", "in", (own_period.id, other_period.id))]), own_period
        )
        with self.assertRaises(AccessError):
            other_period.with_user(accountant).read(["period_start"])

    def test_forecast_uses_processed_sales_and_exposure(self):
        self._place(5, fields.Datetime.now() - timedelta(days=10))
        self._sale_report(quantity=2)
        self.rule._refresh_forecast()
        forecast = self.rule.forecast_ids.sorted("snapshot_date")[-1]
        self.assertEqual(forecast.sold_quantity, 2)
        self.assertEqual(forecast.available_now, 3)
        self.assertGreater(forecast.exposed_days, 0)
        self.assertEqual(forecast.suggested_quantity, 3)
        self.assertIn(forecast.confidence, ("low", "forecast"))

    def test_recovery_window_attributes_contract_sales_once_and_rejects_overlap(self):
        self._place(2, fields.Datetime.now() - timedelta(days=5))
        self._sale_report(quantity=1)
        start = fields.Datetime.now() - timedelta(days=3)
        end = fields.Datetime.now() + timedelta(days=3)
        operation = self.env["mb.commercial.operation"].create(
            {
                "name": "Refill recovery",
                "operation_type": "depot_refill",
                "partner_id": self.gallery.id,
                "contract_id": self.contract.id,
                "depot_warehouse_id": self.depot.id,
                "planned_start": start,
                "planned_end": start + timedelta(hours=2),
                "recovery_scope": "contract_period",
                "recovery_date_from": start,
                "recovery_date_to": end,
            }
        )
        self.assertEqual(operation.actual_revenue, 0)
        self.assertEqual(operation.comparison_window_revenue, 65)
        with self.assertRaises(ValidationError):
            self.env["mb.commercial.operation"].create(
                {
                    "name": "Overlapping recovery",
                    "operation_type": "depot_refill",
                    "partner_id": self.gallery.id,
                    "contract_id": self.contract.id,
                    "depot_warehouse_id": self.depot.id,
                    "planned_start": start + timedelta(hours=3),
                    "planned_end": start + timedelta(hours=4),
                    "recovery_scope": "contract_period",
                    "recovery_date_from": start + timedelta(days=1),
                    "recovery_date_to": end + timedelta(days=1),
                }
            )

    def test_refill_operation_creates_native_transfer_to_depot(self):
        self._place(5, fields.Datetime.now() - timedelta(days=10))
        self._sale_report(quantity=2)
        action = self.contract.action_create_refill_operation()
        operation = self.env["mb.commercial.operation"].browse(action["res_id"])
        self.assertEqual(operation.operation_type, "depot_refill")
        self.assertEqual(operation.project_id, self.contract.project_id)
        operation.action_approve()
        operation.action_prepare_market_stock()
        self.assertEqual(operation.preparation_picking_id.location_dest_id, self.depot.lot_stock_id)
        self.assertEqual(operation.preparation_picking_id.state, "assigned")

    def test_rent_bill_is_prorated_idempotent_and_analytic(self):
        today = fields.Date.today()
        self.contract.rent_period_to_prepare = today
        first = self.contract.action_prepare_rent_bill()
        second = self.contract.action_prepare_rent_bill()
        self.assertEqual(first["res_id"], second["res_id"])
        period = self.contract.rent_period_ids
        days = monthrange(today.year, today.month)[1]
        expected = self.env.company.currency_id.round(310.0 * (days - 9) / days)
        self.assertEqual(period.amount, expected)
        self.assertEqual(period.bill_id.state, "draft")
        self.assertEqual(
            period.bill_id.invoice_line_ids.analytic_distribution,
            {str(self.contract.analytic_account_id.id): 100.0},
        )

    def test_depot_invoice_revenue_carries_contract_analytic_account(self):
        self._place(2, fields.Datetime.now() - timedelta(days=5))
        report = self._sale_report(quantity=1, invoice=True)
        self.assertEqual(report.sale_order_ids.mb_commercial_contract_id, self.contract)
        self.assertEqual(report.invoice_ids.mb_commercial_contract_id, self.contract)
        self.assertEqual(
            report.invoice_ids.invoice_line_ids.filtered(
                lambda line: line.display_type == "product"
            ).analytic_distribution,
            {str(self.contract.analytic_account_id.id): 100.0},
        )
        picking = report.sale_order_ids.picking_ids
        self.assertEqual(picking.project_id, self.contract.project_id)
        plan_column = self.contract.analytic_account_id.plan_id._column_name()
        stock_costs = self.env["account.analytic.line"].search(
            [
                (plan_column, "=", self.contract.analytic_account_id.id),
                ("category", "=", "picking_entry"),
            ]
        )
        self.assertEqual(sum(stock_costs.mapped("amount")), -20.0)

    def _depot_scenario(self, **values):
        """2000 a month at 35% commission, 310 rent, two 4-hour permanences."""
        return self.env["mb.depot.profitability.scenario"].create(
            {
                "contract_id": self.contract.id,
                "expected_monthly_sales": 2000.0,
                "product_cost_ratio": 20.0,
                "permanences_per_month": 2.0,
                "hours_per_permanence": 4.0,
                "travel_cost_per_permanence": 20.0,
                "travel_hours_per_permanence": 1.5,
                **values,
            }
        )

    def test_depot_scenario_spreads_commission_fee_and_permanences_over_the_term(self):
        scenario = self._depot_scenario()

        self.assertEqual(scenario.commission_rate, 35.0)
        self.assertEqual(scenario.monthly_fixed_rent, 310.0)
        self.assertEqual(scenario.term_months, 6)
        self.assertEqual(scenario.monthly_commission, 700.0)
        self.assertEqual(scenario.monthly_receipts, 1300.0)
        self.assertEqual(scenario.monthly_product_cost, 400.0)
        self.assertEqual(scenario.monthly_contribution, 900.0)
        self.assertEqual(scenario.monthly_fixed_cost, 350.0)
        self.assertEqual(scenario.monthly_margin, 550.0)
        self.assertEqual(scenario.term_margin, 3300.0)
        self.assertEqual(scenario.permanence_count, 12.0)
        self.assertEqual(scenario.work_hours, 48.0)
        self.assertEqual(scenario.travel_hours, 18.0)
        self.assertEqual(scenario.effort_hours, 66.0)
        self.assertEqual(scenario.margin_per_effort_hour, 50.0)
        self.assertAlmostEqual(scenario.break_even_monthly_sales, 777.78, places=2)
        self.assertEqual(scenario.recommendation, "go")
        self.assertIn("above break-even", scenario.recommendation_note)

    def test_depot_below_break_even_is_not_worth_the_permanences(self):
        scenario = self._depot_scenario(expected_monthly_sales=600.0)

        self.assertEqual(scenario.monthly_margin, -80.0)
        self.assertEqual(scenario.term_margin, -480.0)
        self.assertEqual(scenario.recommendation, "no_go")
        self.assertIn("needed to cover", scenario.recommendation_note)

    def test_depot_hourly_target_downgrades_an_otherwise_profitable_contract(self):
        self.env.company.mb_market_target_margin_per_hour = 60.0
        scenario = self._depot_scenario()

        self.assertEqual(scenario.target_margin_per_hour, 60.0)
        self.assertEqual(scenario.margin_per_effort_hour, 50.0)
        self.assertEqual(scenario.recommendation, "marginal")
        self.assertIn("below the", scenario.recommendation_note)

    def test_depot_without_expected_sales_cannot_be_judged(self):
        scenario = self._depot_scenario(expected_monthly_sales=0.0)

        self.assertTrue(scenario.calculation_blocked)
        self.assertEqual(scenario.recommendation, "unknown")
        self.assertIn("each month", scenario.recommendation_note)
        with self.assertRaises(ValidationError):
            scenario.action_approve()

    def test_depot_term_and_permanences_come_from_the_contract(self):
        self.contract.date_end = self.contract.date_start + relativedelta(months=6)
        self.env["mb.commercial.obligation"].create(
            {
                "name": "Saturday permanence",
                "contract_id": self.contract.id,
                "date_start": self.contract.date_start,
                "required_occurrences": 2,
                "period_unit": "month",
                "duration_hours": 4.0,
            }
        )
        scenario = self.env["mb.depot.profitability.scenario"].create(
            {
                "contract_id": self.contract.id,
                "expected_monthly_sales": 2000.0,
            }
        )

        self.assertEqual(scenario.term_months, 6)
        self.assertEqual(scenario.permanences_per_month, 2.0)
        self.assertEqual(scenario.hours_per_permanence, 4.0)

    def test_weekly_permanences_are_not_four_a_month(self):
        self.env["mb.commercial.obligation"].create(
            {
                "name": "Weekly permanence",
                "contract_id": self.contract.id,
                "date_start": self.contract.date_start,
                "required_occurrences": 1,
                "period_unit": "week",
                "duration_hours": 3.0,
            }
        )
        scenario = self.env["mb.depot.profitability.scenario"].create(
            {
                "contract_id": self.contract.id,
                "expected_monthly_sales": 2000.0,
            }
        )

        self.assertAlmostEqual(scenario.permanences_per_month, 52.0 / 12.0, places=4)
        self.assertAlmostEqual(scenario.hours_per_permanence, 3.0, places=4)

    def test_a_contract_ending_on_the_last_day_owes_that_month_too(self):
        self.contract.date_start = fields.Date.to_date("2026-01-01")
        self.contract.date_end = fields.Date.to_date("2026-12-31")
        scenario = self._depot_scenario()

        self.assertEqual(scenario.term_months, 12)

    def test_unaccepted_travel_quote_cannot_price_the_drive_at_zero(self):
        connector = self.env["mb.tollquote.connector"].create(
            {
                "name": "Depot quotes",
                "company_id": self.env.company.id,
                "api_token": "secret",
            }
        )
        estimate = self.env["mb.travel.estimate"].create(
            {
                "name": "Depot round trip",
                "connector_id": connector.id,
                "company_id": self.env.company.id,
                "origin_latitude": 48.85,
                "origin_longitude": 2.35,
                "destination_latitude": 45.76,
                "destination_longitude": 4.83,
            }
        )
        scenario = self._depot_scenario(
            travel_estimate_id=estimate.id,
            travel_cost_per_permanence=0.0,
            travel_hours_per_permanence=0.0,
        )

        self.assertNotEqual(estimate.state, "accepted")
        self.assertTrue(scenario.calculation_blocked)
        self.assertEqual(scenario.recommendation, "unknown")
        self.assertIn("travel quote", scenario.recommendation_note)

    def test_approved_scenario_does_not_follow_later_contract_changes(self):
        scenario = self._depot_scenario()
        scenario.action_approve()

        self.contract.monthly_fixed_rent = 900.0
        self.depot.depot_commission = 60.0
        scenario.invalidate_recordset()

        self.assertEqual(scenario.monthly_fixed_rent, 310.0)
        self.assertEqual(scenario.commission_rate, 35.0)
        self.assertEqual(scenario.term_margin, 3300.0)
        self.assertEqual(scenario.recommendation, "go")

    def test_approved_depot_scenario_is_frozen_and_carried_on_the_contract(self):
        scenario = self._depot_scenario()
        scenario.action_approve()

        self.assertEqual(scenario.state, "approved")
        self.assertEqual(self.contract.primary_depot_scenario_id, scenario)
        self.assertEqual(self.contract.depot_recommendation, "go")
        self.assertEqual(self.contract.depot_term_margin, 3300.0)
        self.assertEqual(self.contract.depot_margin_per_hour, 50.0)
        with self.assertRaises(UserError):
            scenario.expected_monthly_sales = 2500.0

    def test_overlapping_depot_contract_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["mb.commercial.contract"].create(
                {
                    "partner_id": self.gallery.id,
                    "depot_warehouse_id": self.depot.id,
                    "source_warehouse_id": self.home.id,
                    "date_start": self.contract.date_start,
                    "rent_billing_method": "information",
                }
            )

    def test_contract_end_and_next_start_on_same_day_overlap_inclusively(self):
        self.contract.write(
            {
                "date_start": fields.Date.to_date("2094-01-01"),
                "date_end": fields.Date.to_date("2094-01-31"),
            }
        )
        values = {
            "partner_id": self.gallery.id,
            "depot_warehouse_id": self.depot.id,
            "source_warehouse_id": self.home.id,
            "rent_billing_method": "information",
        }
        with self.assertRaisesRegex(ValidationError, "overlapping active"):
            with self.env.cr.savepoint():
                self.env["mb.commercial.contract"].create(
                    {**values, "date_start": fields.Date.to_date("2094-01-31")}
                )
        following = self.env["mb.commercial.contract"].create(
            {**values, "date_start": fields.Date.to_date("2094-02-01")}
        )
        self.assertEqual(following.date_start, fields.Date.to_date("2094-02-01"))

    def test_same_dates_are_allowed_for_distinct_company_owned_depots(self):
        self.contract.active = False
        other_company = self.env["res.company"].create({"name": "Other Depot Workshop"})
        other_partner = (
            self.env["res.partner"]
            .with_company(other_company)
            .create(
                {
                    "name": "Other Company Gallery",
                    "is_company": True,
                    "company_id": other_company.id,
                }
            )
        )
        other_depot = (
            self.env["stock.warehouse"]
            .with_company(other_company)
            .create(
                {
                    "name": "Other Company Gallery",
                    "code": f"O{other_company.id:04d}"[-5:],
                    "company_id": other_company.id,
                    "reception_steps": "one_step",
                    "delivery_steps": "ship_only",
                    "is_depot": True,
                    "mb_depot_legal_structure": "resale",
                    "depot_partner_id": other_partner.id,
                }
            )
        )
        start = fields.Date.to_date("2094-03-01")
        first = self.env["mb.commercial.contract"].create(
            {
                "partner_id": self.gallery.id,
                "depot_warehouse_id": self.depot.id,
                "date_start": start,
                "rent_billing_method": "information",
            }
        )
        other = (
            self.env["mb.commercial.contract"]
            .with_company(other_company)
            .create(
                {
                    "company_id": other_company.id,
                    "partner_id": other_partner.id,
                    "depot_warehouse_id": other_depot.id,
                    "date_start": start,
                    "rent_billing_method": "information",
                }
            )
        )
        self.assertEqual(first.date_start, other.date_start)
