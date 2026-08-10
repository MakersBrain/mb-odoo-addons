import json
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class MbFiring(models.Model):
    _name = "mb.firing"
    _description = "Kiln firing"
    _inherit = ["mail.thread"]
    _order = "date_start desc, id desc"
    _check_company_auto = True

    _INTERNAL_WRITE_TOKEN = object()
    _TERMINAL_STATES = {"done", "cancel"}

    name = fields.Char(required=True, copy=False, default=lambda self: _("New"))
    kiln_id = fields.Many2one(
        comodel_name="mb.kiln", required=True, tracking=True,
        check_company=True)
    kind = fields.Selection(
        selection=[
            ("bisque", "Bisque"),
            ("glaze", "Glaze"),
            ("other", "Other"),
        ],
        required=True,
        default="bisque",
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Loading"),
            ("firing", "Firing"),
            ("cooling", "Cooling"),
            ("done", "Unloaded"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company", required=True, index=True,
        default=lambda self: self.env.company)

    workorder_ids = fields.One2many(
        comodel_name="mrp.workorder",
        inverse_name="mb_firing_id",
        string="Work orders",
        help="Work orders from any number of manufacturing orders. A kiln is "
             "filled because firing is expensive, so a load mixes them.",
    )
    production_ids = fields.Many2many(
        comodel_name="mrp.production",
        string="Manufacturing orders",
        compute="_compute_production_ids",
    )
    carrier_ids = fields.Many2many(
        comodel_name="stock.package",
        string="Boards loaded",
        domain="[('package_type_id.package_use', '=', 'reusable')]",
        check_company=True,
        help="Ware boards and shelves. Scanned instead of the pieces, which "
             "cannot hold a label before firing.",
    )

    date_start = fields.Datetime(tracking=True)
    date_end = fields.Datetime(tracking=True)
    cooling_end = fields.Datetime(
        tracking=True,
        help="Earliest moment the load may be unloaded and labelled. Not the "
             "same moment the manufacturing order is marked done.",
    )
    cooling_interrupted = fields.Boolean(
        help="Set when the load was opened before cooling finished.")
    interruption_reason = fields.Text()

    peak_temperature = fields.Float(
        tracking=True,
        help="Queried and reportable. An under-fired glaze is a less mature "
             "glaze, so this is a compliance figure and not only a schedule one.",
    )
    hold_minutes = fields.Float(string="Hold (minutes)")
    program_name = fields.Char(
        string="Programme",
        help="The controller programme this load was fired on, as the provider "
             "labels it.")
    program_id = fields.Many2one(
        comodel_name="mb.kiln.program",
        string="Programme mapping",
        ondelete="set null",
        index=True,
        check_company=True,
        help="The mapping `program_name` was matched to. Kept as a link and not "
             "only as the label, because it is what lets a programme say how "
             "long its own firings actually take.",
    )
    duration_hours = fields.Float(
        compute="_compute_duration_hours",
        store=True,
        help="Heating only, end minus start. Cooling is held separately, "
             "because a programme's cooling hold is declared rather than "
             "observed - the kiln stops reporting long before the load is cool.",
    )
    energy_kwh = fields.Float(
        string="Energy (kWh)",
        help="Consumed by this firing, where the controller reports it.")
    raw_attachment_id = fields.Many2one(
        comodel_name="ir.attachment",
        string="Provider payload",
        copy=False,
        check_company=True,
        help="Exactly what the provider returned, kept for diagnostics and "
             "for fields this model does not model yet. Measured at about "
             "82 KB per firing. Never contains a credential: the client sends "
             "the token in a header and the body carries none.",
    )
    curve_attachment_id = fields.Many2one(
        comodel_name="ir.attachment",
        string="Firing curve",
        copy=False,
        check_company=True,
        help="The full trace, as evidence. Roughly 1,400 points for a twelve "
             "hour firing, and never read point by point, so it is a file "
             "rather than a table.",
    )

    provider = fields.Selection(
        selection=[
            ("rohde_mykiln", "ROHDE myKiln"),
            ("manual", "Entered manually"),
        ],
        default="manual",
        required=True,
    )
    external_id = fields.Char(
        copy=False,
        help="The provider's identifier for this firing. The key that makes "
             "import idempotent, so replaying a sync window converges.",
    )

    _provider_firing_uniq = models.Constraint(
        "unique (provider, external_id, company_id)",
        "A provider firing may only be imported once.",
    )

    @api.constrains("kiln_id", "program_id", "kind", "company_id", "workorder_ids")
    def _check_load_compatibility(self):
        for firing in self:
            if firing.kiln_id.company_id != firing.company_id:
                raise ValidationError(_(
                    "%(firing)s and kiln %(kiln)s must belong to the same company.",
                    firing=firing.display_name,
                    kiln=firing.kiln_id.display_name,
                ))
            if firing.program_id:
                if firing.program_id.kiln_id != firing.kiln_id:
                    raise ValidationError(_(
                        "Programme %(program)s belongs to %(program_kiln)s, not %(kiln)s.",
                        program=firing.program_id.display_name,
                        program_kiln=firing.program_id.kiln_id.display_name,
                        kiln=firing.kiln_id.display_name,
                    ))
                if firing.program_id.kind != firing.kind:
                    raise ValidationError(_(
                        "Programme %(program)s is for %(program_kind)s firing, not %(kind)s.",
                        program=firing.program_id.display_name,
                        program_kind=firing.program_id.kind,
                        kind=firing.kind,
                    ))
                if (firing.kiln_id.max_temperature
                        and firing.program_id.peak_temperature
                        and firing.program_id.peak_temperature
                        > firing.kiln_id.max_temperature):
                    raise ValidationError(_(
                        "Programme %(program)s peaks at %(peak)s C, above %(kiln)s's "
                        "maximum of %(maximum)s C.",
                        program=firing.program_id.display_name,
                        peak=firing.program_id.peak_temperature,
                        kiln=firing.kiln_id.display_name,
                        maximum=firing.kiln_id.max_temperature,
                    ))
            for workorder in firing.workorder_ids:
                workorder._mb_validate_firing(firing)

    def _replace_attachment(self, field_name, filename, document):
        """Write a JSON attachment and drop the one it supersedes.

        Replacing rather than appending is what makes a replayed import
        converge instead of accumulating one copy per poll - which, at roughly
        82 KB of provider payload per firing, is the difference between a few
        megabytes and unbounded growth.
        """
        self.ensure_one()
        if not document:
            return self.env["ir.attachment"]
        body = json.dumps(document, separators=(",", ":"), default=str)
        attachment = self.env["ir.attachment"].create({
            "name": filename,
            "res_model": self._name,
            "res_id": self.id,
            "mimetype": "application/json",
            "raw": body.encode("utf-8"),
        })
        previous = self[field_name]
        self._mb_internal().write({field_name: attachment.id})
        if previous:
            previous.unlink()
        return attachment

    def _attach_curve(self, curve, external_id):
        """The normalized trace: elapsed seconds, temperature, setpoint, segment.

        Kept alongside the raw payload rather than derived from it on demand,
        because this one is provider-neutral and is what any reader should use.
        """
        return self._replace_attachment(
            "curve_attachment_id", "firing-%s-curve.json" % external_id, curve)

    def _attach_raw(self, raw, external_id):
        """The provider's own response, unaltered."""
        return self._replace_attachment(
            "raw_attachment_id", "firing-%s-raw.json" % external_id, raw)

    @api.depends("date_start", "date_end")
    def _compute_duration_hours(self):
        for firing in self:
            if firing.date_start and firing.date_end:
                delta = firing.date_end - firing.date_start
                firing.duration_hours = delta.total_seconds() / 3600.0
            else:
                firing.duration_hours = 0.0

    @api.depends("workorder_ids.production_id")
    def _compute_production_ids(self):
        for firing in self:
            firing.production_ids = firing.workorder_ids.production_id

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("name", _("New")) == _("New"):
                values["name"] = self.env["ir.sequence"].next_by_code(
                    "mb.firing") or _("New")
        return super().create(vals_list)

    def _mb_internal(self):
        """Return a recordset whose write authority cannot be forged by RPC."""
        return self.with_context(
            mb_firing_write_token=self._INTERNAL_WRITE_TOKEN)

    def _mb_apply_provider_values(self, values):
        """Apply provider evidence, including refreshes of terminal firings."""
        return self._mb_internal().write(values)

    def write(self, values):
        internal = (
            self.env.context.get("mb_firing_write_token")
            is self._INTERNAL_WRITE_TOKEN
        )
        if not internal and any(
            firing.state in self._TERMINAL_STATES for firing in self
        ):
            raise UserError(_(
                "A completed or cancelled firing is immutable. Record a new "
                "firing or use the provider synchronisation path."
            ))
        result = super().write(values)
        if "workorder_ids" in values:
            self._mb_sync_group_duration()
        return result

    def unlink(self):
        if any(firing.state in self._TERMINAL_STATES for firing in self):
            raise UserError(_(
                "A completed or cancelled firing cannot be deleted."
            ))
        return super().unlink()

    def _mb_sync_group_duration(self):
        """Charge one physical kiln occupation across a shared load.

        Each manufacturing order still owns its native work order, but only
        the first work order in the physical firing reserves and costs the
        controller programme's duration. The remaining work orders are fellow
        contents of that same load, not additional kiln cycles.
        """
        for firing in self:
            workorders = firing.workorder_ids.sorted(
                key=lambda order: (
                    not bool(order.leave_id),
                    order.date_start or fields.Datetime.now(),
                    order.id,
                )
            )
            if not workorders:
                continue
            lead = workorders[:1]
            minutes = firing.program_id._occupied_minutes(
                lead.operation_id.mb_kiln_occupies_cooling)
            for workorder in workorders:
                expected = minutes if workorder == lead else 0.0
                if workorder.duration_expected != expected:
                    workorder.with_context(
                        bypass_duration_calculation=True
                    ).write({"duration_expected": expected})
            # If Odoo had already planned every MO separately, keep the lead
            # reservation and remove the duplicates. The remaining WOs still
            # belong to the firing, but they are contents of its physical slot
            # rather than extra uses of the kiln.
            if lead.leave_id:
                lead.leave_id.write({
                    "date_to": lead.leave_id.date_from + timedelta(minutes=minutes),
                })
                (workorders - lead).mapped("leave_id").unlink()

    def action_start(self):
        for firing in self:
            if firing.state != "draft":
                raise UserError(_("Only a loading firing can be started."))
            firing._check_load_compatibility()
            firing._mb_internal().write({
                "state": "firing", "date_start": fields.Datetime.now()})
        return True

    def action_finish(self):
        for firing in self:
            if firing.state != "firing":
                raise UserError(_("Only a firing in progress can enter cooling."))
            ended = fields.Datetime.now()
            cooling_end = False
            if firing.program_id:
                cooling_end = ended + timedelta(hours=firing.program_id.cooling_hours)
            firing._mb_internal().write({
                "state": "cooling",
                "date_end": ended,
                "cooling_end": cooling_end,
            })
        return True

    def _finish_loaded_workorders(self):
        """Finish this load once; never advance an unrelated later operation."""
        for firing in self:
            open_orders = firing.workorder_ids.filtered(
                lambda order: order.state not in ("done", "cancel"))
            if open_orders:
                open_orders.button_finish()

    def action_unload(self):
        """Release the load for labelling, refusing while it is still hot."""
        for firing in self:
            if firing.state == "done":
                continue
            if firing.state != "cooling":
                raise UserError(_("Only a cooling firing can be unloaded."))
            if firing.cooling_end and firing.cooling_end > fields.Datetime.now():
                raise UserError(_(
                    "%(name)s is cooling until %(until)s. Unloading now needs the "
                    "interruption recorded, because opening a kiln early changes "
                    "what came out of it.",
                    name=firing.name,
                    until=firing.cooling_end,
                ))
            firing._finish_loaded_workorders()
            firing._mb_internal().write({"state": "done"})
        return self.mapped("carrier_ids")

    def action_force_unload(self):
        """Unload before cooling has finished, on the record."""
        for firing in self:
            if firing.state == "done":
                continue
            if firing.state != "cooling":
                raise UserError(_("Only a cooling firing can be force-unloaded."))
            if not firing.interruption_reason:
                raise UserError(_(
                    "Record why %s was opened early before forcing it.",
                    firing.name,
                ))
            firing._finish_loaded_workorders()
            firing._mb_internal().write({
                "cooling_interrupted": True, "state": "done"})
        return self.mapped("carrier_ids")
