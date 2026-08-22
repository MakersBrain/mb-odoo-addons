"""Select an opaque tenant database from a header set by the trusted proxy.

Why this exists rather than Odoo's own `dbfilter`
-------------------------------------------------
Odoo resolves a database from the hostname, via `--db-filter` patterns like
`%h` or `%d`. That works when the database name is derivable from the host.
MakersBrain tenant databases are named `mb_<32 hex>` -- opaque identifiers with
no relationship to the customer's domain, which may be a custom domain the
tenant brought themselves. There is no pattern that maps one to the other, so
the mapping lives in the proxy, which already holds it in order to route.

Why trusting a header is safe here
----------------------------------
It is only safe because of three conditions, and all three are enforced:

1. `proxy_mode` is on, so Odoo is only reachable through the trusted proxy.
   Without it this module does not install its hook at all (see the bottom of
   this file).
2. The module is loaded via `server_wide_modules`, which is a deployment
   decision made in the configuration file, not something a database can turn
   on for itself.
3. The header cannot widen the result. It is intersected with whatever Odoo's
   own `db_filter` already allowed, so it can only ever narrow the set. A
   header naming a database the server would not otherwise serve yields the
   empty list, never that database.

The header carries a full anchored regex (`^mb_<32 hex>\\Z`) rather than a bare
name, because that is the shape Odoo's own `dbfilter` uses and the proxy
composes it from the same template. It is matched against a fixed pattern, not
compiled and executed, so an alternation or a wildcard in the header is a
rejection rather than a broader match.

This module patches `odoo.http.db_filter`. Patching core is normally the wrong
answer, but `db_filter` is a module-level function that Odoo resolves at call
time from a dozen call sites across `http.py` and the `web` and `auth_oauth`
controllers; there is no registry hook or inheritance seam that reaches them
all. The patch is installed once, at import, and only under the conditions
above.
"""

import logging
import re

from odoo import http
from odoo.tools import config

_logger = logging.getLogger(__name__)
_original_db_filter = http.db_filter
_trusted_filter = re.compile(r"\^(mb_[0-9a-f]{32})\\Z")


def _gateway_db_filter(databases, host=None):
    filtered = _original_db_filter(databases, host)
    # `http.request` is a werkzeug LocalProxy. Outside a request it is unbound,
    # and *attribute access on it raises RuntimeError* rather than returning a
    # getattr default -- so the guard has to test the proxy itself. Testing the
    # proxy is safe: LocalProxy.__bool__ reports False when unbound instead of
    # raising. Every current caller of db_filter runs inside a request, but a
    # cron, a CLI command or a test must not blow up in here.
    if not http.request:
        return filtered
    supplied = http.request.httprequest.headers.get("X-Odoo-Dbfilter")
    if supplied is None:
        return filtered
    match = _trusted_filter.fullmatch(supplied)
    if match is None:
        # Deliberately not logging the value: it is attacker-controlled and
        # ends up in operator log aggregation.
        _logger.warning("rejecting malformed trusted database filter")
        return []
    selected = match.group(1)
    return [database for database in filtered if database == selected]


if config.get("proxy_mode") and "mb_dbfilter_gateway" in config.get("server_wide_modules", []):
    _logger.info("enabling trusted MakersBrain database gateway")
    http.db_filter = _gateway_db_filter
