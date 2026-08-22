from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class MbCommercialOperation(models.Model):
    _inherit = "mb.commercial.operation"

    pos_config_ids = fields.One2many(
        "pos.config",
        "mb_commercial_operation_id",
        string="Point of Sale Configurations",
    )
    pos_session_ids = fields.One2many(
        "pos.session",
        "mb_commercial_operation_id",
        string="Point of Sale Sessions",
    )
    pos_order_ids = fields.One2many(
        "pos.order",
        "mb_commercial_operation_id",
        string="Point of Sale Orders",
    )
    pos_out_picking_type_id = fields.Many2one(
        "stock.picking.type",
        check_company=True,
        copy=False,
        ondelete="restrict",
    )
    pos_return_picking_type_id = fields.Many2one(
        "stock.picking.type",
        check_company=True,
        copy=False,
        ondelete="restrict",
    )
    pos_documents_expected = fields.Boolean()
    pos_documents_complete = fields.Boolean(compute="_compute_pos_documents_complete")

    def _get_operation_profitability_items(self):
        self.ensure_one()
        items = super()._get_operation_profitability_items()
        for order in self.pos_order_ids.filtered(
            lambda record: record.state not in ("cancel", "invoiced")
        ):
            items.append(
                {
                    "model": order._name,
                    "res_id": order.id,
                    "component": "revenue",
                    "date": fields.Date.to_date(order.date_order),
                    "amount": order.amount_total - order.amount_tax,
                    "currency": order.currency_id,
                }
            )
        return items

    @api.depends("pos_documents_expected", "pos_session_ids.state", "pos_order_ids.state")
    def _compute_pos_documents_complete(self):
        for operation in self:
            sessions = operation.pos_session_ids
            orders = operation.pos_order_ids
            operation.pos_documents_complete = (
                not operation.pos_documents_expected
                or bool(sessions)
                and bool(orders)
                and all(session.state == "closed" for session in sessions)
                and all(order.state in ("done", "invoiced", "cancel") for order in orders)
            )

    def _ensure_pos_picking_types(self):
        self.ensure_one()
        if self.operation_type != "market" or not self.market_location_id:
            raise ValidationError(
                _("Prepare the market stock location before configuring its Point of Sale.")
            )
        if self.pos_out_picking_type_id and self.pos_return_picking_type_id:
            return self.pos_out_picking_type_id
        warehouse = self.source_warehouse_id
        customer_location = self.env.ref("stock.stock_location_customers")
        out_type = warehouse.out_type_id.copy(
            {
                "name": _("Market %(market)s Sales", market=self.name),
                "sequence_id": False,
                "sequence_code": "MKT%s" % self.id,
                "default_location_src_id": self.market_location_id.id,
                "default_location_dest_id": customer_location.id,
                "return_picking_type_id": False,
                "analytic_costs": True,
                "mb_commercial_operation_id": self.id,
            }
        )
        return_type = warehouse.in_type_id.copy(
            {
                "name": _("Market %(market)s Returns", market=self.name),
                "sequence_id": False,
                "sequence_code": "MKTR%s" % self.id,
                "default_location_src_id": customer_location.id,
                "default_location_dest_id": self.market_location_id.id,
                "return_picking_type_id": out_type.id,
                "analytic_costs": True,
                "mb_commercial_operation_id": self.id,
            }
        )
        out_type.return_picking_type_id = return_type
        self.write(
            {
                "pos_out_picking_type_id": out_type.id,
                "pos_return_picking_type_id": return_type.id,
            }
        )
        return out_type

    def action_view_pos_orders(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("point_of_sale.action_pos_pos_form")
        action["domain"] = [("mb_commercial_operation_id", "=", self.id)]
        action["context"] = {"create": False}
        return action

    def action_view_pos_configs(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "point_of_sale.action_pos_config_kanban"
        )
        action["domain"] = [("company_id", "=", self.company_id.id)]
        return action

    def action_financial_close(self):
        if self.filtered(lambda operation: not operation.pos_documents_complete):
            raise UserError(_("Close the expected Point of Sale sessions before financial close."))
        return super().action_financial_close()
