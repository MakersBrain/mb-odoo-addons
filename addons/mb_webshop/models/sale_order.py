from datetime import timedelta

from odoo import _, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _mb_original_delivered_quantity(self, line):
        """Return only quantities delivered by this order, never return moves."""
        self.ensure_one()
        line.ensure_one()
        moves = line.move_ids.filtered(
            lambda move: move.state == "done"
            and move.picking_id.picking_type_code == "outgoing"
            and not move.origin_returned_move_id
        )
        return sum(
            move.product_uom._compute_quantity(
                move.quantity, line.product_uom_id, round=False
            )
            for move in moves
        )

    def _mb_return_window_is_open(self):
        self.ensure_one()
        deliveries = self.picking_ids.filtered(
            lambda picking: picking.state == "done"
            and picking.picking_type_code == "outgoing"
            and picking.date_done
        )
        if not self.website_id or not deliveries:
            return False
        deadline = max(deliveries.mapped("date_done")) + timedelta(
            days=self.website_id.mb_return_window_days
        )
        return fields.Datetime.now() <= deadline

    def _mb_returnable_quantity(self, line):
        self.ensure_one()
        line.ensure_one()
        requested = sum(self.env["mb.webshop.return.line"].sudo().search([
            ("order_line_id", "=", line.id),
            ("return_id.state", "!=", "rejected"),
        ]).mapped("quantity"))
        return max(self._mb_original_delivered_quantity(line) - requested, 0)

    def _mb_returnable_lines(self):
        self.ensure_one()
        if (
            self.state not in ("sale", "done")
            or not self.website_id
            or not self._mb_return_window_is_open()
        ):
            return self.env["sale.order.line"]
        return self.order_line.filtered(
            lambda line: not line.is_delivery
            and not line.display_type
            and line.product_id.is_storable
            and line.product_uom_id.compare(
                self._mb_returnable_quantity(line), 0
            ) > 0
        )

    def _mb_hold_eligible(self, product):
        self.ensure_one()
        return bool(
            self.website_id
            and product.is_storable
            and not product.allow_out_of_stock_order
        )

    def _mb_active_hold(self, product):
        self.ensure_one()
        return self.env["mb.webshop.stock.hold"].sudo().search([
            ("order_id", "=", self.id),
            ("product_id", "=", product.id),
            ("state", "=", "active"),
            ("expires_at", ">", fields.Datetime.now()),
        ], limit=1)

    def _get_free_qty(self, product):
        available = super()._get_free_qty(product)
        if self._mb_hold_eligible(product):
            hold = self._mb_active_hold(product)
            if hold:
                # free_qty excludes our real reservation; add it back only to
                # the cart that owns it.
                available += product.uom_id._compute_quantity(
                    hold.move_id.quantity, product.uom_id
                )
        return available

    def _verify_updated_quantity(self, order_line, product_id, new_qty, uom_id, **kwargs):
        product = self.env["product.product"].browse(product_id)
        if self._mb_hold_eligible(product):
            holds = self.env["mb.webshop.stock.hold"].sudo()
            holds._lock_products(product)
            holds._expire_due(product)
        return super()._verify_updated_quantity(
            order_line, product_id, new_qty, uom_id, **kwargs
        )

    def _mb_cart_quantity(self, product):
        self.ensure_one()
        return sum(
            line.product_uom_id._compute_quantity(
                line.product_uom_qty, product.uom_id
            )
            for line in self.order_line.filtered(
                lambda line: line.product_id == product and not line.is_delivery
            )
        )

    def _mb_new_hold_move(self, product, quantity):
        self.ensure_one()
        destination = self.env.ref("mb_webshop.stock_location_cart_holds")
        move = self.env["stock.move"].sudo().create({
            "product_id": product.id,
            "product_uom_qty": quantity,
            "product_uom": product.uom_id.id,
            "location_id": self.warehouse_id.lot_stock_id.id,
            "location_dest_id": destination.id,
            "company_id": self.company_id.id,
            "origin": self.name,
            "procure_method": "make_to_stock",
        })
        move._action_confirm(merge=False)
        move._action_assign()
        if move.state != "assigned" or product.uom_id.compare(move.quantity, quantity) < 0:
            if move.state != "draft":
                move._do_unreserve()
            move._action_cancel()
            raise ValidationError(_(
                "%(product)s is no longer available in the requested quantity.",
                product=product.display_name,
            ))
        return move

    def _mb_sync_stock_hold(self, product):
        self.ensure_one()
        holds = self.env["mb.webshop.stock.hold"].sudo()
        holds._lock_products(product)
        hold = holds.search([
            ("order_id", "=", self.id),
            ("product_id", "=", product.id),
        ], limit=1)
        quantity = self._mb_cart_quantity(product) if self._mb_hold_eligible(product) else 0
        if hold and hold.state == "active" and hold.quantity == quantity:
            hold.write({"expires_at": holds._expires_at(self.website_id)})
            return hold
        if hold and hold.state == "active":
            hold._release_reservation("released")
        if quantity <= 0:
            return holds

        move = self._mb_new_hold_move(product, quantity)
        values = {
            "move_id": move.id,
            "quantity": quantity,
            "expires_at": holds._expires_at(self.website_id),
            "state": "active",
        }
        if hold:
            hold.write(values)
            return hold
        return holds.create({
            "order_id": self.id,
            "product_id": product.id,
            **values,
        })

    def _cart_add(self, product_id, quantity=1.0, *, uom_id=None, **kwargs):
        result = super()._cart_add(product_id, quantity, uom_id=uom_id, **kwargs)
        self._mb_sync_stock_hold(self.env["product.product"].browse(product_id))
        return result

    def _cart_update_line_quantity(self, line_id, quantity, **kwargs):
        line = self.order_line.filtered(lambda candidate: candidate.id == line_id)
        product = line.product_id
        result = super()._cart_update_line_quantity(line_id, quantity, **kwargs)
        if product:
            self._mb_sync_stock_hold(product)
        return result

    def _check_cart_is_ready_to_be_paid(self):
        for order in self:
            products = order.order_line.product_id.filtered(
                lambda product, order=order: order._mb_hold_eligible(product)
            )
            for product in products.sorted("id"):
                order._mb_sync_stock_hold(product)
        return super()._check_cart_is_ready_to_be_paid()

    def action_confirm(self):
        for order in self.filtered("website_id"):
            products = order.order_line.product_id.filtered(
                lambda product, order=order: order._mb_hold_eligible(product)
            )
            for product in products.sorted("id"):
                order._mb_sync_stock_hold(product)
            holds = self.env["mb.webshop.stock.hold"].sudo().search([
                ("order_id", "=", order.id), ("state", "=", "active")
            ])
            holds._release_reservation("converted")
        return super().action_confirm()
