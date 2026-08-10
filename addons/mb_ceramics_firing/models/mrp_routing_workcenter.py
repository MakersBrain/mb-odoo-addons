from odoo import api, fields, models


class MrpRoutingWorkcenter(models.Model):
    """A firing operation takes its duration from the programme it fires.

    Everywhere else on a routing, a duration is a person's estimate that gets
    better with practice - which is why Odoo can compute it from the last ten
    work orders. A firing is not like that. Its length is set by the controller
    schedule: the ramps, the holds and the drop are decided before anything is
    loaded, and no amount of practice makes a twelve-hour glaze programme run in
    ten. Typing that number onto every bill of materials would only give you
    somewhere for it to go stale.

    So choosing a programme writes `time_cycle_manual`. That field rather than
    `time_cycle` deliberately: `time_cycle` is Odoo's own computation, feeding
    total duration, work order duration and cost, and the right way in is the
    input it reads, not the output. Everything downstream then works untouched.

    Written rather than computed, which is the less obvious half. Making
    `time_cycle_manual` a stored computed field looks tidier and does not work:
    the core field carries `default=60`, the default lands in the create values,
    and a computed field whose value was supplied is not computed. So the
    programme is applied explicitly, on create, on write, and again whenever the
    programme's own hours change.

    A programme that declares no hours overrides nothing, so half-configured
    data leaves the routing alone rather than quietly scheduling a firing that
    takes no time at all.
    """

    _inherit = "mrp.routing.workcenter"

    mb_kiln_program_id = fields.Many2one(
        comodel_name="mb.kiln.program",
        string="Kiln programme",
        ondelete="restrict",
        check_company=True,
        domain="[('kiln_id.workcenter_id', '=', workcenter_id)]",
        help="The controller schedule this operation fires. Choosing one takes "
             "the duration out of your hands and puts it on the programme, "
             "where a change reaches every routing that fires it.",
    )
    mb_kiln_occupies_cooling = fields.Boolean(
        string="Kiln held while cooling",
        default=True,
        help="A kiln cannot take the next load while it is still hot, so the "
             "cooling hold is time the work centre is occupied even though "
             "nobody is working. Turn this off only if the load is drawn hot.",
    )

    def _apply_kiln_program(self):
        """Push the programme's length onto the operation's duration."""
        for operation in self:
            minutes = operation.mb_kiln_program_id._occupied_minutes(
                operation.mb_kiln_occupies_cooling)
            if minutes:
                operation.time_cycle_manual = minutes

    @api.onchange("mb_kiln_program_id", "mb_kiln_occupies_cooling")
    def _onchange_mb_kiln_program_id(self):
        self._apply_kiln_program()

    @api.model_create_multi
    def create(self, vals_list):
        operations = super().create(vals_list)
        operations.filtered("mb_kiln_program_id")._apply_kiln_program()
        return operations

    def write(self, values):
        result = super().write(values)
        if {"mb_kiln_program_id", "mb_kiln_occupies_cooling"} & set(values):
            # No recursion: the write below carries neither key.
            self._apply_kiln_program()
        return result
