from odoo.tests.common import TransactionCase, tagged

from ..models.mykiln_normalize import (
    kiln_specification, index_kiln_types, normalize_firing, normalize_kilns,
    normalize_program,
)
from . import fixtures


@tagged("post_install", "-at_install")
class TestNormalize(TransactionCase):
    """Pure functions, no network and no provider account."""

    def test_kilns_join_their_controllers(self):
        kilns = normalize_kilns(fixtures.KILNS, fixtures.CONTROLLERS)
        self.assertEqual(len(kilns), 2)
        first = kilns[0]
        self.assertEqual(first["external_id"], "41")
        self.assertEqual(first["name"], "Ecotop 80")
        self.assertTrue(first["connected"])
        self.assertTrue(first["is_firing"])
        self.assertEqual(first["current_temperature"], 1043.5)
        self.assertEqual(first["segment"], 3)

    def test_unnamed_kiln_gets_a_placeholder(self):
        kilns = normalize_kilns(fixtures.KILNS, fixtures.CONTROLLERS)
        self.assertEqual(kilns[1]["name"], "MyKiln 42")

    def test_fahrenheit_is_converted(self):
        """68 F is 20 C. A controller in Fahrenheit must not reach Odoo raw."""
        kilns = normalize_kilns(fixtures.KILNS, fixtures.CONTROLLERS)
        self.assertEqual(kilns[1]["current_temperature"], 20.0)

    def test_firing_carries_peak_and_curve(self):
        firing = normalize_firing(fixtures.FIRING_DETAIL, fixtures.FIRING_SAMPLES)
        self.assertEqual(firing["external_id"], "4417")
        self.assertEqual(firing["kiln_external_id"], "41")
        self.assertEqual(firing["peak_temperature"], 998.25)
        self.assertEqual(firing["sample_count"], 4)
        self.assertEqual(firing["state"], "done")
        self.assertEqual(firing["duration_seconds"], 12 * 3600)
        self.assertEqual(firing["program"], "Bisque 1000")

    def test_running_firing_has_no_end(self):
        firing = normalize_firing(fixtures.RUNNING_DETAIL, fixtures.FIRING_SAMPLES)
        self.assertEqual(firing["state"], "firing")
        self.assertFalse(firing["ended_at"])
        # Falls back to the last sample, since there is no end timestamp.
        self.assertEqual(firing["duration_seconds"], 5400)

    def test_open_firing_on_a_cooling_kiln_is_cooling(self):
        """Observed on the live account: a firing with no end date whose kiln
        reports cooling and whose samples already peaked. Left at "firing" the
        cooling gate would never open."""
        firing = normalize_firing(
            fixtures.RUNNING_DETAIL, fixtures.FIRING_SAMPLES, kiln_state="cooling")
        self.assertEqual(firing["state"], "cooling")

    def test_closed_firing_stays_done_whatever_the_kiln_says(self):
        firing = normalize_firing(
            fixtures.FIRING_DETAIL, fixtures.FIRING_SAMPLES, kiln_state="cooling")
        self.assertEqual(firing["state"], "done")

    def test_unkeyable_firing_is_refused(self):
        """No id or no start means it cannot be keyed, so it must not import."""
        self.assertIsNone(normalize_firing({"kiln": {"id": 41}}, {}))
        self.assertIsNone(normalize_firing(
            {"id": 1, "kiln": {"id": 41}, "start_date_time": ""}, {}))

    # -- specification -----------------------------------------------------

    def test_specification_comes_from_the_kiln_and_the_catalogue(self):
        index = index_kiln_types(fixtures.KILN_TYPES)
        spec = kiln_specification(fixtures.KILNS[0], index)
        # From the kiln: it is the record describing this machine.
        self.assertEqual(spec["chamber_litres"], 80)
        self.assertEqual(spec["max_temperature"], 1320.0)
        self.assertEqual(spec["power_kw"], 6.0)
        self.assertEqual(spec["serial_number"], "80275")
        # From the catalogue: it is the record describing the model.
        self.assertEqual(spec["series"], "TE-S")
        self.assertEqual(spec["configuration"], "top_loader")
        self.assertEqual(spec["voltage"], 400)
        self.assertEqual(spec["phases"], 1)

    def test_a_model_listed_per_region_is_indexed_once(self):
        """The live catalogue lists TE 80 S twice, differing only in sales
        region. They agree on everything read here, so the first wins rather
        than the join becoming ambiguous."""
        index = index_kiln_types(fixtures.KILN_TYPES)
        self.assertEqual(len(index), 2)
        self.assertEqual(index[("rohde", "te 80 s")]["id"], 468)

    def test_a_kiln_with_no_model_gets_no_specification(self):
        spec = kiln_specification(
            fixtures.KILNS[1], index_kiln_types(fixtures.KILN_TYPES))
        self.assertIsNone(spec["manufacturer"])
        self.assertIsNone(spec["series"])
        self.assertIsNone(spec["chamber_litres"])

    def test_an_unknown_model_leaves_the_kiln_facts_intact(self):
        """A kiln whose model is not in the catalogue still reports its own
        volume and maximum, which are the figures that matter."""
        spec = kiln_specification(
            dict(fixtures.KILNS[0], model_number="TE 9000 Z"),
            index_kiln_types(fixtures.KILN_TYPES))
        self.assertEqual(spec["chamber_litres"], 80)
        self.assertIsNone(spec["series"])
        self.assertEqual(spec["heating_method"], "electric")

    def test_kilns_carry_their_specification(self):
        kilns = normalize_kilns(
            fixtures.KILNS, fixtures.CONTROLLERS, fixtures.KILN_TYPES)
        self.assertEqual(kilns[0]["specification"]["model_number"], "TE 80 S")

    # -- programmes --------------------------------------------------------

    def test_programme_is_read_from_a_firing(self):
        program = normalize_program(fixtures.FIRING_DETAIL)
        self.assertEqual(program["program_number"], 3)
        self.assertEqual(program["name"], "Bisque 1000")
        self.assertEqual(len(program["segments"]), 2)
        self.assertEqual(program["segments"][0]["ramp_rate"], 100.0)
        self.assertEqual(program["segments"][0]["target_temperature"], 1000.0)
        self.assertEqual(program["segments"][1]["soak_time"], 90.0)

    def test_an_unsaved_programme_is_labelled_by_its_slot(self):
        """myKiln's programme library is empty on the live account, so
        `library_program_name` is null and the slot is the only label there is.
        It must be the same label `normalize_firing` puts on the firing, or the
        two would never match each other."""
        program = normalize_program(fixtures.FIRING_DETAIL_GLAZE)
        self.assertEqual(program["name"], "Programme 4")
        firing = normalize_firing(fixtures.FIRING_DETAIL_GLAZE, {})
        self.assertEqual(firing["program"], program["name"])
        self.assertEqual(firing["program_number"], 4)

    def test_a_firing_naming_no_slot_yields_no_programme(self):
        self.assertIsNone(normalize_program(
            dict(fixtures.FIRING_DETAIL, program_number=None)))

    def test_a_slot_with_no_segments_is_still_a_programme(self):
        """A firing predating the app's programme capture. A slot with no
        profile is a gap, not a failure."""
        program = normalize_program(
            dict(fixtures.FIRING_DETAIL, program=None))
        self.assertEqual(program["program_number"], 3)
        self.assertEqual(program["segments"], [])
