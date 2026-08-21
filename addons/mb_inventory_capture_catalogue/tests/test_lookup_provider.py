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
            lambda item: item.source == "mb_catalogue"
        )
        self.assertEqual(result["gtin"], "04006381333931")
        self.assertEqual(candidate.normalized_value, "catalogue:mayco/sc-74/473ml")
        self.assertEqual(candidate.grounding_state, "grounded")
        self.assertFalse(candidate.product_id)
        self.assertFalse(capture.product_id)

    def test_manager_can_import_and_select_catalogue_candidate(self):
        capture = self.env["mb.inventory.capture"].create({
            "company_id": self.env.company.id,
        })
        provider = self.env["mb.inventory.capture.lookup.provider"]
        with patch.object(type(provider), "lookup", autospec=True, return_value=[{
                "canonical_id": "catalogue:mayco/sc-74/473ml",
                "label": "Mayco SC-74 Hot Tamale",
                "source": "mb_catalogue",
                "confidence": 1.0,
                "grounded": True,
        }]):
            capture.action_record_scan("4006381333931", "ean_13")
        candidate = capture.candidate_ids.filtered(
            lambda item: item.normalized_value == "catalogue:mayco/sc-74/473ml"
        )
        template = self.env["product.template"].create({
            "name": "Imported Hot Tamale", "is_storable": True,
        })
        service = self.env["mb.catalogue.service"].search([], limit=1)
        with patch.object(type(service), "action_import", autospec=True) as imported, patch.object(
            type(self.env["product.template"]), "_mb_find_by_canonical", autospec=True,
            return_value=template,
        ):
            candidate.action_import_reviewed_product()

        imported.assert_called_once_with(service, ["mayco/sc-74/473ml"])
        self.assertEqual(capture.product_id, template.product_variant_ids)
