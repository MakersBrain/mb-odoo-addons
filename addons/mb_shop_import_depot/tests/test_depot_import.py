import base64
import json

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDepotShopImport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.ref("base.EUR").write({"active": True})
        cls.env.company.currency_id = cls.env.ref("base.EUR")
        cls.warehouse = cls.env["stock.warehouse"].search([
            ("company_id", "=", cls.env.company.id),
        ], limit=1)
        cls.category = cls.env["product.category"].create({"name": "Depot import test"})
        cls.source = cls.env["mb.shop.source"].create({
            "name": "Depot scraper test",
            "provider_key": "sumup",
            "source_key": "depot-test",
            "sku_prefix": "DT",
        })

    def _import(self):
        records = [
            {
                "format": "ceramics.catalogue_item.v2",
                "source": "depot-test",
                "external_id": "depot-test:piece-1",
                "name": "Imported depot piece",
                "category_path": ["Ceramiques pour la maison"],
                "price": 42.0,
                "currency": "EUR",
                "stock_quantity": 1,
                "product_url": "https://example.test/products/piece-1",
                "raw": {"variant": {"isTrackingEnabled": True}},
            },
            {
                "format": "ceramics.catalogue_item.v2",
                "source": "depot-test",
                "external_id": "depot-test:course-1",
                "name": "Imported workshop",
                "category_path": ["Cours et ateliers"],
                "price": 25.0,
                "currency": "EUR",
                "stock_quantity": None,
                "product_url": "https://example.test/products/course-1",
                "raw": {"variant": {"isTrackingEnabled": False}},
            },
        ]
        payload = "\n".join(json.dumps(record) for record in records).encode()
        batch = self.env["mb.shop.import.batch"].create({
            "source_file": base64.b64encode(payload),
            "file_name": "depot-test.ndjson",
            "source_id": self.source.id,
            "target_location_id": self.warehouse.lot_stock_id.id,
            "product_category_id": self.category.id,
            "snapshot_max_age_hours": 0,
        })
        batch.action_parse()
        batch.action_validate()
        batch.action_import_selected()
        self.assertEqual(batch.state, "done", batch.failure_detail)
        return batch

    def test_imported_products_fit_the_depot_placement_catalogue(self):
        batch = self._import()
        piece = batch.line_ids.filtered(lambda line: not line.is_service).ingested_product_id
        service = batch.line_ids.filtered("is_service").ingested_product_id
        partner = self.env["res.partner"].create({
            "name": "Imported Product Gallery", "is_company": True,
        })
        self.env["mb.depot.create"].create({
            "partner_id": partner.id,
            "commission": 40.0,
            "legal_structure": "resale",
        }).action_create()
        depot = self.env["stock.warehouse"].search([
            ("is_depot", "=", True), ("depot_partner_id", "=", partner.id),
        ])
        placement = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.int_type_id.id,
            "location_id": self.warehouse.lot_stock_id.id,
            "location_dest_id": depot.lot_stock_id.id,
        })
        catalogue = self.env["product.product"].search(placement._get_product_catalog_domain())
        self.assertIn(piece, catalogue)
        self.assertNotIn(service, catalogue)
        self.assertTrue(piece.is_storable and piece.sale_ok)
        self.assertFalse(piece.purchase_ok)
        self.assertEqual(piece.invoice_policy, "delivery")

        with self.assertRaisesRegex(ValidationError, "cannot target a depot"):
            self.env["mb.shop.import.batch"].create({
                "source_file": base64.b64encode(b"placeholder"),
                "file_name": "must-not-target-depot.ndjson",
                "source_id": self.source.id,
                "target_location_id": depot.lot_stock_id.id,
                "product_category_id": self.category.id,
            })
