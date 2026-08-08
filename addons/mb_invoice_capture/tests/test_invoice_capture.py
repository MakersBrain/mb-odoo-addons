import base64
import hashlib
import uuid

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInvoiceCapture(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Capture = cls.env["mb.invoice.capture"].sudo()
        cls.company = cls.env.company.sudo()
        cls.workshop_id = str(uuid.uuid4())
        cls.company.mb_control_workshop_id = cls.workshop_id
        cls.partner = cls.env["res.partner"].create({
            "name": "Clay Supplier",
            "vat": "FR40303265045",
            "supplier_rank": 1,
        })
        cls.expense_account = cls.env["account.account"].with_company(cls.company).search([
            ("company_ids", "in", cls.company.id),
            ("account_type", "in", ["expense", "expense_depreciation", "expense_direct_cost"]),
        ], limit=1)
        if not cls.expense_account:
            cls.expense_account = cls.env["account.account"].with_company(cls.company).create({
                "name": "Capture test expense",
                "code": "CAPTURETEST",
                "account_type": "expense",
                "company_ids": [(6, 0, [cls.company.id])],
            })
        cls.source = b"%PDF-1.4\nfixture invoice\n%%EOF"

    def payload(self, **changes):
        payload = {
            "workshop_id": self.workshop_id,
            "external_document_id": "paperless:42",
            "content_digest": hashlib.sha256(self.source).hexdigest(),
            "source_filename": "supplier-invoice.pdf",
            "source_mimetype": "application/pdf",
            "source_base64": base64.b64encode(self.source).decode(),
            "provider": "azure",
            "model": "prebuilt-invoice",
            "model_version": "fixture-v1",
            "provider_operation_id": "fixture-operation",
            "page_count": 1,
            "requires_review": False,
            "field_confidence": {"supplier_vat": 0.99, "total_amount": 0.98},
            "invoice": {
                "supplier_name": "Clay Supplier",
                "supplier_vat": "FR40303265045",
                "invoice_number": "INV-2026-0042",
                "invoice_date": "2026-08-01",
                "currency": self.company.currency_id.name,
                "untaxed_amount": "10.00",
                "tax_amount": "0.00",
                "total_amount": "10.00",
                "lines": [{
                    "description": "Clay",
                    "quantity": "2",
                    "unit_price": "5.00",
                    "account_code": self.expense_account.with_company(self.company).code,
                }],
            },
        }
        payload.update(changes)
        return payload

    def test_balanced_extraction_creates_one_draft_bill(self):
        result = self.Capture.ingest(self.payload())
        replay = self.Capture.ingest(self.payload())
        capture = self.Capture.browse(result["capture_id"])

        self.assertEqual(result["status"], "draft_bill")
        self.assertFalse(replay["applied"])
        self.assertEqual(capture.move_id.state, "draft")
        self.assertEqual(capture.move_id.move_type, "in_invoice")
        self.assertEqual(capture.move_id.partner_id, self.partner)
        self.assertEqual(capture.move_id.amount_total, 10.0)
        self.assertTrue(capture.source_attachment_id)
        self.assertEqual(self.Capture.search_count([
            ("external_document_id", "=", "paperless:42")
        ]), 1)

    def test_changed_revision_never_overwrites_the_prior_bill(self):
        first = self.Capture.ingest(self.payload())
        revised_source = self.source + b"\nrevision"
        second = self.Capture.ingest(self.payload(
            content_digest=hashlib.sha256(revised_source).hexdigest(),
            source_base64=base64.b64encode(revised_source).decode(),
        ))
        first_capture = self.Capture.browse(first["capture_id"])
        second_capture = self.Capture.browse(second["capture_id"])

        self.assertEqual(second_capture.status, "review")
        self.assertFalse(second_capture.move_id)
        self.assertEqual(second_capture.previous_revision_id, first_capture)
        self.assertEqual(first_capture.move_id.state, "draft")

    def test_unknown_supplier_is_reviewed_without_creating_master_data(self):
        count = self.env["res.partner"].search_count([])
        invoice = dict(self.payload()["invoice"], supplier_name="Invented Vendor", supplier_vat="FR00000000000")
        result = self.Capture.ingest(self.payload(invoice=invoice))

        self.assertEqual(result["status"], "review")
        self.assertIsNone(result["bill_id"])
        self.assertEqual(self.env["res.partner"].search_count([]), count)

    def test_customer_contact_can_be_matched_as_first_supplier_invoice(self):
        self.partner.supplier_rank = 0
        self.partner.customer_rank = 1

        result = self.Capture.ingest(self.payload())

        self.assertEqual(result["status"], "draft_bill")
        self.assertEqual(self.Capture.browse(result["capture_id"]).move_id.partner_id, self.partner)

    def test_review_can_create_editable_draft_after_supplier_is_selected(self):
        invoice = dict(
            self.payload()["invoice"],
            supplier_name="New Supplier",
            supplier_vat="FR00000000000",
        )
        result = self.Capture.ingest(self.payload(invoice=invoice))
        capture = self.Capture.browse(result["capture_id"])
        supplier = self.env["res.partner"].create({
            "name": "New Supplier",
            "vat": "FR00000000000",
            "is_company": True,
        })
        capture.write({
            "review_supplier_id": supplier.id,
            "review_expense_account_id": self.expense_account.id,
        })

        action = capture.action_create_reviewed_bill()

        self.assertEqual(action["res_id"], capture.move_id.id)
        self.assertEqual(capture.move_id.partner_id, supplier)
        self.assertEqual(capture.move_id.state, "draft")
        self.assertEqual(capture.status, "review")
        self.assertEqual(capture.move_id.invoice_line_ids.mapped("name"), ["Clay"])

    def test_review_repairs_french_milli_scaled_extracted_lines(self):
        invoice = dict(self.payload()["invoice"], lines=[
            {"description": "Stoneware", "quantity": "12500", "unit_price": "1170"},
            {"description": "Glaze", "quantity": "1000", "unit_price": "39165"},
        ], untaxed_amount="53.79", tax_amount="0.00", total_amount="53.79")
        result = self.Capture.ingest(self.payload(invoice=invoice))
        capture = self.Capture.browse(result["capture_id"])
        capture.write({
            "review_supplier_id": self.partner.id,
            "review_expense_account_id": self.expense_account.id,
        })

        capture.action_create_reviewed_bill()

        lines = capture.move_id.invoice_line_ids
        self.assertEqual(lines.mapped("name"), ["Stoneware", "Glaze"])
        self.assertEqual(lines[0].quantity, 12.5)
        self.assertEqual(lines[1].quantity, 1.0)
        self.assertEqual(capture.move_id.amount_total, 53.79)

    def test_bad_totals_are_reviewed_without_a_bill(self):
        invoice = dict(self.payload()["invoice"], total_amount="99.00")
        result = self.Capture.ingest(self.payload(invoice=invoice))

        self.assertEqual(result["status"], "review")
        self.assertIsNone(result["bill_id"])
        self.assertIn("reconcile", result["review_reason"])

    def test_low_confidence_keeps_the_bill_in_review(self):
        result = self.Capture.ingest(self.payload(requires_review=True))
        capture = self.Capture.browse(result["capture_id"])

        self.assertEqual(capture.status, "review")
        self.assertEqual(capture.move_id.state, "draft")

    def test_cross_workshop_capture_is_denied(self):
        from odoo.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.Capture.ingest(self.payload(workshop_id=str(uuid.uuid4())))

    def test_review_fields_present_invoice_and_confidence(self):
        result = self.Capture.ingest(self.payload())
        capture = self.Capture.browse(result["capture_id"])

        self.assertEqual(capture.supplier_name, "Clay Supplier")
        self.assertEqual(capture.invoice_number, "INV-2026-0042")
        self.assertEqual(capture.total_amount_display, f"10.00 {self.company.currency_id.name}")
        self.assertIn("Clay", str(capture.invoice_lines_summary))
        self.assertIn("Supplier vat", str(capture.confidence_summary))
        self.assertIn("99.0%", str(capture.confidence_summary))
