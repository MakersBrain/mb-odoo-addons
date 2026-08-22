from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCeramicsTaxonomy(TransactionCase):
    def test_finished_ceramics_taxonomy_is_seeded(self):
        root = self.env.ref("mb_ceramics_base.categ_finished_ceramics")
        children = {
            self.env.ref(xmlid).name
            for xmlid in (
                "mb_ceramics_base.categ_tableware",
                "mb_ceramics_base.categ_drinkware",
                "mb_ceramics_base.categ_vases",
                "mb_ceramics_base.categ_planters",
                "mb_ceramics_base.categ_decorative",
                "mb_ceramics_base.categ_tiles",
                "mb_ceramics_base.categ_jewellery",
            )
        }

        self.assertEqual(root.parent_id, self.env.ref("product.product_category_goods"))
        self.assertEqual(len(children), 7)
        self.assertTrue(root.child_id)

    def test_material_taxonomy_is_seeded_under_one_root(self):
        """The gate in mb_ceramics_compliance reads these, so they are not optional."""
        root = self.env.ref("mb_ceramics_base.categ_ceramic_materials")
        families = [
            self.env.ref(f"mb_ceramics_base.categ_{name}")
            for name in (
                "glaze",
                "underglaze",
                "engobe",
                "clay_body",
                "stain",
                "oxide",
                "raw_material",
            )
        ]

        self.assertEqual(root.parent_id, self.env.ref("product.product_category_goods"))
        for family in families:
            self.assertEqual(family.parent_id, root)

    def test_work_centres_are_seeded_and_drying_is_a_wait(self):
        """Drying consumes no resource, so it carries no hourly cost.

        Modelling it as ordinary work would put phantom load on the shop floor
        and drag the OEE figure down with hours nobody worked. It is on the
        continuous calendar for the same reason a kiln is: leather-hard is days.
        """
        for name in (
            "throwing",
            "handbuilding",
            "trimming",
            "assembly",
            "glazing",
            "decorating",
            "drying",
        ):
            self.assertTrue(self.env.ref(f"mb_ceramics_base.mb_workcenter_{name}"))

        drying = self.env.ref("mb_ceramics_base.mb_workcenter_drying")
        self.assertEqual(drying.costs_hour, 0.0)
        self.assertEqual(
            drying.resource_calendar_id,
            self.env.ref("mb_workshop_base.mb_calendar_continuous"),
        )

    def test_the_root_menu_stays_neutral(self):
        """Installing a vertical must not make shared data order-dependent."""
        self.assertEqual(self.env.ref("mb_workshop_base.menu_mb_workshop_root").name, "Workshop")
