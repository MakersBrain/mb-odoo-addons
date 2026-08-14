from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDefaultCounter(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Config = cls.env["pos.config"].sudo()
        cls.Company = cls.env["res.company"].sudo()

    def counters(self, company):
        return self.Config.search([("company_id", "=", company.id)])

    def test_loading_a_chart_seeds_exactly_one_counter(self):
        company = self.Company.create({"name": "Counter workshop"})

        self.env["account.chart.template"].sudo().try_loading(
            "fr", company=company, install_demo=False,
        )

        counter = self.counters(company)
        self.assertEqual(len(counter), 1)
        self.assertEqual(counter.name, company.name)
        # The three the Retail card creates: cash, card, customer account.
        self.assertEqual(len(counter.payment_method_ids), 3)
        self.assertTrue(counter.journal_id)

    def test_seeding_is_idempotent(self):
        company = self.Company.create({"name": "Idempotent workshop"})
        self.env["account.chart.template"].sudo().try_loading(
            "fr", company=company, install_demo=False,
        )
        first = self.counters(company)

        self.assertFalse(self.Config._mb_ensure_default_counter(company))
        self.assertEqual(self.counters(company), first)

    def test_a_company_without_a_chart_is_left_alone(self):
        company = self.Company.create({"name": "Chartless workshop"})

        self.assertFalse(self.Config._mb_ensure_default_counter(company))
        self.assertFalse(self.counters(company))

    def test_a_seeded_counter_retires_the_shop_type_screen(self):
        company = self.Company.create({"name": "Kanban workshop"})
        self.env["account.chart.template"].sudo().try_loading(
            "fr", company=company, install_demo=False,
        )

        state = (
            self.Config.with_company(company)
            .with_context(allowed_company_ids=company.ids)
            .get_pos_kanban_view_state()
        )

        self.assertTrue(state["has_pos_config"])

    def test_a_failed_seed_does_not_roll_back_the_chart(self):
        company = self.Company.create({"name": "Resilient workshop"})

        with patch.object(
            type(self.Config),
            "_mb_ensure_default_counter",
            side_effect=ValueError("no counter today"),
        ):
            self.env["account.chart.template"].sudo().try_loading(
                "fr", company=company, install_demo=False,
            )

        self.assertEqual(company.chart_template, "fr")
        self.assertFalse(self.counters(company))
