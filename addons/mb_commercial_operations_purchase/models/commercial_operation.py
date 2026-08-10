from odoo import _, fields, models
from odoo.exceptions import ValidationError


class MbCommercialOperation(models.Model):
    _inherit = "mb.commercial.operation"

    purchase_order_ids = fields.One2many(
        "purchase.order", "mb_commercial_operation_id", string="Purchase Orders",
    )

    def _get_operation_profitability_items(self):
        self.ensure_one()
        items = super()._get_operation_profitability_items()
        for bill in self.purchase_order_ids.invoice_ids.filtered(
            lambda move: move.state == "posted" and move.move_type in ("in_invoice", "in_refund")
        ):
            items.append({
                "model": bill._name, "res_id": bill.id, "component": "cost",
                "date": bill.date,
                "amount": (-1 if bill.move_type == "in_refund" else 1)
                          * abs(bill.amount_untaxed_signed),
                "currency": self.currency_id,
            })
        return items

    def action_view_purchase_orders(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("purchase.purchase_rfq")
        action["domain"] = [("id", "in", self.purchase_order_ids.ids)]
        action["context"] = {"create": False}
        return action


class MbMarketStockPlanLine(models.Model):
    _inherit = "mb.market.stock.plan.line"

    supply_method = fields.Selection(
        selection_add=[("purchase", "Purchase")], ondelete={"purchase": "set default"},
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
            "shortage": "set default", "supply_proposed": "set default",
            "supply_confirmed": "set default", "in_progress": "set default",
            "at_risk": "set default", "ready_to_pick": "set default",
        },
    )
    purchase_product_id = fields.Many2one(
        "product.product", check_company=True,
        domain="[('purchase_ok', '=', True), ('is_storable', '=', True)]",
        help="Required for a bucket; an assortment shortage is never assigned to an arbitrary SKU.",
    )
    vendor_id = fields.Many2one("res.partner", string="Vendor", check_company=True)
    purchase_line_ids = fields.One2many(
        "purchase.order.line", "mb_market_stock_plan_line_id", string="Purchase Lines",
    )

    def _prepare_supply(self):
        super()._prepare_supply()
        for line in self.filtered(lambda item: item.supply_method == "purchase"):
            product = line.product_id if line.target_type == "product" else line.purchase_product_id
            if not product:
                raise ValidationError(_("Map the assortment shortage to a concrete purchasable product first."))
            if line.target_type == "product":
                line._refresh_availability()
                quantity = line.shortage_qty
            else:
                quantity = line.remaining_bucket_qty
            if quantity <= 0:
                line._update_supply_readiness()
                continue
            active = line.purchase_line_ids.filtered(lambda purchase_line: purchase_line.order_id.state != "cancel")
            if active:
                line._update_supply_readiness()
                continue
            vendor = line.vendor_id
            if not vendor:
                seller = product._select_seller(quantity=quantity, uom_id=product.uom_id)
                vendor = seller.partner_id
            if not vendor:
                raise ValidationError(_("Choose a vendor for %(product)s.", product=product.display_name))
            operation = line.operation_id
            order = operation.purchase_order_ids.filtered(
                lambda purchase, selected_vendor=vendor: (
                    purchase.partner_id == selected_vendor
                    and purchase.state in ("draft", "sent")
                )
            )[:1]
            if not order:
                order = self.env["purchase.order"].create({
                    "partner_id": vendor.id,
                    "company_id": line.company_id.id,
                    "origin": operation.name,
                    "mb_commercial_operation_id": operation.id,
                })
            seller = product._select_seller(
                partner_id=vendor,
                quantity=quantity,
                date=fields.Date.to_date(operation.stock_preparation_deadline or operation.planned_start),
                uom_id=product.uom_id,
            )
            purchase_line = self.env["purchase.order.line"].create({
                "order_id": order.id,
                "product_id": product.id,
                "product_qty": quantity,
                "product_uom_id": product.uom_id.id,
                "price_unit": seller.price if seller else 0.0,
                "date_planned": operation.stock_preparation_deadline or operation.planned_start,
                "mb_market_stock_plan_line_id": line.id,
            })
            purchase_line.order_id.message_post(body=_(
                "Draft purchase supply proposal for commercial stock target %(target)s. Review vendor, price, and deadline before native confirmation.",
                target=line.display_name,
            ))
            line._update_supply_readiness()
        return True

    def _update_supply_readiness(self):
        super()._update_supply_readiness()
        for line in self.filtered(lambda item: item.supply_method == "purchase"):
            purchase_lines = line.purchase_line_ids.filtered(lambda item: item.order_id.state != "cancel")
            state = "shortage"
            note = _("No purchase supply covers this shortage.")
            if purchase_lines:
                orders = purchase_lines.order_id
                if any(order.state in ("draft", "sent", "to approve") for order in orders):
                    state, note = "supply_proposed", _("Draft RFQ supply awaits review and confirmation.")
                elif all(order.state == "done" for order in orders):
                    state, note = "ready_to_pick", _("Purchasing is complete; refresh stock availability.")
                else:
                    cutoff = line.operation_id.stock_preparation_deadline or line.operation_id.planned_start
                    at_risk = any(item.date_planned and item.date_planned > cutoff for item in purchase_lines)
                    started = any(order.picking_ids.filtered(lambda picking: picking.state not in ("draft", "cancel", "done")) for order in orders)
                    state = "at_risk" if at_risk else "in_progress" if started else "supply_confirmed"
                    note = _("Purchased supply is scheduled after the preparation cutoff.") if at_risk else _("Purchase supply is confirmed.")
            line.with_context(mb_supply_refresh=True).write({"readiness": state, "blocking_note": note})
        return True
