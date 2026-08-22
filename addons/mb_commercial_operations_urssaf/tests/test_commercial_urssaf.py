from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError, ValidationError
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

    def _create_operation(self, name="URSSAF operation", company=None):
        company = company or self.env.company
        start = fields.Datetime.now() + timedelta(days=3)
        return self.env["mb.commercial.operation"].create(
            {
                "name": name,
                "company_id": company.id,
                "partner_id": company.partner_id.id,
                "planned_start": start,
                "planned_end": start + timedelta(hours=8),
            }
        )

    def _create_declaration_source(self, invoice, event_key):
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
                "event_key": event_key,
                "recognition_date": fields.Date.today(),
                "category": "bic_goods",
                "amount": 100,
                "engine": "reconciliation",
                "origin_move_id": invoice.id,
                "receipt_method": "transfer",
            }
        )
        return declaration, source

    def test_attribution_resolver_accepts_one_missing_or_same_operation(self):
        operation = self._create_operation()
        pos_order = self.env["pos.order"].new({"mb_commercial_operation_id": operation.id})
        invoice = self.env["account.move"].new({"mb_commercial_operation_id": operation.id})
        empty_pos = self.env["pos.order"].browse()
        empty_invoice = self.env["account.move"].browse()
        Source = self.env["l10n.fr.micro.urssaf.declaration.source"]

        self.assertEqual(
            Source._mb_resolve_commercial_operation(pos_order, invoice, self.env.company),
            operation,
        )
        self.assertEqual(
            Source._mb_resolve_commercial_operation(pos_order, empty_invoice, self.env.company),
            operation,
        )
        self.assertEqual(
            Source._mb_resolve_commercial_operation(empty_pos, invoice, self.env.company),
            operation,
        )
        self.assertFalse(
            Source._mb_resolve_commercial_operation(
                empty_pos,
                empty_invoice,
                self.env.company,
            )
        )

    def test_attribution_resolver_rejects_conflicting_pos_and_invoice(self):
        pos_operation = self._create_operation("POS operation")
        invoice_operation = self._create_operation("Invoice operation")
        pos_order = self.env["pos.order"].new({"mb_commercial_operation_id": pos_operation.id})
        invoice = self.env["account.move"].new({"mb_commercial_operation_id": invoice_operation.id})

        with self.assertRaises(ValidationError):
            self.env["l10n.fr.micro.urssaf.declaration.source"]._mb_resolve_commercial_operation(
                pos_order, invoice, self.env.company
            )

    def test_draft_attribution_follows_invoice_but_filed_snapshot_is_frozen(self):
        first_operation = self._create_operation("First operation")
        second_operation = self._create_operation("Second operation")
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.env.company.partner_id.id,
                "mb_commercial_operation_id": first_operation.id,
            }
        )
        declaration, source = self._create_declaration_source(invoice, "snapshot-propagation")
        self.assertEqual(source.mb_commercial_operation_id, first_operation)

        invoice.mb_commercial_operation_id = second_operation
        self.assertEqual(source.mb_commercial_operation_id, second_operation)

        declaration.with_context(**internal_context()).state = "filed"
        invoice.mb_commercial_operation_id = first_operation
        self.assertEqual(source.mb_commercial_operation_id, second_operation)

    def test_company_change_clears_draft_snapshot(self):
        operation = self._create_operation()
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.env.company.partner_id.id,
                "mb_commercial_operation_id": operation.id,
            }
        )
        declaration, source = self._create_declaration_source(invoice, "company-change")
        other_company = self.env["res.company"].create({"name": "Other URSSAF company"})
        other_operation = self._create_operation("Other-company template", other_company)

        operation.write(
            {
                "company_id": other_company.id,
                "project_id": other_operation.project_id.id,
                "task_id": False,
            }
        )
        self.assertFalse(source.mb_commercial_operation_id)

    def test_company_change_cannot_rewrite_filed_attribution(self):
        operation = self._create_operation()
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.env.company.partner_id.id,
                "mb_commercial_operation_id": operation.id,
            }
        )
        declaration, source = self._create_declaration_source(invoice, "filed-company-change")
        declaration.with_context(**internal_context()).state = "filed"
        self.assertEqual(source.mb_commercial_operation_id, operation)
        self.assertEqual(source._fields["mb_commercial_operation_id"].ondelete, "restrict")
        self.assertTrue(operation.write({"company_id": operation.company_id.id}))
        other_company = self.env["res.company"].create({"name": "Filed other company"})
        other_operation = self._create_operation("Filed other template", other_company)

        with self.assertRaises(UserError):
            operation.write(
                {
                    "company_id": other_company.id,
                    "project_id": other_operation.project_id.id,
                }
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

        # Evidence outranks the analytic account. Losing the account must not
        # relabel an operation a filed declaration has already recognised as
        # having no recognizable revenue.
        operation.project_id.account_id = False
        operation.invalidate_recordset()
        self.assertFalse(operation.analytic_account_id)
        self.assertEqual(operation.urssaf_recognition_status, "filed")

    def test_status_is_readable_without_sight_of_the_declaration_sources(self):
        operation = self.env["mb.commercial.operation"].create(
            {
                "name": "URSSAF ACL market",
                "partner_id": self.env.company.partner_id.id,
                "planned_start": fields.Datetime.now() + timedelta(days=3),
                "planned_end": fields.Datetime.now() + timedelta(days=3, hours=8),
            }
        )
        # The field is rendered on the operation form, which this group opens;
        # the source model is readable only by the accounting groups.
        user = self.env["res.users"].create(
            {
                "name": "Operations only",
                "login": "urssaf-operations-only",
                "group_ids": [
                    fields.Command.link(self.env.ref("base.group_user").id),
                    fields.Command.link(
                        self.env.ref("mb_commercial_operations.group_commercial_operations_user").id
                    ),
                ],
            }
        )
        self.assertFalse(
            self.env["l10n.fr.micro.urssaf.declaration.source"].with_user(user).has_access("read")
        )
        self.assertEqual(
            operation.with_user(user).urssaf_recognition_status,
            "not_applicable",
        )
        self.env["account.analytic.line"].create(
            {
                "name": "Protected recognizable revenue",
                "account_id": operation.analytic_account_id.id,
                "mb_commercial_operation_id": operation.id,
                "amount": 100,
            }
        )
        seen_su = []
        operation_class = type(operation)
        original_hook = operation_class._mb_has_recognizable_revenue

        def checked_hook(record):
            seen_su.append(record.env.su)
            return original_hook(record)

        restricted_operation = operation.with_user(user)
        restricted_operation.invalidate_recordset(["urssaf_recognition_status"])
        with patch.object(operation_class, "_mb_has_recognizable_revenue", checked_hook):
            self.assertEqual(restricted_operation.urssaf_recognition_status, "pending")
        self.assertEqual(seen_su, [False])

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
