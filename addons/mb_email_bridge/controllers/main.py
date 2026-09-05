from werkzeug.exceptions import HTTPException

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.mb_control_bridge.controllers.auth import (
    authenticate_control_request,
    json_body,
    payload_digest,
)


def _error(error):
    if isinstance(error, HTTPException):
        status, message = error.code, error.description
    elif isinstance(error, ValidationError):
        status, message = 422, str(error)
    return request.make_json_response({"error": message}, status=status)


class WebshopSmtpBridge(http.Controller):
    def _handle(self, operation, method):
        try:
            authenticate_control_request()
            body = json_body()
            operation_key = body.pop("operation_key", None)
            digest = payload_digest(body) if operation_key else None
            result = (
                request.env["mb.control.operation.receipt"]
                .sudo()
                ._execute_once(
                    operation_key,
                    operation,
                    digest,
                    lambda: method(request.env.company.sudo(), body),
                )
            )
            response = request.make_json_response(result)
            response.headers["Cache-Control"] = "no-store"
            return response
        except (HTTPException, ValidationError) as error:
            return _error(error)

    @http.route(
        "/mb_control/v1/webshop/smtp/status",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def status(self):
        return self._handle(
            "webshop.smtp.status", lambda company, body: company.mb_webshop_smtp_status(body)
        )

    @http.route(
        "/mb_control/v1/webshop/smtp/configure",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def configure(self):
        return self._handle(
            "webshop.smtp.configure", lambda company, body: company.mb_configure_webshop_smtp(body)
        )

    @http.route(
        "/mb_control/v1/webshop/smtp/reset",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def reset(self):
        return self._handle(
            "webshop.smtp.reset", lambda company, body: company.mb_reset_webshop_smtp(body)
        )
