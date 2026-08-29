{
    "name": "MakersBrain Payment Provider: SumUp",
    "summary": "SumUp as an Odoo payment provider: hosted checkouts, links and QR codes.",
    "description": """
SumUp is the card acquirer an artisan already has, because the reader costs
thirty euros and there is no monthly fee. Odoo ships providers for Adyen,
Stripe, Mollie and a dozen others, and none for SumUp, so this addon adds it.

It uses the **hosted checkout**: one POST to `/v0.1/checkouts` with
`hosted_checkout.enabled` returns a `hosted_checkout_url` that SumUp operates -
card form, 3-D Secure, wallets, receipt - and Odoo never sees a card number.
That is the same shape as `payment_mollie`, and it is deliberate: an inline form
would put this database inside the cardholder-data environment, which is not
where a ceramics workshop belongs.

Two things about SumUp's callbacks decide the design here:

* `return_url` is a *backend* notification, unsigned and without payment
  evidence. So the controller uses it only as a wake-up: it reads the checkout
  back from the API with the merchant's own key before anything is settled.
  Nothing a caller puts in the request body can move an invoice.
* A checkout can be paid without anyone returning to Odoo at all - the QR code
  on a printed invoice is exactly that case. So a cron re-reads pending
  checkouts, and the callback becomes an optimisation rather than a
  requirement.

Credentials are the workshop's own secret key and merchant code, held on the
provider record. There is no deployment-wide key: money settles into the account
named on the request, and that account has to be the one whose name is printed
on the facture.

Refunds go to `/v1.0/merchants/{code}/payments/{id}/refunds`, which SumUp
acknowledges before settlement. Odoo keeps the refund pending and polls the
authoritative transaction events before marking it done.
""",
    "version": "19.0.1.1.1",
    "license": "AGPL-3",
    "category": "Accounting/Payment Providers",
    "author": "MakersBrain",
    "website": "https://sumup.com",
    "depends": [
        "payment",
    ],
    "data": [
        "views/payment_sumup_templates.xml",
        "views/payment_provider_views.xml",
        "views/payment_transaction_views.xml",
        "data/payment_provider_data.xml",
        "data/mb_payment_sumup_cron.xml",
    ],
    "post_init_hook": "post_init_hook",
    "uninstall_hook": "uninstall_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
