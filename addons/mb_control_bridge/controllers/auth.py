import hashlib
import hmac
import os

from werkzeug.exceptions import BadRequest, ServiceUnavailable, Unauthorized

from odoo.http import request


TOKEN_ENV = "MB_CONTROL_BRIDGE_TOKEN"
MAX_BODY_BYTES = 26 * 1024 * 1024


def authenticate_control_request():
    """Authenticate one internal control-plane request.

    The shared value is injected into the tenant container. It is never stored
    in an Odoo model, job payload or log. A reverse proxy may add mTLS later;
    this check remains the application-level tenant credential.
    """
    expected = os.environ.get(TOKEN_ENV, "")
    if not expected:
        raise ServiceUnavailable("control-plane bridge is not configured")
    header = request.httprequest.headers.get("Authorization", "")
    scheme, separator, supplied = header.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not supplied:
        raise Unauthorized("a bearer service credential is required")
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise Unauthorized("invalid service credential")


def json_body():
    length = request.httprequest.content_length
    if length is not None and length > MAX_BODY_BYTES:
        raise BadRequest("request body exceeds the control-plane limit")
    try:
        body = request.get_json_data()
    except Exception as exc:
        raise BadRequest("request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise BadRequest("request body must be a JSON object")
    return body


def payload_digest(payload):
    import json

    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(canonical).hexdigest()
