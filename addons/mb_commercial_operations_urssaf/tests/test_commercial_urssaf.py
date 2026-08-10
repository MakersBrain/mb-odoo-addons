from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCommercialUrssaf(TransactionCase):
    def test_status_tracks_revenue_then_draft_legal_evidence(self):
        start = fields.Datetime.now() + timedelta(days=3)
        operation = self.env["mb.commercial.operation"].create({
            "name": "URSSAF market",
            "partner_id": self.env.company.partner_id.id,
            "planned_start": start,
            "planned_end": start + timedelta(hours=8),
        })
        self.assertEqual(operation.urssaf_recognition_status, "not_applicable")
        self.env["account.analytic.line"].create({
            "name": "Recognizable revenue",
            "account_id": operation.analytic_account_id.id,
            "amount": 100,
        })
        operation.invalidate_recordset(["urssaf_recognition_status", "urssaf_source_ids"])
        self.assertEqual(operation.urssaf_recognition_status, "pending")

        invoice = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.env.company.partner_id.id,
            "invoice_line_ids": [fields.Command.create({
                "name": "Market sale",
                "quantity": 1,
                "price_unit": 100,
                "analytic_distribution": {
                    str(operation.analytic_account_id.id): 100.0,
                },
            })],
        })
        declaration = self.env["l10n.fr.micro.urssaf.declaration"].create({
            "date_from": fields.Date.today().replace(day=1),
            "date_to": fields.Date.today(),
        })
        declaration_line = self.env["l10n.fr.micro.urssaf.declaration.line"].create({
            "declaration_id": declaration.id,
            "category": "bic_goods",
        })
        source = self.env["l10n.fr.micro.urssaf.declaration.source"].create({
            "declaration_id": declaration.id,
            "declaration_line_id": declaration_line.id,
            "event_key": "commercial-operation-test",
            "recognition_date": fields.Date.today(),
            "category": "bic_goods",
            "amount": 100,
            "engine": "reconciliation",
            "origin_move_id": invoice.id,
            "receipt_method": "transfer",
        })
        operation.invalidate_recordset(["urssaf_recognition_status", "urssaf_source_ids"])
        self.assertEqual(operation.urssaf_recognition_status, "computed")
        self.assertEqual(operation.urssaf_source_ids, source)
