import json
import logging
import time
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestLabelPosQr(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prefix = "https://instagram.com/username"
        cls.config = cls.env["pos.config"].create({"name": "Label POS"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "POS cup",
                "default_code": "POS-CUP",
                "available_in_pos": True,
                "sale_ok": True,
                "tracking": "serial",
                "is_storable": True,
            }
        )
        cls.lot = cls.env["stock.lot"].create(
            {
                "name": "PIECE 1",
                "product_id": cls.product.id,
                "company_id": cls.config.company_id.id,
            }
        )
        cls.location = cls.config.picking_type_id.default_location_src_id
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.location, 1, lot_id=cls.lot
        )
        cls.template = cls.env["mb.label.template"].create(
            {
                "name": "POS URL label",
                "company_id": cls.config.company_id.id,
                "width_mm": 40,
                "height_mm": 30,
                "dpi": 203,
                "qr_url_prefix": cls.prefix,
            }
        )
        version = cls.template.save_version({"schema": 1, "elements": []})
        cls.version = cls.env["mb.label.template.version"].browse(version["id"])
        cls.alias = cls.env["mb.label.qr.alias"].mint(
            "%s#POS-CUP/PIECE%%201" % cls.prefix,
            cls.product.id,
            cls.lot.id,
            cls.version.id,
        )

    def test_alias_model_and_prefix_are_loaded_by_pos(self):
        self.assertIn(
            "mb.label.qr.alias", self.env["pos.session"]._load_pos_data_models(self.config)
        )
        self.assertIn(self.prefix, self.config.mb_label_qr_prefixes)
        data = self.env["mb.label.qr.alias"]._load_pos_data_search_read({}, self.config)
        row = next(item for item in data if item["id"] == self.alias.id)
        self.assertEqual(row["lot_name"], "PIECE 1")
        self.assertTrue(row["active"])
        self.assertEqual(row["pos_available_quantity"], 1)

    def test_full_pos_session_bootstrap_contains_alias_projection(self):
        session = self.env["pos.session"].create(
            {
                "config_id": self.config.id,
                "user_id": self.env.user.id,
            }
        )
        data = session.load_data([])
        self.assertIn("mb.label.qr.alias", data)
        row = next(item for item in data["mb.label.qr.alias"] if item["id"] == self.alias.id)
        self.assertEqual(row["value"], self.alias.value)
        self.assertIn(self.prefix, data["pos.config"][0]["mb_label_qr_prefixes"])

    def test_cashier_can_bootstrap_company_scoped_label_data(self):
        cashier = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Label POS cashier",
                    "login": "label-pos-cashier",
                    "company_id": self.config.company_id.id,
                    "company_ids": [(6, 0, self.config.company_id.ids)],
                    "group_ids": [
                        (
                            6,
                            0,
                            [
                                self.env.ref("base.group_user").id,
                                self.env.ref("point_of_sale.group_pos_user").id,
                            ],
                        )
                    ],
                }
            )
        )
        self.assertFalse(cashier.has_group("mb_label.group_mb_label_user"))
        session = self.env["pos.session"].create(
            {
                "config_id": self.config.id,
                "user_id": cashier.id,
            }
        )

        data = session.with_user(cashier).load_data([])

        self.assertIn(self.prefix, data["pos.config"][0]["mb_label_qr_prefixes"])
        self.assertIn(self.alias.id, [row["id"] for row in data["mb.label.qr.alias"]])

    def test_exact_alias_resolves(self):
        exact = self.env["mb.label.qr.alias"].pos_resolve(self.alias.value, self.config.id)
        self.assertEqual(exact["status"], "resolved")
        self.assertEqual(exact["source"], "alias")
        self.assertEqual(exact["lot_name"], "PIECE 1")

    def test_retired_alias_is_loaded_and_rejected(self):
        self.alias.action_retire()
        result = self.env["mb.label.qr.alias"].pos_resolve(self.alias.value, self.config.id)
        self.assertEqual(result["status"], "retired")
        rows = self.env["mb.label.qr.alias"]._load_pos_data_search_read({}, self.config)
        row = next(item for item in rows if item["id"] == self.alias.id)
        self.assertFalse(row["active"])

    def test_unknown_alias_does_not_resolve_from_its_payload(self):
        result = self.env["mb.label.qr.alias"].pos_resolve(
            "%s#POS-CUP/UNKNOWN" % self.prefix, self.config.id
        )
        self.assertEqual(result["status"], "no_match")

    def test_alias_from_another_company_is_rejected(self):
        other_company = self.env["res.company"].create({"name": "Other label company"})
        other_env = (
            self.env["mb.label.template"]
            .with_context(
                allowed_company_ids=[self.env.company.id, other_company.id],
            )
            .with_company(other_company)
            .env
        )
        other_template = other_env["mb.label.template"].create(
            {
                "name": "Other company URL label",
                "company_id": other_company.id,
                "width_mm": 40,
                "height_mm": 30,
                "dpi": 203,
                "qr_url_prefix": self.prefix,
            }
        )
        version = other_template.save_version({"schema": 1, "elements": []})
        foreign_value = "%s#POS-CUP/FOREIGN" % self.prefix
        other_env["mb.label.qr.alias"].create(
            {
                "value": foreign_value,
                "company_id": other_company.id,
                "product_id": self.product.id,
                "template_version_id": version["id"],
            }
        )
        result = self.env["mb.label.qr.alias"].pos_resolve(foreign_value, self.config.id)
        self.assertEqual(result["status"], "wrong_company")

    def test_zero_stock_in_pos_source_location_is_rejected(self):
        empty_product = self.env["product.product"].create(
            {
                "name": "Empty POS cup",
                "default_code": "EMPTY-CUP",
                "available_in_pos": True,
                "sale_ok": True,
                "is_storable": True,
            }
        )
        other_location = self.env["stock.location"].create(
            {
                "name": "Other warehouse stock",
                "usage": "internal",
                "company_id": self.config.company_id.id,
            }
        )
        self.env["stock.quant"]._update_available_quantity(empty_product, other_location, 5)
        empty_alias = self.env["mb.label.qr.alias"].create(
            {
                "value": "%s#EMPTY-CUP" % self.prefix,
                "company_id": self.config.company_id.id,
                "product_id": empty_product.id,
                "template_version_id": self.version.id,
            }
        )
        result = self.env["mb.label.qr.alias"].pos_resolve(empty_alias.value, self.config.id)
        self.assertEqual(result["status"], "out_of_stock")

    def test_ordinary_ean_is_not_claimed(self):
        result = self.env["mb.label.qr.alias"].pos_resolve("3760123456789", self.config.id)
        self.assertEqual(result["status"], "no_match")

    def test_projection_of_one_thousand_aliases_is_bounded(self):
        self.env["mb.label.qr.alias"].create(
            [
                {
                    "value": "%s#PERF-%04d" % (self.prefix, index),
                    "company_id": self.config.company_id.id,
                    "product_id": self.product.id,
                    "template_version_id": self.version.id,
                }
                for index in range(1000)
            ]
        )
        session = self.env["pos.session"].create(
            {
                "config_id": self.config.id,
                "user_id": self.env.user.id,
            }
        )
        started = time.perf_counter()
        data = session.load_data([])
        elapsed = time.perf_counter() - started
        projection = data["mb.label.qr.alias"]
        payload_bytes = len(json.dumps(projection, default=str).encode())
        _logger.info(
            "Label POS projection benchmark: %s aliases, %s bytes, %.4f seconds",
            len(projection),
            payload_bytes,
            elapsed,
        )
        self.assertGreaterEqual(len(projection), 1001)
        self.assertLess(payload_bytes, 1_000_000)
        self.assertLess(elapsed, 5.0)

    def test_projection_batches_stock_availability(self):
        aliases = self.env["mb.label.qr.alias"].create(
            [
                {
                    "value": "%s#BATCH-%04d" % (self.prefix, index),
                    "company_id": self.config.company_id.id,
                    "product_id": self.product.id,
                    "lot_id": self.lot.id,
                    "template_version_id": self.version.id,
                }
                for index in range(20)
            ]
        )
        alias_model = self.env["mb.label.qr.alias"]
        quant_model_class = type(self.env["stock.quant"])
        original_read_group = quant_model_class._read_group
        with patch.object(
            quant_model_class,
            "_read_group",
            autospec=True,
            side_effect=original_read_group,
        ) as read_group:
            rows = alias_model._load_pos_data_read(aliases, self.config)

        self.assertEqual(read_group.call_count, 1)
        self.assertEqual({row["pos_available_quantity"] for row in rows}, {1.0})
