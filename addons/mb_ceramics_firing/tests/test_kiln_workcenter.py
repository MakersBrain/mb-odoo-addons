from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKilnWorkcenter(TransactionCase):
    """A kiln is a work centre, and the artisan should never have to say so."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.continuous = cls.env.ref("mb_workshop_base.mb_calendar_continuous")
        cls.unit = cls.env.ref("uom.product_uom_unit")

    def test_creating_a_kiln_creates_both_halves(self):
        kiln = self.env["mb.kiln"].create({"name": "Rohde Ecotop 80"})
        self.assertTrue(kiln.workcenter_id)
        self.assertTrue(kiln.equipment_id)
        self.assertEqual(kiln.workcenter_id.name, "Rohde Ecotop 80")
        self.assertEqual(kiln.equipment_id.name, "Rohde Ecotop 80")

    def test_kiln_workcenter_runs_around_the_clock(self):
        """The setting a firing plan is wrong without.

        A fourteen hour firing on a nine-to-five calendar becomes three days.
        """
        kiln = self.env["mb.kiln"].create({"name": "Nabertherm Top 60"})
        self.assertEqual(kiln.workcenter_id.resource_calendar_id, self.continuous)
        self.assertEqual(
            sum(self.continuous.attendance_ids.mapped("duration_hours")), 168.0)

    def test_kiln_workcenter_is_tagged_firing(self):
        kiln = self.env["mb.kiln"].create({"name": "Skutt KM1027"})
        tag = self.env.ref("mb_workshop_base.mb_workcenter_tag_firing")
        self.assertIn(tag, kiln.workcenter_id.tag_ids)

    def test_existing_records_are_left_alone(self):
        """A workshop already running MRP keeps the work centre it has."""
        workcenter = self.env["mrp.workcenter"].create({"name": "Old kiln bay"})
        kiln = self.env["mb.kiln"].create({
            "name": "Rohde KE 100",
            "workcenter_id": workcenter.id,
        })
        self.assertEqual(kiln.workcenter_id, workcenter)

    def test_renaming_the_kiln_renames_both_halves(self):
        kiln = self.env["mb.kiln"].create({"name": "Big kiln"})
        kiln.name = "Rohde Ecotop 100"
        self.assertEqual(kiln.workcenter_id.name, "Rohde Ecotop 100")
        self.assertEqual(kiln.equipment_id.name, "Rohde Ecotop 100")

    def test_archiving_the_kiln_archives_the_workcenter(self):
        """Otherwise planning keeps offering a kiln that is no longer there."""
        kiln = self.env["mb.kiln"].create({"name": "Retired kiln"})
        workcenter = kiln.workcenter_id
        kiln.active = False
        self.assertFalse(workcenter.active)
        kiln.active = True
        self.assertTrue(workcenter.active)

    def test_pieces_per_load_is_the_batch(self):
        """The whole reason a kiln is a work centre rather than a calendar note.

        Odoo computes a work order as ceil(quantity / capacity) cycles, so the
        capacity is what says a firing of eight and a firing of forty cost the
        same fourteen hours.
        """
        kiln = self.env["mb.kiln"].create({
            "name": "Rohde Ecotop 80",
            "pieces_per_load": 40,
        })
        product = self.env["product.product"].create({
            "name": "Mug", "is_storable": True})
        capacity, _setup, _cleanup = kiln.workcenter_id._get_capacity(
            product, self.unit, default_capacity=1)
        self.assertEqual(capacity, 40)

    def test_pieces_per_load_follows_the_kiln(self):
        kiln = self.env["mb.kiln"].create({"name": "Kiln", "pieces_per_load": 40})
        kiln.pieces_per_load = 25
        self.assertEqual(kiln.workcenter_id.capacity_ids.capacity, 25)
        kiln.pieces_per_load = 0
        self.assertFalse(kiln.workcenter_id.capacity_ids)

    def test_per_product_capacity_still_wins(self):
        """A workshop that has measured its own load is not overruled."""
        kiln = self.env["mb.kiln"].create({"name": "Kiln", "pieces_per_load": 40})
        tile = self.env["product.product"].create({
            "name": "Test tile", "is_storable": True})
        self.env["mrp.workcenter.capacity"].create({
            "workcenter_id": kiln.workcenter_id.id,
            "product_id": tile.id,
            "product_uom_id": self.unit.id,
            "capacity": 120,
        })
        kiln.pieces_per_load = 30
        capacity, _setup, _cleanup = kiln.workcenter_id._get_capacity(
            tile, self.unit, default_capacity=1)
        self.assertEqual(capacity, 120)


@tagged("post_install", "-at_install")
class TestSeededWorkcenters(TransactionCase):
    def test_the_bench_is_seeded(self):
        for external_id in (
            "mb_workshop_base.mb_workcenter_throwing",
            "mb_workshop_base.mb_workcenter_handbuilding",
            "mb_workshop_base.mb_workcenter_trimming",
            "mb_workshop_base.mb_workcenter_assembly",
            "mb_workshop_base.mb_workcenter_glazing",
            "mb_workshop_base.mb_workcenter_decorating",
        ):
            self.assertTrue(self.env.ref(external_id).active, external_id)

    def test_drying_costs_nothing_and_blocks_nobody(self):
        """Drying is a wait, so it must not report load or consume cost."""
        drying = self.env.ref("mb_workshop_base.mb_workcenter_drying")
        self.assertEqual(drying.costs_hour, 0.0)
        self.assertEqual(
            drying.resource_calendar_id,
            self.env.ref("mb_workshop_base.mb_calendar_continuous"),
        )
        product = self.env["product.product"].create({
            "name": "Bowl", "is_storable": True})
        capacity, _setup, _cleanup = drying._get_capacity(
            product, self.env.ref("uom.product_uom_unit"), default_capacity=1)
        self.assertGreaterEqual(capacity, 1000)
