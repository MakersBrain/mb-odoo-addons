from odoo.addons.payment.tests.common import PaymentCommon


class SumUpCommon(PaymentCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.sumup = cls._prepare_provider(
            "sumup",
            update_values={
                "sumup_api_key": "sup_sk_dummy",
                "sumup_merchant_code": "MCTEST01",
            },
        )
        cls.provider = cls.sumup
        cls.currency = cls.currency_euro

        # What the callbacks carry: the reference this module put in the URL,
        # and nothing else worth reading.
        cls.callback_data = {"ref": cls.reference}

        cls.checkout_data = {
            "id": "cd0d6c1a-0000-4000-8000-000000000001",
            "checkout_reference": cls.reference,
            "amount": cls.amount,
            "currency": "EUR",
            "merchant_code": "MCTEST01",
            "status": "PENDING",
            "hosted_checkout_url": "https://pay.sumup.com/b2c/QWERTY",
            "transactions": [],
        }

    @classmethod
    def _paid_checkout_data(cls, transaction_id="tx_0001"):
        """Return the checkout as SumUp reports it once it has been paid."""
        return dict(
            cls.checkout_data,
            status="PAID",
            transactions=[
                {
                    "id": transaction_id,
                    "transaction_code": "TEEPUC2VLF",
                    "amount": cls.amount,
                    "currency": "EUR",
                    "status": "SUCCESSFUL",
                }
            ],
        )
