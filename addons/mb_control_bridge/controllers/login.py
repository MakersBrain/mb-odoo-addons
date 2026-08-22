import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urljoin, urlparse

import requests
import werkzeug.urls

from odoo import SUPERUSER_ID, http
from odoo.exceptions import AccessDenied
from odoo.http import request

from odoo.addons.auth_oauth.controllers.main import (
    OAuthController as OAuthControllerBase,
)
from odoo.addons.auth_oauth.controllers.main import (
    OAuthLogin as OAuthLoginBase,
)
from odoo.addons.web.controllers.utils import _get_login_redirect_url, ensure_db

from .auth import bootstrap_credential

ATTEMPT_SESSION_KEY = "mb_oidc_login_attempts"
ATTEMPT_LIFETIME_SECONDS = 300
HTTP_TIMEOUT = (3.05, 10)
MAX_RESPONSE_BYTES = 64 * 1024
RESPONSE_CHUNK_BYTES = 8 * 1024
MAX_PENDING_ATTEMPTS = 4


def _base64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _safe_return_target(target):
    target = target or "/odoo"
    parsed = urlparse(target)
    # `/\evil.test` parses entirely into `path`, so scheme and netloc are both
    # empty and `local=True` leaves it untouched -- but browsers normalise the
    # backslash to a slash and follow `//evil.test`. Anything whose second
    # character opens an authority, by either separator, is not local.
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target[1:2] in ("/", "\\"):
        return "/odoo"
    return target


def _bounded_json(response):
    """Decode a bounded JSON object from a streamed response.

    Callers request with `stream=True`: at this point only the headers have
    been read, so a peer that omits (or lies about) `Content-Length` is cut off
    while the body is still arriving instead of after requests has already
    buffered all of it into memory.
    """
    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_RESPONSE_BYTES:
        raise AccessDenied()
    body = b""
    for chunk in response.iter_content(RESPONSE_CHUNK_BYTES):
        body += chunk
        if len(body) > MAX_RESPONSE_BYTES:
            raise AccessDenied()
    try:
        decoded = json.loads(body)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise AccessDenied() from exc
    if not isinstance(decoded, dict):
        raise AccessDenied()
    return decoded


def _pending_attempts():
    stored = request.session.get(ATTEMPT_SESSION_KEY)
    if not isinstance(stored, list):
        if stored is not None:
            request.session[ATTEMPT_SESSION_KEY] = []
        return []
    now = int(time.time())
    pending = []
    for attempt in stored:
        if not isinstance(attempt, dict):
            continue
        if (
            not isinstance(attempt.get("state"), str)
            or not attempt["state"]
            or not attempt["state"].isascii()
        ):
            continue
        created_at = attempt.get("created_at")
        # Attempts are written by this controller with an integer timestamp.
        # Reject rather than coerce corrupted session data: booleans, floats,
        # and numeric strings should not acquire a fresh interpretation here.
        if not isinstance(created_at, int) or isinstance(created_at, bool):
            continue
        if now - created_at > ATTEMPT_LIFETIME_SECONDS or created_at > now + 5:
            continue
        pending.append(attempt)
    if pending != stored:
        request.session[ATTEMPT_SESSION_KEY] = pending
    return pending


def _has_pending_attempt(state, pending=None):
    if not isinstance(state, str) or not state.isascii():
        return False
    if pending is None:
        pending = _pending_attempts()
    return any(secrets.compare_digest(attempt["state"], state) for attempt in pending)


def should_redirect_to_mb_sso(method, authenticated, params):
    return (
        method == "GET"
        and not authenticated
        and params.get("local") != "1"
        and not params.get("oauth_error")
    )


class MBLogin(OAuthLoginBase):
    def _new_code_flow_link(self, provider):
        verifier = _base64url(secrets.token_bytes(48))
        state = _base64url(secrets.token_bytes(32))
        attempt = {
            "id": _base64url(secrets.token_bytes(16)),
            "state": state,
            "nonce": _base64url(secrets.token_bytes(32)),
            "verifier": verifier,
            "created_at": int(time.time()),
            "provider_id": provider["id"],
            "return_target": _safe_return_target(request.params.get("redirect")),
        }
        # A session holds several attempts at once: `list_providers` mints one
        # per code-flow provider on every render, so a second provider -- or
        # the same login page open in another tab -- would otherwise overwrite
        # the only slot and strand every attempt but the last as oauth_error=2.
        pending = _pending_attempts()
        pending.append(attempt)
        request.session[ATTEMPT_SESSION_KEY] = pending[-MAX_PENDING_ATTEMPTS:]
        callback = urljoin(request.httprequest.url_root, "auth_oauth/signin")
        params = {
            "response_type": "code",
            "client_id": provider["client_id"],
            "redirect_uri": callback,
            "scope": provider["scope"],
            "state": state,
            "nonce": attempt["nonce"],
            "code_challenge": _base64url(hashlib.sha256(verifier.encode()).digest()),
            "code_challenge_method": "S256",
        }
        return f"{provider['auth_endpoint']}?{werkzeug.urls.url_encode(params)}"

    def list_providers(self):
        providers = super().list_providers()
        for provider in providers:
            if provider.get("mb_code_flow"):
                provider["auth_link"] = self._new_code_flow_link(provider)
        return providers

    @http.route()
    def web_login(self, *args, **kwargs):
        ensure_db()
        if should_redirect_to_mb_sso(
            request.httprequest.method,
            bool(request.session.uid),
            request.params,
        ):
            provider_id = int(
                request.env["ir.config_parameter"]
                .sudo()
                .get_param("mb_control.oidc_provider_id", "0")
                or 0
            )
            provider = next(
                (
                    candidate
                    for candidate in self.list_providers()
                    if candidate["id"] == provider_id
                ),
                None,
            )
            if provider:
                return request.redirect(provider["auth_link"], 303, local=False)
        return super().web_login(*args, **kwargs)


class MBCodeFlowController(OAuthControllerBase):
    def _consume_attempt(self, state):
        matched = None
        remaining = []
        for attempt in _pending_attempts():
            if matched is None and _has_pending_attempt(state, [attempt]):
                matched = attempt
            else:
                remaining.append(attempt)
        # Removed before anything is verified, and before any upstream request,
        # so a replayed callback finds nothing left to redeem.
        request.session[ATTEMPT_SESSION_KEY] = remaining
        now = int(time.time())
        if (
            matched is None
            or now - int(matched.get("created_at", 0)) > ATTEMPT_LIFETIME_SECONDS
            or int(matched.get("created_at", 0)) > now + 5
        ):
            raise AccessDenied()
        return matched

    def _redeem_code(self, provider, attempt, code):
        callback = urljoin(request.httprequest.url_root, "auth_oauth/signin")
        with requests.post(
            provider.mb_token_endpoint,
            data={
                "grant_type": "authorization_code",
                "client_id": provider.client_id,
                "code": code,
                "redirect_uri": callback,
                "code_verifier": attempt["verifier"],
            },
            timeout=HTTP_TIMEOUT,
            stream=True,
        ) as response:
            if not response.ok:
                raise AccessDenied()
            tokens = _bounded_json(response)
        if not all(
            isinstance(tokens.get(name), str) and tokens[name]
            for name in ("id_token", "access_token")
        ):
            raise AccessDenied()
        return tokens

    def _validate_tokens(self, attempt, tokens):
        company = request.env.company.sudo()
        workshop_id = company.mb_control_workshop_id or ""
        control_api = os.environ.get("MB_CONTROL_API_URL", "").rstrip("/")
        if not workshop_id or not control_api.startswith(("https://", "http://control.localhost:")):
            raise AccessDenied()
        endpoint = f"{control_api}/internal/v1/workshops/{workshop_id}/oidc/verify"
        try:
            credential = bootstrap_credential()
        except (OSError, UnicodeError, ValueError) as exc:
            raise AccessDenied() from exc
        if not credential:
            raise AccessDenied()
        with requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {credential}"},
            json={
                "id_token": tokens["id_token"],
                "access_token": tokens["access_token"],
                "nonce": attempt["nonce"],
            },
            timeout=HTTP_TIMEOUT,
            stream=True,
        ) as response:
            if not response.ok:
                raise AccessDenied()
            identity = _bounded_json(response)
        subject = identity.get("subject")
        if not isinstance(subject, str) or not subject or set(identity) - {"subject"}:
            raise AccessDenied()
        return subject

    def _login_existing_user(self, provider, subject, return_target):
        user = (
            request.env["res.users"]
            .with_user(SUPERUSER_ID)
            .search(
                [
                    ("active", "=", True),
                    ("mb_rauthy_subject", "=", subject),
                    ("oauth_provider_id", "=", provider.id),
                    ("oauth_uid", "=", subject),
                ]
            )
        )
        if len(user) != 1:
            raise AccessDenied()
        request.session.uid = None
        request.session["pre_login"] = user.login
        request.session["pre_uid"] = user.id
        # Same shape as `Session.authenticate`: finalize only when the user has
        # no second factor pending. Otherwise the session stays partial and
        # `_get_login_redirect_url` sends them to `_mfa_url()` carrying the
        # return target -- an external identity provider vouches for who they
        # are, not for the factor this database asks for on top.
        if not user._mfa_url():
            request.session.finalize(request.env)
        response = request.redirect(_get_login_redirect_url(user.id, return_target), 303)
        response.autocorrect_location_header = False
        return response

    @http.route()
    def signin(self, **params):
        ensure_db()
        pending = _pending_attempts()
        if not _has_pending_attempt(params.get("state"), pending):
            configured = int(
                request.env["ir.config_parameter"]
                .sudo()
                .get_param("mb_control.oidc_provider_id", "0")
                or 0
            )
            try:
                state = json.loads(params.get("state", "{}"))
            except (TypeError, ValueError):
                state = {}
            # Never let the built-in bearer/implicit callback authenticate the
            # configured MakersBrain provider, even if an attacker supplies a
            # syntactically valid auth_oauth state object.
            if configured and state.get("p") == configured:
                response = request.redirect("/web/login?oauth_error=2", 303)
                response.autocorrect_location_header = False
                return response
            return super().signin(**params)
        try:
            attempt = self._consume_attempt(params.get("state"))
            if params.get("error") or not isinstance(params.get("code"), str):
                raise AccessDenied()
            provider = (
                request.env["auth.oauth.provider"]
                .sudo()
                .browse(int(attempt["provider_id"]))
                .exists()
            )
            if not provider or not provider.enabled or not provider.mb_code_flow:
                raise AccessDenied()
            tokens = self._redeem_code(provider, attempt, params["code"])
            subject = self._validate_tokens(attempt, tokens)
            return self._login_existing_user(provider, subject, attempt["return_target"])
        except (AccessDenied, KeyError, TypeError, ValueError, requests.RequestException):
            response = request.redirect("/web/login?oauth_error=2", 303)
            response.autocorrect_location_header = False
            return response
