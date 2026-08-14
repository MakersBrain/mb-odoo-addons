import hashlib
import hmac
import os

from werkzeug.exceptions import BadRequest, ServiceUnavailable, Unauthorized

from odoo.http import request


TOKEN_ENV = "MB_CONTROL_BRIDGE_TOKEN"
MAX_BODY_BYTES = 26 * 1024 * 1024


def credential_matches(supplied, expected_hash, bootstrap_token, allow_initial_bootstrap):
    if expected_hash:
        supplied_hash = hashlib.sha256(supplied.encode()).hexdigest()
        return hmac.compare_digest(supplied_hash, expected_hash)
    if allow_initial_bootstrap and bootstrap_token:
        return hmac.compare_digest(supplied.encode(), bootstrap_token.encode())
    return False


def authenticate_control_request(allow_initial_bootstrap=False):
    """Authenticate one internal control-plane request.

    Normal requests are checked against the selected tenant database's
    high-entropy credential verifier. The shared environment value is accepted
    only for the first bootstrap, before that verifier exists. Plaintext tenant
    credentials are never stored in an Odoo model, receipt or log.
    """
    header = request.httprequest.headers.get("Authorization", "")
    scheme, separator, supplied = header.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not supplied:
        raise Unauthorized("a bearer service credential is required")
    company = request.env.company.sudo()
    expected_hash = company.mb_control_bridge_token_hash or ""
    bootstrap_token = os.environ.get(TOKEN_ENV, "")
    if not expected_hash and allow_initial_bootstrap and not bootstrap_token:
        raise ServiceUnavailable("control-plane bootstrap credential is not configured")
    if not expected_hash and not allow_initial_bootstrap:
        raise ServiceUnavailable("tenant bridge credential is not provisioned")
    valid = credential_matches(
        supplied, expected_hash, bootstrap_token, allow_initial_bootstrap
    )
    if not valid:
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
