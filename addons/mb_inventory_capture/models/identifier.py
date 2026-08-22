import re

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

GTIN_SCHEMES = {"gtin_8": 8, "gtin_12": 12, "gtin_13": 13, "gtin_14": 14}
PRIVATE_SCHEMES = {"manufacturer_sku", "supplier_code", "internal"}


def normalize_identifier(scheme, value):
    printed = (value or "").strip()
    if scheme in GTIN_SCHEMES:
        digits = re.sub(r"[\s-]", "", printed)
        expected = GTIN_SCHEMES[scheme]
        if not digits.isdigit() or len(digits) != expected:
            raise ValidationError(
                _("%(scheme)s must contain %(length)s digits.", scheme=scheme, length=expected)
            )
        expected_check = (
            10
            - sum(
                int(digit) * (3 if index % 2 == 0 else 1)
                for index, digit in enumerate(reversed(digits[:-1]))
            )
            % 10
        ) % 10
        if expected_check != int(digits[-1]):
            raise ValidationError(_("The GTIN check digit is invalid."))
        return digits.zfill(14)
    if scheme not in PRIVATE_SCHEMES:
        raise ValidationError(_("Unsupported identifier scheme."))
    normalized = " ".join(printed.casefold().split())
    if not normalized or len(normalized) > 255:
        raise ValidationError(_("The identifier must contain between 1 and 255 characters."))
    return normalized


def normalize_any_gtin(value):
    """Return the GTIN-14 comparison value, or ``None`` for non/invalid GTINs."""
    printed = (value or "").strip()
    digits = re.sub(r"[\s-]", "", printed)
    scheme = next(
        (candidate for candidate, length in GTIN_SCHEMES.items() if len(digits) == length),
        None,
    )
    if not scheme:
        return None
    try:
        return normalize_identifier(scheme, printed)
    except ValidationError:
        return None


def expand_upc_e(value):
    """Expand an 8-digit UPC-E (number system + payload + check) to UPC-A."""
    digits = re.sub(r"[\s-]", "", (value or "").strip())
    if len(digits) != 8 or not digits.isdigit() or digits[0] not in {"0", "1"}:
        return None
    number_system, payload, check = digits[0], digits[1:7], digits[7]
    last = payload[5]
    if last in "012":
        body = number_system + payload[:2] + last + "0000" + payload[2:5]
    elif last == "3":
        body = number_system + payload[:3] + "00000" + payload[3:5]
    elif last == "4":
        body = number_system + payload[:4] + "00000" + payload[4]
    else:
        body = number_system + payload[:5] + "0000" + last
    expanded = body + check
    return expanded if normalize_any_gtin(expanded) else None


def parse_gs1_element_string(value):
    """Parse the fixed fields and AI 10/30 from a scanner element string.

    Browser scanners commonly expose either parenthesized human-readable text
    or a raw FNC1 value using ASCII group separator. Unknown AIs are returned as
    warnings rather than guessed because variable field lengths are contextual.
    """
    raw = (value or "").strip()
    result = {"gtin": None, "lot": None, "expiry": None, "quantity": None, "warnings": []}
    if not raw:
        return result
    parenthesized = re.findall(r"\((01|10|17|30)\)(.*?)(?=\((?:01|10|17|30)\)|$)", raw)
    if parenthesized:
        fields_found = parenthesized
    else:
        cursor = raw.removeprefix("]d2")
        fields_found = []
        while cursor:
            if cursor.startswith("01") and len(cursor) >= 16:
                fields_found.append(("01", cursor[2:16]))
                cursor = cursor[16:]
            elif cursor.startswith("17") and len(cursor) >= 8:
                fields_found.append(("17", cursor[2:8]))
                cursor = cursor[8:]
            elif cursor.startswith("10"):
                value_part, separator, remainder = cursor[2:].partition("\x1d")
                fields_found.append(("10", value_part[:20]))
                cursor = remainder if separator else ""
            elif cursor.startswith("30"):
                value_part, separator, remainder = cursor[2:].partition("\x1d")
                fields_found.append(("30", value_part[:8]))
                cursor = remainder if separator else ""
            else:
                result["warnings"].append(_("Unsupported or malformed GS1 application identifier."))
                break
    for application_id, extracted in fields_found:
        extracted = extracted.strip()
        if application_id == "01":
            result["gtin"] = normalize_identifier("gtin_14", extracted)
        elif application_id == "10":
            result["lot"] = extracted or None
        elif application_id == "17":
            if re.fullmatch(r"\d{6}", extracted):
                proposed = f"20{extracted[:2]}-{extracted[2:4]}-{extracted[4:6]}"
                try:
                    fields.Date.to_date(proposed)
                except ValueError:
                    result["warnings"].append(_("Malformed GS1 expiry date."))
                else:
                    result["expiry"] = proposed
            else:
                result["warnings"].append(_("Malformed GS1 expiry date."))
        elif application_id == "30":
            result["quantity"] = int(extracted) if extracted.isdigit() else None
    return result


class ProductIdentifier(models.Model):
    _name = "mb.product.identifier"
    _description = "Verified product identifier"
    _inherit = ["mail.thread"]
    _order = "product_id, scheme, printed_value"
    _check_company_auto = True

    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", index=True)
    scope_key = fields.Integer(compute="_compute_scope_key", store=True, index=True)
    product_id = fields.Many2one(
        "product.product",
        required=True,
        ondelete="restrict",
        check_company=True,
        index=True,
    )
    scheme = fields.Selection(
        [
            (key, key.replace("_", " ").upper())
            for key in sorted(set(GTIN_SCHEMES) | PRIVATE_SCHEMES)
        ],
        required=True,
    )
    comparison_scheme = fields.Char(required=True, readonly=True, index=True)
    printed_value = fields.Char(required=True)
    normalized_value = fields.Char(required=True, readonly=True, index=True)
    source = fields.Char(required=True, default="manual")
    source_record_id = fields.Char()
    verification_state = fields.Selection(
        [("unverified", "Unverified"), ("verified", "Verified"), ("conflict", "Conflict")],
        required=True,
        default="unverified",
    )
    pack_identity = fields.Char()

    _identifier_unique = models.Constraint(
        "UNIQUE(scope_key, comparison_scheme, normalized_value)",
        "This identifier is already assigned to another product.",
    )

    @api.depends("company_id")
    def _compute_scope_key(self):
        for identifier in self:
            identifier.scope_key = identifier.company_id.id or 0

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for values in vals_list:
            values = dict(values)
            scheme = values.get("scheme")
            if scheme in GTIN_SCHEMES:
                if values.get("company_id"):
                    raise ValidationError(
                        _("GS1 identifiers are global and cannot be company-scoped.")
                    )
                comparison_scheme = "gtin"
            else:
                comparison_scheme = scheme
            values["comparison_scheme"] = comparison_scheme
            values["normalized_value"] = normalize_identifier(scheme, values.get("printed_value"))
            prepared.append(values)
        try:
            with self.env.cr.savepoint():
                records = super().create(prepared)
        except IntegrityError as error:
            for values in prepared:
                conflict = self.search(
                    [
                        ("scope_key", "=", values.get("company_id") or 0),
                        ("comparison_scheme", "=", values["comparison_scheme"]),
                        ("normalized_value", "=", values["normalized_value"]),
                    ],
                    limit=1,
                )
                if conflict:
                    raise ValidationError(
                        _(
                            "This identifier is already assigned to %(product)s.",
                            product=conflict.product_id.display_name,
                        )
                    ) from error
            raise
        records._check_primary_barcode_conflict()
        return records

    def write(self, values):
        protected = {
            "scheme",
            "printed_value",
            "normalized_value",
            "comparison_scheme",
            "company_id",
            "product_id",
        }
        if protected.intersection(values) and not self.env.context.get("mb_identifier_reassign"):
            raise ValidationError(
                _(
                    "Identifier identity and ownership are immutable; use the audited reassign action."
                )
            )
        result = super().write(values)
        self._check_primary_barcode_conflict()
        return result

    def _check_primary_barcode_conflict(self):
        for identifier in self.filtered(lambda record: record.comparison_scheme == "gtin"):
            products = self.env["product.product"].search(
                [
                    ("barcode", "!=", False),
                    ("id", "!=", identifier.product_id.id),
                ]
            )
            for product in products:
                if normalize_any_gtin(product.barcode) == identifier.normalized_value:
                    raise ValidationError(
                        _(
                            "This GTIN is already the primary barcode of %s.",
                            product.display_name,
                        )
                    )

    def action_reassign(self, product, reason):
        self.ensure_one()
        if not self.env.user.has_group("stock.group_stock_manager"):
            raise ValidationError(_("Only an inventory manager can reassign an identifier."))
        if not product or not reason or not reason.strip():
            raise ValidationError(_("A new owner and reassignment reason are required."))
        old_product = self.product_id
        self.with_context(mb_identifier_reassign=True).write({"product_id": product.id})
        self.message_post(
            body=_(
                "Identifier reassigned from %(old)s to %(new)s. Reason: %(reason)s",
                old=old_product.display_name,
                new=product.display_name,
                reason=reason.strip(),
            )
        )


class ProductProduct(models.Model):
    _inherit = "product.product"

    mb_identifier_ids = fields.One2many("mb.product.identifier", "product_id")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._check_mb_barcode_identifier_conflict()
        records._register_mb_primary_barcodes()
        return records

    def write(self, values):
        result = super().write(values)
        if "barcode" in values:
            self._check_mb_barcode_identifier_conflict()
            self._register_mb_primary_barcodes()
        return result

    @api.model
    def _register_mb_existing_primary_barcodes(self, batch_size=1000):
        """Backfill the identifier registry without building an unbounded domain."""
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        last_id = 0
        while products := self.search(
            [("barcode", "!=", False), ("id", ">", last_id)],
            order="id",
            limit=batch_size,
        ):
            products._register_mb_primary_barcodes()
            # Each completed batch writes its claims to the registry. The next
            # batch's normal lookup therefore still catches a GTIN claimed by
            # an earlier batch rather than treating batches as isolated.
            last_id = products[-1].id

    def _register_mb_primary_barcodes(self):
        registry = self.env["mb.product.identifier"].sudo()
        normalized_by_product = {}
        for product in self.filtered("barcode"):
            normalized = normalize_any_gtin(product.barcode)
            if normalized:
                normalized_by_product[product] = normalized
        if not normalized_by_product:
            return
        # One lookup and one create for the batch, instead of a search and a
        # create per product. `_check_mb_barcode_identifier_conflict` has
        # already rejected any value another product holds, so taking the first
        # holder of a value here is the same arbitrary choice the previous
        # `limit=1` search made.
        claimed = {}
        for holder in registry.search(
            [
                ("comparison_scheme", "=", "gtin"),
                ("normalized_value", "in", list(normalized_by_product.values())),
            ]
        ):
            claimed.setdefault(holder.normalized_value, holder.product_id)
        pending = []
        for product, normalized in normalized_by_product.items():
            owner = claimed.get(normalized)
            if owner is not None:
                if owner != product:
                    raise ValidationError(
                        _("This GTIN is already assigned to %s.", owner.display_name)
                    )
                continue
            digits = re.sub(r"[\s-]", "", product.barcode)
            scheme = next(key for key, length in GTIN_SCHEMES.items() if len(digits) == length)
            # Claim it for the rest of this batch too: two products carrying the
            # same GTIN in one write must still collide, as they did when each
            # product ran its own query.
            claimed[normalized] = product
            pending.append(
                {
                    "product_id": product.id,
                    "scheme": scheme,
                    "printed_value": product.barcode,
                    "source": "primary_barcode",
                    "verification_state": "verified",
                }
            )
        if pending:
            registry.create(pending)

    def _check_mb_barcode_identifier_conflict(self):
        normalized_by_product = {}
        for product in self.filtered("barcode"):
            normalized = normalize_any_gtin(product.barcode)
            if normalized:
                normalized_by_product[product] = normalized
        if not normalized_by_product:
            return
        # One lookup for the whole batch. A write that renumbers a hundred
        # products used to issue a hundred searches before rejecting the first
        # collision.
        holders = self.env["mb.product.identifier"].search(
            [
                ("comparison_scheme", "=", "gtin"),
                ("normalized_value", "in", list(normalized_by_product.values())),
            ]
        )
        # Uniqueness is per (scope_key, scheme, value), so one value may have
        # several holders. Keep them all: picking an arbitrary one could return
        # the product's own identifier and mask a genuine collision.
        holders_by_value = {}
        for holder in holders:
            holders_by_value.setdefault(holder.normalized_value, []).append(holder)
        for product, normalized in normalized_by_product.items():
            conflict = next(
                (
                    holder
                    for holder in holders_by_value.get(normalized, [])
                    if holder.product_id != product
                ),
                None,
            )
            if conflict:
                raise ValidationError(
                    _(
                        "This GTIN is already assigned to %s.",
                        conflict.product_id.display_name,
                    )
                )
