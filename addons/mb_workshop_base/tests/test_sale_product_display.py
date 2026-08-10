from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import format_amount


@tagged("post_install", "-at_install")
class TestSaleProductDisplay(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_template = cls.env["product.template"].create({
            "name": "Custom cup",
            "default_code": "CUP-CUSTOM",
            "list_price": 50.0,
        })
        cls.product = cls.product_template.product_variant_id
        cls.pricelist = cls.env["product.pricelist"].create({
            "name": "Custom order price",
            "currency_id": cls.env.company.currency_id.id,
            "item_ids": [(0, 0, {
                "applied_on": "3_global",
                "compute_price": "percentage",
                "percent_price": 10.0,
            })],
        })

    def _sale_context(self):
        return {
            "mb_show_sale_selector_price": True,
            "mb_sale_pricelist_id": self.pricelist.id,
            "mb_sale_currency_id": self.pricelist.currency_id.id,
        }

    def test_template_selector_uses_pricelist_price(self):
        expected = format_amount(
            self.env, 45.0, self.pricelist.currency_id, trailing_zeroes=False)

        display_name = self.product_template.with_context(
            **self._sale_context()).display_name

        self.assertEqual(display_name, f"[CUP-CUSTOM] Custom cup — {expected}")

    def test_variant_selector_uses_pricelist_price(self):
        expected = format_amount(
            self.env, 45.0, self.pricelist.currency_id, trailing_zeroes=False)

        display_name = self.product.with_context(**self._sale_context()).display_name

        self.assertEqual(display_name, f"[CUP-CUSTOM] Custom cup — {expected}")

    def test_general_selector_uses_standard_sales_price(self):
        expected = format_amount(
            self.env, 50.0, self.env.company.currency_id, trailing_zeroes=False)

        display_name = self.product.with_context(
            mb_show_product_selector_price=True).display_name

        self.assertEqual(display_name, f"[CUP-CUSTOM] Custom cup — {expected}")

    def test_price_is_not_added_outside_sale_selector(self):
        self.assertEqual(
            self.product_template.display_name,
            "[CUP-CUSTOM] Custom cup",
        )

    def test_selector_price_respects_order_date_and_uom(self):
        dozen = self.env["uom.uom"].create({
            "name": "Dozen cups",
            "relative_uom_id": self.product.uom_id.id,
            "relative_factor": 12.0,
        })
        dated_pricelist = self.env["product.pricelist"].create({
            "name": "Dated unit price",
            "currency_id": self.env.company.currency_id.id,
            "item_ids": [(0, 0, {
                "applied_on": "0_product_variant",
                "product_id": self.product.id,
                "compute_price": "fixed",
                "fixed_price": 40.0,
                "date_start": fields.Datetime.to_datetime("2026-09-01 00:00:00"),
            })],
        })
        context = {
            "mb_show_sale_selector_price": True,
            "mb_sale_pricelist_id": dated_pricelist.id,
            "mb_sale_currency_id": dated_pricelist.currency_id.id,
            "mb_sale_uom_id": dozen.id,
            "mb_sale_price_date": "2026-09-10 12:00:00",
        }
        expected = format_amount(
            self.env, 480.0, dated_pricelist.currency_id, trailing_zeroes=False)

        self.assertEqual(
            self.product.with_context(**context).display_name,
            f"[CUP-CUSTOM] Custom cup — {expected}",
        )
