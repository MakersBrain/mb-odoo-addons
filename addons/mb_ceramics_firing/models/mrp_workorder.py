from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    mb_firing_id = fields.Many2one(
        comodel_name="mb.firing",
        string="Firing",
        index=True,
        copy=False,
        ondelete="set null",
        check_company=True,
        help="The physical firing this operation happened in. A Many2one here "
             "and a One2many there is the whole many-to-many: one firing holds "
             "work orders from several manufacturing orders, and each work "
             "order sits in exactly one firing.",
    )
    mb_firing_planned_id = fields.Many2one(
        "mb.firing", string="Planned firing", index=True, copy=False,
        ondelete="set null", check_company=True,
        help="Earmarked kiln slot. This is not physical loading evidence.",
    )
    mb_firing_missed_reason = fields.Text(copy=False, readonly=True)

    def _mb_validate_planned_firing(self, firing=None):
        for workorder in self:
            slot = firing or workorder.mb_firing_planned_id
            if not slot:
                continue
            operation = workorder.operation_id
            if slot.state != "planned":
                raise ValidationError(_("Work can only be earmarked for a planned firing."))
            if workorder.company_id != slot.company_id:
                raise ValidationError(_("The work order and firing must belong to one company."))
            if workorder.workcenter_id != slot.kiln_id.workcenter_id:
                raise ValidationError(_(
                    "%s is planned on another kiln work centre.", workorder.display_name,
                ))
            if not operation or operation.mb_kiln_program_id != slot.program_id:
                raise ValidationError(_(
                    "%s does not use the planned kiln programme.", workorder.display_name,
                ))
            if slot.program_id.kind != slot.kind:
                raise ValidationError(_("The work order and firing kinds are incompatible."))
        return True

    def mb_plan_firing(self, firing):
        firing.ensure_one()
        self._mb_validate_planned_firing(firing)
        self.write({"mb_firing_planned_id": firing.id})
        return True

    def _mb_validate_firing(self, firing=None):
        """One operation may only enter the physical load it was planned for."""
        for workorder in self:
            load = firing or workorder.mb_firing_id
            if not load:
                continue
            operation = workorder.operation_id
            if load.state != "draft" and workorder.mb_firing_id != load:
                raise ValidationError(_("Work can only be added while a firing is loading."))
            if workorder.company_id != load.company_id:
                raise ValidationError(_(
                    "%(workorder)s and %(firing)s must belong to the same company.",
                    workorder=workorder.display_name,
                    firing=load.display_name,
                ))
            if workorder.state != "ready":
                raise ValidationError(_(
                    "%(workorder)s is not ready for firing yet.",
                    workorder=workorder.display_name,
                ))
            if workorder.workcenter_id != load.kiln_id.workcenter_id:
                raise ValidationError(_(
                    "%(workorder)s is planned on %(planned)s, not kiln %(kiln)s.",
                    workorder=workorder.display_name,
                    planned=workorder.workcenter_id.display_name,
                    kiln=load.kiln_id.display_name,
                ))
            if not operation or operation.mb_kiln_program_id != load.program_id:
                raise ValidationError(_(
                    "%(workorder)s is not planned with programme %(program)s.",
                    workorder=workorder.display_name,
                    program=load.program_id.display_name,
                ))
            if load.program_id.kind != load.kind:
                raise ValidationError(_(
                    "%(workorder)s and %(firing)s have incompatible firing kinds.",
                    workorder=workorder.display_name,
                    firing=load.display_name,
                ))
        return True

    def mb_assign_firing(self, firing):
        firing.ensure_one()
        if firing.state != "draft":
            raise ValidationError(_("Work can only be added while a firing is loading."))
        self._mb_validate_firing(firing)
        self.write({"mb_firing_id": firing.id})
        firing._mb_sync_group_duration()
        return True

    def write(self, values):
        previous_planned = self.mapped("mb_firing_planned_id")
        if "mb_firing_planned_id" in values and not self.env.context.get(
            "mb_firing_terminal_cleanup"
        ):
            terminal = self.mapped("mb_firing_planned_id").filtered(
                lambda firing: firing.state in firing._TERMINAL_STATES
            )
            if terminal:
                raise ValidationError(_(
                    "A planned link cannot be changed on a terminal firing."
                ))
        if "mb_firing_id" in values:
            terminal = self.mapped("mb_firing_id").filtered(
                lambda firing: firing.state in firing._TERMINAL_STATES)
            if terminal:
                raise ValidationError(_(
                    "A work order cannot be removed from a completed firing."
                ))
        previous = self.mapped("mb_firing_id")
        result = super().write(values)
        if "mb_firing_planned_id" in values:
            planned = previous_planned | self.mapped("mb_firing_planned_id")
            planned.filtered(lambda firing: firing.state == "planned")._mb_replan_slot()
        if "mb_firing_id" in values:
            (previous | self.mapped("mb_firing_id"))._mb_sync_group_duration()
            for workorder in self.filtered(lambda order: not order.mb_firing_id):
                workorder.with_context(bypass_duration_calculation=True).write({
                    "duration_expected": workorder._get_duration_expected(),
                })
        return result

    @api.constrains("mb_firing_id", "workcenter_id", "operation_id")
    def _check_mb_firing_id(self):
        self.filtered("mb_firing_id")._mb_validate_firing()

    @api.constrains("mb_firing_planned_id", "workcenter_id", "operation_id")
    def _check_mb_firing_planned_id(self):
        self.filtered("mb_firing_planned_id")._mb_validate_planned_firing()
