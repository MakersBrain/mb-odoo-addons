from datetime import timedelta

from odoo import _, api, fields, models


class WebshopStockHold(models.Model):
    _name = "mb.webshop.stock.hold"
    _description = "Atomic webshop cart stock hold"
    _order = "expires_at, id"

    order_id = fields.Many2one(
        "sale.order", required=True, index=True, ondelete="cascade", readonly=True
    )
    product_id = fields.Many2one(
        "product.product", required=True, index=True, ondelete="restrict", readonly=True
    )
    move_id = fields.Many2one(
        "stock.move", index=True, ondelete="set null", readonly=True
    )
    quantity = fields.Float(required=True, readonly=True)
    expires_at = fields.Datetime(required=True, index=True, readonly=True)
    state = fields.Selection(
        [
            ("active", "Active"),
            ("expired", "Expired"),
            ("released", "Released"),
            ("converted", "Converted to order"),
        ],
        required=True,
        default="active",
        index=True,
        readonly=True,
    )

    _order_product_unique = models.Constraint(
        "UNIQUE(order_id, product_id)",
        "A cart can have only one stock hold per product.",
    )

    @api.model
    def _lock_products(self, products):
        ids = sorted(set(products.ids))
        if ids:
            self.env.cr.execute(
                "SELECT id FROM product_product WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
                [ids],
            )

    @api.model
    def _expires_at(self, website):
        minutes = website.mb_cart_hold_minutes or 15
        return fields.Datetime.now() + timedelta(minutes=minutes)

    def _release_reservation(self, state):
        for hold in self:
            move = hold.move_id.sudo().exists()
            if move and move.state not in ("done", "cancel"):
                if move.state != "draft":
                    move._do_unreserve()
                move._action_cancel()
            hold.write({"state": state})

    @api.model
    def _expire_due(self, products=None):
        domain = [
            ("state", "=", "active"),
            ("expires_at", "<=", fields.Datetime.now()),
        ]
        if products:
            domain.append(("product_id", "in", products.ids))
        due = self.sudo().search(domain)
        if not due:
            return 0
        self._lock_products(due.product_id)
        # Re-read after waiting: a cart request may have refreshed the hold.
        due = self.sudo().search([
            ("id", "in", due.ids),
            ("state", "=", "active"),
            ("expires_at", "<=", fields.Datetime.now()),
        ])
        due._release_reservation("expired")
        for order in due.order_id.filtered(lambda order: order.state in ("draft", "sent")):
            order.shop_warning = _(
                "A cart stock hold expired. Availability will be checked again before payment."
            )
        return len(due)
