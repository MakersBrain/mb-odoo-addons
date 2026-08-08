import base64
import binascii
import re
from decimal import Decimal, InvalidOperation

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_EXTERNAL_ID_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,255}$")
MAX_SOURCE_BYTES = 20 * 1024 * 1024


def _decimal(value, field_name):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(_("%(field)s must be a decimal number.", field=field_name)) from exc
    if not result.is_finite():
        raise ValidationError(_("%(field)s must be finite.", field=field_name))
    return result


def _normalized_identifier(value):
    return "".join(character for character in (value or "").upper() if character.isalnum())


def _normalized_name(value):
    return " ".join((value or "").casefold().split())


class InvoiceCapture(models.Model):
    _name = "mb.invoice.capture"
    _description = "Supplier invoice capture"
    _inherit = ["mail.thread"]
    _order = "received_at desc, id desc"

    company_id = fields.Many2one(
        "res.company", required=True, index=True, readonly=True,
        default=lambda self: self.env.company,
    )
    external_document_id = fields.Char(required=True, index=True, readonly=True)
    content_digest = fields.Char(required=True, readonly=True)
    revision = fields.Integer(required=True, readonly=True, default=1)
    previous_revision_id = fields.Many2one(
        "mb.invoice.capture", readonly=True, ondelete="restrict"
    )
    status = fields.Selection(
        [
            ("received", "Received"),
            ("review", "Needs review"),
            ("draft_bill", "Draft bill created"),
        ],
        required=True,
        default="received",
        readonly=True,
        tracking=True,
        index=True,
    )
    review_reason = fields.Text(readonly=True, tracking=True)
    move_id = fields.Many2one("account.move", readonly=True, ondelete="restrict")
    source_attachment_id = fields.Many2one(
        "ir.attachment", readonly=True, ondelete="restrict"
    )
    source_filename = fields.Char(required=True, readonly=True)
    source_mimetype = fields.Char(required=True, readonly=True)
    extraction_provider = fields.Selection(
        [("structured", "Structured invoice"), ("azure", "Azure Document Intelligence")],
        required=True,
        readonly=True,
    )
    extraction_model = fields.Char(readonly=True)
    extraction_model_version = fields.Char(readonly=True)
    extraction_operation_id = fields.Char(readonly=True)
    page_count = fields.Integer(readonly=True)
    normalized_payload = fields.Json(required=True, readonly=True)
    field_confidence = fields.Json(readonly=True)
    received_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    _document_revision_unique = models.Constraint(
        "UNIQUE(company_id, external_document_id, content_digest)",
        "This document revision has already been captured.",
    )
    _document_revision_number_unique = models.Constraint(
        "UNIQUE(company_id, external_document_id, revision)",
        "Each document revision number must be unique.",
    )

    @api.model
    def _validate_envelope(self, payload):
        company = self.env.company
        workshop_id = str(payload.get("workshop_id", "")).lower()
        if not company.mb_control_workshop_id:
            raise ValidationError("the Odoo company is not linked to a control-plane workshop")
        if workshop_id != company.mb_control_workshop_id:
            raise ValidationError("invoice capture belongs to another workshop")
        external_id = str(payload.get("external_document_id", ""))
        digest = str(payload.get("content_digest", "")).lower()
        provider = payload.get("provider")
        filename = str(payload.get("source_filename", "")).strip()
        mimetype = str(payload.get("source_mimetype", "")).strip().lower()
        if not SAFE_EXTERNAL_ID_RE.fullmatch(external_id):
            raise ValidationError("external_document_id is invalid")
        if not HEX_64_RE.fullmatch(digest):
            raise ValidationError("content_digest must be a lowercase SHA-256 digest")
        if provider not in {"structured", "azure"}:
            raise ValidationError("unsupported extraction provider")
        if not filename or "/" in filename or "\\" in filename:
            raise ValidationError("source_filename must be a plain filename")
        if mimetype not in {
            "application/pdf", "image/jpeg", "image/png", "image/tiff",
            "application/xml", "text/xml",
        }:
            raise ValidationError("unsupported invoice source type")
        page_count = payload.get("page_count", 1)
        if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count < 1:
            raise ValidationError("page_count must be a positive integer")
        normalized = payload.get("invoice")
        confidence = payload.get("field_confidence", {})
        if not isinstance(normalized, dict):
            raise ValidationError("invoice must be an object")
        if not isinstance(confidence, dict):
            raise ValidationError("field_confidence must be an object")
        return company, external_id, digest, provider, filename, mimetype, page_count, normalized, confidence

    @api.model
    def _decode_source(self, encoded, digest):
        if not isinstance(encoded, str) or not encoded:
            raise ValidationError("source_base64 is required")
        try:
            source = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValidationError("source_base64 is invalid") from exc
        if not source or len(source) > MAX_SOURCE_BYTES:
            raise ValidationError("invoice source is empty or exceeds 20 MiB")
        import hashlib

        if hashlib.sha256(source).hexdigest() != digest:
            raise ValidationError("invoice source does not match content_digest")
        return source

    @api.model
    def _match_supplier(self, invoice, company):
        candidates = self.env["res.partner"].search([
            ("supplier_rank", ">", 0),
            "|", ("company_id", "=", False), ("company_id", "=", company.id),
        ])
        vat = _normalized_identifier(invoice.get("supplier_vat"))
        siren = _normalized_identifier(invoice.get("supplier_siren"))
        name = _normalized_name(invoice.get("supplier_name"))
        if vat:
            matches = candidates.filtered(lambda partner: _normalized_identifier(partner.vat) == vat)
            if len(matches) == 1:
                return matches
            if len(matches) > 1:
                return self.env["res.partner"], "Several suppliers have the extracted VAT identifier."
        if siren:
            def partner_siren(partner):
                siret = partner["siret"] if "siret" in partner._fields else ""
                return _normalized_identifier(siret)[:9]

            matches = candidates.filtered(lambda partner: partner_siren(partner) == siren[:9])
            if len(matches) == 1:
                return matches
            if len(matches) > 1:
                return self.env["res.partner"], "Several suppliers have the extracted SIREN."
        if name:
            matches = candidates.filtered(lambda partner: _normalized_name(partner.name) == name)
            if len(matches) == 1:
                return matches
            if len(matches) > 1:
                return self.env["res.partner"], "The extracted supplier name is ambiguous."
        return self.env["res.partner"], "No existing supplier matches the extracted identity."

    @api.model
    def _currency(self, code):
        currency = self.env["res.currency"].search([("name", "=", code)], limit=2)
        if len(currency) != 1 or not currency.active:
            return self.env["res.currency"]
        return currency

    @api.model
    def _account_for_code(self, code, company):
        if not isinstance(code, str) or not code.strip():
            return self.env["account.account"]
        return self.env["account.account"].with_company(company).search([
            ("code", "=", code.strip()),
            ("company_ids", "in", company.id),
            ("account_type", "in", ["expense", "expense_depreciation", "expense_direct_cost"]),
        ], limit=2)

    @api.model
    def _tax_for_rate(self, rate, company):
        value = float(_decimal(rate, "tax_rate"))
        return self.env["account.tax"].search([
            ("company_id", "=", company.id),
            ("type_tax_use", "=", "purchase"),
            ("amount_type", "=", "percent"),
            ("amount", "=", value),
            ("active", "=", True),
        ], limit=2)

    @api.model
    def _prepare_lines(self, invoice, company):
        source_lines = invoice.get("lines")
        if not isinstance(source_lines, list) or not source_lines:
            return [], "The extraction contains no invoice lines."
        commands = []
        for position, line in enumerate(source_lines, start=1):
            if not isinstance(line, dict):
                return [], f"Invoice line {position} is not an object."
            description = str(line.get("description", "")).strip()
            quantity = _decimal(line.get("quantity"), f"line {position} quantity")
            price_unit = _decimal(line.get("unit_price"), f"line {position} unit_price")
            if not description or quantity <= 0:
                return [], f"Invoice line {position} needs a description and positive quantity."
            account = self._account_for_code(line.get("account_code"), company)
            if len(account) != 1:
                return [], f"Invoice line {position} does not map to one existing expense account."
            product = self.env["product.product"]
            sku = line.get("product_default_code")
            if sku:
                product = self.env["product.product"].search([
                    ("default_code", "=", sku),
                    ("company_id", "in", [False, company.id]),
                ], limit=2)
                if len(product) != 1:
                    return [], f"Invoice line {position} does not map to one existing product."
            taxes = self.env["account.tax"]
            if line.get("tax_rate") is not None:
                taxes = self._tax_for_rate(line["tax_rate"], company)
                if len(taxes) != 1:
                    return [], f"Invoice line {position} does not map to one purchase tax."
            commands.append((0, 0, {
                "name": description,
                "quantity": float(quantity),
                "price_unit": float(price_unit),
                "account_id": account.id,
                "product_id": product.id or False,
                "tax_ids": [(6, 0, taxes.ids)],
            }))
        return commands, None

    @api.model
    def _create_draft_bill(self, capture, invoice, company):
        supplier = self._match_supplier(invoice, company)
        if isinstance(supplier, tuple):
            return self.env["account.move"], supplier[1]
        currency = self._currency(invoice.get("currency"))
        if not currency:
            return self.env["account.move"], "The extracted currency is not active in Odoo."
        line_commands, reason = self._prepare_lines(invoice, company)
        if reason:
            return self.env["account.move"], reason
        if not invoice.get("invoice_date"):
            return self.env["account.move"], "The extraction has no invoice date."
        move = self.env["account.move"].with_company(company).create({
            "move_type": "in_invoice",
            "company_id": company.id,
            "partner_id": supplier.id,
            "currency_id": currency.id,
            "invoice_date": invoice["invoice_date"],
            "invoice_date_due": invoice.get("due_date") or False,
            "ref": invoice.get("invoice_number") or False,
            "invoice_line_ids": line_commands,
        })
        expected_untaxed = _decimal(invoice.get("untaxed_amount"), "untaxed_amount")
        expected_tax = _decimal(invoice.get("tax_amount"), "tax_amount")
        expected_total = _decimal(invoice.get("total_amount"), "total_amount")
        actual = (
            Decimal(str(move.amount_untaxed)),
            Decimal(str(move.amount_tax)),
            Decimal(str(move.amount_total)),
        )
        expected = (expected_untaxed, expected_tax, expected_total)
        if any(
            not currency.is_zero(float(left - right))
            for left, right in zip(actual, expected, strict=True)
        ):
            move.unlink()
            return self.env["account.move"], "Extracted untaxed, tax and total amounts do not reconcile."
        if move.state != "draft":
            move.unlink()
            return self.env["account.move"], "Invoice capture may create draft bills only."
        return move, None

    @api.model
    def ingest(self, payload):
        (
            company, external_id, digest, provider, filename, mimetype,
            page_count, invoice, confidence,
        ) = self._validate_envelope(payload)
        existing = self.search([
            ("company_id", "=", company.id),
            ("external_document_id", "=", external_id),
            ("content_digest", "=", digest),
        ], limit=1)
        if existing:
            return existing._result(applied=False)
        source = self._decode_source(payload.get("source_base64"), digest)
        previous = self.search([
            ("company_id", "=", company.id),
            ("external_document_id", "=", external_id),
        ], order="revision desc", limit=1)
        capture = self.create({
            "company_id": company.id,
            "external_document_id": external_id,
            "content_digest": digest,
            "revision": previous.revision + 1 if previous else 1,
            "previous_revision_id": previous.id or False,
            "source_filename": filename,
            "source_mimetype": mimetype,
            "extraction_provider": provider,
            "extraction_model": payload.get("model") or False,
            "extraction_model_version": payload.get("model_version") or False,
            "extraction_operation_id": payload.get("provider_operation_id") or False,
            "page_count": page_count,
            "normalized_payload": invoice,
            "field_confidence": confidence,
        })
        attachment = self.env["ir.attachment"].create({
            "name": filename,
            "type": "binary",
            "datas": base64.b64encode(source),
            "mimetype": mimetype,
            "res_model": self._name,
            "res_id": capture.id,
        })
        capture.source_attachment_id = attachment
        if previous:
            capture.write({
                "status": "review",
                "review_reason": "A changed Paperless document revision was retained without overwriting the prior bill.",
            })
            return capture._result(applied=True)
        move, reason = self._create_draft_bill(capture, invoice, company)
        requires_review = bool(payload.get("requires_review"))
        if reason:
            capture.write({"status": "review", "review_reason": reason})
        else:
            capture.write({
                "move_id": move.id,
                "status": "review" if requires_review else "draft_bill",
                "review_reason": "Extraction confidence requires accountant review." if requires_review else False,
            })
        return capture._result(applied=True)

    def _result(self, applied):
        self.ensure_one()
        return {
            "applied": applied,
            "capture_id": self.id,
            "external_document_id": self.external_document_id,
            "revision": self.revision,
            "status": self.status,
            "bill_id": self.move_id.id or None,
            "review_reason": self.review_reason or None,
        }

    def action_open_bill(self):
        self.ensure_one()
        if not self.move_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Draft supplier bill"),
            "res_model": "account.move",
            "res_id": self.move_id.id,
            "view_mode": "form",
            "target": "current",
        }
