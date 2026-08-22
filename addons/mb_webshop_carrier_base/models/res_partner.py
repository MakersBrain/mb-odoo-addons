from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    mb_pickup_ref = fields.Char(copy=False, index=True)
    mb_pickup_provider = fields.Char(copy=False, index=True)
    mb_pickup_service = fields.Char(copy=False)
    mb_street_name = fields.Char(
        string="Street name",
        help="Structured street name used by carriers that require a separate house number.",
    )
    mb_house_number = fields.Char(string="House number")
    mb_house_number_addition = fields.Char(string="House number addition")

    def _can_be_edited_by_current_customer(self, **kwargs):
        return super()._can_be_edited_by_current_customer(**kwargs) and not any(
            self.mapped("mb_pickup_ref")
        )
