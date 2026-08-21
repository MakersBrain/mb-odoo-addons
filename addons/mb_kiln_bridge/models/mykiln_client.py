"""HTTP client for the JSON API used by ROHDE's myKiln service.

The endpoint set and joins between kilns, controllers and firings are:

    POST /api/v1/authenticate/       {"username": ..., "password": ...} -> token
    Authorization: Token <token>
    GET  /api/v1/kilns/              physical metadata, and a controller ref
    GET  /api/v1/controllers/        live readings
    GET  /api/v1/kiln_types/         ROHDE's own model catalogue
    GET  /api/v1/firings/?limit&offset
    GET  /api/v1/firings/<id>        one firing's detail and programme
    GET  /api/v1/firings/<id>/data   its samples, as parallel arrays

**There is no programme library to read.** Two endpoints look like one and
neither is:

* `/api/v1/programs/` answers, and returns one row per firing ever recorded -
  seventy-two rows for seventy-two firings, ids ascending with the firings.
  They are per-firing snapshots, not a library. A row carries no name and no
  slot number, only an id, two event-relay settings and, on the detail, its
  segments. Listing it tells you nothing you can label.
* `/api/v1/library_programs/` is the real library, and it is empty - the
  potter has never saved a programme into it. `library_program_name` on a
  firing is null for the same reason.

So the programme list a workshop actually fires is derived, not fetched: every
firing reports the controller slot it ran on (`program_number`) and embeds the
programme as it ran (`program.segments`). Group the firings by slot, take the
most recent one in each, and that is the current programme. It costs one
listing call plus one detail call per distinct slot rather than a call per
firing.

Deliberately free of Odoo imports: it can be exercised by tests with a fake
transport and no database. It is also read-only - there is no method here that
could start a firing or edit provider data.
"""

import logging
from datetime import datetime, timezone

import requests

_logger = logging.getLogger(__name__)

MYKILN_BASE_URL = "https://mykiln.eu"
DEFAULT_TIMEOUT = 120
FIRING_PAGE_SIZE = 100
# Asked for in one call because kiln types are a bounded lookup table, not a
# chronological feed.
KILN_TYPE_PAGE_SIZE = 1000


class MykilnError(Exception):
    """Provider did not answer usefully, including network failures.

    Network errors are wrapped into this rather than allowed to escape as
    requests exceptions. The caller records provider trouble on the connection
    and stops; a bare ReadTimeout would bypass that and reach the user as a
    traceback instead.
    """


class MykilnAuthError(MykilnError):
    """Credentials were refused. One retry, then stop - never a retry loop."""


def as_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip().replace(",", "."))
        except ValueError:
            return None
    return None


def as_str(value):
    return value if isinstance(value, str) else ""


def nested_id(record, key):
    """myKiln returns a relation as either a bare id or an object carrying one."""
    value = (record or {}).get(key)
    if isinstance(value, dict):
        return as_number(value.get("id"))
    return as_number(value)


def parse_instant(value):
    """API v1 uses ISO timestamps. An offsetless value is UTC, not local."""
    text = as_str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def results(payload):
    """Paginated list bodies, or a bare array."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return [r for r in payload["results"] if isinstance(r, dict)]
    return []


class MykilnClient:
    def __init__(self, username, password, base_url=None, timeout=DEFAULT_TIMEOUT,
                 session=None, token=None):
        self._base_url = (base_url or MYKILN_BASE_URL).rstrip("/")
        self._username = username
        self._password = password
        self._timeout = timeout
        self._session = session or requests.Session()
        # A token handed in by the caller is reused instead of logging in.
        # myKiln issues Django REST Framework tokens, which do not expire on a
        # clock, so the only thing that invalidates one is the provider
        # revoking it - handled by the single re-authentication in _get_json.
        self._token = token or None
        self._token_changed = False

    # -- transport ---------------------------------------------------------

    def count_firings(self):
        """How many firings exist, from the paginated envelope."""
        payload = self._get_json("/api/v1/firings/?limit=1&offset=0")
        count = as_number((payload or {}).get("count")) if isinstance(payload, dict) else None
        return int(count) if count is not None else 0

    def _request(self, path, method="GET", json_body=None, authenticated=True):
        headers = {
            "Accept": "application/json",
            "User-Agent": "mb-kiln-bridge/1.0",
        }
        if authenticated:
            if not self._token:
                self.login()
            headers["Authorization"] = "Token %s" % self._token
        return self._session.request(
            method, "%s%s" % (self._base_url, path),
            headers=headers, json=json_body, timeout=self._timeout,
        )

    def login(self):
        response = self._session.request(
            "POST", "%s/api/v1/authenticate/" % self._base_url,
            headers={"Accept": "application/json"},
            json={"username": self._username, "password": self._password},
            timeout=self._timeout,
        )
        body = {}
        try:
            body = response.json() or {}
        except ValueError:
            pass
        token = as_str(body.get("token"))
        if response.status_code >= 400 or not token:
            detail = as_str(body.get("detail"))
            # The password is never included, here or anywhere else.
            raise MykilnAuthError(
                detail or "login failed with status %s" % response.status_code)
        self._token = token
        self._token_changed = True

    @property
    def token(self):
        """Current token, so the caller can persist a refreshed one."""
        return self._token

    @property
    def token_changed(self):
        """True when this client had to log in, so a stored token is stale."""
        return self._token_changed

    def _get_json(self, path, _retried=False):
        try:
            response = self._request(path)
        except requests.Timeout as error:
            # Measured against the live service: the firings listing takes
            # 0.4s for five rows and 22s for fifty, and a page of two hundred
            # came back faster than one of fifty. The latency is the provider's
            # and it is erratic, so one retry is worth more than a longer wait.
            if _retried:
                raise MykilnError("%s timed out twice" % path) from error
            _logger.info("mykiln: %s timed out, retrying once", path)
            return self._get_json(path, _retried=True)
        except requests.RequestException as error:
            raise MykilnError("%s failed: %s" % (path, type(error).__name__)) from error
        if response.status_code in (401, 403):
            # Exactly one re-authentication, then give up. Repeated auth
            # failure is an unhealthy connection, not something to retry.
            self._token = None
            response = self._request(path)
            if response.status_code in (401, 403):
                raise MykilnAuthError("provider returned %s" % response.status_code)
        if response.status_code >= 400:
            raise MykilnError("GET %s returned %s" % (path, response.status_code))
        try:
            return response.json()
        except ValueError as exc:
            raise MykilnError("GET %s did not return JSON" % path) from exc

    # -- read surface ------------------------------------------------------

    def list_kilns(self):
        return results(self._get_json("/api/v1/kilns/"))

    def list_controllers(self):
        return results(self._get_json("/api/v1/controllers/"))

    def list_kiln_types(self):
        """ROHDE's catalogue of models: series, loading, voltage, phases.

        Not the workshop's kilns - every model the manufacturer sells, three
        hundred odd rows in one call. It is what turns the `model_number` on a
        kiln into a specification. Chamber volume and maximum temperature are
        not in here; they are on the kiln itself, which is the authority since
        a model can be built to more than one specification.
        """
        return results(self._get_json(
            "/api/v1/kiln_types/?limit=%s" % KILN_TYPE_PAGE_SIZE))

    def list_firings(self, limit=FIRING_PAGE_SIZE, offset=0):
        return results(self._get_json(
            "/api/v1/firings/?limit=%s&offset=%s" % (limit, offset)))

    def get_firing(self, firing_id):
        payload = self._get_json("/api/v1/firings/%s" % firing_id)
        return payload if isinstance(payload, dict) else None

    def get_firing_samples(self, firing_id):
        payload = self._get_json("/api/v1/firings/%s/data" % firing_id)
        return payload if isinstance(payload, dict) else None
