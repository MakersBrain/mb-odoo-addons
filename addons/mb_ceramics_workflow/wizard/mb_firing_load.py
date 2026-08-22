from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MbFiringLoad(models.TransientModel):
    _name = "mb.firing.load"
    _description = "Load compatible ware into a kiln firing"

    firing_id = fields.Many2one("mb.firing", required=True, readonly=True)
    board_ids = fields.Many2many(
        "stock.package",
        string="Boards",
        domain="[('package_type_id.package_use', '=', 'reusable')]",
    )
    workorder_ids = fields.Many2many("mrp.workorder", string="Work orders")
    eligible_workorder_ids = fields.Many2many(
        "mrp.workorder", compute="_compute_eligible_workorders"
    )

    @api.depends("firing_id")
    def _compute_eligible_workorders(self):
        for wizard in self:
            firing = wizard.firing_id
            if not firing or not firing.program_id:
                wizard.eligible_workorder_ids = False
                continue
            wizard.eligible_workorder_ids = self.env["mrp.workorder"].search(
                [
                    ("state", "=", "ready"),
                    ("mb_firing_id", "=", False),
                    ("workcenter_id", "=", firing.kiln_id.workcenter_id.id),
                    ("operation_id.mb_kiln_program_id", "=", firing.program_id.id),
                    ("company_id", "=", firing.company_id.id),
                ]
            )

    @api.onchange("board_ids")
    def _onchange_board_ids(self):
        if not self.board_ids:
            return
        contents = self.env["mb.board.content"].search(
            [
                ("board_id", "in", self.board_ids.ids),
                ("state", "=", "current"),
            ]
        )
        orders = contents.current_workorder_id & self.eligible_workorder_ids
        self.workorder_ids = orders

    def action_load(self):
        self.ensure_one()
        firing = self.firing_id
        if firing.state != "draft":
            raise UserError(_("Only a loading firing can receive work."))
        selected = self.workorder_ids
        if self.board_ids:
            contents = self.env["mb.board.content"].search(
                [
                    ("board_id", "in", self.board_ids.ids),
                    ("state", "=", "current"),
                ]
            )
            selected |= contents.current_workorder_id.filtered(
                lambda workorder: workorder in self.eligible_workorder_ids
            )
            productions = selected.production_id
            missing_boards = (
                self.env["mb.board.content"]
                .search(
                    [
                        ("production_id", "in", productions.ids),
                        ("state", "=", "current"),
                        ("board_id", "not in", self.board_ids.ids),
                    ]
                )
                .board_id
            )
            if missing_boards:
                raise UserError(
                    _(
                        "The same firing work order also stands on: %(boards)s. Load "
                        "those boards or split the manufacturing order first.",
                        boards=", ".join(missing_boards.mapped("display_name")),
                    )
                )
        if not selected:
            raise UserError(_("Select at least one compatible work order or board."))
        invalid = selected - self.eligible_workorder_ids
        if invalid:
            raise UserError(_("Some selected work orders are not compatible with this firing."))
        selected.mb_assign_firing(firing)
        firing.carrier_ids = [fields.Command.link(board.id) for board in self.board_ids]
        return {"type": "ir.actions.act_window_close"}
