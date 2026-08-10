from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    mb_depot_stock_closed_through = fields.Date(
        string="Depot inventory history closed through",
        copy=False,
        help="Permanent inventory-closing horizon. Depot sale reports cannot "
             "insert stock movements on or before this date.",
    )

    def write(self, values):
        if "mb_depot_stock_closed_through" in values:
            if not self.env.is_superuser() and not self.env.user.has_group(
                "account.group_account_manager"
            ):
                raise AccessError(_(
                    "Only an Accounting Administrator can close depot inventory history."
                ))
            new_date = fields.Date.to_date(values["mb_depot_stock_closed_through"]) \
                if values["mb_depot_stock_closed_through"] else False
            for company in self:
                if company.mb_depot_stock_closed_through and (
                    not new_date or new_date < company.mb_depot_stock_closed_through
                ):
                    raise ValidationError(_(
                        "The depot inventory closing horizon cannot be reduced."
                    ))
        return super().write(values)
