from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import re
import unicodedata
from collections import Counter
from datetime import timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare

from .adapters import MAX_SOURCE_BYTES, AdapterError, parse
from .image_fetch import ImageFetchError, fetch_image


_logger = logging.getLogger(__name__)
_INTERNAL_TOKEN = object()
MAX_FAILURE_CHARS = 2_000
DEFAULT_SNAPSHOT_MAX_AGE_HOURS = 72


def _internal(records):
    return records.with_context(mb_shop_import_internal=_INTERNAL_TOKEN)


def _is_internal(records):
    return records.env.context.get("mb_shop_import_internal") is _INTERNAL_TOKEN


def _slug(value, limit=40):
    folded = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", folded).strip("-").upper()
    return cleaned[:limit].strip("-")


def _default_code(record, prefix):
    tail = (record.get("product_url") or "").rstrip("/").rsplit("/", 1)[-1]
    token = _slug(tail) or _slug(record.get("name"))
    parts = [prefix, token]
    if record.get("variant_title"):
        parts.append(_slug(record["variant_title"], limit=16))
    return "-".join(part for part in parts if part)


def _decode_upload(value):
    try:
        decoded = base64.b64decode(value or b"", validate=True)
    except (binascii.Error, TypeError, ValueError) as error:
        raise ValidationError(_("The uploaded file data is invalid.")) from error
    if len(decoded) > MAX_SOURCE_BYTES:
        raise ValidationError(_("The uploaded catalogue artifact exceeds 20 MB."))
    return decoded


class ShopSource(models.Model):
    _name = "mb.shop.source"
    _description = "Scraped shop source"
    _order = "name"
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company", required=True, index=True, default=lambda self: self.env.company,
        ondelete="cascade",
    )
    provider_key = fields.Char(required=True, readonly=True, index=True)
    source_key = fields.Char(required=True, readonly=True, index=True)
    sku_prefix = fields.Char(required=True, help="Short prefix used for generated internal references.")
    homepage_url = fields.Char()
    active = fields.Boolean(default=True)
    last_seen_at = fields.Datetime(readonly=True, copy=False)
    service_category_names = fields.Text(
        default="Cours et ateliers",
        help="One exact, case-insensitive source category per line. Matching rows become services.",
    )
    allowed_image_hosts = fields.Text(
        default="images.sumup.com",
        help="One HTTPS image hostname per line.",
    )

    _identity_unique = models.Constraint(
        "UNIQUE(company_id, provider_key, source_key)",
        "A scraper source can be registered only once per company and provider.",
    )

    @api.constrains("source_key", "provider_key", "sku_prefix")
    def _check_identity_tokens(self):
        key_re = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
        for source in self:
            if not key_re.fullmatch(source.source_key or ""):
                raise ValidationError(_("The scraper source key is not valid."))
            if not key_re.fullmatch(source.provider_key or ""):
                raise ValidationError(_("The provider key is not valid."))
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{0,15}", source.sku_prefix or ""):
                raise ValidationError(_("The SKU prefix must contain 1–16 uppercase letters, digits, or hyphens."))

    def write(self, values):
        if {"company_id", "provider_key", "source_key"}.intersection(values):
            raise UserError(_("A scraper source identity cannot be changed after creation."))
        return super().write(values)

    def service_categories(self):
        self.ensure_one()
        return {
            line.strip().casefold()
            for line in (self.service_category_names or "").splitlines()
            if line.strip()
        }

    def image_hosts(self):
        self.ensure_one()
        return {
            line.strip().lower().rstrip(".")
            for line in (self.allowed_image_hosts or "").splitlines()
            if line.strip()
        }


class ShopProductBinding(models.Model):
    _name = "mb.shop.product.binding"
    _description = "Shop source product binding"
    _order = "source_id, external_id"
    _check_company_auto = True

    company_id = fields.Many2one(
        related="source_id.company_id", store=True, readonly=True, index=True,
    )
    source_id = fields.Many2one(
        "mb.shop.source", required=True, index=True, ondelete="cascade", check_company=True,
    )
    external_id = fields.Char(required=True, readonly=True, index=True)
    product_id = fields.Many2one(
        "product.product", required=True, index=True, ondelete="restrict", check_company=True,
    )
    source_url = fields.Char(readonly=True)
    adapter_key = fields.Char(readonly=True)
    adapter_version = fields.Integer(readonly=True, default=1)
    last_seen_at = fields.Datetime(readonly=True)

    _external_unique = models.Constraint(
        "UNIQUE(source_id, external_id)",
        "A source variant can be bound only once.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not _is_internal(self):
            raise UserError(_("Shop product bindings are created only by a confirmed import."))
        return super().create(vals_list)

    def write(self, values):
        protected = {"company_id", "source_id", "external_id", "product_id"}
        if protected.intersection(values) and not _is_internal(self):
            raise UserError(_("A shop product binding cannot be redirected."))
        return super().write(values)


class ShopImportBatch(models.Model):
    _name = "mb.shop.import.batch"
    _description = "Shop catalogue import"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(required=True, readonly=True, copy=False, default=lambda self: _("New"))
    company_id = fields.Many2one(
        "res.company", required=True, readonly=True, index=True,
        default=lambda self: self.env.company,
    )
    source_file = fields.Binary(attachment=True, copy=False)
    file_name = fields.Char(required=True, copy=False)
    file_size = fields.Integer(readonly=True, copy=False)
    file_sha256 = fields.Char(readonly=True, copy=False, index=True)
    adapter_key = fields.Selection(
        [("auto", "Detect automatically"), ("catalogue_v2", "Catalogue v2 NDJSON"),
         ("catalogue_csv", "Catalogue scraper CSV")],
        required=True, default="auto", tracking=True,
    )
    parsed_adapter_key = fields.Char(readonly=True, copy=False)
    adapter_version = fields.Integer(readonly=True, default=1, copy=False)
    source_id = fields.Many2one(
        "mb.shop.source", required=True, check_company=True, tracking=True,
    )
    source_snapshot_at = fields.Datetime(readonly=True, copy=False)
    source_snapshot_from = fields.Datetime(readonly=True, copy=False)
    state = fields.Selection(
        [("uploaded", "Uploaded"), ("review", "Review"), ("ready", "Ready"),
         ("importing", "Importing"), ("done", "Done"), ("failed", "Failed"),
         ("cancelled", "Cancelled")],
        required=True, readonly=True, default="uploaded", tracking=True, index=True,
    )
    target_location_id = fields.Many2one(
        "stock.location", check_company=True, tracking=True,
        domain="[('usage', '=', 'internal'), ('company_id', '=', company_id)]",
    )
    product_category_id = fields.Many2one("product.category", tracking=True)
    currency_id = fields.Many2one("res.currency", readonly=True, copy=False)
    price_tax_basis = fields.Selection(
        [("no_sales_tax", "No sales tax"), ("tax_included", "Published price includes tax"),
         ("tax_excluded", "Published price excludes tax")],
        required=True, default="no_sales_tax", tracking=True,
    )
    sales_tax_ids = fields.Many2many(
        "account.tax", "mb_shop_import_batch_tax_rel", "batch_id", "tax_id",
        string="Sales taxes", check_company=True,
        domain="[('type_tax_use', '=', 'sale'), ('company_id', '=', company_id)]",
    )
    update_existing_prices = fields.Boolean(tracking=True)
    import_images = fields.Boolean(tracking=True)
    overwrite_images = fields.Boolean(tracking=True)
    snapshot_max_age_hours = fields.Integer(default=DEFAULT_SNAPSHOT_MAX_AGE_HOURS)
    snapshot_stale_policy = fields.Selection(
        [("block", "Block tracked stock"), ("warn", "Allow after warning")],
        required=True,
        default="block",
        tracking=True,
    )
    line_ids = fields.One2many("mb.shop.import.line", "batch_id", copy=False)
    affected_product_tmpl_ids = fields.Many2many(
        "product.template", "mb_shop_import_batch_product_rel", "batch_id", "template_id",
        readonly=True, copy=False,
    )
    total_count = fields.Integer(compute="_compute_counts")
    selected_count = fields.Integer(compute="_compute_counts")
    create_count = fields.Integer(compute="_compute_counts")
    update_count = fields.Integer(compute="_compute_counts")
    skip_count = fields.Integer(compute="_compute_counts")
    warning_count = fields.Integer(compute="_compute_counts")
    error_count = fields.Integer(compute="_compute_counts")
    parsed_at = fields.Datetime(readonly=True, copy=False)
    validated_at = fields.Datetime(readonly=True, copy=False)
    validated_snapshot_stale = fields.Boolean(readonly=True, copy=False)
    warnings_acknowledged_at = fields.Datetime(readonly=True, copy=False)
    warnings_acknowledged_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    imported_at = fields.Datetime(readonly=True, copy=False)
    imported_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    result_summary = fields.Json(readonly=True, copy=False)
    failure_detail = fields.Text(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for vals in vals_list:
            values = dict(vals)
            if values.get("source_file"):
                _decode_upload(values["source_file"])
            if values.get("name", _("New")) == _("New"):
                values["name"] = self.env["ir.sequence"].next_by_code(
                    "mb.shop.import.batch"
                ) or _("New")
            prepared.append(values)
        return super().create(prepared)

    @api.depends("line_ids.selected", "line_ids.proposed_action", "line_ids.validation_status")
    def _compute_counts(self):
        for batch in self:
            lines = batch.line_ids
            batch.total_count = len(lines)
            batch.selected_count = len(lines.filtered("selected"))
            batch.create_count = len(lines.filtered(lambda line: line.proposed_action == "create"))
            batch.update_count = len(lines.filtered(lambda line: line.proposed_action == "update"))
            batch.skip_count = len(lines.filtered(lambda line: line.proposed_action == "skip"))
            batch.warning_count = len(lines.filtered(lambda line: line.validation_status == "warning"))
            batch.error_count = len(lines.filtered(lambda line: line.validation_status == "error"))

    def write(self, values):
        if values.get("source_file"):
            _decode_upload(values["source_file"])
        lifecycle = {
            "company_id", "file_size", "file_sha256", "parsed_adapter_key",
            "adapter_version", "source_snapshot_at", "source_snapshot_from", "state",
            "currency_id", "affected_product_tmpl_ids", "parsed_at", "validated_at",
            "validated_snapshot_stale",
            "warnings_acknowledged_at", "warnings_acknowledged_by_id", "imported_at",
            "imported_by_id", "result_summary", "failure_detail",
        }
        if lifecycle.intersection(values) and not _is_internal(self):
            raise UserError(_("Import evidence and lifecycle fields cannot be edited directly."))
        if self.filtered(lambda batch: batch.state in {"done", "cancelled"}) and not _is_internal(self):
            raise UserError(_("A completed or cancelled import is immutable."))
        source_fields = {"source_file", "file_name", "adapter_key", "source_id"}
        policies = {
            "target_location_id",
            "product_category_id", "price_tax_basis", "sales_tax_ids",
            "update_existing_prices", "import_images", "overwrite_images",
            "snapshot_max_age_hours", "snapshot_stale_policy",
        }
        result = super().write(values)
        if source_fields.intersection(values) and not _is_internal(self):
            _internal(self.mapped("line_ids")).unlink()
            _internal(self).write({
                "state": "uploaded",
                "file_size": 0,
                "file_sha256": False,
                "parsed_adapter_key": False,
                "currency_id": False,
                "source_snapshot_from": False,
                "source_snapshot_at": False,
                "parsed_at": False,
                "validated_at": False,
                "validated_snapshot_stale": False,
                "warnings_acknowledged_at": False,
                "warnings_acknowledged_by_id": False,
                "failure_detail": False,
                "result_summary": False,
            })
        if policies.intersection(values) and not _is_internal(self):
            _internal(self.filtered(lambda batch: batch.state in {"review", "ready", "failed"})).write({
                "state": "review",
                "validated_at": False,
                "validated_snapshot_stale": False,
                "warnings_acknowledged_at": False,
                "warnings_acknowledged_by_id": False,
            })
        return result

    @api.constrains("target_location_id", "company_id")
    def _check_target_location(self):
        for batch in self.filtered("target_location_id"):
            if batch.target_location_id.usage != "internal" \
                    or batch.target_location_id.company_id != batch.company_id:
                raise ValidationError(_("The stock target must be an internal location of the batch company."))

    @api.constrains("sales_tax_ids", "company_id")
    def _check_sales_taxes(self):
        for batch in self:
            invalid = batch.sales_tax_ids.filtered(
                lambda tax, company=batch.company_id:
                    tax.company_id != company or tax.type_tax_use != "sale"
            )
            if invalid:
                raise ValidationError(_("Every selected tax must be a sales tax of the batch company."))

    @api.constrains("snapshot_max_age_hours")
    def _check_snapshot_age(self):
        if any(batch.snapshot_max_age_hours < 0 for batch in self):
            raise ValidationError(_("Snapshot maximum age cannot be negative."))

    def _decode_source(self):
        self.ensure_one()
        return _decode_upload(self.source_file)

    def _category_is_service(self, path):
        self.ensure_one()
        return bool(path and path[0].casefold() in self.source_id.service_categories())

    def action_parse(self):
        self.ensure_one()
        self.check_access("write")
        if self.state in {"done", "cancelled", "importing"}:
            raise UserError(_("This import can no longer be parsed."))
        data = self._decode_source()
        try:
            artifact = parse(
                data, self.file_name, self.source_id.source_key,
                None if self.adapter_key == "auto" else self.adapter_key,
            )
        except AdapterError as error:
            raise ValidationError(str(error)) from error
        if artifact.currency:
            currency = self.env["res.currency"].with_context(active_test=False).search([
                ("name", "=", artifact.currency),
            ], limit=1)
            if not currency:
                raise ValidationError(_("Currency %(currency)s is not available in Odoo.", currency=artifact.currency))
        else:
            raise ValidationError(_("Every catalogue artifact must declare one currency."))
        _internal(self.line_ids).unlink()
        codes = []
        commands = []
        for sequence, record in enumerate(artifact.rows, start=1):
            code = _default_code(record, self.source_id.sku_prefix)
            codes.append(code)
            commands.append(Command.create({
                "sequence": sequence,
                "external_id": record["external_id"],
                "parent_external_id": record.get("parent_external_id"),
                "identity_is_fallback": record["identity_is_fallback"],
                "name": record["name"],
                "variant_title": record.get("variant_title"),
                "default_code": code,
                "product_url": record.get("product_url"),
                "description": record.get("description"),
                "category_path": record.get("category_path"),
                "source_category": (record.get("category_path") or [False])[0],
                "source_price": record["price"],
                "currency_id": currency.id,
                "published_vat_status": record.get("vat_status"),
                "stock_quantity": record.get("stock_quantity") or 0.0,
                "stock_is_tracked": record["stock_is_tracked"],
                "availability": record.get("availability"),
                "image_url": record.get("image_url"),
                "is_service": self._category_is_service(record.get("category_path")),
                "raw_record": record["raw_record"],
                "fetched_at": record.get("fetched_at"),
            }))
        duplicate_codes = {code for code, count in Counter(codes).items() if count > 1}
        now = fields.Datetime.now()
        values = {
            "line_ids": commands,
            "file_size": len(data),
            "file_sha256": hashlib.sha256(data).hexdigest(),
            "parsed_adapter_key": artifact.adapter_key,
            "currency_id": currency.id,
            "source_snapshot_from": fields.Datetime.to_string(artifact.fetched_at_min) if artifact.fetched_at_min else False,
            "source_snapshot_at": fields.Datetime.to_string(artifact.fetched_at_max) if artifact.fetched_at_max else False,
            "parsed_at": now,
            "validated_at": False,
            "validated_snapshot_stale": False,
            "warnings_acknowledged_at": False,
            "warnings_acknowledged_by_id": False,
            "state": "review",
            "failure_detail": False,
            "result_summary": False,
        }
        _internal(self).write(values)
        if duplicate_codes:
            _internal(self.line_ids.filtered(lambda line: line.default_code in duplicate_codes)).write({
                "validation_status": "error",
                "validation_messages": _("Generated internal reference collides inside this file."),
                "selected": False,
                "duplicate_code": True,
            })
        _internal(self.source_id).write({"last_seen_at": now})
        return self._reopen()

    def _tax_price(self, source_price):
        self.ensure_one()
        taxes = self.sales_tax_ids
        if self.price_tax_basis == "no_sales_tax":
            if taxes:
                raise ValidationError(_("No-sales-tax imports cannot select sales taxes."))
            return source_price, source_price
        if not taxes:
            raise ValidationError(_("Select at least one Odoo sales tax for a taxable import."))
        currency = self.currency_id
        if self.price_tax_basis == "tax_excluded":
            result = taxes.compute_all(source_price, currency=currency, quantity=1.0,
                                       handle_price_include=False)
            return source_price, result["total_included"]
        # Reverse Odoo's own tax calculation rather than duplicating percentage,
        # group, fixed-tax, or rounding semantics in importer code.
        low, high = 0.0, max(source_price, 1.0)
        for _iteration in range(80):
            middle = (low + high) / 2
            total = taxes.compute_all(
                middle, currency=currency, quantity=1.0, handle_price_include=False,
            )["total_included"]
            if total < source_price:
                low = middle
            else:
                high = middle
        net = currency.round((low + high) / 2)
        displayed = taxes.compute_all(
            net, currency=currency, quantity=1.0, handle_price_include=False,
        )["total_included"]
        if float_compare(displayed, source_price, precision_rounding=currency.rounding):
            raise ValidationError(_(
                "The selected taxes cannot reproduce published price %(price)s.",
                price=source_price,
            ))
        return net, displayed

    def _validate_policy(self):
        self.ensure_one()
        if not self.target_location_id:
            raise ValidationError(_("Choose the stock location for physical products."))
        if not self.product_category_id:
            raise ValidationError(_("Choose the Odoo category for physical products."))
        if self.currency_id != self.company_id.currency_id:
            raise ValidationError(_(
                "The artifact currency %(source)s differs from company currency %(company)s.",
                source=self.currency_id.name, company=self.company_id.currency_id.name,
            ))
        if self.overwrite_images and not self.import_images:
            raise ValidationError(_("Overwriting images requires image import."))
        if self.import_images and not self.source_id.image_hosts():
            raise ValidationError(_(
                "Configure at least one allowed image hostname before enabling image import."
            ))
        self._tax_price(1.0)

    def _match_product(self, line):
        binding = self.env["mb.shop.product.binding"].search([
            ("source_id", "=", self.source_id.id),
            ("external_id", "=", line.external_id),
        ], limit=1)
        if binding:
            return binding.product_id, "binding"
        product = self.env["product.product"].search([
            ("default_code", "=", line.default_code),
            ("company_id", "=", self.company_id.id),
        ], limit=2)
        if len(product) == 1:
            return product, "default_code"
        if len(product) > 1:
            return product.browse(), "ambiguous_code"
        if line.manual_product_id:
            return line.manual_product_id, "manual"
        return product, "new"

    def _quant_values(self, product):
        if not product:
            return 0.0, 0.0
        quants = self.env["stock.quant"].search([
            ("product_id", "=", product.id),
            ("location_id", "=", self.target_location_id.id),
        ])
        return sum(quants.mapped("quantity")), sum(quants.mapped("reserved_quantity"))

    def action_validate(self):
        self.ensure_one()
        self.check_access("write")
        if self.state not in {"review", "ready", "failed"} or not self.line_ids:
            raise UserError(_("Parse an uploaded catalogue before validating it."))
        self._validate_policy()
        duplicate_codes = {
            code for code, count in Counter(self.line_ids.mapped("default_code")).items()
            if count > 1
        }
        snapshot_stale = False
        if self.source_snapshot_at and self.snapshot_max_age_hours:
            snapshot_stale = fields.Datetime.now() - self.source_snapshot_at > timedelta(
                hours=self.snapshot_max_age_hours
            )
        for line in self.line_ids:
            errors = []
            warnings = []
            product, match_method = self._match_product(line)
            if line.default_code in duplicate_codes:
                errors.append(_("Generated internal reference collides inside this file."))
            if match_method == "ambiguous_code":
                errors.append(_("More than one company product has this internal reference."))
            if product and product.company_id != self.company_id:
                errors.append(_("The matched product belongs to another company."))
            if product and line.stock_is_tracked and product.tracking != "none":
                errors.append(_("Stock cannot be adjusted without lots or serials for this tracked product."))
            if line.identity_is_fallback:
                warnings.append(_("The scraper CSV lacks an exact variant ID; review its fallback identity."))
            if snapshot_stale and line.stock_is_tracked and not line.is_service:
                message = _("The scraper stock snapshot is older than the configured maximum age.")
                if self.snapshot_stale_policy == "block":
                    errors.append(message)
                else:
                    warnings.append(message)
            if line.is_service and line.stock_is_tracked:
                warnings.append(_("Service stock is ignored."))
            try:
                list_price, customer_price = self._tax_price(line.source_price)
            except ValidationError as error:
                errors.append(str(error))
                list_price = customer_price = 0.0
            quantity, reserved = self._quant_values(product)
            current_list_price = product.list_price if product else 0.0
            price_changed = bool(product) and bool(float_compare(
                current_list_price, list_price, precision_rounding=self.currency_id.rounding,
            ))
            stock_changed = bool(line.stock_is_tracked and not line.is_service and float_compare(
                quantity, line.stock_quantity, precision_rounding=product.uom_id.rounding if product else 0.01,
            ))
            if product:
                action = "update"
            else:
                action = "create"
            selected = line.selected
            if line.validation_status == "new":
                selected = not line.identity_is_fallback
            if errors:
                selected = False
            status = "error" if errors else "warning" if warnings else "valid"
            _internal(line).write({
                "matched_product_id": product.id if product else False,
                "match_method": match_method,
                "proposed_action": action if selected else "skip",
                "proposed_list_price": list_price,
                "proposed_customer_price": customer_price,
                "current_name": product.display_name if product else False,
                "current_list_price": current_list_price,
                "price_changed": price_changed,
                "stock_changed": stock_changed,
                "reviewed_quantity": quantity,
                "reviewed_reserved_quantity": reserved,
                "has_reviewed_baseline": True,
                "validation_status": status,
                "validation_messages": "\n".join([*errors, *warnings]),
                "selected": selected,
                "duplicate_code": line.default_code in duplicate_codes,
            })
        now = fields.Datetime.now()
        _internal(self).write({
            "state": "ready",
            "validated_at": now,
            "validated_snapshot_stale": snapshot_stale,
            "warnings_acknowledged_at": False,
            "warnings_acknowledged_by_id": False,
            "failure_detail": False,
        })
        return self._reopen()

    def action_acknowledge_warnings(self):
        self.ensure_one()
        self.check_access("write")
        if self.state != "ready":
            raise UserError(_("Validate the import before acknowledging warnings."))
        _internal(self).write({
            "warnings_acknowledged_at": fields.Datetime.now(),
            "warnings_acknowledged_by_id": self.env.user.id,
        })
        return self._reopen()

    def action_select_valid(self):
        self.ensure_one()
        self.check_access("write")
        if self.state not in {"review", "ready"}:
            raise UserError(_("Only a reviewed import can be selected."))
        self.line_ids.filtered(lambda line: line.validation_status == "valid").write({"selected": True})
        self.line_ids.filtered(lambda line: line.validation_status != "valid").write({"selected": False})
        return self._reopen()

    def _lock_and_check_stock(self, lines):
        products = lines.mapped("matched_product_id")
        if products:
            self.env.cr.execute(
                "SELECT id FROM product_product WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
                [products.ids],
            )
            self.env.cr.execute(
                """SELECT id FROM stock_quant
                     WHERE product_id = ANY(%s) AND location_id = %s
                     ORDER BY id FOR UPDATE""",
                [products.ids, self.target_location_id.id],
            )
            self.env["stock.quant"].invalidate_model(["quantity", "reserved_quantity"])
        for line in lines.filtered(lambda item: item.stock_is_tracked and not item.is_service):
            quantity, reserved = self._quant_values(line.matched_product_id)
            rounding = line.matched_product_id.uom_id.rounding if line.matched_product_id else 0.01
            if float_compare(quantity, line.reviewed_quantity, precision_rounding=rounding) \
                    or float_compare(reserved, line.reviewed_reserved_quantity, precision_rounding=rounding):
                raise ValidationError(_(
                    "Stock for %(product)s changed after review. Validate the batch again.",
                    product=line.name,
                ))

    def _create_or_update_product(self, line):
        product = line.matched_product_id
        tax_command = [Command.set(self.sales_tax_ids.ids)]
        policy_values = {
            "type": "service" if line.is_service else "consu",
            "is_storable": not line.is_service,
            "sale_ok": True,
            "purchase_ok": False,
            "invoice_policy": "order" if line.is_service else "delivery",
        }
        if not product:
            template_values = {
                "name": line.name,
                "default_code": line.default_code,
                "company_id": self.company_id.id,
                **policy_values,
                "list_price": line.proposed_list_price,
                "taxes_id": tax_command,
                "description_sale": line.description or False,
            }
            if not line.is_service:
                template_values["categ_id"] = self.product_category_id.id
            template = self.env["product.template"].create(template_values)
            product = template.product_variant_id
        else:
            values = {
                key: value for key, value in policy_values.items()
                if getattr(product.product_tmpl_id, key) != value
            }
            template = product.product_tmpl_id
            if self.update_existing_prices and template.list_price != line.proposed_list_price:
                values["list_price"] = line.proposed_list_price
                values["taxes_id"] = tax_command
            if values:
                template.write(values)
        forbidden_routes = self.env["stock.route"].browse()
        for xmlid in ("stock.route_warehouse0_mto", "purchase_stock.route_warehouse0_buy"):
            route = self.env.ref(xmlid, raise_if_not_found=False)
            if route:
                forbidden_routes |= route
        explicit_forbidden = template.route_ids & forbidden_routes
        if explicit_forbidden:
            template.route_ids = [Command.unlink(route.id) for route in explicit_forbidden]
        if line.source_category:
            tag = self.env["product.tag"].search([("name", "=", line.source_category)], limit=1)
            if not tag:
                tag = self.env["product.tag"].create({"name": line.source_category})
            if tag not in template.product_tag_ids:
                template.product_tag_ids = [Command.link(tag.id)]
        binding = self.env["mb.shop.product.binding"].search([
            ("source_id", "=", self.source_id.id),
            ("external_id", "=", line.external_id),
        ], limit=1)
        values = {
            "source_url": line.product_url or False,
            "adapter_key": self.parsed_adapter_key,
            "adapter_version": self.adapter_version,
            "last_seen_at": fields.Datetime.now(),
        }
        if binding:
            if binding.product_id != product:
                raise ValidationError(_("The source binding now points at another product."))
            _internal(binding).write(values)
        else:
            binding = _internal(self.env["mb.shop.product.binding"]).create({
                **values,
                "source_id": self.source_id.id,
                "external_id": line.external_id,
                "product_id": product.id,
            })
        return product

    def _set_stock(self, line, product):
        if line.is_service or not line.stock_is_tracked:
            return False
        quants = self.env["stock.quant"].search([
            ("product_id", "=", product.id),
            ("location_id", "=", self.target_location_id.id),
            ("lot_id", "=", False),
            ("package_id", "=", False),
            ("owner_id", "=", False),
        ])
        if len(quants) > 1:
            raise ValidationError(_("More than one untracked quant exists for %(product)s.", product=product.display_name))
        quant = quants[:1]
        before = quant.quantity if quant else 0.0
        if not float_compare(before, line.stock_quantity, precision_rounding=product.uom_id.rounding):
            return False
        if quant:
            inventory_quant = quant.with_context(inventory_mode=True)
            inventory_quant.inventory_quantity = line.stock_quantity
        else:
            inventory_quant = self.env["stock.quant"].with_context(inventory_mode=True).create({
                "product_id": product.id,
                "location_id": self.target_location_id.id,
                "inventory_quantity": line.stock_quantity,
            })
        inventory_quant.action_apply_inventory()
        return {"before": before, "after": line.stock_quantity}

    def action_import_selected(self):
        self.ensure_one()
        self.check_access("write")
        if not self.env.user.has_group("mb_shop_import.group_shop_import_manager"):
            raise AccessError(_("Only a Shop Import Manager can ingest reviewed products."))
        if self.state != "ready" or not self.validated_at:
            raise UserError(_("Validate the import immediately before ingestion."))
        selected = self.line_ids.filtered("selected")
        if not selected:
            raise UserError(_("Select at least one valid line to import."))
        errors = selected.filtered(lambda line: line.validation_status == "error")
        if errors:
            raise UserError(_("Selected lines with errors cannot be imported."))
        if selected.filtered(lambda line: line.validation_status == "warning") \
                and not self.warnings_acknowledged_at:
            raise UserError(_("Acknowledge selected warnings before importing."))
        selected_stock = selected.filtered(
            lambda line: line.stock_is_tracked and not line.is_service
        )
        snapshot_is_now_stale = bool(
            selected_stock
            and self.source_snapshot_at
            and self.snapshot_max_age_hours
            and fields.Datetime.now() - self.source_snapshot_at
            > timedelta(hours=self.snapshot_max_age_hours)
        )
        if snapshot_is_now_stale and not self.validated_snapshot_stale:
            raise UserError(_(
                "The source stock snapshot became stale after validation. Validate the batch again."
            ))
        _internal(self).write({"state": "importing", "failure_detail": False})
        try:
            with self.env.cr.savepoint():
                self._lock_and_check_stock(selected)
                created = updated = stock_written = 0
                affected = self.env["product.template"]
                stock_changes = []
                for line in selected.sorted("sequence"):
                    was_new = not bool(line.matched_product_id)
                    product = self._create_or_update_product(line)
                    created += int(was_new)
                    updated += int(not was_new)
                    affected |= product.product_tmpl_id
                    stock_change = self._set_stock(line, product)
                    if stock_change:
                        stock_written += 1
                        stock_changes.append({
                            "external_id": line.external_id,
                            "product_id": product.id,
                            **stock_change,
                        })
                    _internal(line).write({
                        "matched_product_id": product.id,
                        "proposed_action": "update",
                        "validation_status": "ingested",
                        "ingested_product_id": product.id,
                    })
                summary = {
                    "selected": len(selected),
                    "created": created,
                    "updated": updated,
                    "stock_written": stock_written,
                    "stock_changes": stock_changes,
                    "adapter": self.parsed_adapter_key,
                    "file_sha256": self.file_sha256,
                }
                _internal(self).write({
                    "state": "done",
                    "affected_product_tmpl_ids": [Command.set(affected.ids)],
                    "imported_at": fields.Datetime.now(),
                    "imported_by_id": self.env.user.id,
                    "result_summary": summary,
                })
        except Exception as error:  # the savepoint keeps every business write atomic
            self.env.invalidate_all()
            if isinstance(error, (UserError, ValidationError, AccessError)):
                detail = str(error).replace("\x00", "")[:MAX_FAILURE_CHARS]
            else:
                detail = _(
                    "An unexpected import error occurred. Ask an administrator to inspect "
                    "the server log for batch %(batch)s.",
                    batch=self.name,
                )
            _logger.exception("shop import %s rolled back", self.id)
            _internal(self).write({
                "state": "failed",
                "failure_detail": detail,
                "result_summary": {"error": detail},
            })
        if self.state == "done" and self.import_images:
            self.action_import_images()
        return self._reopen()

    def action_import_images(self):
        self.ensure_one()
        self.check_access("write")
        if not self.env.user.has_group("mb_shop_import.group_shop_import_manager"):
            raise AccessError(_("Only a Shop Import Manager can import product images."))
        if self.state != "done":
            raise UserError(_("Images can be imported only after product ingestion."))
        allowed_hosts = self.source_id.image_hosts()
        if not allowed_hosts:
            raise UserError(_("Configure at least one allowed image hostname on the shop source."))
        cache = {}
        for line in self.line_ids.filtered(lambda item: item.selected and item.ingested_product_id):
            template = line.ingested_product_id.product_tmpl_id
            if not line.image_url:
                _internal(line).write({"image_status": "skipped", "image_failure": False})
                continue
            if template.image_1920 and not self.overwrite_images:
                _internal(line).write({"image_status": "skipped", "image_failure": False})
                continue
            try:
                with self.env.cr.savepoint():
                    image = cache.get(line.image_url)
                    if not image:
                        image = fetch_image(line.image_url, allowed_hosts)
                        cache[line.image_url] = image
                    template.image_1920 = base64.b64encode(image.data)
                    _internal(line).write({"image_status": "imported", "image_failure": False})
            except Exception as error:
                self.env.invalidate_all()
                if isinstance(error, (ImageFetchError, UserError, ValidationError, AccessError)):
                    detail = str(error)[:500]
                else:
                    _logger.exception("shop import image failed for line %s", line.id)
                    detail = _("An unexpected image import error occurred.")
                _internal(line).write({
                    "image_status": "failed",
                    "image_failure": detail,
                })
        return self._reopen()

    def action_cancel(self):
        self.check_access("write")
        for batch in self:
            if batch.state in {"done", "importing"}:
                raise UserError(_("An imported or importing batch cannot be cancelled."))
        _internal(self).write({"state": "cancelled"})
        return True

    def action_purge_source_evidence(self):
        self.ensure_one()
        if not self.env.user.has_group("mb_shop_import.group_shop_import_manager"):
            raise AccessError(_("Only a Shop Import Manager can purge retained source evidence."))
        if self.state not in {"done", "cancelled", "failed"}:
            raise UserError(_("Source evidence can be purged only after the batch is closed."))
        _internal(self.line_ids).write({"raw_record": False})
        _internal(self).write({"source_file": False})
        return self._reopen()

    def action_open_products(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Imported products"),
            "res_model": "product.template",
            "view_mode": "list,form",
            "domain": [("id", "in", self.affected_product_tmpl_ids.ids)],
            "context": {"create": False},
        }

    def action_open_lines(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "mb_shop_import.action_shop_import_lines"
        )
        action["domain"] = [("batch_id", "=", self.id)]
        action["context"] = {"create": False, "delete": False}
        return action

    def _reopen(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }


class ShopImportLine(models.Model):
    _name = "mb.shop.import.line"
    _description = "Shop catalogue import line"
    _order = "sequence, id"
    _check_company_auto = True

    batch_id = fields.Many2one(
        "mb.shop.import.batch", required=True, ondelete="cascade", index=True, check_company=True,
    )
    company_id = fields.Many2one(related="batch_id.company_id", store=True, readonly=True, index=True)
    sequence = fields.Integer(required=True, readonly=True)
    raw_record = fields.Json(readonly=True, copy=False)
    external_id = fields.Char(required=True, readonly=True, index=True)
    parent_external_id = fields.Char(readonly=True)
    identity_is_fallback = fields.Boolean(readonly=True)
    name = fields.Char(required=True)
    variant_title = fields.Char()
    default_code = fields.Char(required=True)
    product_url = fields.Char(readonly=True)
    description = fields.Text()
    category_path = fields.Json(readonly=True)
    source_category = fields.Char(readonly=True)
    source_price = fields.Monetary(required=True)
    currency_id = fields.Many2one("res.currency", required=True, readonly=True)
    published_vat_status = fields.Char(readonly=True)
    proposed_list_price = fields.Monetary(readonly=True)
    proposed_customer_price = fields.Monetary(readonly=True)
    current_name = fields.Char(readonly=True)
    current_list_price = fields.Monetary(readonly=True)
    price_changed = fields.Boolean(readonly=True, index=True)
    stock_quantity = fields.Float()
    stock_is_tracked = fields.Boolean(readonly=True)
    reviewed_quantity = fields.Float(readonly=True)
    reviewed_reserved_quantity = fields.Float(readonly=True)
    stock_changed = fields.Boolean(readonly=True, index=True)
    has_reviewed_baseline = fields.Boolean(readonly=True)
    availability = fields.Char(readonly=True)
    image_url = fields.Char(readonly=True)
    image_status = fields.Selection(
        [("pending", "Pending"), ("imported", "Imported"), ("skipped", "Skipped"),
         ("failed", "Failed")], readonly=True,
    )
    image_failure = fields.Char(readonly=True)
    fetched_at = fields.Datetime(readonly=True)
    is_service = fields.Boolean()
    matched_product_id = fields.Many2one(
        "product.product", readonly=True, ondelete="restrict", check_company=True,
    )
    manual_product_id = fields.Many2one(
        "product.product",
        string="Explicit product match",
        ondelete="restrict",
        check_company=True,
        domain="[('company_id', '=', company_id)]",
    )
    ingested_product_id = fields.Many2one(
        "product.product", readonly=True, ondelete="restrict", check_company=True,
    )
    match_method = fields.Selection(
        [("new", "New"), ("manual", "Explicit review match"), ("binding", "Source binding"),
         ("default_code", "Internal reference"), ("ambiguous_code", "Ambiguous reference")],
        readonly=True,
    )
    proposed_action = fields.Selection(
        [("create", "Create"), ("update", "Update"), ("skip", "Skip")],
        default="create",
    )
    selected = fields.Boolean()
    validation_status = fields.Selection(
        [("new", "Not validated"), ("valid", "Valid"), ("warning", "Warning"),
         ("error", "Error"), ("ingested", "Ingested")],
        required=True, default="new", readonly=True, index=True,
    )
    validation_messages = fields.Text(readonly=True)
    duplicate_code = fields.Boolean(readonly=True, index=True)

    _batch_external_unique = models.Constraint(
        "UNIQUE(batch_id, external_id)", "An external variant may appear once in a batch."
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not _is_internal(self):
            raise UserError(_("Staging lines can be created only by parsing an uploaded artifact."))
        return super().create(vals_list)

    def unlink(self):
        if not _is_internal(self):
            raise UserError(_("Staging lines cannot be deleted manually."))
        return super().unlink()

    def write(self, values):
        immutable = {
            "batch_id", "company_id", "sequence", "raw_record", "external_id",
            "parent_external_id", "identity_is_fallback", "product_url", "category_path",
            "source_category", "currency_id", "published_vat_status", "stock_is_tracked",
            "availability", "image_url", "fetched_at", "matched_product_id",
            "ingested_product_id", "match_method", "proposed_action", "proposed_list_price",
            "proposed_customer_price", "current_name", "current_list_price", "price_changed",
            "reviewed_quantity", "reviewed_reserved_quantity", "stock_changed", "duplicate_code",
            "has_reviewed_baseline", "validation_status", "validation_messages",
            "image_status", "image_failure",
        }
        if immutable.intersection(values) and not _is_internal(self):
            raise UserError(_("Source evidence and computed review fields cannot be edited."))
        if self.filtered(lambda line: line.batch_id.state not in {"review", "ready"}) \
                and not _is_internal(self):
            raise UserError(_("Lines can be edited only while their batch is under review."))
        result = super().write(values)
        editable = {
            "name", "variant_title", "default_code", "description", "source_price",
            "stock_quantity", "is_service", "manual_product_id",
        }
        if editable.intersection(values) and not _is_internal(self):
            batches = self.mapped("batch_id")
            _internal(self).write({
                "validation_status": "new",
                "validation_messages": False,
                "has_reviewed_baseline": False,
            })
            _internal(batches).write({
                "state": "review",
                "validated_at": False,
                "validated_snapshot_stale": False,
                "warnings_acknowledged_at": False,
                "warnings_acknowledged_by_id": False,
            })
        elif "selected" in values and not _is_internal(self):
            for line in self:
                action = "skip"
                if line.selected:
                    action = "update" if line.matched_product_id else "create"
                _internal(line).write({"proposed_action": action})
            _internal(self.mapped("batch_id")).write({
                "warnings_acknowledged_at": False,
                "warnings_acknowledged_by_id": False,
            })
        return result
