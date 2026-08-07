"""The picker, with the catalogue service stubbed out.

These stay offline on purpose. What is worth pinning here is the behaviour the
wizard adds - that a search imports nothing, that a product the workshop already
has cannot be imported twice, that an empty selection is refused - and none of
that is a property of the HTTP call.
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

SEARCH_RESPONSE = {
    "products": [
        {"canonical_product_id": "aaaaaaaa-0000-4000-8000-000000000001",
         "brand": "AMACO", "manufacturer_sku": "PC20", "canonical_name": "Blue Rutile",
         "family": "glaze", "firing_range": "cone 5 to cone 6", "source_count": 7,
         "min_price_per_litre": 21.90, "max_price_per_litre": 164.41},
        {"canonical_product_id": "aaaaaaaa-0000-4000-8000-000000000002",
         "brand": "AMACO", "manufacturer_sku": "PC21", "canonical_name": "Arctic Blue",
         "family": "glaze", "firing_range": None, "source_count": 3,
         "min_price_per_litre": 25.00, "max_price_per_litre": 90.00},
    ]
}

FETCH_RESPONSE = {
    "products": [
        {"canonical_product_id": "aaaaaaaa-0000-4000-8000-000000000001",
         "brand": "AMACO", "manufacturer_sku": "PC20", "canonical_name": "Blue Rutile",
         "family": "glaze", "firing_range": "cone 5 to cone 6",
         "offers": [
             {"source_id": "ceradel", "supplier_name": "Blue Rutile",
              "supplier_reference": "1425200", "price": 24.0, "currency": "EUR",
              "vat_status": "inclusive", "package_quantity": 473.0,
              "package_unit": "ml"},
         ]},
    ]
}


def fake_get(self, service, path, params=None):
    """Stands in for mb.catalogue.client._get."""
    return FETCH_RESPONSE if (params or {}).get("ids") else SEARCH_RESPONSE


@tagged("post_install", "-at_install")
class TestImportWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env["mb.catalogue.service"].create({
            "name": "Test catalogue", "base_url": "http://catalogue.test"})
        partner = cls.env["res.partner"].create({"name": "Ceradel", "is_company": True})
        cls.env["mb.catalogue.supplier"].create({
            "source_id": "ceradel", "partner_id": partner.id,
            "vat_status": "inclusive", "vat_rate": 20.0})

    def _wizard(self, query="PC-20"):
        return self.env["mb.catalogue.import"].create({
            "service_id": self.service.id, "query": query})

    def test_search_imports_nothing(self):
        wizard = self._wizard()
        with patch("odoo.addons.mb_catalogue_sync.models.mb_catalogue_client"
                   ".MbCatalogueClient._get", fake_get):
            wizard.action_search()
        self.assertEqual(len(wizard.line_ids), 2)
        self.assertEqual(
            self.env["product.template"].search_count([("mb_canonical_id", "!=", False)]), 0)

    def test_results_are_ordered_by_how_many_shops_carry_it(self):
        wizard = self._wizard()
        with patch("odoo.addons.mb_catalogue_sync.models.mb_catalogue_client"
                   ".MbCatalogueClient._get", fake_get):
            wizard.action_search()
        self.assertEqual(wizard.line_ids.mapped("manufacturer_sku"), ["PC20", "PC21"])

    def test_only_the_ticked_lines_are_imported(self):
        wizard = self._wizard()
        with patch("odoo.addons.mb_catalogue_sync.models.mb_catalogue_client"
                   ".MbCatalogueClient._get", fake_get):
            wizard.action_search()
            wizard.line_ids.filtered(lambda l: l.manufacturer_sku == "PC20").selected = True
            wizard.action_import()
        imported = self.env["product.template"].search([("mb_canonical_id", "!=", False)])
        self.assertEqual(len(imported), 1)
        self.assertEqual(imported.mb_manufacturer_sku, "PC20")

    def test_importing_nothing_is_refused_rather_than_silent(self):
        wizard = self._wizard()
        with patch("odoo.addons.mb_catalogue_sync.models.mb_catalogue_client"
                   ".MbCatalogueClient._get", fake_get):
            wizard.action_search()
            with self.assertRaises(UserError):
                wizard.action_import()

    def test_a_product_already_held_is_shown_as_held(self):
        """Rather than offered again and imported twice."""
        wizard = self._wizard()
        with patch("odoo.addons.mb_catalogue_sync.models.mb_catalogue_client"
                   ".MbCatalogueClient._get", fake_get):
            wizard.action_search()
            wizard.line_ids.filtered(lambda l: l.manufacturer_sku == "PC20").selected = True
            wizard.action_import()

            again = self._wizard()
            again.action_search()
        held = again.line_ids.filtered(lambda l: l.manufacturer_sku == "PC20")
        self.assertTrue(held.product_tmpl_id)
        self.assertEqual(held.product_tmpl_id.mb_manufacturer_sku, "PC20")
