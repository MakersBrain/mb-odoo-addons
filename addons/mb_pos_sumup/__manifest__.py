{
    "name": "Makersbrain POS SumUp (mobile app)",
    "summary": "Take a card in the POS by handing the payment to the SumUp app on the same phone.",
    "description": """
The artisan already owns a SumUp reader and a phone. This makes the phone the
terminal: the POS hands the amount to the SumUp app over its URL scheme, the app
talks to the reader, and the callback brings the browser back with the result.
No terminal API, no IoT box, no second device.

**Why a deep link rather than the terminal API.** SumUp's server-side terminal
endpoints drive a Solo or an Air Lane - a networked reader with its own
identity. A card reader paired over Bluetooth to a phone has none, and only the
SumUp app can reach it. So the payment goes where the reader is.

**What the flow actually is.**

    POS  ──window.location──▶  sumupmerchant://pay/1.0?...&foreign-tx-id=<line uuid>
    SumUp app  ──callback──▶   /pos/ui/<config>/payment/<order uuid>?smp-status=...
    POS boots  ──▶  restores the order from IndexedDB, finds the line, finishes it

The POS page is left and reloaded, which is the part that has to be got right.
The payment line is written to IndexedDB *before* the handover, the callback
returns to the payment screen's own route so the router lands there, and the
line is found again by `foreign-tx-id` - the one parameter SumUp echoes back
unchanged. Falling back on the pending-line lookup covers SumUp app versions
older than 1.53.2, which do not echo it.

**What is trusted.** `smp-status` in the callback is a URL parameter, and a URL
parameter is a claim, not evidence. When the payment method names a SumUp
provider, the result is verified against
`GET /v2.1/merchants/{code}/transactions?foreign_transaction_id=...`, amount
currency, merchant and foreign reference included, before the line is marked
paid. A configured, enabled provider is mandatory.

Refunds do not go through the app. They are an API call against the original
transaction code, so they need the provider configured; without it the POS says
so rather than appearing to refund.

**Constraints inherited from the platform.** Android or iOS, in Safari or
Chrome. The native Odoo mobile app has no URL handling and cannot come back
from the SumUp app, and a desktop browser has no SumUp app to open.

**The affiliate key has to allow the browser.** SumUp binds a key to a list of
application identifiers, and the two platforms establish that identity
differently: Android reads the `app-id` this module sends, while the iOS URL
scheme has no such parameter at all and the SumUp app derives the caller
itself. Called from a browser it reports `com.sumup.appswitch`, so that
identifier belongs on the key next to your own - otherwise iOS opens the SumUp
app and it fails at the reader with a server error, which reads like a
connectivity fault and is not one.
""",
    "version": "19.0.1.1.0",
    "license": "LGPL-3",
    "category": "Sales/Point of Sale",
    "author": "Makersbrain",
    "depends": [
        "point_of_sale",
        # The provider holds the secret key and the merchant code that verify a
        # callback and address a refund.
        "mb_payment_sumup",
    ],
    "data": [
        "views/pos_payment_method_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "mb_pos_sumup/static/src/**/*",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
