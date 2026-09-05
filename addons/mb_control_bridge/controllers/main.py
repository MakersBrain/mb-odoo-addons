import uuid

from werkzeug.exceptions import BadRequest, HTTPException

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from .auth import authenticate_control_request, json_body, payload_digest

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
    return request.make_json_response({"error": message}, status=status)


def _execute_once(operation_key, command, digest, action):
    return (
        request.env["mb.control.operation.receipt"]
        .sudo()
        ._execute_once(operation_key, command, digest, action)
    )


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
        except (HTTPException, ValidationError) as error:
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
            result = _execute_once(
                operation_key,
                "webshop.domain",
                digest,
                lambda: request.env.company.sudo().mb_project_webshop_domain(body),
            )
            return request.make_json_response(result)
        except (HTTPException, ValidationError) as error:
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
            carriers = (
                request.env["delivery.carrier"]
                .sudo()
                .search(
                    [
                        ("delivery_type", "in", tuple(PROVIDER_BY_DELIVERY_TYPE)),
                        ("company_id", "!=", False),
                    ]
                )
            )
            return request.make_json_response(
                [
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
                ]
            )
        except (HTTPException, ValidationError) as error:
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
            company = (
                request.env["res.company"].sudo().browse(int(body.get("company_id") or 0)).exists()
            )
            carrier = (
                request.env["delivery.carrier"]
                .sudo()
                .browse(int(body.get("carrier_id") or 0))
                .exists()
            )
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
            with request.env.cr.savepoint():
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
                response = request.make_json_response({"bound": True, "carrier_id": carrier.id})
            return response
        except (HTTPException, ValidationError) as error:
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
            company = (
                request.env["res.company"].sudo().browse(int(body.get("company_id") or 0)).exists()
            )
            carrier = (
                request.env["delivery.carrier"]
                .sudo()
                .browse(int(body.get("carrier_id") or 0))
                .exists()
            )
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
            with request.env.cr.savepoint():
                carrier.with_context(mb_carrier_lifecycle_write=True).write(
                    {
                        "mb_secret_ref": False,
                        "mb_credential_state": "unconfigured",
                        "mb_last_error": False,
                    }
                )
                response = request.make_json_response({"unbound": True, "carrier_id": carrier.id})
            return response
        except (HTTPException, ValidationError) as error:
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
            result = _execute_once(
                operation_key,
                "tenant.bootstrap",
                digest,
                lambda: request.env.company.sudo().mb_bootstrap_tenant(body),
            )
            return request.make_json_response(result)
        except (HTTPException, ValidationError) as error:
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
            return request.make_json_response(
                {
                    "status": "ready",
                    "database": request.db,
                    "workshop_id": company.mb_control_workshop_id or None,
                    "entitlement_version": company.mb_entitlement_version,
                }
            )
        except (HTTPException, ValidationError) as error:
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
            digest = payload_digest(body)
            result = _execute_once(
                operation_key,
                "membership.reconcile",
                digest,
                lambda: request.env["res.users"].sudo().mb_reconcile_membership(body),
            )
            return request.make_json_response(result)
        except (HTTPException, ValidationError) as error:
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
            result = _execute_once(
                operation_key,
                "privacy.erasure_replay",
                digest,
                lambda: request.env["res.users"].sudo().mb_replay_erasure(body),
            )
            return request.make_json_response(result)
        except (HTTPException, ValidationError) as error:
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
            result = _execute_once(
                operation_key,
                "entitlement.apply",
                digest,
                lambda: request.env.company.sudo().mb_apply_entitlement(body),
            )
            return request.make_json_response(result)
        except (HTTPException, ValidationError) as error:
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
            result = _execute_once(
                operation_key,
                "module.enable",
                digest,
                lambda: request.env.company.sudo().mb_enable_module_bundle(body),
            )
            return request.make_json_response(result)
        except (HTTPException, ValidationError) as error:
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
            result = _execute_once(
                operation_key,
                "module.restrict",
                digest,
                lambda: request.env.company.sudo().mb_restrict_module_bundle(body),
            )
            return request.make_json_response(result)
        except (HTTPException, ValidationError) as error:
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
        except (HTTPException, ValidationError) as error:
            return _json_error(error)
