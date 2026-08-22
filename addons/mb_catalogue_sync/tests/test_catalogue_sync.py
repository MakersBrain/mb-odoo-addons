"""What the import must keep doing.

The payload is a real one, trimmed: Mayco SC74 Hot Tamale as four suppliers
actually publish it, including the two spellings of the same jar (236/237 ml,
472/473 ml) that the grouping exists to handle.
"""

from odoo.tests import TransactionCase, tagged

PAYLOAD = {
    "canonical_product_id": "0f0e6b3e-1111-4222-8333-444455556666",
    "brand": "Mayco",
    "manufacturer_sku": "SC74",
    "canonical_name": "Hot Tamale",
    "family": "glaze",
    "firing_range": "cone 06 to cone 10",
    "offers": [
        {
            "source_id": "ceradel",
            "supplier_name": "Hot Tamale",
            "supplier_reference": "1425102",
            "price": 26.88,
            "currency": "EUR",
            "vat_status": "inclusive",
            "package_quantity": 473.0,
            "package_unit": "ml",
        },
        {
            "source_id": "ceradel",
            "supplier_name": "Hot Tamale",
            "supplier_reference": "1425101",
            "price": 14.99,
            "currency": "EUR",
            "vat_status": "inclusive",
            "package_quantity": 236.0,
            "package_unit": "ml",
        },
        # The same 16 oz jar, published by another shop as 472 ml.
        {
            "source_id": "1240-design",
            "supplier_name": "Hot Tamale Ceramic Glaze",
            "supplier_reference": "HT472",
            "price": 23.77,
            "currency": "EUR",
            "vat_status": "inclusive",
            "package_quantity": 472.0,
            "package_unit": "ml",
        },
        # A source with no VAT basis published, and none configured on the vendor.
        {
            "source_id": "cerama-shop",
            "supplier_name": "Hot Tamale Formato: 236 ml",
            "supplier_reference": "CS236",
            "price": 14.50,
            "currency": "EUR",
            "vat_status": None,
            "package_quantity": 236.0,
            "package_unit": "ml",
        },
        # A source this workshop does not buy from.
        {
            "source_id": "hiclay",
            "supplier_name": "STROKE & COAT SC-74 HOT TAMALE",
            "supplier_reference": "SC74",
            "price": 22.0,
            "currency": "USD",
            "vat_status": "exclusive",
            "package_quantity": 1.0,
            "package_unit": "pint",
        },
    ],
}


@tagged("post_install", "-at_install")
class TestCatalogueSync(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.env["product.template"]
        partners = cls.env["res.partner"]
        cls.ceradel = partners.create({"name": "Ceradel", "is_company": True})
        cls.design = partners.create({"name": "1240 Design", "is_company": True})
        cls.unmapped = partners.create({"name": "Cerama Shop", "is_company": True})
        supplier = cls.env["mb.catalogue.supplier"]
        supplier.create(
            {
                "source_id": "ceradel",
                "partner_id": cls.ceradel.id,
                "vat_status": "inclusive",
                "vat_rate": 20.0,
                "delay": 5,
            }
        )
        supplier.create(
            {
                "source_id": "1240-design",
                "partner_id": cls.design.id,
                "vat_status": "inclusive",
                "vat_rate": 20.0,
            }
        )
        # Mapped, but with no VAT basis anywhere: its offer must be refused.
        supplier.create({"source_id": "cerama-shop", "partner_id": cls.unmapped.id})

    def _import(self):
        template, created = self.template._mb_upsert_canonical(PAYLOAD)
        written, refused = template._mb_sync_supplier_offers(PAYLOAD["offers"])
        return template, created, written, refused

    def test_import_creates_one_template_with_external_id(self):
        template, created, _written, _refused = self._import()
        self.assertTrue(created)
        self.assertEqual(template.name, "Hot Tamale")
        self.assertEqual(template.mb_manufacturer_sku, "SC74")
        self.assertTrue(template.purchase_ok)

    def test_family_becomes_a_product_category(self):
        template, _created, _written, _refused = self._import()
        self.assertEqual(template.categ_id, self.env.ref("mb_ceramics_base.categ_glaze"))
        self.assertEqual(
            template.categ_id.parent_id, self.env.ref("mb_ceramics_base.categ_ceramic_materials")
        )

    def test_an_unknown_family_lands_somewhere_visible(self):
        """Not nowhere: an uncategorised product is invisible to every filter."""
        payload = dict(PAYLOAD, canonical_product_id="unknown-family-0001", family="lustre")
        template, _created = self.template._mb_upsert_canonical(payload)
        self.assertEqual(
            template.categ_id, self.env.ref("mb_ceramics_base.categ_ceramic_materials")
        )

    def test_manufacturer_code_is_the_internal_reference_on_every_pack(self):
        """On the variants, because the template's own default_code is a compute
        that goes False as soon as a product has two packs."""
        template, _created, _written, _refused = self._import()
        self.assertEqual(len(template.product_variant_ids), 2)
        self.assertEqual(template.product_variant_ids.mapped("default_code"), ["SC74", "SC74"])
        for variant in template.product_variant_ids:
            self.assertIn("SC74", variant.display_name)

    def test_a_single_pack_product_shows_the_code_on_the_template(self):
        payload = dict(
            PAYLOAD, canonical_product_id="single-pack-0001", offers=[PAYLOAD["offers"][0]]
        )
        template, _created = self.template._mb_upsert_canonical(payload)
        self.assertEqual(len(template.product_variant_ids), 1)
        self.assertEqual(template.default_code, "SC74")

    def test_category_and_code_are_filled_but_never_overwritten(self):
        """Empty is not a choice; what the artisan set is."""
        template, _created, _written, _refused = self._import()
        chosen = self.env["product.category"].create({"name": "My own shelf"})
        template.categ_id = chosen
        template.product_variant_ids.write({"default_code": "SHELF-1"})
        self.template._mb_upsert_canonical(PAYLOAD)
        self.assertEqual(template.categ_id, chosen)
        self.assertEqual(set(template.product_variant_ids.mapped("default_code")), {"SHELF-1"})

    def test_reimport_is_idempotent(self):
        first, _created, _written, _refused = self._import()
        second, created_again, _written, _refused = self._import()
        self.assertEqual(first, second)
        self.assertFalse(created_again)
        self.assertEqual(self.template.search_count([("mb_manufacturer_sku", "=", "SC74")]), 1)
        self.assertEqual(
            self.env["product.supplierinfo"].search_count([("product_tmpl_id", "=", first.id)]), 3
        )

    def test_vendor_price_breaks_keep_distinct_native_quantity_tiers(self):
        tiered_offer = dict(
            PAYLOAD["offers"][0],
            min_order_quantity=12.0,
            price=24.0,
        )
        payload = dict(PAYLOAD, offers=[PAYLOAD["offers"][0], tiered_offer])
        template, _created = self.template._mb_upsert_canonical(payload)

        written, refused = template._mb_sync_supplier_offers(payload["offers"])
        template._mb_sync_supplier_offers(payload["offers"])

        tiers = self.env["product.supplierinfo"].search(
            [
                ("product_tmpl_id", "=", template.id),
                ("partner_id", "=", self.ceradel.id),
            ]
        )
        self.assertEqual(written, 2)
        self.assertFalse(refused)
        self.assertEqual(len(tiers), 2)
        self.assertEqual(set(tiers.mapped("min_qty")), {0.0, 12.0})

    def test_the_same_jar_published_twice_is_one_variant(self):
        """472 ml and 473 ml are one 16 oz jar, and must not split the stock."""
        template, _created, _written, _refused = self._import()
        labels = sorted(
            value.name
            for value in template.product_variant_ids.product_template_attribute_value_ids
        )
        self.assertEqual(sorted(set(labels)), ["236 ml", "473 ml"])
        self.assertEqual(len(template.product_variant_ids), 2)

    def test_vat_inclusive_price_is_stored_net(self):
        template, _created, _written, _refused = self._import()
        info = self.env["product.supplierinfo"].search(
            [
                ("product_tmpl_id", "=", template.id),
                ("partner_id", "=", self.ceradel.id),
            ]
        )
        prices = sorted(round(record.price, 2) for record in info)
        # 26.88 and 14.99 gross at 20% are 22.40 and 12.49 net.
        self.assertEqual(prices, [12.49, 22.40])

    def test_an_offer_without_a_vat_basis_is_refused_not_guessed(self):
        _template, _created, _written, refused = self._import()
        self.assertEqual(refused.get("unknown_vat_status"), 1)

    def test_an_unmapped_source_produces_no_vendor(self):
        template, _created, _written, refused = self._import()
        self.assertEqual(refused.get("source_not_mapped"), 1)
        vendors = (
            self.env["product.supplierinfo"]
            .search([("product_tmpl_id", "=", template.id)])
            .mapped("partner_id")
        )
        self.assertNotIn(self.unmapped, vendors)

    def test_pack_conversions(self):
        units = self.env["mb.catalogue.units"]
        quantity, uom = units._package_to_uom(1.0, "pint")
        self.assertAlmostEqual(quantity, 473.176, places=3)
        self.assertEqual(uom, self.env.ref("uom.product_uom_milliliter"))
        quantity, uom = units._package_to_uom(1.0, "kg")
        self.assertEqual(quantity, 1000.0)
        self.assertEqual(uom, self.env.ref("uom.product_uom_gram"))
        # A unit nobody has taught it is not an error and not a zero.
        self.assertEqual(units._package_to_uom(1.0, "cartload"), (None, None))
