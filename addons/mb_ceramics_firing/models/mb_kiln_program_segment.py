from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .program_schedule import FULL_POWER_RATE, schedule


class MbKilnProgramSegment(models.Model):
    """One ramp-and-hold step of a controller programme.

    Held as records rather than as a blob because this is the part a potter
    reads and argues with: the rate a glaze is taken up at, the hold at top
    temperature, the slow climb through quartz inversion. A JSON field would
    make all of that invisible in a list view and unsearchable.

    Segments are also where a programme's declared duration comes from. A
    controller stores a rate, a target and a soak, never a length - so the
    length is computed here, by the same arithmetic the controller uses.
    """

    _name = "mb.kiln.program.segment"
    _description = "Kiln programme segment"
    _order = "program_id, number"
    _check_company_auto = True

    program_id = fields.Many2one(
        comodel_name="mb.kiln.program",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    number = fields.Integer(
        required=True, default=1, help="Segment order, as the controller numbers it."
    )

    ramp_rate = fields.Float(
        string="Rate (deg/h)",
        help="How fast the controller climbs to the target. At or above 999 "
        "the controller reads it as full power and the ramp is not "
        "scheduled at all.",
    )
    target_temperature = fields.Float(
        string="Target (deg C)", help="Where this segment ends. The next segment ramps from here."
    )
    soak_time = fields.Float(
        string="Hold (minutes)", help="How long the target is held before the next segment starts."
    )

    full_power = fields.Boolean(
        compute="_compute_schedule",
        string="Full power",
        help="The rate says climb as fast as the elements allow, so how long "
        "the climb takes is the kiln's business and cannot be scheduled.",
    )
    start_temperature = fields.Float(
        compute="_compute_schedule",
        string="From (deg C)",
        help="Where the previous segment left off; ambient for the first.",
    )
    ramp_minutes = fields.Float(compute="_compute_schedule", string="Ramp (min)")
    duration_minutes = fields.Float(compute="_compute_schedule", string="Segment (min)")
    elapsed_minutes = fields.Float(
        compute="_compute_schedule",
        string="Elapsed (min)",
        help="Where this segment ends, measured from the start of the programme.",
    )

    company_id = fields.Many2one(
        related="program_id.company_id", store=True, required=True, index=True, precompute=True
    )

    _program_segment_uniq = models.Constraint(
        "unique (program_id, number)",
        "A programme numbers each segment once.",
    )

    @api.depends(
        "number",
        "ramp_rate",
        "target_temperature",
        "soak_time",
        # Siblings, not decoration: lowering segment 2's target changes where
        # segment 3 starts and therefore how long it takes. Depending only on
        # this record's own fields would leave every later segment stale.
        "program_id.segment_ids.number",
        "program_id.segment_ids.ramp_rate",
        "program_id.segment_ids.target_temperature",
        "program_id.segment_ids.soak_time",
    )
    def _compute_schedule(self):
        """Timings, computed over the whole programme rather than per segment.

        A segment's ramp depends on where the one before it finished, so this
        walks the programme in order and picks out each segment's row. Editing
        any segment therefore recomputes every segment after it, which is the
        behaviour a potter expects when they lower a target.
        """
        unresolved = self
        for program in self.mapped("program_id"):
            # Siblings are walked but never written to: a compute may only
            # assign to the records it was given, and a segment cannot know
            # where it starts without the ones before it.
            siblings = program.segment_ids.sorted(key=lambda segment: (segment.number, segment.id))
            for segment, row in zip(siblings, schedule(siblings), strict=True):
                if segment not in self:
                    continue
                segment.full_power = (
                    bool(segment.ramp_rate) and segment.ramp_rate >= FULL_POWER_RATE
                )
                segment.start_temperature = row["start_temperature"]
                segment.ramp_minutes = row["ramp_minutes"]
                segment.duration_minutes = row["ramp_minutes"] + row["soak_minutes"]
                segment.elapsed_minutes = row["end_minutes"]
                unresolved -= segment
        # A segment with no programme yet - a new line in an editable list -
        # still has to be assigned to, or the ORM raises for the ones it asked
        # about and did not get back.
        for segment in unresolved:
            segment.full_power = bool(segment.ramp_rate) and segment.ramp_rate >= FULL_POWER_RATE
            segment.start_temperature = 0.0
            segment.ramp_minutes = 0.0
            segment.duration_minutes = segment.soak_time or 0.0
            segment.elapsed_minutes = segment.soak_time or 0.0

    @api.constrains("ramp_rate", "soak_time")
    def _check_positive(self):
        for segment in self:
            if segment.ramp_rate < 0.0 or segment.soak_time < 0.0:
                raise ValidationError(_("A segment cannot have a negative rate or hold."))

    def _values(self):
        """The provider-comparable shape of these segments, in order."""
        return [
            {
                "number": segment.number,
                "ramp_rate": segment.ramp_rate,
                "target_temperature": segment.target_temperature,
                "soak_time": segment.soak_time,
            }
            for segment in self.sorted(key=lambda record: (record.number, record.id))
        ]
