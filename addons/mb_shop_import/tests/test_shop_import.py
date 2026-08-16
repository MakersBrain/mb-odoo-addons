import base64
from pathlib import Path
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

from ..models.shop_import import _internal


FIXTURE = Path(__file__).parent / "fixtures" / "emily-sample.ndjson"


@tagged("post_install", "-at_install")
class TestShopImport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.eur = cls.env.ref("base.EUR")
        cls.company = cls.env.company
        cls.company.currency_id = cls.eur
        cls.source = cls.env["mb.shop.source"].search([
            ("company_id", "=", cls.company.id),
            ("provider_key", "=", "sumup"),
            ("source_key", "=", "emily-alarcon"),
        ], limit=1) or cls.env["mb.shop.source"].create({
            "name": "Emily Alarcon Ceramique",
            "company_id": cls.company.id,
            "provider_key": "sumup",
            "source_key": "emily-alarcon",
            "sku_prefix": "EA",
        })
        cls.location = cls.env["stock.warehouse"].search([
            ("company_id", "=", cls.company.id),
        ], limit=1).lot_stock_id
        cls.category = cls.env["product.category"].create({"name": "Imported finished pieces"})
        cls.payload = base64.b64encode(FIXTURE.read_bytes())

    def _batch(self, payload=None, **overrides):
        return self.env["mb.shop.import.batch"].create({
            "source_file": payload or self.payload,
            "file_name": "emily-sample.ndjson",
            "source_id": self.source.id,
            "target_location_id": self.location.id,
            "product_category_id": self.category.id,
            "snapshot_max_age_hours": 0,
            **overrides,
        })

    def _ready(self):
        batch = self._batch()
        before = self.env["product.template"].search_count([])
        batch.action_parse()
        self.assertEqual(self.env["product.template"].search_count([]), before)
        batch.action_validate()
        self.assertEqual(batch.state, "ready")
        return batch

    def test_parse_is_review_only_and_classifies_services_and_stock(self):
        batch = self._batch()
        templates_before = self.env["product.template"].search_count([])
        quants_before = self.env["stock.quant"].search_count([])
        batch.action_parse()
        self.assertEqual(batch.state, "review")
        self.assertEqual(len(batch.line_ids), 5)
        self.assertEqual(self.env["product.template"].search_count([]), templates_before)
        self.assertEqual(self.env["stock.quant"].search_count([]), quants_before)
        self.assertEqual(len(batch.line_ids.filtered("is_service")), 1)
        self.assertEqual(len(batch.line_ids.filtered("stock_is_tracked")), 3)
        self.assertEqual(batch.file_sha256, __import__("hashlib").sha256(FIXTURE.read_bytes()).hexdigest())

    def test_import_sets_product_policy_bindings_and_exact_stock(self):
        batch = self._ready()
        batch.action_import_selected()
        self.assertEqual(batch.state, "done", batch.failure_detail)
        self.assertEqual(batch.result_summary["created"], 5)
        self.assertEqual(len(batch.affected_product_tmpl_ids), 5)
        self.assertEqual(self.env["mb.shop.product.binding"].search_count([
            ("source_id", "=", self.source.id),
        ]), 5)
        physical = batch.line_ids.filtered(lambda line: not line.is_service).mapped("ingested_product_id")
        service = batch.line_ids.filtered("is_service").ingested_product_id
        self.assertTrue(all(product.company_id == self.company for product in physical | service))
        self.assertTrue(all(product.sale_ok and product.is_storable for product in physical))
        self.assertTrue(all(not product.purchase_ok for product in physical | service))
        self.assertTrue(all(product.invoice_policy == "delivery" for product in physical))
        self.assertFalse(service.is_storable)
        self.assertEqual(service.type, "service")
        bowl = batch.line_ids.filtered(lambda line: line.name == "Bol Cœur").ingested_product_id
        self.assertEqual(self.env["stock.quant"]._get_available_quantity(bowl, self.location), 1)
        blue = batch.line_ids.filtered(lambda line: line.variant_title == "Bleu").ingested_product_id
        self.assertEqual(self.env["stock.quant"]._get_available_quantity(blue, self.location), 2)
        untracked = batch.line_ids.filtered(lambda line: line.name == "Fouet matcha").ingested_product_id
        self.assertEqual(self.env["stock.quant"]._get_available_quantity(untracked, self.location), 0)

    def test_reimport_is_idempotent_and_preserves_manual_name_and_category(self):
        first = self._ready()
        first.action_import_selected()
        product = first.line_ids.filtered(lambda line: line.name == "Bol Cœur").ingested_product_id
        manual_category = self.env["product.category"].create({"name": "Manual category"})
        product.product_tmpl_id.write({"name": "My shelf name", "categ_id": manual_category.id})
        count = self.env["product.template"].search_count([])
        second = self._ready()
        second.action_import_selected()
        self.assertEqual(second.state, "done", second.failure_detail)
        self.assertEqual(second.result_summary["created"], 0)
        self.assertEqual(self.env["product.template"].search_count([]), count)
        self.assertEqual(product.product_tmpl_id.name, "My shelf name")
        self.assertEqual(product.categ_id, manual_category)

    def test_reimport_repairs_required_sale_and_depot_policy(self):
        first = self._ready()
        first.action_import_selected()
        product = first.line_ids.filtered(lambda line: line.name == "Bol Cœur").ingested_product_id
        product.product_tmpl_id.write({
            "sale_ok": False,
            "purchase_ok": True,
            "invoice_policy": "order",
        })
        forbidden_routes = self.env["stock.route"].browse()
        for xmlid in ("stock.route_warehouse0_mto", "purchase_stock.route_warehouse0_buy"):
            route = self.env.ref(xmlid, raise_if_not_found=False)
            if route:
                forbidden_routes |= route
        if forbidden_routes:
            product.product_tmpl_id.route_ids = [
                fields.Command.link(route.id) for route in forbidden_routes
            ]

        second = self._ready()
        second.action_import_selected()

        self.assertTrue(product.sale_ok)
        self.assertFalse(product.purchase_ok)
        self.assertTrue(product.is_storable)
        self.assertEqual(product.invoice_policy, "delivery")
        self.assertFalse(product.route_ids & forbidden_routes)

    def test_unselected_errors_do_not_block_valid_selected_lines(self):
        batch = self._ready()
        first, second = batch.line_ids[:2]
        second.default_code = first.default_code
        batch.action_validate()
        self.assertEqual(len(batch.line_ids.filtered(lambda line: line.validation_status == "error")), 2)
        self.assertEqual(batch.skip_count, 2)

        batch.action_import_selected()

        self.assertEqual(batch.state, "done", batch.failure_detail)
        self.assertEqual(batch.result_summary["selected"], 3)

    def test_manager_can_purge_closed_source_evidence_without_deleting_summary(self):
        batch = self._ready()
        batch.action_import_selected()
        summary = batch.result_summary

        batch.action_purge_source_evidence()

        self.assertFalse(batch.source_file)
        self.assertFalse(any(batch.line_ids.mapped("raw_record")))
        self.assertEqual(batch.result_summary, summary)

    def test_stock_change_after_preflight_is_not_overwritten(self):
        first = self._ready()
        first.action_import_selected()
        second = self._ready()
        bowl_line = second.line_ids.filtered(lambda line: line.name == "Bol Cœur")
        bowl = bowl_line.matched_product_id
        quant = self.env["stock.quant"].search([
            ("product_id", "=", bowl.id), ("location_id", "=", self.location.id),
        ], limit=1).with_context(inventory_mode=True)
        quant.inventory_quantity = 2
        quant.action_apply_inventory()
        second.action_import_selected()
        self.assertEqual(second.state, "failed")
        self.assertIn("changed after review", second.failure_detail)
        self.assertEqual(self.env["stock.quant"]._get_available_quantity(bowl, self.location), 2)

    def test_ingestion_failure_rolls_back_products_but_persists_failure(self):
        batch = self._ready()
        before = self.env["product.template"].search_count([])
        with patch.object(type(batch), "_set_stock", side_effect=ValidationError("synthetic failure")):
            batch.action_import_selected()
        self.assertEqual(batch.state, "failed")
        self.assertIn("synthetic failure", batch.failure_detail)
        self.assertEqual(self.env["product.template"].search_count([]), before)
        self.assertFalse(self.env["mb.shop.product.binding"].search([
            ("source_id", "=", self.source.id),
        ]))

    def test_unexpected_image_failure_does_not_undo_product_ingestion(self):
        batch = self._batch()
        batch.import_images = True
        batch.action_parse()
        batch.action_validate()
        with patch(
            "odoo.addons.mb_shop_import.models.shop_import.fetch_image",
            side_effect=RuntimeError("secret internal endpoint"),
        ):
            batch.action_import_selected()

        self.assertEqual(batch.state, "done", batch.failure_detail)
        self.assertEqual(batch.result_summary["created"], 5)
        failed = batch.line_ids.filtered(lambda line: line.image_status == "failed")
        self.assertTrue(failed)
        self.assertTrue(all("secret internal endpoint" not in line.image_failure for line in failed))

    def test_edit_invalidates_preflight_and_warning_acknowledgement(self):
        batch = self._ready()
        line = batch.line_ids[0]
        line.name = "Reviewed name"
        self.assertEqual(batch.state, "review")
        self.assertFalse(batch.validated_at)
        self.assertEqual(line.validation_status, "new")

    def test_reviewer_cannot_confirm_business_writes(self):
        batch = self._ready()
        reviewer = new_test_user(
            self.env,
            login="shop-reviewer-no-ingest",
            groups="mb_shop_import.group_shop_import_reviewer",
            company_id=self.company.id,
            company_ids=[fields.Command.set(self.company.ids)],
        )
        with self.assertRaisesRegex(AccessError, "Shop Import Manager"):
            batch.with_user(reviewer).action_import_selected()

    def test_reviewer_can_explicitly_match_a_company_product(self):
        product = self.env["product.product"].create({
            "name": "Existing shelf piece",
            "default_code": "MANUAL-MATCH",
            "company_id": self.company.id,
        })
        batch = self._batch()
        batch.action_parse()
        line = batch.line_ids[0]
        line.manual_product_id = product

        batch.action_validate()

        self.assertEqual(line.matched_product_id, product)
        self.assertEqual(line.match_method, "manual")
        self.assertEqual(line.proposed_action, "update")

    def test_stale_snapshot_policy_can_block_or_require_acknowledgement(self):
        batch = self._batch(snapshot_max_age_hours=1, snapshot_stale_policy="block")
        batch.action_parse()
        batch.action_validate()
        tracked = batch.line_ids.filtered(
            lambda line: line.stock_is_tracked and not line.is_service
        )
        self.assertTrue(all(line.validation_status == "error" for line in tracked))

        batch.snapshot_stale_policy = "warn"
        batch.action_validate()

        self.assertTrue(all(line.validation_status == "warning" for line in tracked))

    def test_tax_preview_uses_odoo_tax_for_included_and_excluded_prices(self):
        tax = self.env["account.tax"].create({
            "name": "Shop import 20%",
            "amount": 20.0,
            "amount_type": "percent",
            "type_tax_use": "sale",
            "company_id": self.company.id,
        })
        included = self._batch(
            price_tax_basis="tax_included",
            sales_tax_ids=[fields.Command.set([tax.id])],
        )
        included.action_parse()
        included.action_validate()
        included_line = included.line_ids.filtered(lambda line: line.name == "Bol Cœur")
        self.assertEqual(included_line.proposed_customer_price, 28.0)
        self.assertEqual(included_line.proposed_list_price, 23.33)

        excluded = self._batch(
            price_tax_basis="tax_excluded",
            sales_tax_ids=[fields.Command.set([tax.id])],
        )
        excluded.action_parse()
        excluded.action_validate()
        excluded_line = excluded.line_ids.filtered(lambda line: line.name == "Bol Cœur")
        self.assertEqual(excluded_line.proposed_list_price, 28.0)
        self.assertEqual(excluded_line.proposed_customer_price, 33.6)

    def test_company_rules_hide_sources_batches_lines_and_bindings(self):
        other = self.env["res.company"].create({"name": "Other shop-import workshop"})
        source = self.env["mb.shop.source"].with_company(other).create({
            "name": "Other source",
            "company_id": other.id,
            "provider_key": "sumup",
            "source_key": "other-shop",
            "sku_prefix": "OS",
        })
        batch = self.env["mb.shop.import.batch"].with_company(other).create({
            "company_id": other.id,
            "file_name": "other.ndjson",
            "source_id": source.id,
        })
        line = _internal(self.env["mb.shop.import.line"].with_company(other)).create({
            "batch_id": batch.id,
            "sequence": 1,
            "external_id": "other:one",
            "name": "Other piece",
            "default_code": "OS-ONE",
            "source_price": 1.0,
            "currency_id": other.currency_id.id,
        })
        product = self.env["product.product"].with_company(other).create({
            "name": "Other bound piece",
            "company_id": other.id,
        })
        binding = _internal(self.env["mb.shop.product.binding"].with_company(other)).create({
            "source_id": source.id,
            "external_id": "other:one",
            "product_id": product.id,
        })
        user = new_test_user(
            self.env,
            login="single-company-shop-reviewer",
            groups="mb_shop_import.group_shop_import_reviewer",
            company_id=self.company.id,
            company_ids=[fields.Command.set(self.company.ids)],
        )
        for record in (source, batch, line, binding):
            restricted = record.with_user(user).with_context(
                allowed_company_ids=[self.company.id]
            )
            self.assertFalse(restricted.search([("id", "=", record.id)]))
