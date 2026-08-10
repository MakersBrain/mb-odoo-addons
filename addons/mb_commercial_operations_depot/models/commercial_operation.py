from odoo import _, fields, models


class MbCommercialOperation(models.Model):
    _inherit = "mb.commercial.operation"

    operation_type = fields.Selection(
        selection_add=[
            ("depot_refill", "Depot Refill"),
            ("depot_permanence", "Depot Permanence"),
        ],
        ondelete={"depot_refill": "set default", "depot_permanence": "set default"},
    )
    depot_warehouse_id = fields.Many2one(
        "stock.warehouse",
        check_company=True,
        domain="[('is_depot', '=', True), ('company_id', '=', company_id)]",
        tracking=True,
    )

    def _ensure_market_location(self):
        self.ensure_one()
        if self.operation_type == "depot_refill" and self.depot_warehouse_id:
            if self.market_location_id != self.depot_warehouse_id.lot_stock_id:
                self.market_location_id = self.depot_warehouse_id.lot_stock_id
            return self.market_location_id
        return super()._ensure_market_location()

    def _stock_discrepancies(self):
        self.ensure_one()
        if self.operation_type == "depot_refill":
            if not self.preparation_picking_id or self.preparation_picking_id.state != "done":
                return [_('The refill transfer is not completed.')]
            return []
        return super()._stock_discrepancies()


class MbCommercialObligation(models.Model):
    _inherit = "mb.commercial.obligation"

    obligation_type = fields.Selection(
        selection_add=[
            ("depot_permanence", "Depot permanence"),
            ("depot_refill", "Depot refill visit"),
        ],
        ondelete={"depot_permanence": "set default", "depot_refill": "set default"},
    )


class MbCommercialObligationOccurrence(models.Model):
    _inherit = "mb.commercial.obligation.occurrence"

    def _prepare_operation_values(self):
        values = super()._prepare_operation_values()
        obligation_type = self.obligation_id.obligation_type
        if obligation_type in ("depot_permanence", "depot_refill"):
            values.update({
                "operation_type": obligation_type,
                "depot_warehouse_id": self.contract_id.depot_warehouse_id.id,
                "source_warehouse_id": self.contract_id.source_warehouse_id.id,
            })
        return values
