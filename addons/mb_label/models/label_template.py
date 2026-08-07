import copy
import re
import unicodedata
from urllib.parse import quote, urlsplit, urlunsplit

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


ALLOWED_TYPES = {"text", "qr", "barcode", "image", "rect", "ellipse", "triangle", "line"}
ALLOWED_BINDINGS = {
    "product.default_code",
    "product.name",
    "product.barcode",
    "product.price",
    "product.price.raw",
    "lot.name",
    "company.name",
    "company.currency",
    "qr",
    "qr.path",
}
ALLOWED_FILTERS = {
    "default", "fixed", "lower", "money", "money_trim", "number", "title", "trim", "upper",
}
TOKEN_RE = re.compile(r"\{\{\s*([\w.-]+)\s*((?:\|[^{}]*)?)\}\}")
FILTER_RE = re.compile(r"^([a-z_]+)(?::(.*))?$", re.IGNORECASE)


def parse_filters(source):
    filters = []
    if not source:
        return filters
    for raw in source.split("|")[1:]:
        match = FILTER_RE.fullmatch(raw.strip())
        if not match or match.group(1).lower() not in ALLOWED_FILTERS:
            raise ValidationError(_("Unsupported label formatting filter: %s", raw.strip()))
        name, argument = match.group(1).lower(), match.group(2)
        if name == "fixed":
            if argument is None or not argument.isdigit() or not 0 <= int(argument) <= 4:
                raise ValidationError(_("The fixed filter needs a decimal count between 0 and 4."))
        elif name != "default" and argument is not None:
            raise ValidationError(_("The '%s' label filter does not accept an argument.", name))
        if argument is not None and len(argument) > 64:
            raise ValidationError(_("A label formatting argument cannot exceed 64 characters."))
        filters.append((name, argument))
    return filters


def normalize_qr(value):
    value = unicodedata.normalize("NFKC", value or "").strip()
    if not value:
        raise ValidationError(_("The rendered QR value is empty."))
    if len(value) > 1024:
        raise ValidationError(_("A QR value cannot exceed 1024 characters."))
    return value


def normalize_qr_url_prefix(value):
    value = unicodedata.normalize("NFKC", value or "").strip().rstrip("#")
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.fragment:
        raise ValidationError(_("The QR URL prefix must be an HTTP(S) URL without a fragment."))
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, ""))


def qr_identity_path(product_code, lot_name=None):
    sku = quote(unicodedata.normalize("NFKC", str(product_code or "")).strip(), safe="-._~")
    if not sku:
        raise ValidationError(_("A product needs an internal reference before a QR label can be printed."))
    if not lot_name:
        return sku
    lot = quote(unicodedata.normalize("NFKC", str(lot_name)).strip(), safe="-._~")
    if not lot:
        raise ValidationError(_("A lot or serial QR path cannot be empty."))
    return "%s/%s" % (sku, lot)


def build_qr_value(prefix, product_code, lot_name=None):
    path = qr_identity_path(product_code, lot_name)
    prefix = normalize_qr_url_prefix(prefix)
    return "%s#%s" % (prefix, path) if prefix else path


def validate_document(document):
    if not isinstance(document, dict):
        raise ValidationError(_("The label document must be a JSON object."))
    if document.get("schema") != 1:
        raise ValidationError(_("Unsupported label document schema."))
    elements = document.get("elements")
    if not isinstance(elements, list):
        raise ValidationError(_("The label document needs an elements list."))
    seen = set()
    for element in elements:
        if not isinstance(element, dict) or element.get("type") not in ALLOWED_TYPES:
            raise ValidationError(_("Unsupported label element."))
        element_id = element.get("id")
        if not isinstance(element_id, str) or not element_id or element_id in seen:
            raise ValidationError(_("Every element needs a unique stable id."))
        seen.add(element_id)
        for key in ("x", "y", "width", "height"):
            value = element.get(key)
            if not isinstance(value, (int, float)) or value < 0:
                raise ValidationError(_("Element geometry must use positive millimetres."))
        if element.get("align") not in (None, "left", "center", "right"):
            raise ValidationError(_("Unsupported text alignment."))
        if element.get("valign") not in (None, "top", "middle", "bottom"):
            raise ValidationError(_("Unsupported vertical text alignment."))
        if element.get("font") not in (None, "sans", "serif", "mono"):
            raise ValidationError(_("Unsupported label font."))
        if element.get("background") not in (None, "transparent", "white", "black"):
            raise ValidationError(_("Unsupported element background."))
        if element.get("tint") not in (None, "solid", "75", "50", "25"):
            raise ValidationError(_("Unsupported thermal tint."))
        if element.get("dither") not in (
                None, "threshold", "floyd-steinberg", "atkinson", "ordered"):
            raise ValidationError(_("Unsupported image dithering mode."))
        threshold = element.get("dither_threshold")
        if threshold is not None and (
                not isinstance(threshold, (int, float)) or not 0 <= threshold <= 255):
            raise ValidationError(_("The image threshold must be between 0 and 255."))
        quiet_zone = element.get("quiet_zone")
        if quiet_zone is not None and (
                not isinstance(quiet_zone, int) or isinstance(quiet_zone, bool)
                or not 0 <= quiet_zone <= 8):
            raise ValidationError(_("The QR quiet zone must contain between 0 and 8 modules."))
        if element.get("group_id") is not None and not isinstance(element["group_id"], str):
            raise ValidationError(_("Element group identifiers must be text."))
        if element.get("required") is not None and not isinstance(element["required"], bool):
            raise ValidationError(_("The required-value setting must be true or false."))
        for source_key in ("text", "data"):
            source = element.get(source_key)
            if source is None:
                continue
            if not isinstance(source, str):
                raise ValidationError(_("Element content must be text."))
            for binding, filters in TOKEN_RE.findall(source):
                if binding not in ALLOWED_BINDINGS and not binding.startswith("manual."):
                    raise ValidationError(_("Binding '%s' is not allowed.", binding))
                parse_filters(filters)
            if "{{" in TOKEN_RE.sub("", source) or "}}" in TOKEN_RE.sub("", source):
                raise ValidationError(_("Malformed label binding expression."))
    return copy.deepcopy(document)


class MbLabelTemplate(models.Model):
    _name = "mb.label.template"
    _description = "Label Template"
    _order = "is_default desc, name"
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True)
    width_mm = fields.Float(required=True, default=40.0)
    height_mm = fields.Float(required=True, default=30.0)
    dpi = fields.Integer(required=True, default=203)
    qr_url_prefix = fields.Char(
        string="QR URL Prefix",
        help="Optional public URL placed before #SKU or #SKU/LOT in every generated QR code.")
    printer_target = fields.Char(
        help="Advisory printer or media target imported from the label design.")
    round_media = fields.Boolean(string="Round label")
    continuous_media = fields.Boolean(string="Continuous media")
    orientation = fields.Selection(
        [("portrait", "Portrait"), ("landscape", "Landscape")],
        required=True, default="landscape")
    active = fields.Boolean(default=True)
    is_default = fields.Boolean(string="Default")
    version_ids = fields.One2many("mb.label.template.version", "template_id")
    current_version_id = fields.Many2one(
        "mb.label.template.version", string="Current Version", copy=False, readonly=True,
        check_company=True)

    @api.constrains("width_mm", "height_mm", "dpi")
    def _check_media(self):
        for record in self:
            if not 5 <= record.width_mm <= 300 or not 5 <= record.height_mm <= 500:
                raise ValidationError(_("Label dimensions must be between 5 and 300/500 mm."))
            if not 72 <= record.dpi <= 600:
                raise ValidationError(_("Label DPI must be between 72 and 600."))

    @api.constrains("is_default", "company_id")
    def _check_default(self):
        for record in self.filtered("is_default"):
            others = self.search_count([
                ("id", "!=", record.id), ("company_id", "=", record.company_id.id),
                ("is_default", "=", True), ("active", "=", True),
            ])
            if others:
                raise ValidationError(_("A company can have only one default label template."))

    def action_set_default(self):
        self.ensure_one()
        self.search([
            ("company_id", "=", self.company_id.id), ("id", "!=", self.id)
        ]).write({"is_default": False})
        self.is_default = True

    def save_version(self, document, qr_payload_template="{{qr}}", qr_url_prefix=None):
        self.ensure_one()
        self.check_access("write")
        document = validate_document(document)
        prefix = normalize_qr_url_prefix(
            self.qr_url_prefix if qr_url_prefix is None else qr_url_prefix)
        for binding, filters in TOKEN_RE.findall(qr_payload_template or ""):
            if binding not in ALLOWED_BINDINGS and not binding.startswith("manual."):
                raise ValidationError(_("Binding '%s' is not allowed.", binding))
            parse_filters(filters)
        unresolved = TOKEN_RE.sub("", qr_payload_template or "")
        if "{{" in unresolved or "}}" in unresolved:
            raise ValidationError(_("Malformed label binding expression."))
        next_number = max(self.version_ids.mapped("number") or [0]) + 1
        version = self.env["mb.label.template.version"].create({
            "template_id": self.id,
            "number": next_number,
            "document_json": document,
            "qr_payload_template": qr_payload_template or "{{qr}}",
            "qr_url_prefix": prefix,
            "printer_target": self.printer_target,
            "round_media": self.round_media,
            "continuous_media": self.continuous_media,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "dpi": self.dpi,
        })
        self.write({"current_version_id": version.id, "qr_url_prefix": prefix})
        return version.read(["id", "number", "document_json", "qr_payload_template"])[0]

    def save_editor_version(self, document, settings=None):
        self.ensure_one()
        self.check_access("write")
        settings = settings or {}
        allowed = {
            "width_mm", "height_mm", "dpi", "qr_url_prefix", "printer_target",
            "round_media", "continuous_media", "qr_payload_template",
        }
        unknown = set(settings) - allowed
        if unknown:
            raise ValidationError(_("Unsupported label setting: %s", ", ".join(sorted(unknown))))
        values = {
            key: settings[key] for key in allowed
            if key in settings and key not in ("qr_url_prefix", "qr_payload_template")
        }
        if values:
            self.write(values)
        return self.save_version(
            document,
            settings.get("qr_payload_template", "{{qr}}"),
            settings.get("qr_url_prefix", self.qr_url_prefix),
        )

    @api.model
    def editor_bootstrap(self):
        templates = self.search([])
        return [{
            "id": item.id,
            "name": item.name,
            "width_mm": item.width_mm,
            "height_mm": item.height_mm,
            "dpi": item.dpi,
            "is_default": item.is_default,
            "version_number": item.current_version_id.number or 0,
            "document": item.current_version_id.document_json or {"schema": 1, "elements": []},
            "qr_payload_template": item.current_version_id.qr_payload_template or "{{qr}}",
            "qr_url_prefix": item.current_version_id.qr_url_prefix or item.qr_url_prefix or "",
            "printer_target": item.current_version_id.printer_target or item.printer_target or "",
            "round_media": item.current_version_id.round_media or item.round_media,
            "continuous_media": item.current_version_id.continuous_media or item.continuous_media,
        } for item in templates]

    @api.model
    def editor_preview_options(self):
        products = self.env["product.product"].search([
            ("active", "=", True), ("sale_ok", "=", True),
        ], order="name, id", limit=200)
        lots = self.env["stock.lot"].search([
            ("product_id", "in", products.ids), ("company_id", "in", [False, self.env.company.id]),
        ], order="name, id", limit=500)
        return {
            "products": [{
                "id": product.id, "name": product.display_name,
            } for product in products],
            "lots": [{
                "id": lot.id, "name": lot.name, "product_id": lot.product_id.id,
            } for lot in lots],
        }

    @api.model
    def editor_preview_bindings(self, product_id, lot_id=None, qr_url_prefix=""):
        product = self.env["product.product"].browse(int(product_id)).exists()
        if not product:
            raise ValidationError(_("Choose an available product for the label preview."))
        lot = self.env["stock.lot"].browse(int(lot_id)).exists() if lot_id else None
        return self.env["mb.label.render.service"].bindings_for(
            product, lot, {}, normalize_qr_url_prefix(qr_url_prefix))


class MbLabelTemplateVersion(models.Model):
    _name = "mb.label.template.version"
    _description = "Immutable Label Template Version"
    _order = "template_id, number desc"
    _check_company_auto = True

    template_id = fields.Many2one(
        "mb.label.template", required=True, ondelete="restrict", check_company=True, index=True)
    company_id = fields.Many2one(related="template_id.company_id", store=True, index=True)
    number = fields.Integer(required=True)
    document_json = fields.Json(required=True)
    qr_payload_template = fields.Char(required=True, default="{{qr}}")
    qr_url_prefix = fields.Char(readonly=True)
    printer_target = fields.Char(readonly=True)
    round_media = fields.Boolean(readonly=True)
    continuous_media = fields.Boolean(readonly=True)
    width_mm = fields.Float(required=True)
    height_mm = fields.Float(required=True)
    dpi = fields.Integer(required=True)
    author_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)

    _number_unique = models.Constraint(
        "UNIQUE(template_id, number)", "Template version numbers must be unique.")

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            values["document_json"] = validate_document(values.get("document_json"))
            values["qr_url_prefix"] = normalize_qr_url_prefix(values.get("qr_url_prefix"))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_("Saved label versions are immutable; save a new version instead."))

    def unlink(self):
        raise UserError(_("Saved label versions cannot be deleted."))
