from unittest.mock import patch

from odoo import http
from odoo.tests import TransactionCase, tagged

from odoo.addons.mb_dbfilter_gateway import override

TENANT = "mb_" + "a" * 32
OTHER = "mb_" + "b" * 32
SERVED = [TENANT, OTHER, "mb_odoo"]


class FakeHttpRequest:
    def __init__(self, headers):
        self.headers = headers


class FakeRequest:
    def __init__(self, headers):
        self.httprequest = FakeHttpRequest(headers)


@tagged("post_install", "-at_install")
class TestTrustedDatabaseGateway(TransactionCase):
    """The gateway narrows Odoo's own db_filter; it must never widen it.

    `_original_db_filter` is stubbed to a passthrough throughout. The subject
    here is the header handling this module adds, not Odoo's dbfilter, and
    binding the real one would make these assertions depend on the test
    runner's own --db-filter configuration.
    """

    def _filter(self, headers, databases=None):
        with (
            patch.object(override, "_original_db_filter", lambda dbs, host: list(dbs)),
            patch.object(http, "request", FakeRequest(headers)),
        ):
            return override._gateway_db_filter(
                SERVED if databases is None else databases, host="shop.example.fr"
            )

    def test_no_bound_request_is_not_an_error(self):
        """db_filter is reachable outside a request; the hook must not raise.

        `http.request` is an unbound LocalProxy there, and attribute access on
        it raises RuntimeError rather than returning a getattr default. The
        guard has to test the proxy, not getattr through it.
        """
        with patch.object(override, "_original_db_filter", lambda dbs, host: list(dbs)):
            self.assertEqual(override._gateway_db_filter(SERVED, host="shop.example.fr"), SERVED)

    def test_absent_header_leaves_the_filter_untouched(self):
        self.assertEqual(self._filter({}), SERVED)

    def test_well_formed_header_selects_exactly_one_database(self):
        self.assertEqual(self._filter({"X-Odoo-Dbfilter": f"^{TENANT}\\Z"}), [TENANT])

    def test_header_cannot_widen_beyond_what_odoo_already_allowed(self):
        """The intersection is the whole security argument: a header naming a
        database this server does not serve yields nothing, not that database.
        """
        self.assertEqual(self._filter({"X-Odoo-Dbfilter": f"^{TENANT}\\Z"}, databases=[OTHER]), [])

    def test_malformed_headers_are_rejected_outright(self):
        for label, value in [
            ("unanchored bare name", TENANT),
            ("missing start anchor", f"{TENANT}\\Z"),
            ("missing end anchor", f"^{TENANT}"),
            ("wildcard", "^mb_.*\\Z"),
            ("character class", "^mb_[0-9a-f]{32}\\Z"),
            ("alternation of two tenants", f"^{TENANT}\\Z|^{OTHER}\\Z"),
            ("too short", "^mb_" + "a" * 31 + "\\Z"),
            ("too long", "^mb_" + "a" * 33 + "\\Z"),
            ("uppercase hex", "^mb_" + "A" * 32 + "\\Z"),
            ("wrong prefix", "^other_" + "a" * 32 + "\\Z"),
            ("trailing newline", f"^{TENANT}\\Z\n"),
            ("empty", ""),
        ]:
            with self.subTest(header=label):
                self.assertEqual(
                    self._filter({"X-Odoo-Dbfilter": value}),
                    [],
                    f"{label!r} must be rejected, not matched",
                )
