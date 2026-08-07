import pprint

from odoo import http
from odoo.http import request

from odoo.addons.payment.logging import get_payment_logger

_logger = get_payment_logger(__name__)


class SumUpController(http.Controller):
    _return_url = "/payment/sumup/return"
    _webhook_url = "/payment/sumup/webhook"

    @http.route(
        _return_url, type="http", auth="public", methods=["GET", "POST"], csrf=False,
        save_session=False,
    )
    def sumup_return_from_checkout(self, **data):
        """Process the customer's return from the SumUp-hosted checkout page.

        `save_session=False` for the reason given in every other provider's
        return route: the session cookie is set without `SameSite`, some
        browsers drop it on a cross-site POST, and Odoo would otherwise hand
        the customer a brand new session. The redirect to `/payment/status`
        satisfies any `SameSite` policy, so the original session comes back
        with it.

        :param dict data: The transaction reference (`ref`) embedded in the
                          redirect URL. Nothing else here is trusted.
        """
        _logger.info("handling redirection from SumUp with data:\n%s", pprint.pformat(data))
        self._verify_and_process(data)
        return request.redirect("/payment/status")

    @http.route(_webhook_url, type="http", auth="public", methods=["GET", "POST"], csrf=False)
    def sumup_webhook(self, **data):
        """Process the notification SumUp sends to the checkout's `return_url`.

        SumUp neither signs this notification nor puts payment evidence in it,
        so the body is not read at all: the reference comes from the URL this
        module built, and the payment data is fetched from the API with the
        merchant's own key. Forging a call to this route therefore achieves
        nothing beyond an early poll.

        :param dict data: The transaction reference (`ref`) embedded in the URL.
        :return: An empty string to acknowledge the notification.
        :rtype: str
        """
        _logger.info("notification received from SumUp with data:\n%s", pprint.pformat(data))
        self._verify_and_process(data)
        return ""  # Acknowledge the notification.

    @staticmethod
    def _verify_and_process(data):
        """Read the checkout back from SumUp and process it.

        :param dict data: The payment data holding the transaction reference.
        :return: None
        """
        tx_sudo = request.env["payment.transaction"].sudo()._search_by_reference("sumup", data)
        if not tx_sudo:
            return
        tx_sudo._sumup_poll_checkout()
