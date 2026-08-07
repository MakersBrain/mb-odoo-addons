"""Constants of the SumUp API, kept in one place so a change to their reference
is a change to one file.
"""

# Every SumUp endpoint used here lives under this host; the version is part of
# the endpoint because SumUp mixes v0.1 (checkouts), v1.0 (refunds) and v2.1
# (transactions) in the same API.
API_URL = "https://api.sumup.com"

# ISO 4217 codes accepted by POST /v0.1/checkouts.
# https://developer.sumup.com/api/checkouts/create - read 6 August 2026.
#
# This is the API's list, not one account's. SumUp additionally refuses a
# checkout whose currency is not the merchant country's - a French merchant
# takes EUR and nothing else, and asking for USD returns "Given currency differs
# from merchant's country currency". Narrow `available_currency_ids` on the
# provider to the currency the account actually settles in.
SUPPORTED_CURRENCIES = [
    "BGN",
    "BRL",
    "CHF",
    "CLP",
    "COP",
    "CZK",
    "DKK",
    "EUR",
    "GBP",
    "HRK",
    "HUF",
    "NOK",
    "PLN",
    "RON",
    "SEK",
    "USD",
]

# The hosted checkout presents whatever the merchant account is enabled for -
# cards, and per country wallets and APMs. Odoo needs one payment method to
# offer at checkout, and card is the one every SumUp account has.
DEFAULT_PAYMENT_METHOD_CODES = {
    "card",
}

# Status of a checkout, as returned by GET /v0.1/checkouts/{id}.
CHECKOUT_STATUS = {
    "PENDING": "pending",
    "PAID": "done",
    "FAILED": "cancel",
    "EXPIRED": "cancel",
}

# Status of a transaction, as returned by
# GET /v2.1/merchants/{code}/transactions. This is a different vocabulary from
# the checkout one above, and the POS reads it rather than the checkout status.
TRANSACTION_STATUS_SUCCESSFUL = "SUCCESSFUL"
