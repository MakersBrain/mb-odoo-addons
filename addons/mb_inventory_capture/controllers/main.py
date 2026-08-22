import base64
import logging

from werkzeug.exceptions import BadRequest, Conflict, Gone, HTTPException, NotFound

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.mb_control_bridge.controllers.auth import (
    authenticate_control_request,
    json_body,
    payload_digest,
)

_logger = logging.getLogger(__name__)


def _error(error):
    if isinstance(error, HTTPException):
        return request.make_json_response({"error": error.description}, status=error.code)
    if isinstance(error, ValidationError):
        return request.make_json_response({"error": str(error)}, status=422)
    _logger.exception("inventory capture control route failed")
    return request.make_json_response({"error": "internal inventory-capture error"}, status=500)


def _company_capture(capture_uuid):
    capture = (
        request.env["mb.inventory.capture"]
        .sudo()
        .search(
            [
                ("capture_uuid", "=", capture_uuid),
                ("company_id", "=", request.env.company.id),
            ],
            limit=1,
        )
    )
    if not capture:
        raise NotFound("capture not found")
    return capture


class InventoryCaptureController(http.Controller):
    @http.route(
        "/mb_control/v1/inventory-captures/<string:capture_uuid>/assets/<string:asset_uuid>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def asset(self, capture_uuid, asset_uuid):
        try:
            authenticate_control_request()
            capture = _company_capture(capture_uuid)
            if capture.state == "cancelled":
                raise Gone("capture was cancelled")
            if capture.state != "processing":
                raise Conflict("capture is not processing")
            asset = capture.asset_ids.filtered(lambda item: item.asset_uuid == asset_uuid)[:1]
            if not asset or not asset.attachment_id:
                raise NotFound("asset not found")
            encoded = asset.attachment_id.with_context(bin_size=False).datas
            try:
                content = base64.b64decode(encoded, validate=True)
            except Exception as error:
                raise Conflict("stored sanitized asset is corrupt") from error
            if len(content) != asset.byte_length:
                raise Conflict("stored asset length does not match its evidence record")
            return request.make_response(
                content,
                headers=[
                    ("Content-Type", asset.mimetype),
                    ("Content-Length", str(asset.byte_length)),
                    ("Digest", f"sha-256={asset.sanitized_sha256}"),
                    ("X-Content-SHA256", asset.sanitized_sha256),
                    ("Cache-Control", "no-store"),
                    ("Content-Disposition", f'attachment; filename="{asset.asset_uuid}"'),
                    ("X-Content-Type-Options", "nosniff"),
                ],
            )
        except Exception as error:
            return _error(error)

    @http.route(
        "/mb_control/v1/inventory-captures/results",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def result(self):
        try:
            authenticate_control_request()
            body = json_body()
            operation_key = body.get("operation_key")
            if not isinstance(operation_key, str) or not operation_key:
                raise BadRequest("operation_key is required")
            capture_uuid = body.get("capture_id")
            if not isinstance(capture_uuid, str) or not capture_uuid:
                raise BadRequest("capture_id is required")
            capture = _company_capture(capture_uuid)
            digest = payload_digest(body)
            receipts = request.env["mb.control.operation.receipt"].sudo()
            replay = receipts.for_replay(operation_key, "inventory.capture.result", digest)
            if replay:
                return request.make_json_response(replay.response)
            response = capture.ingest_result(body)
            try:
                with request.env.cr.savepoint():
                    receipts.record(operation_key, "inventory.capture.result", digest, response)
            except Exception:
                replay = receipts.for_replay(operation_key, "inventory.capture.result", digest)
                if not replay:
                    raise
                response = replay.response
            return request.make_json_response(response)
        except Exception as error:
            return _error(error)
