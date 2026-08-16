from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCeramicsShopImport(TransactionCase):
    def test_batch_defaults_to_canonical_finished_ceramics_category(self):
        defaults = self.env["mb.shop.import.batch"].default_get(["product_category_id"])
        self.assertEqual(
            defaults["product_category_id"],
            self.env.ref("mb_ceramics_base.categ_finished_ceramics").id,
        )
