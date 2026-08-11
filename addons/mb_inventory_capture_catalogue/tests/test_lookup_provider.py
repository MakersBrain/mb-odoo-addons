from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInventoryCaptureCatalogueLookup(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["mb.catalogue.service"].create({
            "name": "Fixture catalogue",
            "base_url": "https://catalogue.example.test",
        })

    def test_exact_barcode_result_is_grounded_without_creating_product(self):
        capture = self.env["mb.inventory.capture"].create({
            "company_id": self.env.company.id,
        })
        payload = {"products": [{
            "canonical_product_id": "mayco/sc-74/473ml",
            "brand": "Mayco",
            "manufacturer_sku": "SC-74",
            "canonical_name": "Hot Tamale",
        }]}
        with patch(
            "odoo.addons.mb_catalogue_sync.models.mb_catalogue_service."
            "MbCatalogueService.action_lookup_barcode",
            return_value=payload,
        ) as lookup:
            result = capture.action_record_scan("4006381333931", "ean_13")

        lookup.assert_called_once_with("04006381333931", limit=10)
        candidate = capture.candidate_ids.filtered(
            lambda item: item.source == "makersbrain_catalogue"
        )
        self.assertEqual(result["gtin"], "04006381333931")
        self.assertEqual(candidate.normalized_value, "mayco/sc-74/473ml")
        self.assertEqual(candidate.grounding_state, "grounded")
        self.assertFalse(candidate.product_id)
        self.assertFalse(capture.product_id)
