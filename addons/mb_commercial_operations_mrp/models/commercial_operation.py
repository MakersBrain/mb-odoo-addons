from odoo import _, fields, models
from odoo.exceptions import ValidationError


class MbCommercialOperation(models.Model):
    _inherit = "mb.commercial.operation"

    manufacturing_order_ids = fields.One2many(
        "mrp.production",
        "mb_commercial_operation_id",
        string="Manufacturing Orders",
    )

    def action_view_manufacturing_orders(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("mrp.mrp_production_action")
        action["domain"] = [("id", "in", self.manufacturing_order_ids.ids)]
        action["context"] = {"create": False}
        return action


class MbMarketStockPlanLine(models.Model):
    _inherit = "mb.market.stock.plan.line"

    supply_method = fields.Selection(
        selection_add=[("manufacture", "Manufacture")],
        ondelete={"manufacture": "set default"},
    )
    readiness = fields.Selection(
        selection_add=[
            ("shortage", "Shortage"),
            ("supply_proposed", "Supply Proposed"),
            ("supply_confirmed", "Supply Confirmed"),
            ("in_progress", "In Progress"),
            ("at_risk", "At Risk"),
            ("ready_to_pick", "Ready to Pick"),
        ],
        ondelete={
            "shortage": "set default",
            "supply_proposed": "set default",
            "supply_confirmed": "set default",
            "in_progress": "set default",
            "at_risk": "set default",
            "ready_to_pick": "set default",
        },
    )
    manufacturing_product_id = fields.Many2one(
        "product.product",
        string="Manufacturable Product",
        check_company=True,
        domain="[('is_storable', '=', True)]",
        help="Required for an assortment bucket; no arbitrary SKU is manufactured automatically.",
    )
    manufacturing_bom_id = fields.Many2one(
        "mrp.bom",
        string="Bill of Materials",
        check_company=True,
    )
    production_ids = fields.One2many(
        "mrp.production",
        "mb_market_stock_plan_line_id",
        string="Manufacturing Orders",
    )

    def _prepare_supply(self):
        super()._prepare_supply()
        for line in self.filtered(lambda item: item.supply_method == "manufacture"):
            product = (
                line.product_id if line.target_type == "product" else line.manufacturing_product_id
            )
            if not product:
                raise ValidationError(
                    _(
                        "Map assortment target %(target)s to a concrete manufacturable product first.",
                        target=line.display_name,
                    )
                )
            if line.target_type == "product":
                line._refresh_availability()
                quantity = line.shortage_qty
            else:
                quantity = line.remaining_bucket_qty
            if quantity <= 0:
                line._update_supply_readiness()
                continue
            active = line.production_ids.filtered(lambda production: production.state != "cancel")
            if active:
                line._update_supply_readiness()
                continue
            bom = line.manufacturing_bom_id or self.env["mrp.bom"].search(
                [
                    ("company_id", "in", (False, line.company_id.id)),
                    "|",
                    ("product_id", "=", product.id),
                    "&",
                    ("product_id", "=", False),
                    ("product_tmpl_id", "=", product.product_tmpl_id.id),
                ],
                limit=1,
            )
            if not bom:
                raise ValidationError(
                    _(
                        "No bill of materials is available for %(product)s.",
                        product=product.display_name,
                    )
                )
            operation = line.operation_id
            destination = operation.source_location_id or operation.source_warehouse_id.lot_stock_id
            production = (
                self.env["mrp.production"]
                .with_context(
                    default_date_deadline=operation.stock_preparation_deadline
                    or operation.planned_start
                )
                .create(
                    {
                        "product_id": product.id,
                        "product_qty": quantity,
                        "product_uom_id": product.uom_id.id,
                        "bom_id": bom.id,
                        "location_dest_id": destination.id,
                        "date_deadline": operation.stock_preparation_deadline
                        or operation.planned_start,
                        # A source-document reference built from record names, not prose.
                        "origin": f"{operation.name} / {line.display_name}",
                        "company_id": line.company_id.id,
                        "mb_market_stock_plan_line_id": line.id,
                        "mb_commercial_operation_id": operation.id,
                    }
                )
            )
            production.message_post(
                body=_(
                    "Draft supply proposal for commercial stock target %(target)s. Review components, capacity, and dates before native confirmation.",
                    target=line.display_name,
                )
            )
            line._update_supply_readiness()
        return True

    def _update_supply_readiness(self):
        super()._update_supply_readiness()
        for line in self.filtered(lambda item: item.supply_method == "manufacture"):
            orders = line.production_ids.filtered(lambda production: production.state != "cancel")
            state = "shortage"
            note = _("No manufacturing supply covers this shortage.")
            if orders:
                if any(order.state == "draft" for order in orders):
                    state, note = (
                        "supply_proposed",
                        _("Draft manufacturing supply awaits review and confirmation."),
                    )
                elif any(order.state in ("progress", "to_close") for order in orders):
                    state, note = "in_progress", _("Manufacturing is in progress.")
                elif all(order.state == "done" for order in orders):
                    state, note = (
                        "ready_to_pick",
                        _(
                            "Manufacturing is complete; refresh stock availability before preparation."
                        ),
                    )
                else:
                    cutoff = (
                        line.operation_id.stock_preparation_deadline
                        or line.operation_id.planned_start
                    )
                    at_risk = any(
                        order.date_finished
                        and order.date_finished > cutoff
                        or order.components_availability_state == "unavailable"
                        for order in orders
                    )
                    state = "at_risk" if at_risk else "supply_confirmed"
                    note = (
                        _("Confirmed supply is late or lacks components.")
                        if at_risk
                        else _("Manufacturing supply is confirmed.")
                    )
            line.with_context(mb_supply_refresh=True).write(
                {"readiness": state, "blocking_note": note}
            )
        return True
