import hashlib
import re

from odoo import http
from odoo.http import request

from ..provider import ProviderError, ProviderValidationError, provider_class


IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SUBSCRIPTION = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
MAX_BODY = 256 * 1024


class CarrierWebhookController(http.Controller):

    @http.route(
        "/mb_carrier/webhook/<string:provider_code>/<string:subscription_id>",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def carrier_webhook(self, provider_code, subscription_id):
        if not IDENTIFIER.fullmatch(provider_code) or not SUBSCRIPTION.fullmatch(subscription_id):
            return request.make_json_response({"error": "not found"}, status=404)
        declared_length = request.httprequest.content_length
        if declared_length is not None and declared_length > MAX_BODY:
            return request.make_json_response({"error": "payload too large"}, status=413)
        raw_body = request.httprequest.get_data(cache=False, as_text=False)
        if not raw_body or len(raw_body) > MAX_BODY:
            return request.make_json_response({"error": "invalid payload"}, status=400)

        carrier = request.env["delivery.carrier"].sudo().search([
            ("mb_provider_code", "=", provider_code),
            ("mb_subscription_id", "=", subscription_id),
            ("mb_provider_enabled", "=", True),
        ], limit=1)
        if not carrier:
            return request.make_json_response({"error": "not found"}, status=404)
        try:
            credentials = carrier._mb_resolve_credentials(timeout=(0.35, 0.9))
            webhook_secret = credentials.get("webhook_secret", "")
            if not isinstance(webhook_secret, str) or len(webhook_secret) < 24:
                raise ProviderValidationError("webhook secret unavailable")
            provider = provider_class(provider_code)(
                credentials=credentials,
                production=bool(carrier.prod_environment),
                carrier=carrier,
            )
            if not provider.verify_webhook(
                raw_body, request.httprequest.headers, webhook_secret
            ):
                return request.make_json_response({"error": "invalid signature"}, status=401)
            event = provider.parse_webhook(raw_body)
            if not event.provider_ref or event.kind not in ("document", "tracking"):
                raise ProviderValidationError("invalid webhook envelope")
        except ProviderValidationError:
            return request.make_json_response({"error": "invalid payload"}, status=400)
        except ProviderError:
            return request.make_json_response({"error": "provider unavailable"}, status=503)
        except Exception:
            # Secret resolution failures are deliberately indistinguishable and
            # never echo credential/provider details into the response.
            return request.make_json_response({"error": "temporarily unavailable"}, status=503)

        event_key = event.event_id or hashlib.sha256(raw_body).hexdigest()
        if len(event_key) > 128:
            event_key = hashlib.sha256(event_key.encode()).hexdigest()
        request.env["mb.carrier.webhook.event"].sudo().receive(carrier, event, event_key)
        return request.make_json_response({"accepted": True}, status=202)
