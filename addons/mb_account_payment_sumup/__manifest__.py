{
    "name": "Makersbrain Invoice Payment: SumUp link and QR code",
    "summary": "Pay an invoice by scanning it: a SumUp checkout, or the Odoo portal, as a QR code.",
    "description": """
An invoice handed over at the studio door is paid by someone holding a phone.
This turns that invoice into a payment: one button produces a link and a QR
code, the QR code prints on the PDF, and the customer pays by scanning it.

**Two destinations, because they fail differently.**

* *SumUp hosted checkout* creates the checkout up front and encodes SumUp's own
  URL. Nothing of ours is on the path between the customer and their card, so it
  works when this Odoo is behind a VPN, asleep, or simply unreachable from the
  customer's phone. Settlement arrives later, through the callback or through
  the polling cron in `mb_payment_sumup`.
* *Customer portal* encodes Odoo's own `/payment/pay` link. The customer lands
  on the invoice, sees what they are paying and can choose any enabled provider
  - but only if they can reach this instance.

The first is the default because the common case is a printed invoice and a
customer standing in a workshop.

**The link is bound to the invoice, not regenerated per view.** Odoo's
`payment.link.wizard` recomputes its URL whenever the amount changes, which is
free for a portal link and not free for a checkout: every recompute would mint
another checkout in the merchant's reporting. So the SumUp link is created by an
explicit action, stored on the invoice, and reused while it is still open.

The QR code is rendered by Odoo's own barcode endpoint, so nothing is fetched
from outside when the PDF is printed.
""",
    "version": "19.0.1.1.0",
    "license": "LGPL-3",
    "category": "Accounting/Accounting",
    "author": "Makersbrain",
    "depends": [
        "mb_payment_sumup",
        # The transaction has to know which invoice it settles, and the portal
        # link is `payment.link.wizard`'s account.move override.
        "account_payment",
    ],
    "data": [
        "security/ir.model.access.csv",
        "wizards/mb_sumup_link_wizard_views.xml",
        "views/account_move_views.xml",
        "report/mb_sumup_invoice_qr.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
