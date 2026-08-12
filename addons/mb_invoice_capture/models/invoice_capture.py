import base64
import binascii
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_EXTERNAL_ID_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,255}$")
MAX_SOURCE_BYTES = 20 * 1024 * 1024
_INTERNAL_WRITE_TOKEN = object()


def _is_internal_write(records):
    return (
        records.env.su
        or records.env.context.get("mb_invoice_capture_internal_write")
        is _INTERNAL_WRITE_TOKEN
    )


def _internal(records):
    return records.with_context(
        mb_invoice_capture_internal_write=_INTERNAL_WRITE_TOKEN,
    )


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
    _check_company_auto = True

    _review_editable_fields = {
        "review_supplier_id",
        "review_expense_account_id",
        "review_tax_id",
    }

    company_id = fields.Many2one(
        "res.company", required=True, index=True, readonly=True,
        default=lambda self: self.env.company,
    )
    external_document_id = fields.Char(required=True, index=True, readonly=True)
    source_document_url = fields.Char(string="Paperless document", readonly=True)
    content_digest = fields.Char(required=True, readonly=True)
    revision = fields.Integer(required=True, readonly=True, default=1)
    previous_revision_id = fields.Many2one(
        "mb.invoice.capture", readonly=True, ondelete="restrict", check_company=True,
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
    review_reason = fields.Text(string="Review reason", readonly=True, tracking=True)
    move_id = fields.Many2one(
        "account.move", readonly=True, ondelete="restrict", check_company=True,
    )
    purchase_order_id = fields.Many2one(
        "purchase.order", string="Purchase order", readonly=True, ondelete="restrict",
        check_company=True,
    )
    review_line_ids = fields.One2many(
        "mb.invoice.capture.line", "capture_id", string="Product matching", copy=False
    )
    source_attachment_id = fields.Many2one(
        "ir.attachment", readonly=True, ondelete="restrict", check_company=True,
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
    review_supplier_id = fields.Many2one(
        "res.partner",
        string="Confirmed supplier",
        domain="[('company_id', 'in', [False, company_id])]",
        check_company=True,
        tracking=True,
    )
    review_expense_account_id = fields.Many2one(
        "account.account",
        string="Expense account",
        domain="[('account_type', 'in', ('expense', 'expense_depreciation', 'expense_direct_cost'))]",
        check_company=True,
        tracking=True,
    )
    review_tax_id = fields.Many2one(
        "account.tax",
        string="Purchase tax",
        domain="[('type_tax_use', '=', 'purchase')]",
        check_company=True,
        tracking=True,
    )
    supplier_name = fields.Char(compute="_compute_review_fields")
    supplier_vat = fields.Char(compute="_compute_review_fields")
    invoice_number = fields.Char(compute="_compute_review_fields")
    invoice_date_display = fields.Char(compute="_compute_review_fields")
    due_date_display = fields.Char(compute="_compute_review_fields")
    currency_code = fields.Char(compute="_compute_review_fields")
    untaxed_amount_display = fields.Char(compute="_compute_review_fields")
    tax_amount_display = fields.Char(compute="_compute_review_fields")
    total_amount_display = fields.Char(compute="_compute_review_fields")
    invoice_lines_summary = fields.Html(
        compute="_compute_review_fields", sanitize=True
    )
    confidence_summary = fields.Html(
        compute="_compute_review_fields", sanitize=True
    )
    received_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        captures = super().create(vals_list)
        captures._ensure_review_lines()
        return captures

    def write(self, values):
        protected = set(values) - self._review_editable_fields
        if protected and not _is_internal_write(self):
            raise UserError(_(
                "Captured source evidence and lifecycle fields cannot be edited."
            ))
        return super().write(values)

    @api.constrains(
        "previous_revision_id", "external_document_id", "revision", "company_id",
    )
    def _check_previous_revision(self):
        for capture in self.filtered("previous_revision_id"):
            previous = capture.previous_revision_id
            if (
                previous == capture
                or previous.company_id != capture.company_id
                or previous.external_document_id != capture.external_document_id
                or previous.revision >= capture.revision
            ):
                raise ValidationError(_(
                    "The previous revision must be an earlier capture of the same document."
                ))

    @api.constrains("source_attachment_id")
    def _check_source_attachment(self):
        for capture in self.filtered("source_attachment_id"):
            attachment = capture.source_attachment_id
            if attachment.res_model != capture._name or attachment.res_id != capture.id:
                raise ValidationError(_(
                    "The source attachment must belong to its invoice capture."
                ))

    def _ensure_review_lines(self):
        for capture in self.filtered(lambda record: not record.review_line_ids):
            supplier = capture.review_supplier_id
            if not supplier:
                matched = capture._match_supplier(
                    capture.normalized_payload or {}, capture.company_id
                )
                if not isinstance(matched, tuple):
                    supplier = matched
            values = capture._parsed_review_line_values(capture.normalized_payload or {})
            for position, value in enumerate(values, start=1):
                product, match_method = capture._match_product(
                    value.get("product_code"), value.get("barcode"), supplier
                )
                _internal(self.env["mb.invoice.capture.line"]).create({
                    "capture_id": capture.id,
                    "sequence": position * 10,
                    "description": value["description"],
                    "extracted_product_code": value.get("product_code") or False,
                    "extracted_barcode": value.get("barcode") or False,
                    "extracted_quantity": float(value["quantity"]),
                    "extracted_unit_price": float(value["unit_price"]),
                    "review_product_id": product.id or False,
                    "review_uom_id": product.uom_id.id if product else False,
                    "review_quantity": float(value["quantity"]),
                    "review_unit_price": float(value["unit_price"]),
                    "match_method": match_method,
                })

    def _parsed_review_line_values(self, invoice):
        self.ensure_one()
        source_lines = invoice.get("lines")
        parsed = []
        if isinstance(source_lines, list):
            for position, line in enumerate(source_lines, start=1):
                if not isinstance(line, dict):
                    continue
                description = str(line.get("description") or "").strip()
                try:
                    quantity = _decimal(line.get("quantity"), f"line {position} quantity")
                    unit_price = _decimal(line.get("unit_price"), f"line {position} unit_price")
                except ValidationError:
                    continue
                if description and quantity > 0 and unit_price >= 0:
                    parsed.append({
                        "description": description,
                        "product_code": str(
                            line.get("supplier_product_code")
                            or line.get("product_default_code")
                            or line.get("product_code")
                            or ""
                        ).strip(),
                        "barcode": str(line.get("barcode") or "").strip(),
                        "quantity": quantity,
                        "unit_price": unit_price,
                    })
        extracted_untaxed = _decimal(invoice.get("untaxed_amount") or 0, "untaxed_amount")
        raw_total = sum(
            (line["quantity"] * line["unit_price"] for line in parsed), Decimal(0)
        )
        if extracted_untaxed > 0 and raw_total > 0:
            for scale in (Decimal(10), Decimal(100), Decimal(1000)):
                scaled_total = raw_total / (scale * scale)
                if abs(scaled_total - extracted_untaxed) <= max(
                    Decimal("0.02"), extracted_untaxed * Decimal("0.001")
                ):
                    for line in parsed:
                        line["quantity"] /= scale
                        line["unit_price"] /= scale
                    break
        return parsed

    def _match_product(self, product_code, barcode, supplier):
        self.ensure_one()
        Product = self.env["product.product"].with_company(self.company_id)

        def unique_product(domain):
            products = Product.search([
                ("active", "=", True),
                ("purchase_ok", "=", True),
                ("company_id", "in", [False, self.company_id.id]),
                *domain,
            ], limit=2)
            return products if len(products) == 1 else Product

        if product_code and supplier:
            sellers = self.env["product.supplierinfo"].search([
                ("partner_id", "child_of", supplier.commercial_partner_id.id),
                ("product_code", "=", product_code),
            ])
            products = Product
            for seller in sellers:
                candidates = seller.product_id or seller.product_tmpl_id.product_variant_ids
                products |= candidates.filtered(
                    lambda product: product.active
                    and product.purchase_ok
                    and (not product.company_id or product.company_id == self.company_id)
                )
            if len(products) == 1:
                return products, "supplier_code"
        if barcode:
            product = unique_product([("barcode", "=", barcode)])
            if product:
                return product, "barcode"
        if product_code:
            product = unique_product([("default_code", "=", product_code)])
            if product:
                return product, "internal_reference"
        return Product, "unmatched"

    @api.depends("normalized_payload", "field_confidence")
    def _compute_review_fields(self):
        confidence_labels = {
            "CustomerAddress": _("Customer address"),
            "CustomerName": _("Customer name"),
            "DueDate": _("Due date"),
            "InvoiceDate": _("Invoice date"),
            "InvoiceId": _("Invoice number"),
            "InvoiceTotal": _("Total"),
            "Items": _("Line items"),
            "SubTotal": _("Untaxed amount"),
            "TotalTax": _("Tax amount"),
            "VendorAddress": _("Supplier address"),
            "VendorName": _("Supplier name"),
            "VendorTaxId": _("Supplier VAT"),
        }
        for capture in self:
            invoice = capture.normalized_payload or {}
            capture.supplier_name = invoice.get("supplier_name") or False
            capture.supplier_vat = invoice.get("supplier_vat") or False
            capture.invoice_number = invoice.get("invoice_number") or False
            capture.invoice_date_display = invoice.get("invoice_date") or False
            capture.due_date_display = invoice.get("due_date") or False
            capture.currency_code = invoice.get("currency") or False
            capture.untaxed_amount_display = self._amount_display(
                invoice.get("untaxed_amount"), invoice.get("currency")
            )
            capture.tax_amount_display = self._amount_display(
                invoice.get("tax_amount"), invoice.get("currency")
            )
            capture.total_amount_display = self._amount_display(
                invoice.get("total_amount"), invoice.get("currency")
            )
            capture.invoice_lines_summary = self._lines_html(invoice.get("lines"))
            capture.confidence_summary = self._confidence_html(
                capture.field_confidence, confidence_labels
            )

    @api.model
    def _amount_display(self, amount, currency):
        if amount is None:
            return False
        return f"{amount} {currency or ''}".strip()

    @api.model
    def _lines_html(self, lines):
        if not isinstance(lines, list) or not lines:
            return Markup("<p class='text-muted'>%s</p>") % escape(_("No line items extracted."))
        rows = []
        for position, line in enumerate(lines, start=1):
            if not isinstance(line, dict):
                continue
            rows.append(Markup("""
                <tr>
                    <td>%s</td><td>%s</td><td class="text-end">%s</td>
                    <td class="text-end">%s</td><td class="text-end">%s</td>
                </tr>
            """) % (
                position,
                escape(line.get("description") or _("Invoice line")),
                escape(line.get("quantity") if line.get("quantity") is not None else ""),
                escape(line.get("unit_price") if line.get("unit_price") is not None else ""),
                escape(line.get("tax_rate") if line.get("tax_rate") is not None else ""),
            ))
        return Markup("""
            <div class="table-responsive"><table class="table table-sm table-hover mb-0">
                <thead><tr><th>#</th><th>%s</th><th class="text-end">%s</th>
                <th class="text-end">%s</th><th class="text-end">%s</th></tr></thead>
                <tbody>%s</tbody>
            </table></div>
        """) % (
            escape(_("Description")), escape(_("Quantity")),
            escape(_("Unit price")), escape(_("Tax rate")), Markup(" ").join(rows),
        )

    @api.model
    def _confidence_html(self, confidence, labels):
        if not isinstance(confidence, dict) or not confidence:
            return Markup("<p class='text-muted'>%s</p>") % escape(_("No confidence scores supplied."))
        rows = []
        for key, score in sorted(confidence.items()):
            try:
                percentage = float(score) * 100
            except (TypeError, ValueError):
                value = _("Not available")
                badge = "text-bg-secondary"
            else:
                value = f"{percentage:.1f}%"
                badge = (
                    "text-bg-success" if percentage >= 85
                    else "text-bg-warning" if percentage >= 75
                    else "text-bg-danger"
                )
            fallback_label = re.sub(r"(?<!^)(?=[A-Z])", " ", key).replace("_", " ").capitalize()
            label = labels.get(key, fallback_label)
            rows.append(Markup("""
                <tr><td>%s</td><td class="text-end">
                    <span class="badge %s">%s</span>
                </td></tr>
            """) % (escape(label), badge, escape(value)))
        return Markup("""
            <table class="table table-sm table-hover mb-0">
                <thead><tr><th>%s</th><th class="text-end">%s</th></tr></thead>
                <tbody>%s</tbody>
            </table>
        """) % (
            escape(_("Extracted field")), escape(_("Confidence")), Markup(" ").join(rows),
        )

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
            raise ValidationError(_("the Odoo company is not linked to a control-plane workshop"))
        if workshop_id != company.mb_control_workshop_id:
            raise ValidationError(_("invoice capture belongs to another workshop"))
        external_id = str(payload.get("external_document_id", ""))
        digest = str(payload.get("content_digest", "")).lower()
        provider = payload.get("provider")
        filename = str(payload.get("source_filename", "")).strip()
        mimetype = str(payload.get("source_mimetype", "")).strip().lower()
        if not SAFE_EXTERNAL_ID_RE.fullmatch(external_id):
            raise ValidationError(_("external_document_id is invalid"))
        if not HEX_64_RE.fullmatch(digest):
            raise ValidationError(_("content_digest must be a lowercase SHA-256 digest"))
        if provider not in {"structured", "azure"}:
            raise ValidationError(_("unsupported extraction provider"))
        if not filename or "/" in filename or "\\" in filename:
            raise ValidationError(_("source_filename must be a plain filename"))
        if mimetype not in {
            "application/pdf", "image/jpeg", "image/png", "image/tiff",
            "application/xml", "text/xml",
        }:
            raise ValidationError(_("unsupported invoice source type"))
        page_count = payload.get("page_count", 1)
        if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count < 1:
            raise ValidationError(_("page_count must be a positive integer"))
        normalized = payload.get("invoice")
        confidence = payload.get("field_confidence", {})
        source_url = str(payload.get("source_document_url") or "").strip()
        if source_url:
            parsed_url = urlparse(source_url)
            if parsed_url.scheme != "https" or not parsed_url.netloc or len(source_url) > 2048:
                raise ValidationError(_("source_document_url must be an absolute HTTPS URL"))
        if not isinstance(normalized, dict):
            raise ValidationError(_("invoice must be an object"))
        if not isinstance(confidence, dict):
            raise ValidationError(_("field_confidence must be an object"))
        return company, external_id, digest, provider, filename, mimetype, page_count, normalized, confidence

    @api.model
    def _decode_source(self, encoded, digest):
        if not isinstance(encoded, str) or not encoded:
            raise ValidationError(_("source_base64 is required"))
        try:
            source = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValidationError(_("source_base64 is invalid")) from exc
        if not source or len(source) > MAX_SOURCE_BYTES:
            raise ValidationError(_("invoice source is empty or exceeds 20 MiB"))
        import hashlib

        if hashlib.sha256(source).hexdigest() != digest:
            raise ValidationError(_("invoice source does not match content_digest"))
        return source

    @api.model
    def _match_supplier(self, invoice, company):
        candidates = self.env["res.partner"].search([
            ("active", "=", True),
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
                return self.env["res.partner"], _("Several suppliers have the extracted VAT identifier.")
        if siren:
            def partner_siren(partner):
                siret = partner["siret"] if "siret" in partner._fields else ""
                return _normalized_identifier(siret)[:9]

            matches = candidates.filtered(lambda partner: partner_siren(partner) == siren[:9])
            if len(matches) == 1:
                return matches
            if len(matches) > 1:
                return self.env["res.partner"], _("Several suppliers have the extracted SIREN.")
        if name:
            matches = candidates.filtered(lambda partner: _normalized_name(partner.name) == name)
            if len(matches) == 1:
                return matches
            if len(matches) > 1:
                return self.env["res.partner"], _("The extracted supplier name is ambiguous.")
        return self.env["res.partner"], _("No existing supplier matches the extracted identity.")

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
            return [], _("The extraction contains no invoice lines.")
        commands = []
        for position, line in enumerate(source_lines, start=1):
            if not isinstance(line, dict):
                return [], _("Invoice line %(line)s is not an object.", line=position)
            description = str(line.get("description", "")).strip()
            quantity = _decimal(line.get("quantity"), f"line {position} quantity")
            price_unit = _decimal(line.get("unit_price"), f"line {position} unit_price")
            if not description or quantity <= 0:
                return [], _("Invoice line %(line)s needs a description and a positive quantity.", line=position)
            account = self._account_for_code(line.get("account_code"), company)
            if len(account) != 1:
                return [], _("Invoice line %(line)s does not map to one existing expense account.", line=position)
            product = self.env["product.product"]
            sku = line.get("product_default_code")
            if sku:
                product = self.env["product.product"].search([
                    ("default_code", "=", sku),
                    ("company_id", "in", [False, company.id]),
                ], limit=2)
                if len(product) != 1:
                    return [], _("Invoice line %(line)s does not map to one existing product.", line=position)
            taxes = self.env["account.tax"]
            if line.get("tax_rate") is not None:
                taxes = self._tax_for_rate(line["tax_rate"], company)
                if len(taxes) != 1:
                    return [], _("Invoice line %(line)s does not map to one purchase tax.", line=position)
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
            return self.env["account.move"], _("The extracted currency is not active in Odoo.")
        line_commands, reason = self._prepare_lines(invoice, company)
        if reason:
            return self.env["account.move"], reason
        if not invoice.get("invoice_date"):
            return self.env["account.move"], _("The extraction has no invoice date.")
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
            return self.env["account.move"], _("Extracted untaxed, tax and total amounts do not reconcile.")
        if move.state != "draft":
            move.unlink()
            return self.env["account.move"], _("Invoice capture may create draft bills only.")
        capture._link_source_to_bill(move)
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
            "source_document_url": payload.get("source_document_url") or False,
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
                "review_reason": _("A changed Paperless document revision was retained without overwriting the prior bill."),
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
                "review_reason": _("Extraction confidence requires accountant review.") if requires_review else False,
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

    def action_open_purchase_order(self):
        self.ensure_one()
        if not self.purchase_order_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Purchase order"),
            "res_model": "purchase.order",
            "res_id": self.purchase_order_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_retry_product_matching(self):
        self.ensure_one()
        if self.purchase_order_id:
            raise UserError(_("Product matching is locked after creating the purchase order."))
        self._ensure_review_lines()
        supplier = self.review_supplier_id or self.move_id.partner_id
        for line in self.review_line_ids.filtered(
            lambda review_line: not review_line.review_product_id
        ):
            product, match_method = self._match_product(
                line.extracted_product_code, line.extracted_barcode, supplier
            )
            if product:
                _internal(line).write({
                    "review_product_id": product.id,
                    "review_uom_id": product.uom_id.id,
                    "match_method": match_method,
                })
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_create_purchase_order(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM mb_invoice_capture WHERE id = %s FOR UPDATE", [self.id]
        )
        self.invalidate_recordset(["purchase_order_id"])
        if self.purchase_order_id:
            return self.action_open_purchase_order()
        self._ensure_review_lines()
        supplier = self.review_supplier_id or self.move_id.partner_id
        if not supplier:
            matched = self._match_supplier(self.normalized_payload or {}, self.company_id)
            if isinstance(matched, tuple):
                raise UserError(_("Select the supplier before creating a purchase order."))
            supplier = matched
            self.review_supplier_id = supplier
        if not self.review_line_ids:
            raise UserError(_("No valid extracted invoice lines are available to purchase."))
        unmatched = self.review_line_ids.filtered(lambda line: not line.review_product_id)
        if unmatched:
            raise UserError(_(
                "Match every invoice line to an existing product before creating the "
                "purchase order."
            ))
        invalid = self.review_line_ids.filtered(
            lambda line: line.review_quantity <= 0
            or line.review_unit_price < 0
            or not line.review_uom_id
            or line.review_uom_id not in (
                line.review_product_id.uom_id
                | line.review_product_id.uom_ids
                | line.review_product_id.seller_ids.product_uom_id
            )
        )
        if invalid:
            raise UserError(_(
                "Every matched line needs a positive quantity, a non-negative price, and "
                "a unit compatible with the product."
            ))
        bill_lines = self.move_id.invoice_line_ids.filtered(
            lambda line: line.display_type == "product"
        ) if self.move_id else self.env["account.move.line"]
        if self.move_id and len(bill_lines) != len(self.review_line_ids):
            raise UserError(_(
                "The bill line count no longer matches the captured invoice. Reconcile the "
                "bill lines before creating its purchase order."
            ))
        currency = self.move_id.currency_id or self._currency(
            (self.normalized_payload or {}).get("currency")
        )
        if not currency:
            raise UserError(_("The extracted currency is not active in Odoo."))
        purchase_date = (
            self.move_id.invoice_date
            or fields.Date.to_date((self.normalized_payload or {}).get("invoice_date"))
            or fields.Date.context_today(self)
        )
        purchase_datetime = fields.Datetime.to_datetime(purchase_date)
        commands = []
        for position, review_line in enumerate(self.review_line_ids.sorted("sequence")):
            bill_line = bill_lines.sorted("sequence")[position] if bill_lines else False
            quantity = bill_line.quantity if bill_line else review_line.review_quantity
            price_unit = bill_line.price_unit if bill_line else review_line.review_unit_price
            taxes = (
                bill_line.tax_ids
                if bill_line
                else self.review_tax_id or review_line.review_product_id.supplier_taxes_id
            ).filtered(lambda tax: tax.company_id == self.company_id)
            commands.append((0, 0, {
                "sequence": review_line.sequence,
                "product_id": review_line.review_product_id.id,
                "name": review_line.description,
                "product_qty": quantity,
                "product_uom_id": review_line.review_uom_id.id,
                "price_unit": price_unit,
                "date_planned": purchase_datetime,
                "tax_ids": [(6, 0, taxes.ids)],
            }))
        order = self.env["purchase.order"].with_company(self.company_id).create({
            "company_id": self.company_id.id,
            "partner_id": supplier.id,
            "currency_id": currency.id,
            "date_order": purchase_datetime,
            "partner_ref": (self.normalized_payload or {}).get("invoice_number") or False,
            "origin": self.external_document_id,
            "order_line": commands,
        })
        if order.state not in ("draft", "sent"):
            order.unlink()
            raise UserError(_("Invoice capture may create draft purchase orders only."))
        order_lines = order.order_line.filtered(lambda line: not line.display_type).sorted("sequence")
        for position, review_line in enumerate(self.review_line_ids.sorted("sequence")):
            _internal(review_line).purchase_line_id = order_lines[position]
            if bill_lines:
                bill_line = bill_lines.sorted("sequence")[position]
                values = {"purchase_line_id": order_lines[position].id}
                if self.move_id.state == "draft":
                    values.update({
                        "product_id": review_line.review_product_id.id,
                        "product_uom_id": review_line.review_uom_id.id,
                    })
                bill_line.write(values)
        self._link_source(order, _("Source invoice"))
        _internal(self).purchase_order_id = order
        order.message_post(body=Markup(
            "<p>%s</p>"
        ) % escape(_(
            "This purchase order was reconstructed from a supplier invoice. Confirm it only "
            "after reviewing the products and quantities; validate the receipt only after "
            "physically receiving the goods."
        )))
        return self.action_open_purchase_order()

    def action_create_reviewed_bill(self):
        self.ensure_one()
        if self.move_id:
            return self.action_open_bill()
        if self.status != "review":
            raise UserError(_("Only an invoice awaiting review can create a reviewed bill."))
        invoice = self.normalized_payload or {}
        supplier = self.review_supplier_id
        if not supplier:
            matched = self._match_supplier(invoice, self.company_id)
            if isinstance(matched, tuple):
                _internal(self).review_reason = matched[1]
                return {"type": "ir.actions.client", "tag": "reload"}
            supplier = matched
            self.review_supplier_id = supplier
        if not self.review_expense_account_id:
            _internal(self).review_reason = _(
                "Select an expense account, then create the draft bill again."
            )
            return {"type": "ir.actions.client", "tag": "reload"}
        tax_amount = _decimal(invoice.get("tax_amount"), "tax_amount")
        company = self.company_id
        if (
            not self.review_tax_id
            and "l10n_fr_micro_tax_regime" in company._fields
            and company.l10n_fr_micro_tax_regime == "franchise"
            and company.l10n_fr_micro_purchase_tax_id
        ):
            self.review_tax_id = company.l10n_fr_micro_purchase_tax_id
        if tax_amount and not self.review_tax_id:
            _internal(self).review_reason = _(
                "Select the purchase tax, then create the draft bill again."
            )
            return {"type": "ir.actions.client", "tag": "reload"}
        currency = self._currency(invoice.get("currency"))
        if not currency:
            _internal(self).review_reason = _(
                "The extracted currency is not active in Odoo."
            )
            return {"type": "ir.actions.client", "tag": "reload"}
        untaxed = _decimal(invoice.get("untaxed_amount"), "untaxed_amount")
        gross_franchise_purchase = bool(
            self.review_tax_id
            and "l10n_fr_micro_franchise_tax" in self.review_tax_id._fields
            and self.review_tax_id.l10n_fr_micro_franchise_tax
            and self.review_tax_id.type_tax_use == "purchase"
        )
        line_amount = (
            _decimal(invoice.get("total_amount"), "total_amount")
            if gross_franchise_purchase else untaxed
        )
        line_commands = self._prepare_reviewed_lines(
            invoice, line_amount, self.review_expense_account_id, self.review_tax_id,
        )
        move = self.env["account.move"].with_company(self.company_id).create({
            "move_type": "in_invoice",
            "company_id": self.company_id.id,
            "partner_id": supplier.id,
            "currency_id": currency.id,
            "invoice_date": invoice.get("invoice_date") or fields.Date.context_today(self),
            "invoice_date_due": invoice.get("due_date") or False,
            "ref": invoice.get("invoice_number") or False,
            "invoice_line_ids": line_commands,
        })
        self._link_source_to_bill(move)
        _internal(self).write({
            "move_id": move.id,
            "status": "review",
            "review_reason": _(
                "Draft bill created from the reviewed header totals. Verify its supplier, "
                "tax and line details before posting."
            ),
        })
        return self.action_open_bill()

    def _link_source_to_bill(self, move):
        return self._link_source(move, _("Original source"))

    def _link_source(self, record, source_label):
        self.ensure_one()
        if not self.source_attachment_id or not record:
            return self.env["ir.attachment"]
        attachment_model = self.env["ir.attachment"].sudo()
        attachment = attachment_model.search([
            ("res_model", "=", record._name),
            ("res_id", "=", record.id),
            ("checksum", "=", self.source_attachment_id.checksum),
        ], limit=1)
        if attachment:
            return attachment
        attachment = self.source_attachment_id.sudo().copy({
            "name": self.source_filename,
            "res_model": record._name,
            "res_id": record.id,
            "description": _(
                "%(label)s from %(reference)s",
                label=source_label,
                reference=self.external_document_id,
            ),
        })
        reference = escape(self.external_document_id)
        if self.source_document_url:
            body = Markup("<p>%s <a href=\"%s\" target=\"_blank\" rel=\"noopener noreferrer\">%s</a></p>") % (
                escape(_("Source document:")),
                escape(self.source_document_url),
                reference,
            )
        else:
            body = Markup("<p>%s %s</p>") % (escape(_("Source document:")), reference)
        record.message_post(body=body, attachment_ids=attachment.ids)
        return attachment

    def _prepare_reviewed_lines(self, invoice, target_amount, account, tax):
        self.ensure_one()
        self._ensure_review_lines()
        parsed = [
            [line.description, Decimal(str(line.review_quantity)), Decimal(str(line.review_unit_price)), line]
            for line in self.review_line_ids.sorted("sequence")
            if line.description and line.review_quantity > 0
        ]
        if not parsed:
            return [(0, 0, {
                "name": _("Captured invoice %(number)s", number=invoice.get("invoice_number") or ""),
                "quantity": 1,
                "price_unit": float(target_amount),
                "account_id": account.id,
                "tax_ids": [(6, 0, tax.ids)],
            })]

        raw_total = sum((quantity * unit_price for _, quantity, unit_price, _ in parsed), Decimal(0))
        difference = target_amount - raw_total
        if not self.company_id.currency_id.is_zero(float(difference)):
            raise UserError(_(
                "The reviewed lines total %(lines)s but the extracted header is "
                "%(header)s. Add an explicit freight, discount, or rounding line "
                "before creating the bill.",
                lines=raw_total,
                header=target_amount,
            ))
        return [(0, 0, {
            "name": description,
            "quantity": float(quantity),
            "price_unit": float(unit_price),
            "account_id": account.id,
            "product_id": review_line.review_product_id.id or False,
            "product_uom_id": review_line.review_uom_id.id or False,
            "tax_ids": [(6, 0, tax.ids)],
        }) for description, quantity, unit_price, review_line in parsed]


class InvoiceCaptureLine(models.Model):
    _name = "mb.invoice.capture.line"
    _description = "Supplier invoice product matching line"
    _order = "capture_id, sequence, id"
    _check_company_auto = True

    _review_editable_fields = {
        "sequence",
        "description",
        "review_product_id",
        "review_uom_id",
        "review_quantity",
        "review_unit_price",
    }

    capture_id = fields.Many2one(
        "mb.invoice.capture", required=True, ondelete="cascade", index=True,
        check_company=True,
    )
    company_id = fields.Many2one(related="capture_id.company_id", store=True, index=True)
    sequence = fields.Integer(required=True, default=10)
    description = fields.Char(required=True)
    extracted_product_code = fields.Char(readonly=True)
    extracted_barcode = fields.Char(readonly=True)
    extracted_quantity = fields.Float(readonly=True, digits="Product Unit")
    extracted_unit_price = fields.Float(readonly=True, digits="Product Price")
    review_product_id = fields.Many2one(
        "product.product",
        string="Matched product",
        domain="[('purchase_ok', '=', True), ('company_id', 'in', [False, company_id])]",
        check_company=True,
    )
    review_uom_id = fields.Many2one(
        "uom.uom", string="Purchase unit", domain="[('id', 'in', allowed_uom_ids)]"
    )
    allowed_uom_ids = fields.Many2many(
        "uom.uom", compute="_compute_allowed_uom_ids"
    )
    review_quantity = fields.Float(string="Purchase quantity", digits="Product Unit")
    review_unit_price = fields.Float(string="Unit price", digits="Product Price")
    match_method = fields.Selection([
        ("supplier_code", "Supplier product code"),
        ("barcode", "Barcode"),
        ("internal_reference", "Internal reference"),
        ("manual", "Manual"),
        ("unmatched", "Not matched"),
    ], required=True, default="unmatched", readonly=True)
    is_storable = fields.Boolean(
        related="review_product_id.is_storable", string="Tracks inventory"
    )
    purchase_line_id = fields.Many2one(
        "purchase.order.line", readonly=True, ondelete="restrict", check_company=True,
    )

    _capture_sequence_unique = models.Constraint(
        "UNIQUE(capture_id, sequence)",
        "Each captured invoice line sequence must be unique.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        protected = set().union(*(set(values) for values in vals_list)) \
            - (self._review_editable_fields | {"capture_id"})
        if protected and not _is_internal_write(self):
            raise UserError(_("Extracted invoice-line evidence cannot be created manually."))
        return super().create(vals_list)

    def write(self, values):
        protected = set(values) - self._review_editable_fields
        if protected and not _is_internal_write(self):
            raise UserError(_("Extracted invoice-line evidence cannot be edited."))
        return super().write(values)

    @api.onchange("review_product_id")
    def _onchange_review_product_id(self):
        for line in self:
            if line.review_product_id:
                line.review_uom_id = line.review_product_id.uom_id
                if line._origin.review_product_id != line.review_product_id:
                    line.match_method = "manual"
            else:
                line.review_uom_id = False
                line.match_method = "unmatched"

    @api.depends("review_product_id")
    def _compute_allowed_uom_ids(self):
        for line in self:
            product = line.review_product_id
            line.allowed_uom_ids = (
                product.uom_id | product.uom_ids | product.seller_ids.product_uom_id
                if product else self.env["uom.uom"]
            )
