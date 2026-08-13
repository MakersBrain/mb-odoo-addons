from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFiringDuration(TransactionCase):
    """A firing's length is the programme's, not a number typed on a routing."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.kiln = cls.env["mb.kiln"].create({
            "name": "Rohde Ecotop 80",
            "pieces_per_load": 40,
        })
        cls.program = cls.env["mb.kiln.program"].create({
            "kiln_id": cls.kiln.id,
            "name": "Programme 4",
            "kind": "glaze",
            "firing_hours": 11.0,
            "cooling_hours": 13.0,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Mug", "is_storable": True})
        cls.bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.product.product_tmpl_id.id,
            "product_qty": 1.0,
        })

    def _operation(self, **overrides):
        values = {
            "name": "Glaze firing",
            "bom_id": self.bom.id,
            "workcenter_id": self.kiln.workcenter_id.id,
            "mb_kiln_program_id": self.program.id,
        }
        values.update(overrides)
        return self.env["mrp.routing.workcenter"].create(values)

    def test_duration_comes_from_the_programme(self):
        """Eleven hours firing plus thirteen cooling, in minutes."""
        operation = self._operation()
        self.assertEqual(operation.time_cycle_manual, 24 * 60)
        self.assertEqual(operation.time_cycle, 24 * 60)

    def test_cooling_can_be_excluded(self):
        operation = self._operation(mb_kiln_occupies_cooling=False)
        self.assertEqual(operation.time_cycle_manual, 11 * 60)

    def test_changing_the_programme_reaches_the_routing(self):
        """The point of the link: one change, every routing that fires it."""
        operation = self._operation()
        self.program.firing_hours = 12.0
        self.assertEqual(operation.time_cycle_manual, 25 * 60)

    def test_an_undeclared_programme_overrides_nothing(self):
        """Half-configured data must not schedule an instant firing."""
        blank = self.env["mb.kiln.program"].create({
            "kiln_id": self.kiln.id,
            "name": "Programme 9",
            "cooling_hours": 8.0,
        })
        operation = self._operation(
            mb_kiln_program_id=blank.id, time_cycle_manual=90.0)
        self.assertEqual(operation.time_cycle_manual, 90.0)

    def test_an_operation_without_a_programme_is_untouched(self):
        bench = self.env.ref("mb_ceramics_base.mb_workcenter_throwing")
        operation = self.env["mrp.routing.workcenter"].create({
            "name": "Throwing",
            "bom_id": self.bom.id,
            "workcenter_id": bench.id,
            "time_cycle_manual": 12.0,
        })
        self.assertEqual(operation.time_cycle_manual, 12.0)
        self.assertFalse(operation.mb_kiln_program_id)

    def test_the_firing_is_one_batch_not_one_per_piece(self):
        """Duration and capacity together: the whole point of both changes.

        Twenty mugs fit in one load of forty, so twenty mugs cost one firing.
        """
        operation = self._operation()
        expected = self.env["mrp.routing.workcenter"].browse(operation.id)
        with_qty = expected.with_context(
            product=self.product, quantity=20, unit=self.product.uom_id)
        self.assertEqual(with_qty.cycle_number, 1)
        self.assertEqual(with_qty.time_total, 24 * 60)

    def test_forty_one_pieces_need_a_second_firing(self):
        operation = self._operation()
        with_qty = operation.with_context(
            product=self.product, quantity=41, unit=self.product.uom_id)
        self.assertEqual(with_qty.cycle_number, 2)
        self.assertEqual(with_qty.time_total, 48 * 60)


@tagged("post_install", "-at_install")
class TestMeasuredDuration(TransactionCase):
    """What a programme's firings actually took, kept apart from what it claims."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.kiln = cls.env["mb.kiln"].create({"name": "Rohde Ecotop 80"})
        cls.program = cls.env["mb.kiln.program"].create({
            "kiln_id": cls.kiln.id,
            "name": "Programme 4",
            "kind": "glaze",
            "firing_hours": 11.0,
        })

    def _firing(self, hours, state="done"):
        start = datetime(2026, 3, 1, 6, 0, 0)
        return self.env["mb.firing"].create({
            "kiln_id": self.kiln.id,
            "program_id": self.program.id,
            "kind": "glaze",
            "state": state,
            "date_start": start,
            "date_end": start + timedelta(hours=hours),
        })

    def test_duration_hours_is_end_minus_start(self):
        self.assertEqual(self._firing(11.5).duration_hours, 11.5)

    def test_measured_is_the_median(self):
        """The median, so one interrupted firing cannot move the figure."""
        for hours in (11.0, 12.0, 13.0, 40.0):
            self._firing(hours)
        self.assertEqual(self.program.firing_count, 4)
        self.assertEqual(self.program.measured_hours, 12.5)

    def test_unfinished_firings_do_not_count(self):
        self._firing(12.0)
        self._firing(3.0, state="firing")
        self.assertEqual(self.program.firing_count, 1)
        self.assertEqual(self.program.measured_hours, 12.0)

    def test_measuring_never_moves_the_plan_on_its_own(self):
        self._firing(14.0)
        self.assertEqual(self.program.measured_hours, 14.0)
        self.assertEqual(self.program.firing_hours, 11.0)
        self.program.action_adopt_measured()
        self.assertEqual(self.program.firing_hours, 14.0)
