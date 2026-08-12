import logging
import re

from odoo import http
from odoo.tools import config


_logger = logging.getLogger(__name__)
_original_db_filter = http.db_filter
_trusted_filter = re.compile(r"\^(mb_[0-9a-f]{32})\\Z")


def _gateway_db_filter(databases, host=None):
    filtered = _original_db_filter(databases, host)
    request = getattr(http, "request", None)
    http_request = getattr(request, "httprequest", None)
    if http_request is None:
        return filtered
    supplied = http_request.headers.get("X-Odoo-Dbfilter")
    if supplied is None:
        return filtered
    match = _trusted_filter.fullmatch(supplied)
    if match is None:
        _logger.warning(
            "rejecting malformed trusted database filter"
        )
        return []
    selected = match.group(1)
    return [database for database in filtered if database == selected]


if config.get("proxy_mode") and "mb_dbfilter_gateway" in config.get(
    "server_wide_modules", []
):
    _logger.info("enabling trusted MakersBrain database gateway")
    http.db_filter = _gateway_db_filter
