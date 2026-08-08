import logging

from werkzeug.exceptions import BadRequest, HTTPException

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from .auth import authenticate_control_request, json_body, payload_digest


_logger = logging.getLogger(__name__)


def _json_error(error):
    if isinstance(error, HTTPException):
        status = error.code
        message = error.description
    elif isinstance(error, ValidationError):
        status = 422
        message = str(error)
    else:
        status = 500
        message = "internal control-plane bridge error"
    return request.make_json_response({"error": message}, status=status)


class ControlPlaneBridge(http.Controller):
    @http.route(
        "/mb_control/v1/tenant/bootstrap",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def bootstrap_tenant(self):
        try:
            authenticate_control_request()
            body = json_body()
            operation_key = body.pop("operation_key", None)
            if not operation_key:
                raise BadRequest("operation_key is required")
            digest = payload_digest(body)
            receipts = request.env["mb.control.operation.receipt"].sudo()
            existing = receipts.for_replay(operation_key, "tenant.bootstrap", digest)
            if existing:
                return request.make_json_response(existing.response)
            result = request.env.company.sudo().mb_bootstrap_tenant(body)
            receipts.record(operation_key, "tenant.bootstrap", digest, result)
            return request.make_json_response(result)
        except Exception as error:
            if not isinstance(error, (HTTPException, ValidationError)):
                _logger.exception("tenant bootstrap failed")
            return _json_error(error)

    @http.route(
        "/mb_control/v1/health",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def health(self):
        try:
            authenticate_control_request()
            company = request.env.company.sudo()
            return request.make_json_response({
                "status": "ready",
                "database": request.db,
                "workshop_id": company.mb_control_workshop_id or None,
                "entitlement_version": company.mb_entitlement_version,
            })
        except Exception as error:
            return _json_error(error)

    @http.route(
        "/mb_control/v1/memberships/reconcile",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def reconcile_membership(self):
        try:
            authenticate_control_request()
            body = json_body()
            operation_key = body.pop("operation_key", None)
            if not operation_key:
                raise BadRequest("operation_key is required")
            receipts = request.env["mb.control.operation.receipt"].sudo()
            existing = receipts.for_replay(
                operation_key, "membership.reconcile", payload_digest(body)
            )
            if existing:
                return request.make_json_response(existing.response)
            result = request.env["res.users"].sudo().mb_reconcile_membership(body)
            receipts.record(
                operation_key, "membership.reconcile", payload_digest(body), result
            )
            return request.make_json_response(result)
        except Exception as error:
            if not isinstance(error, (HTTPException, ValidationError)):
                _logger.exception("membership reconciliation failed")
            return _json_error(error)

    @http.route(
        "/mb_control/v1/entitlements/apply",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def apply_entitlement(self):
        try:
            authenticate_control_request()
            body = json_body()
            operation_key = body.pop("operation_key", None)
            if not operation_key:
                raise BadRequest("operation_key is required")
            digest = payload_digest(body)
            receipts = request.env["mb.control.operation.receipt"].sudo()
            existing = receipts.for_replay(
                operation_key, "entitlement.apply", digest
            )
            if existing:
                return request.make_json_response(existing.response)
            result = request.env.company.sudo().mb_apply_entitlement(body)
            receipts.record(operation_key, "entitlement.apply", digest, result)
            return request.make_json_response(result)
        except Exception as error:
            if not isinstance(error, (HTTPException, ValidationError)):
                _logger.exception("entitlement application failed")
            return _json_error(error)
