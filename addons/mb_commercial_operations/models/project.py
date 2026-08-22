from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    mb_commercial_kind = fields.Selection(
        [
            ("contract", "Commercial Contract"),
            ("market", "Market / Fair"),
            ("venue", "Venue Operation"),
        ],
        string="Commercial purpose",
        index=True,
    )
    mb_commercial_contract_ids = fields.One2many(
        "mb.commercial.contract",
        "project_id",
        string="Commercial contracts",
    )
    mb_commercial_operation_ids = fields.One2many(
        "mb.commercial.operation",
        "project_id",
        string="Commercial operations",
    )


class ProjectTask(models.Model):
    _inherit = "project.task"

    mb_commercial_operation_id = fields.Many2one(
        "mb.commercial.operation",
        string="Commercial operation",
        copy=False,
        index=True,
        check_company=True,
        ondelete="set null",
    )
    mb_travel_hours = fields.Float(string="Travel hours", copy=False)
    mb_on_site_hours = fields.Float(string="On-site hours", copy=False)
