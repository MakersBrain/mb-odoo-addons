from odoo.tests.common import TransactionCase, tagged

from ..models.program_schedule import (
    peak_temperature,
    ramp_minutes,
    schedule,
    total_minutes,
)


@tagged("post_install", "-at_install")
class TestProgramSchedule(TransactionCase):
    """The controller's own arithmetic, on plain dicts and no database."""

    def test_a_ramp_is_the_climb_at_the_stated_rate(self):
        # 100 deg/h from 20 to 1000 is 9.8 hours.
        self.assertAlmostEqual(ramp_minutes(100.0, 20.0, 1000.0), 588.0)

    def test_full_power_schedules_no_ramp(self):
        """999 and above is the controller's skip-the-ramp sentinel, not a
        rate. How fast the elements actually manage is the kiln's business and
        cannot be put in a plan."""
        self.assertEqual(ramp_minutes(999.0, 20.0, 1000.0), 0.0)
        self.assertEqual(ramp_minutes(1000.0, 20.0, 1000.0), 0.0)
        self.assertEqual(ramp_minutes(0.0, 20.0, 1000.0), 0.0)

    def test_a_cooling_segment_takes_time_too(self):
        """A controlled cool through quartz inversion is a segment like any
        other, and its ramp is an absolute difference rather than a negative
        one."""
        self.assertAlmostEqual(ramp_minutes(60.0, 1000.0, 700.0), 300.0)

    def test_each_segment_starts_where_the_last_one_ended(self):
        rows = schedule(
            [
                {"ramp_rate": 100.0, "target_temperature": 600.0, "soak_time": 0},
                {"ramp_rate": 60.0, "target_temperature": 1000.0, "soak_time": 30},
            ]
        )
        self.assertAlmostEqual(rows[0]["start_temperature"], 20.0)
        self.assertAlmostEqual(rows[0]["end_minutes"], 348.0)
        self.assertAlmostEqual(rows[1]["start_temperature"], 600.0)
        self.assertAlmostEqual(rows[1]["ramp_minutes"], 400.0)
        self.assertAlmostEqual(rows[1]["end_minutes"], 778.0)

    def test_a_hold_at_full_power_is_the_hold_alone(self):
        """The live shape: a second segment carrying a rate of 1000 and the
        temperature the first one already reached. It is a hold."""
        total = total_minutes(
            [
                {"ramp_rate": 100.0, "target_temperature": 1000.0, "soak_time": 0},
                {"ramp_rate": 1000.0, "target_temperature": 1000.0, "soak_time": 90},
            ]
        )
        self.assertAlmostEqual(total, 678.0)

    def test_a_programme_with_no_segments_says_nothing(self):
        self.assertEqual(total_minutes([]), 0.0)
        self.assertIsNone(peak_temperature([]))

    def test_the_peak_is_the_highest_target_asked_for(self):
        self.assertEqual(
            peak_temperature(
                [
                    {"target_temperature": 900.0},
                    {"target_temperature": 1230.0},
                    {"target_temperature": 700.0},
                ]
            ),
            1230.0,
        )


@tagged("post_install", "-at_install")
class TestProgramSegments(TransactionCase):
    """The same arithmetic once it is records a potter can edit."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.kiln = cls.env["mb.kiln"].create({"name": "Test kiln"})
        cls.program = cls.env["mb.kiln.program"].create(
            {
                "kiln_id": cls.kiln.id,
                "name": "Programme 2",
                "kind": "bisque",
                "segment_ids": [
                    (
                        0,
                        0,
                        {
                            "number": 1,
                            "ramp_rate": 100.0,
                            "target_temperature": 600.0,
                            "soak_time": 0.0,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "number": 2,
                            "ramp_rate": 60.0,
                            "target_temperature": 1000.0,
                            "soak_time": 30.0,
                        },
                    ),
                ],
            }
        )

    def test_scheduled_hours_come_from_the_segments(self):
        self.assertAlmostEqual(self.program.scheduled_hours, 778.0 / 60.0)
        self.assertEqual(self.program.segment_count, 2)

    def test_editing_a_segment_moves_every_segment_after_it(self):
        """The reason the timings are computed over the whole programme rather
        than per segment: lowering one target changes where the next starts."""
        first, second = self.program.segment_ids.sorted("number")
        first.target_temperature = 300.0
        self.assertAlmostEqual(second.start_temperature, 300.0)
        self.assertAlmostEqual(second.ramp_minutes, 700.0)

    def test_adopting_the_schedule_is_deliberate(self):
        """The declared duration never moves on its own, because a plan rests
        on it."""
        self.program.firing_hours = 9.0
        self.program.segment_ids.sorted("number")[1].soak_time = 120.0
        self.assertEqual(self.program.firing_hours, 9.0)
        self.program.action_adopt_scheduled()
        self.assertAlmostEqual(self.program.firing_hours, 868.0 / 60.0)

    def test_a_full_power_segment_is_flagged(self):
        segment = self.env["mb.kiln.program.segment"].create(
            {
                "program_id": self.program.id,
                "number": 3,
                "ramp_rate": 1000.0,
                "target_temperature": 1000.0,
                "soak_time": 60.0,
            }
        )
        self.assertTrue(segment.full_power)
        self.assertEqual(segment.ramp_minutes, 0.0)
        self.assertEqual(segment.duration_minutes, 60.0)

    def test_a_segment_cannot_hold_for_a_negative_time(self):
        from odoo.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.env["mb.kiln.program.segment"].create(
                {
                    "program_id": self.program.id,
                    "number": 9,
                    "ramp_rate": 60.0,
                    "target_temperature": 900.0,
                    "soak_time": -10.0,
                }
            )
