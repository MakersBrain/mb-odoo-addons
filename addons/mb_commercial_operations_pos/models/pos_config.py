from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class PosConfig(models.Model):
    _inherit = "pos.config"

    mb_commercial_operation_id = fields.Many2one(
        "mb.commercial.operation",
        string="Market Operation",
        check_company=True,
        copy=False,
        index=True,
        domain="[('operation_type', '=', 'market'), ('state', 'in', ('approved', 'scheduled', 'in_progress'))]",
    )
    mb_regular_picking_type_id = fields.Many2one(
        "stock.picking.type",
        check_company=True,
        copy=False,
    )
    mb_market_product_ids = fields.Many2many(
        "product.product",
        compute="_compute_mb_market_product_ids",
    )

    @api.depends("mb_commercial_operation_id", "mb_commercial_operation_id.market_location_id")
    def _compute_mb_market_product_ids(self):
        for config in self:
            location = config.mb_commercial_operation_id.market_location_id
            if not location:
                config.mb_market_product_ids = False
                continue
            available = [
                product.id
                for product, quantity, reserved in self.env["stock.quant"]
                .sudo()
                ._read_group(
                    [("location_id", "child_of", location.id)],
                    ["product_id"],
                    ["quantity:sum", "reserved_quantity:sum"],
                )
                if quantity - reserved > 0
            ]
            config.mb_market_product_ids = [fields.Command.set(available)]

    def _check_no_active_session_for_reconfiguration(self):
        active = self.mapped("session_ids").filtered(lambda session: session.state != "closed")
        if active:
            raise UserError(_("Close the active POS session before changing its market operation."))

    def action_configure_market_operation(self):
        for config in self:
            config._check_no_active_session_for_reconfiguration()
            operation = config.mb_commercial_operation_id
            if not operation:
                if config.mb_regular_picking_type_id:
                    config.with_context(mb_pos_operation_sync=True).write(
                        {
                            "picking_type_id": config.mb_regular_picking_type_id.id,
                            "mb_regular_picking_type_id": False,
                        }
                    )
                continue
            if operation.company_id != config.company_id:
                raise ValidationError(
                    _("The Point of Sale and market operation must share a company.")
                )
            picking_type = operation._ensure_pos_picking_types()
            values = {"picking_type_id": picking_type.id}
            if not config.mb_regular_picking_type_id:
                values["mb_regular_picking_type_id"] = config.picking_type_id.id
            config.with_context(mb_pos_operation_sync=True).write(values)
        return True

    def write(self, vals):
        changing_operation = "mb_commercial_operation_id" in vals and not self.env.context.get(
            "mb_pos_operation_sync"
        )
        if changing_operation:
            self._check_no_active_session_for_reconfiguration()
        result = super().write(vals)
        if changing_operation:
            self.action_configure_market_operation()
        return result
