import base64
import binascii
import hashlib
import io
import json
import os
import re
import uuid
import warnings
from urllib.parse import urljoin, urlparse

from PIL import Image, ImageOps, UnidentifiedImageError
from psycopg2 import IntegrityError
import requests

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .identifier import GTIN_SCHEMES, normalize_identifier, parse_gs1_element_string


MAX_SOURCE_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 12_000_000
MAX_RAW_RESPONSE_CHARS = 65_536
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INTERNAL_WRITE_TOKEN = object()


def _internal(records):
    return records.sudo().with_context(mb_inventory_capture_internal=_INTERNAL_WRITE_TOKEN)


def _is_internal(records):
    return records.env.su or (
        records.env.context.get("mb_inventory_capture_internal") is _INTERNAL_WRITE_TOKEN
    )


def _uuid(value, field_name):
    normalized = str(value or "").lower()
    if not UUID_RE.fullmatch(normalized):
        raise ValidationError(_("%(field)s must be a lowercase UUID.", field=field_name))
    return normalized


def _bounded_json(value, field_name, maximum=MAX_RAW_RESPONSE_CHARS):
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ValidationError(_("%(field)s must be valid JSON.", field=field_name)) from error
    if len(encoded) > maximum:
        raise ValidationError(_("%(field)s exceeds the retained evidence limit.", field=field_name))
    return value


def sanitize_image(encoded):
    try:
        received = base64.b64decode(encoded, validate=True)
    except (binascii.Error, TypeError, ValueError) as error:
        raise ValidationError(_("The upload is not valid base64 image data.")) from error
    if not received or len(received) > MAX_SOURCE_BYTES:
        raise ValidationError(_("The image must be between 1 byte and 15 MB."))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(received)) as probe:
                if getattr(probe, "n_frames", 1) != 1:
                    raise ValidationError(_("Animated or multi-frame images are not accepted."))
                width, height = probe.size
                image_format = probe.format
                probe.verify()
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise ValidationError(_("The image exceeds the 12-megapixel limit."))
            with Image.open(io.BytesIO(received)) as opened:
                oriented = ImageOps.exif_transpose(opened)
                if image_format in {"JPEG", "JPG"}:
                    converted = oriented.convert("RGB")
                    mimetype, extension = "image/jpeg", "jpg"
                elif image_format == "PNG":
                    converted = oriented.convert("RGBA" if "A" in oriented.getbands() else "RGB")
                    mimetype, extension = "image/png", "png"
                else:
                    raise ValidationError(_("Only genuine JPEG and PNG images are accepted."))
                output = io.BytesIO()
                if extension == "jpg":
                    converted.save(output, format="JPEG", quality=90, optimize=True)
                else:
                    converted.save(output, format="PNG", optimize=True)
                sanitized = output.getvalue()
                width, height = converted.size
    except ValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning,
            UnidentifiedImageError, OSError, ValueError) as error:
        raise ValidationError(_("The upload is not a safe decodable JPEG or PNG image.")) from error
    return {
        "received_sha256": hashlib.sha256(received).hexdigest(),
        "sanitized_sha256": hashlib.sha256(sanitized).hexdigest(),
        "data": sanitized,
        "mimetype": mimetype,
        "extension": extension,
        "width": width,
        "height": height,
    }


class InventoryCapture(models.Model):
    _name = "mb.inventory.capture"
    _description = "Product photo inventory capture"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(required=True, readonly=True, copy=False, default=lambda self: _("New"))
    capture_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    company_id = fields.Many2one(
        "res.company", required=True, readonly=True, default=lambda self: self.env.company,
        index=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("processing", "Processing"), ("review", "Review"),
         ("applied", "Applied"), ("failed", "Failed"), ("cancelled", "Cancelled")],
        required=True, default="draft", readonly=True, tracking=True, index=True,
    )
    picking_id = fields.Many2one("stock.picking", ondelete="restrict", check_company=True)
    move_id = fields.Many2one("stock.move", ondelete="restrict", check_company=True)
    move_line_id = fields.Many2one("stock.move.line", ondelete="restrict", check_company=True)
    asset_ids = fields.One2many("mb.inventory.capture.asset", "capture_id", copy=False)
    attempt_ids = fields.One2many("mb.inventory.capture.attempt", "capture_id", copy=False)
    candidate_ids = fields.One2many("mb.inventory.capture.candidate", "capture_id", copy=False)
    product_id = fields.Many2one(
        "product.product", ondelete="restrict", check_company=True, tracking=True,
    )
    lot_id = fields.Many2one("stock.lot", ondelete="restrict", check_company=True, tracking=True)
    proposed_lot = fields.Char(tracking=True)
    proposed_quantity = fields.Float(tracking=True)
    proposed_expiry = fields.Date(tracking=True)
    apply_expiry = fields.Boolean(
        help="Apply the explicitly reviewed expiry date to the native lot record."
    )
    product_conflict_acknowledged = fields.Boolean(tracking=True)
    applied_by = fields.Many2one("res.users", readonly=True, copy=False)
    applied_at = fields.Datetime(readonly=True, copy=False)
    failure_code = fields.Char(readonly=True, copy=False)
    failure_detail = fields.Text(readonly=True, copy=False)

    _capture_uuid_unique = models.Constraint(
        "UNIQUE(capture_uuid)", "A capture UUID can be used only once."
    )

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for values in vals_list:
            values = dict(values)
            values.setdefault("capture_uuid", str(uuid.uuid4()))
            if values.get("name", _("New")) == _("New"):
                values["name"] = self.env["ir.sequence"].next_by_code(
                    "mb.inventory.capture"
                ) or _("New")
            prepared.append(values)
        return super().create(prepared)

    def write(self, values):
        protected = {
            "capture_uuid", "company_id", "state", "asset_ids", "attempt_ids",
            "candidate_ids", "applied_by", "applied_at", "failure_code", "failure_detail",
        }
        if protected.intersection(values) and not _is_internal(self):
            raise UserError(_("Capture evidence and lifecycle fields cannot be edited directly."))
        if self.filtered(lambda capture: capture.state in {"applied", "cancelled"}) and not _is_internal(self):
            raise UserError(_("An applied or cancelled capture is immutable."))
        return super().write(values)

    @api.constrains("picking_id", "move_id", "move_line_id", "company_id")
    def _check_receipt_context(self):
        for capture in self:
            if capture.picking_id and capture.picking_id.picking_type_code != "incoming":
                raise ValidationError(_("A capture can only be attached to an incoming transfer."))
            if capture.move_id and capture.picking_id and capture.move_id.picking_id != capture.picking_id:
                raise ValidationError(_("The stock move does not belong to the capture receipt."))
            if capture.move_line_id and capture.move_id and capture.move_line_id.move_id != capture.move_id:
                raise ValidationError(_("The stock move line does not belong to the capture move."))

    @api.model
    def create_for_receipt(self, picking_id, move_id=False, move_line_id=False):
        picking = self.env["stock.picking"].browse(int(picking_id)).exists()
        if not picking:
            raise ValidationError(_("The receipt no longer exists."))
        picking.check_access("read")
        return self.create({
            "company_id": picking.company_id.id,
            "picking_id": picking.id,
            "move_id": int(move_id) if move_id else False,
            "move_line_id": int(move_line_id) if move_line_id else False,
        }).read(["id", "capture_uuid", "name"])[0]

    def upload_image(self, encoded, role="front", filename=None):
        self.ensure_one()
        self.check_access("write")
        if self.state != "draft":
            raise UserError(_("Images can only be added while the capture is a draft."))
        if role not in {"front", "lot_detail"}:
            raise ValidationError(_("The source image role must be front or lot detail."))
        sanitized = sanitize_image(encoded)
        existing = self.asset_ids.filtered(
            lambda asset: asset.role == role
            and asset.sanitized_sha256 == sanitized["sanitized_sha256"]
        )[:1]
        if existing:
            return existing.public_payload()
        if len(self.asset_ids.filtered(lambda asset: asset.role in {"front", "lot_detail"})) >= 2:
            raise ValidationError(_("The first release accepts at most two source images."))
        asset = _internal(self.env["mb.inventory.capture.asset"]).create({
            "capture_id": self.id,
            "company_id": self.company_id.id,
            "asset_uuid": str(uuid.uuid4()),
            "role": role,
            "mimetype": sanitized["mimetype"],
            "pixel_width": sanitized["width"],
            "pixel_height": sanitized["height"],
            "byte_length": len(sanitized["data"]),
            "received_sha256": sanitized["received_sha256"],
            "sanitized_sha256": sanitized["sanitized_sha256"],
            "sanitizer_version": "pillow-orient-strip-v1",
        })
        safe_stem = re.sub(r"[^A-Za-z0-9._-]", "_", (filename or role))[:80]
        attachment = self.env["ir.attachment"].create({
            "name": f"{safe_stem}.{sanitized['extension']}",
            "res_model": asset._name,
            "res_id": asset.id,
            "company_id": self.company_id.id,
            "mimetype": sanitized["mimetype"],
            "datas": base64.b64encode(sanitized["data"]),
        })
        _internal(asset).write({"attachment_id": attachment.id})
        return asset.public_payload()

    def action_record_scan(self, raw_value, symbology=None):
        self.ensure_one()
        if self.state not in {"draft", "review"}:
            raise UserError(_("A code cannot be added in the current capture state."))
        raw_value = str(raw_value or "").strip()
        if not raw_value or len(raw_value) > 512:
            raise ValidationError(_("The decoded value must contain between 1 and 512 characters."))
        operation_key = f"local-barcode:{self.capture_uuid}:{uuid.uuid4()}"
        attempt = _internal(self.env["mb.inventory.capture.attempt"]).create({
            "capture_id": self.id,
            "company_id": self.company_id.id,
            "attempt_uuid": str(uuid.uuid4()),
            "operation_key": operation_key,
            "kind": "barcode",
            "provider": "browser",
            "model": symbology or "unknown",
            "state": "succeeded",
            "started_at": fields.Datetime.now(),
            "ended_at": fields.Datetime.now(),
            "normalized_response": {"raw_value": raw_value, "symbology": symbology},
        })
        parsed = parse_gs1_element_string(raw_value)
        normalized = parsed.get("gtin")
        if not normalized:
            for scheme in GTIN_SCHEMES:
                try:
                    normalized = normalize_identifier(scheme, raw_value)
                    break
                except ValidationError:
                    continue
        products = self.env["product.product"]
        if normalized:
            identifiers = self.env["mb.product.identifier"].search([
                ("comparison_scheme", "=", "gtin"),
                ("normalized_value", "=", normalized),
            ])
            products |= identifiers.product_id
            for product in self.env["product.product"].search([("barcode", "!=", False)]):
                for scheme in GTIN_SCHEMES:
                    try:
                        if normalize_identifier(scheme, product.barcode) == normalized:
                            products |= product
                            break
                    except ValidationError:
                        continue
        if not products:
            try:
                lookup_candidates = self._append_lookup_candidates(
                    barcode=normalized, query=raw_value,
                )
                products |= lookup_candidates.product_id
            except UserError as error:
                parsed["warnings"].append(str(error))
        for product in products:
            _internal(self.env["mb.inventory.capture.candidate"]).create({
                "capture_id": self.id,
                "company_id": self.company_id.id,
                "attempt_id": attempt.id,
                "kind": "product",
                "raw_value": raw_value,
                "normalized_value": normalized,
                "source": "local_barcode",
                "confidence": 1.0,
                "grounding_state": "grounded",
                "product_id": product.id,
            })
        if parsed.get("lot"):
            _internal(self.env["mb.inventory.capture.candidate"]).create({
                "capture_id": self.id,
                "company_id": self.company_id.id,
                "attempt_id": attempt.id,
                "kind": "lot",
                "raw_value": parsed["lot"],
                "normalized_value": parsed["lot"],
                "source": "gs1_ai_10",
                "confidence": 1.0,
                "grounding_state": "grounded",
            })
        values = {"state": "review"}
        if len(products) == 1:
            values["product_id"] = products.id
        if parsed.get("lot"):
            values["proposed_lot"] = parsed["lot"]
        if parsed.get("quantity") is not None:
            values["proposed_quantity"] = parsed["quantity"]
        if parsed.get("expiry"):
            values["proposed_expiry"] = parsed["expiry"]
        _internal(self).write(values)
        return {
            "capture_id": self.id,
            "product_ids": products.ids,
            "gtin": normalized,
            **parsed,
        }

    def _append_lookup_candidates(self, barcode=None, query=None):
        self.ensure_one()
        results = self.env["mb.inventory.capture.lookup.provider"].lookup(
            barcode=barcode, query=query, limit=10,
        )
        if not isinstance(results, list) or not results:
            return self.env["mb.inventory.capture.candidate"]
        attempt = _internal(self.env["mb.inventory.capture.attempt"]).create({
            "capture_id": self.id,
            "company_id": self.company_id.id,
            "attempt_uuid": str(uuid.uuid4()),
            "operation_key": f"lookup:{self.capture_uuid}:{uuid.uuid4()}",
            "kind": "lookup",
            "provider": "provider-chain",
            "model": "exact-barcode-or-text",
            "state": "succeeded",
            "started_at": fields.Datetime.now(),
            "ended_at": fields.Datetime.now(),
            "normalized_response": {"result_count": len(results)},
        })
        candidates = self.env["mb.inventory.capture.candidate"]
        for result in results[:10]:
            if not isinstance(result, dict):
                continue
            raw_value = str(result.get("label") or result.get("name") or "").strip()[:255]
            normalized_value = str(result.get("canonical_id") or raw_value).strip()[:255]
            if not raw_value or not normalized_value:
                continue
            product = self.env["product.product"].browse(result.get("product_id") or 0).exists()
            candidates |= _internal(candidates).create({
                "capture_id": self.id,
                "company_id": self.company_id.id,
                "attempt_id": attempt.id,
                "kind": "product",
                "raw_value": raw_value,
                "normalized_value": normalized_value,
                "source": str(result.get("source") or "lookup")[:100],
                "confidence": max(0.0, min(float(result.get("confidence") or 0.0), 1.0)),
                "explanation": str(result.get("explanation") or "")[:2000],
                "grounding_state": "grounded" if result.get("grounded") else "unverified",
                "product_id": product.id,
            })
        return candidates

    def action_prepare_extraction(self):
        self.ensure_one()
        self.check_access("write")
        if self.state not in {"draft", "failed", "review"}:
            raise UserError(_("This capture cannot be queued for extraction."))
        source_assets = self.asset_ids.filtered(lambda asset: asset.role in {"front", "lot_detail"})
        if not source_assets:
            raise UserError(_("Add at least one image before requesting extraction."))
        _internal(self).write({"state": "processing", "failure_code": False,
                               "failure_detail": False})
        payload = {
            "capture_id": self.capture_uuid,
            "assets": [{
                "asset_id": asset.asset_uuid,
                "role": asset.role,
                "content_sha256": asset.sanitized_sha256,
            } for asset in source_assets],
            "task": "inventory_label",
            "hints": {},
        }
        workshop_id = self.company_id.mb_control_workshop_id
        if not workshop_id:
            return payload
        base_url = os.environ.get("MB_CONTROL_API_URL", "").strip().rstrip("/")
        token = os.environ.get("MB_CONTROL_BRIDGE_TOKEN", "")
        parsed_url = urlparse(base_url)
        if (parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname
                or not token):
            _internal(self).write({"state": "failed", "failure_code": "not_configured",
                                   "failure_detail": "Extraction broker is not configured."})
            raise UserError(_("The extraction broker is not configured for this workshop."))
        endpoint = urljoin(
            f"{base_url}/",
            f"internal/v1/workshops/{workshop_id}/inventory-captures",
        )
        operation_key = "inventory:%s:%s" % (
            self.capture_uuid,
            hashlib.sha256(json.dumps(payload["assets"], sort_keys=True).encode()).hexdigest(),
        )
        try:
            response = requests.post(
                endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {token}",
                         "Idempotency-Key": operation_key},
                timeout=(3.05, 10),
                allow_redirects=False,
            )
            response.raise_for_status()
            result = response.json()
            if response.status_code != 202 or not result.get("operation_id"):
                raise ValueError("broker returned an invalid acceptance response")
            return {**payload, "operation_id": result["operation_id"]}
        except requests.Timeout:
            # The durable endpoint may have accepted the idempotent operation.
            # Keep processing so the user can retry with the same operation key.
            return {**payload, "outcome": "unknown"}
        except (requests.RequestException, ValueError) as error:
            _internal(self).write({"state": "failed", "failure_code": "enqueue_failed",
                                   "failure_detail": "Extraction could not be queued."})
            raise UserError(_("The extraction request could not be queued. Try again.")) from error

    def ingest_result(self, payload):
        self.ensure_one()
        if self.state == "cancelled":
            raise ValidationError(_("A cancelled capture cannot accept extraction results."))
        if self.state not in {"processing", "review", "failed"}:
            raise ValidationError(_("The capture is not waiting for extraction results."))
        attempt_uuid = _uuid(payload.get("attempt_id"), "attempt_id")
        operation_key = str(payload.get("operation_key") or "").strip()
        if not operation_key or len(operation_key) > 255:
            raise ValidationError(_("operation_key is required and must be at most 255 characters."))
        state = payload.get("state")
        if state not in {"succeeded", "failed", "cancelled"}:
            raise ValidationError(_("The extraction result state is invalid."))
        input_digests = payload.get("input_digests") or []
        if not isinstance(input_digests, list) or not input_digests:
            raise ValidationError(_("input_digests must be a non-empty array."))
        known = set(self.asset_ids.mapped("sanitized_sha256"))
        if any(not isinstance(digest, str) or not SHA256_RE.fullmatch(digest)
               or digest not in known for digest in input_digests):
            raise ValidationError(_("The result references an unknown input digest."))
        normalized = _bounded_json(payload.get("normalized_response") or {},
                                   "normalized_response")
        raw_response = _bounded_json(payload.get("raw_response") or {}, "raw_response")
        parent = self.attempt_ids.filtered(
            lambda item: item.attempt_uuid == str(payload.get("parent_attempt_id") or "").lower()
        )[:1]
        attempt = _internal(self.env["mb.inventory.capture.attempt"]).create({
            "capture_id": self.id,
            "company_id": self.company_id.id,
            "attempt_uuid": attempt_uuid,
            "parent_attempt_id": parent.id,
            "operation_key": operation_key,
            "kind": payload.get("kind") or "ocr",
            "provider": str(payload.get("provider") or "unknown")[:128],
            "model": str(payload.get("model") or "unknown")[:128],
            "model_version": str(payload.get("model_version") or "")[:128],
            "input_asset_ids": [(6, 0, self.asset_ids.filtered(
                lambda asset: asset.sanitized_sha256 in input_digests
            ).ids)],
            "input_digests": input_digests,
            "request_id": str(payload.get("request_id") or "")[:255],
            "state": state,
            "started_at": payload.get("started_at") or fields.Datetime.now(),
            "ended_at": payload.get("ended_at") or fields.Datetime.now(),
            "raw_response": raw_response,
            "normalized_response": normalized,
            "failure_code": str(payload.get("failure_code") or "")[:128],
            "usage": _bounded_json(payload.get("usage") or {}, "usage", 4096),
        })
        if state == "succeeded":
            self._ingest_candidates(attempt, normalized.get("candidates") or [])
            _internal(self).write({"state": "review"})
        elif state == "failed":
            _internal(self).write({
                "state": "failed",
                "failure_code": attempt.failure_code or "provider_failed",
                "failure_detail": str(payload.get("failure_detail") or "")[:2000],
            })
        return {"applied": True, "capture_id": self.capture_uuid,
                "attempt_id": attempt.attempt_uuid, "state": self.state}

    def _ingest_candidates(self, attempt, candidates):
        if not isinstance(candidates, list) or len(candidates) > 30:
            raise ValidationError(_("The provider returned too many candidates."))
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValidationError(_("Every candidate must be an object."))
            kind = candidate.get("kind")
            if kind not in {"product", "lot", "expiry", "quantity"}:
                raise ValidationError(_("The provider returned an unsupported candidate kind."))
            raw_value = str(candidate.get("raw_value") or "")[:512]
            normalized_value = str(candidate.get("normalized_value") or raw_value)[:512]
            confidence = candidate.get("confidence", 0)
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) \
                    or not 0 <= confidence <= 1:
                raise ValidationError(_("Candidate confidence must be between zero and one."))
            region = candidate.get("reported_region") or []
            if region and (not isinstance(region, list) or len(region) != 4
                           or any(isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not 0 <= value <= 1 for value in region)):
                raise ValidationError(_("Candidate reported_region must be four normalized numbers."))
            _internal(self.env["mb.inventory.capture.candidate"]).create({
                "capture_id": self.id,
                "company_id": self.company_id.id,
                "attempt_id": attempt.id,
                "kind": kind,
                "raw_value": raw_value,
                "normalized_value": normalized_value,
                "source": str(candidate.get("source") or attempt.kind)[:128],
                "confidence": confidence,
                "explanation": str(candidate.get("explanation") or "")[:2000],
                "reported_region": region,
                "grounding_state": candidate.get("grounding_state", "unverified"),
            })

    def action_apply(self):
        self.ensure_one()
        if self.state != "review":
            raise UserError(_("Only a reviewed capture can be applied."))
        if not self.product_id:
            raise UserError(_("Confirm a product before applying the capture."))
        if not self.picking_id or self.picking_id.state in {"done", "cancel"}:
            raise UserError(_("Attach the capture to an open receipt before applying it."))
        if self.move_id and self.move_id.product_id != self.product_id:
            raise UserError(_(
                "The confirmed product differs from the receipt line. Reconcile the line explicitly first."
            ))
        if self.product_id.tracking != "none" and not (self.proposed_lot or self.lot_id):
            raise UserError(_("A supplier lot is required for this tracked product."))
        self.env.cr.execute("SELECT id FROM mb_inventory_capture WHERE id = %s FOR UPDATE", [self.id])
        lot = self.lot_id
        if self.product_id.tracking != "none" and not lot:
            lot_name = self.proposed_lot.strip()
            domain = [("company_id", "=", self.company_id.id),
                      ("product_id", "=", self.product_id.id), ("name", "=", lot_name)]
            lot = self.env["stock.lot"].search(domain, limit=1)
            if not lot:
                try:
                    with self.env.cr.savepoint():
                        lot = self.env["stock.lot"].create({
                            "name": lot_name,
                            "company_id": self.company_id.id,
                            "product_id": self.product_id.id,
                            "mb_supplier_lot_origin": "supplier",
                        })
                except IntegrityError:
                    lot = self.env["stock.lot"].search(domain, limit=1)
                    if not lot:
                        raise
        if lot and self.apply_expiry and self.proposed_expiry:
            lot.expiration_date = fields.Datetime.to_datetime(self.proposed_expiry)
        move_line = self.move_line_id
        if move_line:
            if move_line.move_id != self.move_id or move_line.product_id != self.product_id:
                raise UserError(_("The receipt line changed while this capture was being reviewed."))
            if lot:
                move_line.lot_id = lot
        _internal(self).write({
            "lot_id": lot.id if lot else False,
            "state": "applied",
            "applied_by": self.env.user.id,
            "applied_at": fields.Datetime.now(),
        })
        return {"type": "ir.actions.act_window_close"}

    def action_cancel(self):
        for capture in self:
            if capture.state == "applied":
                raise UserError(_("An applied capture cannot be cancelled."))
        _internal(self).write({"state": "cancelled"})
        return True

    @api.model
    def _cron_purge_unapplied_evidence(self, batch_size=100):
        parameter = self.env["ir.config_parameter"].sudo().get_param(
            "mb_inventory_capture.unapplied_image_retention_days", "30"
        )
        try:
            retention_days = max(1, min(int(parameter), 3650))
        except (TypeError, ValueError):
            retention_days = 30
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=retention_days)
        captures = self.sudo().search([
            ("state", "in", ["draft", "review", "failed", "cancelled"]),
            ("write_date", "<", cutoff),
            ("asset_ids", "!=", False),
        ], limit=max(1, min(int(batch_size), 1000)), order="write_date, id")
        purged = 0
        for capture in captures:
            assets = capture.asset_ids
            attachments = assets.attachment_id
            _internal(assets).write({"attachment_id": False})
            attachments.sudo().unlink()
            _internal(assets).unlink()
            capture.message_post(body=_(
                "Sanitized unapplied image evidence was purged after %(days)s days; "
                "structured capture audit data was retained.", days=retention_days,
            ))
            purged += len(assets)
        return purged


class InventoryCaptureAsset(models.Model):
    _name = "mb.inventory.capture.asset"
    _description = "Sanitized inventory capture image"
    _order = "id"
    _check_company_auto = True

    capture_id = fields.Many2one(
        "mb.inventory.capture", required=True, ondelete="cascade", check_company=True, index=True,
    )
    company_id = fields.Many2one("res.company", required=True, readonly=True, index=True)
    asset_uuid = fields.Char(required=True, readonly=True, index=True)
    role = fields.Selection(
        [("front", "Product/front"), ("lot_detail", "Lot detail"), ("crop", "Confirmed crop")],
        required=True, readonly=True,
    )
    attachment_id = fields.Many2one("ir.attachment", readonly=True, ondelete="restrict")
    mimetype = fields.Char(required=True, readonly=True)
    pixel_width = fields.Integer(required=True, readonly=True)
    pixel_height = fields.Integer(required=True, readonly=True)
    byte_length = fields.Integer(required=True, readonly=True)
    received_sha256 = fields.Char(required=True, readonly=True)
    sanitized_sha256 = fields.Char(required=True, readonly=True, index=True)
    sanitizer_version = fields.Char(required=True, readonly=True)
    parent_asset_id = fields.Many2one(
        "mb.inventory.capture.asset", ondelete="restrict", check_company=True, readonly=True,
    )
    crop_rectangle = fields.Json(readonly=True)

    _asset_uuid_unique = models.Constraint("UNIQUE(asset_uuid)", "An asset UUID can be used once.")
    _asset_role_digest_unique = models.Constraint(
        "UNIQUE(capture_id, role, sanitized_sha256)",
        "This sanitized image is already attached in that role.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not _is_internal(self):
            raise AccessError(_("Capture assets can only be created through the sanitizer."))
        return super().create(vals_list)

    def write(self, values):
        if not _is_internal(self):
            raise AccessError(_("Sanitized evidence assets are immutable."))
        return super().write(values)

    @api.constrains("attachment_id", "capture_id", "company_id")
    def _check_attachment_owner(self):
        for asset in self.filtered("attachment_id"):
            attachment = asset.attachment_id
            if attachment.res_model != asset._name or attachment.res_id != asset.id:
                raise ValidationError(_("The attachment must belong to its capture asset."))
            if asset.company_id != asset.capture_id.company_id:
                raise ValidationError(_("The asset and capture must belong to the same company."))

    def public_payload(self):
        self.ensure_one()
        return {"id": self.id, "asset_uuid": self.asset_uuid, "role": self.role,
                "mimetype": self.mimetype, "width": self.pixel_width,
                "height": self.pixel_height, "byte_length": self.byte_length,
                "content_sha256": self.sanitized_sha256}


class InventoryCaptureAttempt(models.Model):
    _name = "mb.inventory.capture.attempt"
    _description = "Immutable inventory extraction attempt"
    _order = "create_date, id"
    _check_company_auto = True

    capture_id = fields.Many2one(
        "mb.inventory.capture", required=True, ondelete="cascade", check_company=True, index=True,
    )
    company_id = fields.Many2one("res.company", required=True, readonly=True, index=True)
    attempt_uuid = fields.Char(required=True, readonly=True, index=True)
    parent_attempt_id = fields.Many2one(
        "mb.inventory.capture.attempt", readonly=True, ondelete="restrict", check_company=True,
    )
    operation_key = fields.Char(required=True, readonly=True, index=True)
    kind = fields.Selection(
        [("barcode", "Barcode"), ("ocr", "OCR"), ("multimodal", "Multimodal AI"),
         ("lookup", "Product lookup")], required=True, readonly=True,
    )
    provider = fields.Char(required=True, readonly=True)
    model = fields.Char(readonly=True)
    model_version = fields.Char(readonly=True)
    input_asset_ids = fields.Many2many(
        "mb.inventory.capture.asset", "mb_capture_attempt_asset_rel", "attempt_id", "asset_id",
        readonly=True,
    )
    input_digests = fields.Json(readonly=True)
    request_id = fields.Char(readonly=True)
    state = fields.Selection(
        [("queued", "Queued"), ("processing", "Processing"),
         ("succeeded", "Succeeded"), ("failed", "Failed"), ("cancelled", "Cancelled")],
        required=True, readonly=True, index=True,
    )
    started_at = fields.Datetime(readonly=True)
    ended_at = fields.Datetime(readonly=True)
    raw_response = fields.Json(readonly=True, groups="stock.group_stock_manager")
    normalized_response = fields.Json(readonly=True)
    failure_code = fields.Char(readonly=True)
    usage = fields.Json(readonly=True)

    _attempt_uuid_unique = models.Constraint(
        "UNIQUE(attempt_uuid)", "An extraction attempt UUID can be used only once."
    )
    _attempt_operation_unique = models.Constraint(
        "UNIQUE(operation_key)", "An extraction operation can be recorded only once."
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not _is_internal(self):
            raise AccessError(_("Extraction attempts can only be appended by capture services."))
        return super().create(vals_list)

    def write(self, values):
        raise AccessError(_("Extraction attempts are immutable."))


class InventoryCaptureCandidate(models.Model):
    _name = "mb.inventory.capture.candidate"
    _description = "Inventory capture candidate"
    _order = "confidence desc, id"
    _check_company_auto = True

    capture_id = fields.Many2one(
        "mb.inventory.capture", required=True, ondelete="cascade", check_company=True, index=True,
    )
    company_id = fields.Many2one("res.company", required=True, readonly=True, index=True)
    attempt_id = fields.Many2one(
        "mb.inventory.capture.attempt", required=True, ondelete="cascade", check_company=True,
    )
    kind = fields.Selection(
        [("product", "Product"), ("lot", "Lot"), ("expiry", "Expiry"),
         ("quantity", "Quantity")], required=True, readonly=True,
    )
    raw_value = fields.Char(required=True, readonly=True)
    normalized_value = fields.Char(required=True, readonly=True)
    source = fields.Char(required=True, readonly=True)
    confidence = fields.Float(required=True, readonly=True)
    explanation = fields.Text(readonly=True)
    product_id = fields.Many2one("product.product", readonly=True, check_company=True)
    evidence_asset_ids = fields.Many2many(
        "mb.inventory.capture.asset", "mb_capture_candidate_asset_rel", "candidate_id", "asset_id",
        readonly=True,
    )
    reported_region = fields.Json(readonly=True)
    grounding_state = fields.Selection(
        [("grounded", "Grounded"), ("user_confirmed_crop", "User-confirmed crop"),
         ("unverified", "Unverified")], required=True, default="unverified", readonly=True,
    )
    decision = fields.Selection(
        [("pending", "Pending"), ("accepted", "Accepted"),
         ("rejected", "Rejected"), ("edited", "Edited")], default="pending", required=True,
    )
    reviewed_value = fields.Char()
    reviewed_by = fields.Many2one("res.users", readonly=True)
    reviewed_at = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not _is_internal(self):
            raise AccessError(_("Candidates can only be appended by an extraction attempt."))
        return super().create(vals_list)

    def write(self, values):
        allowed = {"decision", "reviewed_value"}
        if set(values) - allowed and not _is_internal(self):
            raise AccessError(_("Provider candidate evidence is immutable."))
        result = super().write(values)
        if not _is_internal(self) and allowed.intersection(values):
            _internal(self).write({"reviewed_by": self.env.user.id,
                                   "reviewed_at": fields.Datetime.now()})
        return result
