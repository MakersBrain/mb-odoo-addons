from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.l10n_fr_micro_urssaf.models.internal import internal_context


@tagged("post_install", "-at_install")
class TestCommercialUrssaf(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
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

    def test_status_tracks_revenue_then_draft_legal_evidence(self):
        start = fields.Datetime.now() + timedelta(days=3)
        operation = self.env["mb.commercial.operation"].create(
            {
                "name": "URSSAF market",
                "partner_id": self.env.company.partner_id.id,
                "planned_start": start,
                "planned_end": start + timedelta(hours=8),
            }
        )
        self.assertEqual(operation.urssaf_recognition_status, "not_applicable")
        self.env["account.analytic.line"].create(
            {
                "name": "Recognizable revenue",
                "account_id": operation.analytic_account_id.id,
                "mb_commercial_operation_id": operation.id,
                "amount": 100,
            }
        )
        self.assertEqual(operation.urssaf_recognition_status, "pending")

        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.env.company.partner_id.id,
                "mb_commercial_operation_id": operation.id,
                "invoice_line_ids": [
                    fields.Command.create(
                        {
                            "name": "Market sale",
                            "quantity": 1,
                            "price_unit": 100,
                            "analytic_distribution": {
                                str(operation.analytic_account_id.id): 100.0,
                            },
                        }
                    )
                ],
            }
        )
        declaration = self.env["l10n.fr.micro.urssaf.declaration"].create(
            {
                "date_from": fields.Date.today().replace(day=1),
                "date_to": fields.Date.today(),
            }
        )
        declaration_line = self.env["l10n.fr.micro.urssaf.declaration.line"].create(
            {
                "declaration_id": declaration.id,
                "category": "bic_goods",
            }
        )
        source = self.env["l10n.fr.micro.urssaf.declaration.source"].create(
            {
                "declaration_id": declaration.id,
                "declaration_line_id": declaration_line.id,
                "event_key": "commercial-operation-test",
                "recognition_date": fields.Date.today(),
                "category": "bic_goods",
                "amount": 100,
                "engine": "reconciliation",
                "origin_move_id": invoice.id,
                "receipt_method": "transfer",
            }
        )
        self.assertEqual(operation.urssaf_recognition_status, "computed")
        self.assertEqual(operation.urssaf_source_ids, source)

        # The whole point of the relation: filing the declaration has to
        # move the operation without anyone flushing the cache by hand.
        # Written through the module's own internal context rather than
        # action_file(), which additionally needs manager rights and a
        # anomaly-free declaration -- neither is what this asserts.
        declaration.with_context(**internal_context()).state = "filed"
        self.assertEqual(operation.urssaf_recognition_status, "filed")

    def test_wizard_snapshots_dated_goods_rates_without_reimplementing_rules(self):
        start = fields.Datetime.now() + timedelta(days=10)
        operation = self.env["mb.commercial.operation"].create(
            {
                "name": "Goods rate plan",
                "partner_id": self.env.company.partner_id.id,
                "planned_start": start,
                "planned_end": start + timedelta(hours=4),
            }
        )
        wizard = self.env["mb.commercial.operation.plan.wizard"].create(
            {
                "operation_id": operation.id,
                "name": operation.name,
                "operation_type": "market",
                "company_id": self.env.company.id,
                "partner_id": operation.partner_id.id,
                "departure": start,
                "line_ids": [
                    fields.Command.create(
                        {
                            "expected_sold_qty": 1,
                            "sale_price_excluded_tax": 100,
                            "product_unit_cost": 20,
                            "apply_urssaf_goods_rates": True,
                        }
                    )
                ],
            }
        )
        values = wizard.line_ids._scenario_values()
        rate_model = self.env["l10n.fr.micro.urssaf.rate"]
        date = fields.Date.to_date(start)
        cotisation = rate_model.rate_for("cotisation", "bic_goods", date, self.env.company)
        self.assertEqual(values["urssaf_cotisation_rate_id"], cotisation.id)
        self.assertEqual(values["urssaf_rate_date"], date)
        self.assertGreaterEqual(values["turnover_levy_rate"], cotisation.rate)
