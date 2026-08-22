from odoo import fields, models


class MbKiln(models.Model):
    _inherit = "mb.kiln"

    connection_id = fields.Many2one(
        comodel_name="mb.kiln.connection",
        string="Provider connection",
        ondelete="set null",
        check_company=True,
        help="The connection this kiln was imported through. Clearing it "
        "leaves the kiln and its firings in place; they are ours, not "
        "the provider's.",
    )
