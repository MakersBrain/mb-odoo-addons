import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MbFiring(models.Model):
    _name = "mb.firing"
    _description = "Kiln firing"
    _inherit = ["mail.thread"]
    _order = "date_start desc, id desc"

    name = fields.Char(required=True, copy=False, default=lambda self: _("New"))
    kiln_id = fields.Many2one(
        comodel_name="mb.kiln", required=True, tracking=True)
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
        comodel_name="res.company", default=lambda self: self.env.company)

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
        help="Exactly what the provider returned, kept for diagnostics and "
             "for fields this model does not model yet. Measured at about "
             "82 KB per firing. Never contains a credential: the client sends "
             "the token in a header and the body carries none.",
    )
    curve_attachment_id = fields.Many2one(
        comodel_name="ir.attachment",
        string="Firing curve",
        copy=False,
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
        self[field_name] = attachment
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

    def action_start(self):
        self.write({"state": "firing", "date_start": fields.Datetime.now()})

    def action_finish(self):
        self.write({"state": "cooling", "date_end": fields.Datetime.now()})

    def action_unload(self):
        """Release the load for labelling, refusing while it is still hot."""
        for firing in self:
            if firing.cooling_end and firing.cooling_end > fields.Datetime.now():
                raise UserError(_(
                    "%(name)s is cooling until %(until)s. Unloading now needs the "
                    "interruption recorded, because opening a kiln early changes "
                    "what came out of it.",
                    name=firing.name,
                    until=firing.cooling_end,
                ))
            firing.state = "done"
        return self.mapped("carrier_ids")

    def action_force_unload(self):
        """Unload before cooling has finished, on the record."""
        for firing in self:
            if not firing.interruption_reason:
                raise UserError(_(
                    "Record why %s was opened early before forcing it.",
                    firing.name,
                ))
            firing.write({"cooling_interrupted": True, "state": "done"})
        return self.mapped("carrier_ids")
