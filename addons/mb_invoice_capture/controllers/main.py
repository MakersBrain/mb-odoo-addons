from werkzeug.exceptions import BadRequest, HTTPException

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.mb_control_bridge.controllers.auth import (
    authenticate_control_request,
    json_body,
    payload_digest,
)


class InvoiceCaptureController(http.Controller):
    @http.route(
        "/mb_control/v1/invoices/capture",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def capture(self):
        try:
            authenticate_control_request()
            body = json_body()
            operation_key = body.pop("operation_key", None)
            if not operation_key:
                raise BadRequest("operation_key is required")
            digest = payload_digest(body)
            result = (
                request.env["mb.control.operation.receipt"]
                .sudo()
                ._execute_once(
                    operation_key,
                    "invoice.capture",
                    digest,
                    lambda: request.env["mb.invoice.capture"].sudo().ingest(body),
                )
            )
            return request.make_json_response(result)
        except HTTPException as error:
            return request.make_json_response({"error": error.description}, status=error.code)
        except ValidationError as error:
            return request.make_json_response({"error": str(error)}, status=422)
