import json
import logging
import time

from odoo.tests import TransactionCase, tagged


_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestLabelPosQr(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prefix = "https://instagram.com/username"
        cls.config = cls.env["pos.config"].create({"name": "Label POS"})
        cls.product = cls.env["product.product"].create({
            "name": "POS cup",
            "default_code": "POS-CUP",
            "available_in_pos": True,
            "sale_ok": True,
            "tracking": "serial",
            "is_storable": True,
        })
        cls.lot = cls.env["stock.lot"].create({
            "name": "PIECE 1",
            "product_id": cls.product.id,
            "company_id": cls.config.company_id.id,
        })
        cls.location = cls.config.picking_type_id.default_location_src_id
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.location, 1, lot_id=cls.lot)
        cls.template = cls.env["mb.label.template"].create({
            "name": "POS URL label",
            "company_id": cls.config.company_id.id,
            "width_mm": 40,
            "height_mm": 30,
            "dpi": 203,
            "qr_url_prefix": cls.prefix,
        })
        version = cls.template.save_version({"schema": 1, "elements": []})
        cls.version = cls.env["mb.label.template.version"].browse(version["id"])
        cls.alias = cls.env["mb.label.qr.alias"].mint(
            "%s#POS-CUP/PIECE%%201" % cls.prefix,
            cls.product.id,
            cls.lot.id,
            cls.version.id,
        )

    def test_alias_model_and_prefix_are_loaded_by_pos(self):
        self.assertIn("mb.label.qr.alias", self.env["pos.session"]._load_pos_data_models(self.config))
        self.assertIn(self.prefix, self.config.mb_label_qr_prefixes)
        data = self.env["mb.label.qr.alias"]._load_pos_data_search_read({}, self.config)
        row = next(item for item in data if item["id"] == self.alias.id)
        self.assertEqual(row["lot_name"], "PIECE 1")
        self.assertTrue(row["active"])
        self.assertEqual(row["pos_available_quantity"], 1)

    def test_full_pos_session_bootstrap_contains_alias_projection(self):
        session = self.env["pos.session"].create({
            "config_id": self.config.id,
            "user_id": self.env.user.id,
        })
        data = session.load_data([])
        self.assertIn("mb.label.qr.alias", data)
        row = next(item for item in data["mb.label.qr.alias"] if item["id"] == self.alias.id)
        self.assertEqual(row["value"], self.alias.value)
        self.assertIn(self.prefix, data["pos.config"][0]["mb_label_qr_prefixes"])

    def test_exact_alias_and_compatibility_path_resolve(self):
        exact = self.env["mb.label.qr.alias"].pos_resolve(self.alias.value, self.config.id)
        self.assertEqual(exact["status"], "resolved")
        self.assertEqual(exact["source"], "alias")
        self.assertEqual(exact["lot_name"], "PIECE 1")

        compatibility = self.env["mb.label.qr.alias"].pos_resolve(
            "%s#POS-CUP" % self.prefix, self.config.id)
        self.assertEqual(compatibility["status"], "resolved")
        self.assertEqual(compatibility["source"], "compatibility")
        self.assertEqual(compatibility["product_id"], self.product.id)

    def test_retired_alias_is_loaded_and_rejected(self):
        self.alias.action_retire()
        result = self.env["mb.label.qr.alias"].pos_resolve(self.alias.value, self.config.id)
        self.assertEqual(result["status"], "retired")
        rows = self.env["mb.label.qr.alias"]._load_pos_data_search_read({}, self.config)
        row = next(item for item in rows if item["id"] == self.alias.id)
        self.assertFalse(row["active"])

    def test_unknown_lot_and_unknown_product_fail_visibly(self):
        unknown_lot = self.env["mb.label.qr.alias"].pos_resolve(
            "%s#POS-CUP/UNKNOWN" % self.prefix, self.config.id)
        unknown_product = self.env["mb.label.qr.alias"].pos_resolve(
            "%s#UNKNOWN" % self.prefix, self.config.id)
        self.assertEqual(unknown_lot["status"], "unknown_lot")
        self.assertEqual(unknown_product["status"], "unknown_product")
        malformed = self.env["mb.label.qr.alias"].pos_resolve(
            "%s#POS-CUP/A/B" % self.prefix, self.config.id)
        self.assertEqual(malformed["status"], "invalid")

    def test_alias_from_another_company_is_rejected(self):
        other_company = self.env["res.company"].create({"name": "Other label company"})
        other_env = self.env["mb.label.template"].with_context(
            allowed_company_ids=[self.env.company.id, other_company.id],
        ).with_company(other_company).env
        other_template = other_env["mb.label.template"].create({
            "name": "Other company URL label",
            "company_id": other_company.id,
            "width_mm": 40,
            "height_mm": 30,
            "dpi": 203,
            "qr_url_prefix": self.prefix,
        })
        version = other_template.save_version({"schema": 1, "elements": []})
        foreign_value = "%s#POS-CUP/FOREIGN" % self.prefix
        other_env["mb.label.qr.alias"].create({
            "value": foreign_value,
            "company_id": other_company.id,
            "product_id": self.product.id,
            "template_version_id": version["id"],
        })
        result = self.env["mb.label.qr.alias"].pos_resolve(foreign_value, self.config.id)
        self.assertEqual(result["status"], "wrong_company")

    def test_zero_stock_in_pos_source_location_is_rejected(self):
        empty_product = self.env["product.product"].create({
            "name": "Empty POS cup",
            "default_code": "EMPTY-CUP",
            "available_in_pos": True,
            "sale_ok": True,
            "is_storable": True,
        })
        other_location = self.env["stock.location"].create({
            "name": "Other warehouse stock",
            "usage": "internal",
            "company_id": self.config.company_id.id,
        })
        self.env["stock.quant"]._update_available_quantity(
            empty_product, other_location, 5)
        result = self.env["mb.label.qr.alias"].pos_resolve(
            "%s#EMPTY-CUP" % self.prefix, self.config.id)
        self.assertEqual(result["status"], "out_of_stock")

    def test_ordinary_ean_is_not_claimed(self):
        result = self.env["mb.label.qr.alias"].pos_resolve("3760123456789", self.config.id)
        self.assertEqual(result["status"], "no_match")

    def test_duplicate_sku_is_ambiguous(self):
        self.env["product.product"].create({
            "name": "Duplicate POS cup",
            "default_code": "POS-CUP",
            "available_in_pos": True,
            "sale_ok": True,
        })
        result = self.env["mb.label.qr.alias"].pos_resolve(
            "%s#POS-CUP" % self.prefix, self.config.id)
        self.assertEqual(result["status"], "ambiguous")

    def test_projection_of_one_thousand_aliases_is_bounded(self):
        self.env["mb.label.qr.alias"].create([{
            "value": "%s#PERF-%04d" % (self.prefix, index),
            "company_id": self.config.company_id.id,
            "product_id": self.product.id,
            "template_version_id": self.version.id,
        } for index in range(1000)])
        session = self.env["pos.session"].create({
            "config_id": self.config.id,
            "user_id": self.env.user.id,
        })
        started = time.perf_counter()
        data = session.load_data([])
        elapsed = time.perf_counter() - started
        projection = data["mb.label.qr.alias"]
        payload_bytes = len(json.dumps(projection, default=str).encode())
        _logger.info(
            "Label POS projection benchmark: %s aliases, %s bytes, %.4f seconds",
            len(projection), payload_bytes, elapsed)
        self.assertGreaterEqual(len(projection), 1001)
        self.assertLess(payload_bytes, 1_000_000)
        self.assertLess(elapsed, 5.0)
