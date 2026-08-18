import logging
import uuid

from werkzeug.exceptions import BadRequest, HTTPException

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from .auth import authenticate_control_request, json_body, payload_digest


_logger = logging.getLogger(__name__)
PROVIDER_BY_DELIVERY_TYPE = {
    "mb_boxtal": "boxtal",
    "mb_sendcloud": "sendcloud",
}


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
        "/mb_control/v1/webshop/status",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def webshop_status(self):
        try:
            authenticate_control_request()
            return request.make_json_response(
                request.env.company.sudo().mb_webshop_status(json_body())
            )
        except Exception as error:
            if not isinstance(error, (HTTPException, ValidationError)):
                _logger.exception("webshop status observation failed")
            return _json_error(error)

    @http.route(
        "/mb_control/v1/webshop/domain",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def project_webshop_domain(self):
        try:
            authenticate_control_request()
            body = json_body()
            operation_key = body.pop("operation_key", None)
            if not operation_key:
                raise BadRequest("operation_key is required")
            digest = payload_digest(body)
            receipts = request.env["mb.control.operation.receipt"].sudo()
            existing = receipts.for_replay(operation_key, "webshop.domain", digest)
            if existing:
                return request.make_json_response(existing.response)
            result = request.env.company.sudo().mb_project_webshop_domain(body)
            receipts.record(operation_key, "webshop.domain", digest, result)
            return request.make_json_response(result)
        except Exception as error:
            if not isinstance(error, (HTTPException, ValidationError)):
                _logger.exception("webshop domain projection failed")
            return _json_error(error)

    @http.route(
        "/mb_control/v1/carriers",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def carrier_targets(self):
        try:
            authenticate_control_request()
            carriers = request.env["delivery.carrier"].sudo().search([
                ("delivery_type", "in", tuple(PROVIDER_BY_DELIVERY_TYPE)),
                ("company_id", "!=", False),
            ])
            return request.make_json_response([
                {
                    "company_id": carrier.company_id.id,
                    "company_name": carrier.company_id.display_name,
                    "carrier_id": carrier.id,
                    "carrier_name": carrier.display_name,
                    "provider": PROVIDER_BY_DELIVERY_TYPE[carrier.delivery_type],
                    "environment": "production" if carrier.prod_environment else "test",
                    "service_code": carrier.mb_provider_service_code or "",
                    "configured": bool(carrier.mb_secret_ref),
                }
                for carrier in carriers
            ])
        except Exception as error:
            if not isinstance(error, (HTTPException, ValidationError)):
                _logger.exception("carrier target listing failed")
            return _json_error(error)

    @http.route(
        "/mb_control/v1/carriers/bind-secret",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def bind_carrier_secret(self):
        try:
            authenticate_control_request()
            body = json_body()
            workshop_id = str(body.get("workshop_id") or "")
            company = request.env["res.company"].sudo().browse(int(body.get("company_id") or 0)).exists()
            carrier = request.env["delivery.carrier"].sudo().browse(int(body.get("carrier_id") or 0)).exists()
            environment = body.get("environment")
            secret_ref = str(body.get("secret_ref") or "")
            expected_prefix = f"docker/{workshop_id}/carrier/"
            try:
                secret_id = uuid.UUID(secret_ref.removeprefix(expected_prefix))
            except (ValueError, AttributeError):
                secret_id = None
            if (
                not company
                or company.mb_control_workshop_id != workshop_id
                or not carrier
                or carrier.company_id != company
                or PROVIDER_BY_DELIVERY_TYPE.get(carrier.delivery_type) != body.get("provider")
                or environment not in ("test", "production")
                or carrier.prod_environment != (environment == "production")
                or not secret_ref.startswith(expected_prefix)
                or not secret_id
                or secret_ref != f"{expected_prefix}{secret_id}"
            ):
                raise BadRequest("carrier secret scope is invalid")
            values = {
                "mb_secret_ref": secret_ref,
                "mb_credential_state": environment,
                "mb_last_error": False,
            }
            if carrier.mb_secret_ref and carrier.mb_secret_ref != secret_ref:
                prepare_rotation = getattr(carrier, "_mb_prepare_secret_rotation", None)
                credentials = body.get("credentials")
                if credentials is not None and not isinstance(credentials, dict):
                    raise BadRequest("carrier rotation material is invalid")
                if prepare_rotation:
                    if not isinstance(credentials, dict):
                        raise BadRequest("carrier rotation material is invalid")
                    values["mb_subscription_id"] = prepare_rotation(credentials)
            carrier.with_context(mb_carrier_lifecycle_write=True).write(values)
            return request.make_json_response({"bound": True, "carrier_id": carrier.id})
        except Exception as error:
            if not isinstance(error, (HTTPException, ValidationError)):
                _logger.exception("carrier secret binding failed")
            return _json_error(error)

    @http.route(
        "/mb_control/v1/carriers/unbind-secret",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def unbind_carrier_secret(self):
        try:
            authenticate_control_request()
            body = json_body()
            workshop_id = str(body.get("workshop_id") or "")
            company = request.env["res.company"].sudo().browse(int(body.get("company_id") or 0)).exists()
            carrier = request.env["delivery.carrier"].sudo().browse(int(body.get("carrier_id") or 0)).exists()
            if (
                not company
                or company.mb_control_workshop_id != workshop_id
                or not carrier
                or carrier.company_id != company
                or PROVIDER_BY_DELIVERY_TYPE.get(carrier.delivery_type) != body.get("provider")
                or body.get("environment") not in ("test", "production")
                or carrier.prod_environment != (body.get("environment") == "production")
                or carrier.mb_secret_ref != body.get("secret_ref")
            ):
                raise BadRequest("carrier secret scope is invalid")
            carrier.with_context(mb_carrier_lifecycle_write=True).write({
                "mb_secret_ref": False,
                "mb_credential_state": "unconfigured",
                "mb_last_error": False,
            })
            return request.make_json_response({"unbound": True, "carrier_id": carrier.id})
        except Exception as error:
            if not isinstance(error, (HTTPException, ValidationError)):
                _logger.exception("carrier secret unbinding failed")
            return _json_error(error)

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
            authenticate_control_request(allow_initial_bootstrap=True)
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
        "/mb_control/v1/privacy/erasure-replay",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def replay_erasure(self):
        try:
            authenticate_control_request()
            body = json_body()
            operation_key = body.pop("operation_key", None)
            if not operation_key:
                raise BadRequest("operation_key is required")
            digest = payload_digest(body)
            receipts = request.env["mb.control.operation.receipt"].sudo()
            existing = receipts.for_replay(operation_key, "privacy.erasure_replay", digest)
            if existing:
                return request.make_json_response(existing.response)
            result = request.env["res.users"].sudo().mb_replay_erasure(body)
            receipts.record(operation_key, "privacy.erasure_replay", digest, result)
            return request.make_json_response(result)
        except Exception as error:
            if not isinstance(error, (HTTPException, ValidationError)):
                _logger.exception("erasure replay failed")
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

    @http.route(
        "/mb_control/v1/modules/enable",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def enable_modules(self):
        try:
            authenticate_control_request()
            body = json_body()
            operation_key = body.pop("operation_key", None)
            if not operation_key:
                raise BadRequest("operation_key is required")
            digest = payload_digest(body)
            receipts = request.env["mb.control.operation.receipt"].sudo()
            existing = receipts.for_replay(operation_key, "module.enable", digest)
            if existing:
                return request.make_json_response(existing.response)
            result = request.env.company.sudo().mb_enable_module_bundle(body)
            receipts.record(operation_key, "module.enable", digest, result)
            return request.make_json_response(result)
        except Exception as error:
            if not isinstance(error, (HTTPException, ValidationError)):
                _logger.exception("module enable failed")
            return _json_error(error)

    @http.route(
        "/mb_control/v1/modules/restrict",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def restrict_modules(self):
        try:
            authenticate_control_request()
            body = json_body()
            operation_key = body.pop("operation_key", None)
            if not operation_key:
                raise BadRequest("operation_key is required")
            digest = payload_digest(body)
            receipts = request.env["mb.control.operation.receipt"].sudo()
            existing = receipts.for_replay(operation_key, "module.restrict", digest)
            if existing:
                return request.make_json_response(existing.response)
            result = request.env.company.sudo().mb_restrict_module_bundle(body)
            receipts.record(operation_key, "module.restrict", digest, result)
            return request.make_json_response(result)
        except Exception as error:
            if not isinstance(error, (HTTPException, ValidationError)):
                _logger.exception("module restriction failed")
            return _json_error(error)

    @http.route(
        "/mb_control/v1/privacy/export",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def export_personal_data(self):
        try:
            authenticate_control_request()
            result = request.env["res.users"].sudo().mb_export_personal_data(json_body())
            return request.make_json_response(result)
        except Exception as error:
            if not isinstance(error, (HTTPException, ValidationError)):
                _logger.exception("privacy export failed")
            return _json_error(error)
