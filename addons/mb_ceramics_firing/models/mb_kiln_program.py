import statistics

from odoo import _, api, fields, models

from .program_schedule import peak_temperature as schedule_peak
from .program_schedule import total_minutes


class MbKilnProgram(models.Model):
    """Maps a controller programme to what the workshop actually fires with it.

    A kiln controller knows "Programme 4"; it has no idea that Programme 4 is
    the glaze schedule and Programme 2 the bisque. Only the potter knows, and
    they know it once rather than per firing - so it belongs here as a setting
    rather than as a field someone re-enters on every imported record.

    **Provider-neutral ownership.** A programme is the schedule the potter fires
    to. Workshops without telemetry define one directly, while an installed
    connector may populate its controller slot and segments. Planning therefore
    depends on this ceramics model, never on a specific provider connector.

    **Three durations, deliberately not merged.** `firing_hours` is the
    declared one: what plans are built on. `scheduled_hours` is what the
    programme's own segments add up to - the controller's arithmetic over its
    ramps and holds. `measured_hours` is the median of what actually happened,
    over the firings imported or recorded under this programme.

    They disagree, and the disagreement is the useful part. The schedule says
    what was asked for, the measurement says what a kiln with these elements in
    this room actually manages, and a gap between them is a kiln that is losing
    power or a programme nobody has revised. So the declared figure never moves
    on its own: adopting either of the other two is a button someone presses,
    not a drift that happens overnight while a plan rests on it.

    The median, not the mean: one firing that was interrupted, or one where the
    controller was switched off before the record closed, would drag a mean
    somewhere no real firing has ever been.

    **Segments may be imported, and the programme stays the potter's.** Where a
    connector can read the controller's programme, `segment_ids` and
    `program_number` are refreshed from it and `source` says so. What the
    programme *means* - bisque or glaze, and how long the load must stand - is
    never overwritten by a refresh, because no controller knows it.

    The cooling hold hangs off the same mapping for the same reason. myKiln
    reports when a firing stopped heating but has no concept of when the load
    is cool enough to open, and that interval is a property of the programme
    and the kiln, not of the individual firing.
    """

    _name = "mb.kiln.program"
    _description = "Kiln programme"
    _order = "kiln_id, name"
    _check_company_auto = True

    kiln_id = fields.Many2one(
        comodel_name="mb.kiln", required=True, ondelete="cascade", index=True,
        check_company=True)
    name = fields.Char(
        required=True,
        help="The programme label exactly as the provider reports it, such as "
             "'Programme 4'. On a kiln with no telemetry it is whatever the "
             "controller calls it.")
    program_number = fields.Integer(
        string="Slot",
        help="Which numbered slot this programme occupies on the controller. "
             "It is how a firing says which programme it ran, and it survives "
             "the potter renaming the programme to something they recognise.",
    )
    kind = fields.Selection(
        selection=[("bisque", "Bisque"), ("glaze", "Glaze"), ("other", "Other")],
        required=True, default="bisque")
    active = fields.Boolean(default=True)

    source = fields.Selection(
        selection=[("manual", "Entered here"), ("provider", "Read from the kiln")],
        default="manual", required=True, readonly=True,
        help="Where the segments came from. A programme read from the kiln is "
             "refreshed as the controller's own programme changes; one entered "
             "here is never touched by a refresh.",
    )
    provider_synced_at = fields.Datetime(
        readonly=True, copy=False, string="Segments read at",
        help="When the segments were last refreshed from the controller.")
    provider_firing_at = fields.Datetime(
        readonly=True, copy=False, string="As fired on",
        # Not the sync time: the start of the firing the segments were read
        # from. A backfill walking old history must not overwrite the current
        # profile with an older one, and this is what it compares.
        help="The start of the firing these segments were read from. The "
             "controller reports a programme as it ran, so the most recent "
             "firing is the most current profile.",
    )

    firing_hours = fields.Float(
        string="Firing (hours)",
        help="How long the programme runs, from the start of the first ramp to "
             "the end of the last segment. This is what a routing operation "
             "takes its duration from, so a firing on a bill of materials stops "
             "being a number somebody typed and starts being the schedule.",
    )
    cooling_hours = fields.Float(
        default=12.0,
        string="Cooling (hours)",
        help="How long after the firing ends before the load may be unloaded. "
             "Sets the cooling hold on every firing imported under this "
             "programme, and - because a kiln cannot take the next load while "
             "it is still hot - counts toward how long the work centre is "
             "occupied.",
    )
    peak_temperature = fields.Float(
        help="Expected peak, for reference. Not enforced: a firing that missed "
             "its peak is exactly the thing you want to be able to see.")

    segment_ids = fields.One2many(
        comodel_name="mb.kiln.program.segment",
        inverse_name="program_id",
        string="Segments",
        help="The ramps and holds the controller runs, in order. Typed in for "
             "a kiln that reports nothing, read from the controller for one "
             "that does.",
    )
    segment_count = fields.Integer(compute="_compute_scheduled", store=True)
    scheduled_hours = fields.Float(
        string="Scheduled (hours)",
        compute="_compute_scheduled",
        store=True,
        help="What the segments add up to: every ramp at its stated rate plus "
             "every hold. Zero when the programme has no segments, or when "
             "every ramp is at full power and so cannot be scheduled at all.",
    )

    firing_ids = fields.One2many(
        comodel_name="mb.firing", inverse_name="program_id", string="Firings")
    firing_count = fields.Integer(compute="_compute_measured", store=False)
    measured_hours = fields.Float(
        string="Measured (hours)",
        compute="_compute_measured",
        store=False,
        help="The median duration of the firings actually recorded under this "
             "programme. Compare it with the declared figure; press Adopt to "
             "make it the one plans are built on.",
    )

    company_id = fields.Many2one(
        related="kiln_id.company_id", store=True, required=True, index=True,
        precompute=True)

    _kiln_program_uniq = models.Constraint(
        "unique (kiln_id, name)",
        "A programme is mapped once per kiln.",
    )

    @api.depends("segment_ids.ramp_rate", "segment_ids.target_temperature",
                 "segment_ids.soak_time", "segment_ids.number")
    def _compute_scheduled(self):
        for program in self:
            segments = program.segment_ids.sorted(
                key=lambda segment: (segment.number, segment.id))
            program.segment_count = len(segments)
            program.scheduled_hours = total_minutes(segments) / 60.0

    @api.depends("firing_ids.duration_hours", "firing_ids.state")
    def _compute_measured(self):
        for program in self:
            durations = program.firing_ids.filtered(
                lambda firing: (
                    firing.state in ("cooling", "done") and firing.duration_hours > 0
                )
            ).mapped("duration_hours")
            program.firing_count = len(durations)
            program.measured_hours = (
                statistics.median(durations) if durations else 0.0)

    def write(self, values):
        """A programme's hours reach every routing that fires it.

        This is the whole reason the duration hangs off the programme rather
        than off each operation: measure a firing once, correct the schedule
        once, and every bill of materials that fires it is right.
        """
        result = super().write(values)
        if {"firing_hours", "cooling_hours"} & set(values):
            self.env["mrp.routing.workcenter"].with_context(
                active_test=False
            ).search([
                ("mb_kiln_program_id", "in", self.ids),
            ])._apply_kiln_program()
            self.env["mb.firing"].search([
                ("program_id", "in", self.ids),
                ("state", "in", ("draft", "firing", "cooling")),
            ])._mb_sync_group_duration()
        return result

    def action_adopt_measured(self):
        """Make what happened the thing plans are built on."""
        for program in self.filtered("measured_hours"):
            program.firing_hours = program.measured_hours
        return True

    def action_adopt_scheduled(self):
        """Make what the controller is programmed to do the declared duration.

        The one to press for a programme that has never been fired, where there
        is nothing to measure yet and the segments are the only thing that
        knows how long it runs.
        """
        for program in self.filtered("scheduled_hours"):
            program.firing_hours = program.scheduled_hours
        return True

    def _occupied_minutes(self, include_cooling=True):
        """How long this programme keeps the kiln, in minutes.

        Occupied, not merely firing. Cooling is dead time for the potter and
        busy time for the kiln: nothing else can go in until the load comes
        out. A schedule that counts only the heating hours will cheerfully book
        two firings into one night.

        Zero when the programme declares no duration, which callers read as
        "this programme says nothing about duration" rather than as "instant".
        """
        if not self:
            return 0.0
        self.ensure_one()
        if not self.firing_hours:
            return 0.0
        hours = self.firing_hours
        if include_cooling:
            hours += self.cooling_hours
        return hours * 60.0

    @api.model
    def _match(self, kiln, program_name, program_number=None):
        """The mapping for a firing's programme, or an empty recordset.

        By label first, then by controller slot. The slot matters because the
        label is the one thing a potter is certain to change: a programme
        arrives as "Programme 4" and becomes "Gres 1230" the day they map it,
        and from then on the provider's label matches nothing. The slot does
        not move, so the mapping survives the rename.
        """
        if not kiln:
            return self.browse()
        if program_name:
            found = self.search([
                ("kiln_id", "=", kiln.id),
                ("name", "=", program_name),
            ], limit=1)
            if found:
                return found
        if program_number:
            return self.search([
                ("kiln_id", "=", kiln.id),
                ("program_number", "=", program_number),
            ], limit=1)
        return self.browse()

    @api.model
    def _infer_kind(self, peak):
        """What a peak temperature says a programme is for.

        A guess, made once at import so a newly discovered programme is not
        silently "bisque", and never revisited - the potter's answer wins from
        then on. The thresholds are the ordinary earthenware/stoneware ones:
        below 600 nothing is being fired at all, which is a drying or a test
        cycle rather than a firing type.
        """
        if peak is None or peak < 600.0:
            return "other"
        return "bisque" if peak < 1100.0 else "glaze"

    @api.model
    def _apply_provider(self, kiln, payload):
        """Create or refresh one programme read from a controller.

        `payload` carries `program_number`, `name`, `segments` (dicts of
        `number`, `ramp_rate`, `target_temperature`, `soak_time`) and
        `fired_at`, the start of the firing they were read from.

        What a refresh may change is deliberately narrow. Segments and peak
        temperature come from the controller and are replaced; the name, the
        kind, the declared hours and the cooling hold are the potter's answers
        to questions no controller can answer, and a refresh leaves them
        exactly as they are. The single exception is a programme's first sight
        of its own segments, where there is no prior answer to protect.
        """
        program = self._match(kiln, payload.get("name"),
                              payload.get("program_number"))
        segments = payload.get("segments") or []
        peak = schedule_peak(segments)
        now = fields.Datetime.now()
        fired_at = payload.get("fired_at")

        if not program:
            program = self.create({
                "kiln_id": kiln.id,
                "name": payload.get("name") or _("Programme %s",
                                                 payload.get("program_number")),
                "program_number": payload.get("program_number") or 0,
                "kind": self._infer_kind(peak),
                "peak_temperature": peak or 0.0,
                "source": "provider",
                "provider_synced_at": now,
                "provider_firing_at": fired_at,
                "segment_ids": [fields.Command.create(values)
                                for values in self._segment_values(segments)],
            })
            # Only here, and only because there is nothing to move: a
            # programme created with no duration is invisible to planning, so
            # it starts at what the controller is programmed to take. Every
            # later change to that figure is a button someone presses.
            program.firing_hours = program.scheduled_hours
            return program

        if not program.program_number and payload.get("program_number"):
            program.program_number = payload["program_number"]
        if program.source == "manual" and program.segment_ids:
            # Hand-typed segments are an answer, not a gap. Leave them.
            return program
        if (program.provider_firing_at and fired_at
                and fired_at <= program.provider_firing_at):
            # An older firing than the one already recorded. This is the whole
            # reason the firing date is kept: a backfill walking history
            # backwards would otherwise leave the programme showing its oldest
            # profile rather than its current one.
            return program

        program.write({
            "source": "provider",
            "provider_synced_at": now,
            "provider_firing_at": fired_at or program.provider_firing_at,
            "peak_temperature": peak if peak is not None else program.peak_temperature,
            "segment_ids": (
                [fields.Command.clear()]
                + [fields.Command.create(values)
                   for values in self._segment_values(segments)]),
        })
        return program

    @api.model
    def _segment_values(self, segments):
        """Provider segment dicts, ordered and cleaned into writable values."""
        values = []
        for index, segment in enumerate(segments, start=1):
            values.append({
                "number": int(segment.get("number") or index),
                "ramp_rate": float(segment.get("ramp_rate") or 0.0),
                "target_temperature": float(
                    segment.get("target_temperature") or 0.0),
                "soak_time": float(segment.get("soak_time") or 0.0),
            })
        return sorted(values, key=lambda row: row["number"])
