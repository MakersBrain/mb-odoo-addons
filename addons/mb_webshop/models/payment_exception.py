from odoo import _, fields, models
from odoo.exceptions import UserError

from ..exceptions import WebshopStockUnavailable


class WebshopPaymentException(models.Model):
    _name = "mb.webshop.payment.exception"
    _description = "Recoverable webshop payment exception"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "created_at desc, id desc"

    transaction_id = fields.Many2one(
        "payment.transaction", required=True, readonly=True, index=True,
        ondelete="restrict",
    )
    order_id = fields.Many2one(
        "sale.order", required=True, readonly=True, index=True, ondelete="restrict",
    )
    company_id = fields.Many2one(
        "res.company", related="order_id.company_id", store=True, index=True,
    )
    website_id = fields.Many2one(
        "website", related="order_id.website_id", store=True, index=True,
    )
    reason = fields.Selection(
        [("stock_unavailable", "Stock unavailable after payment")],
        required=True, readonly=True,
    )
    state = fields.Selection(
        [
            ("open", "Needs action"),
            ("refund_pending", "Refund pending"),
            ("fulfilled", "Fulfilment recovered"),
            ("refunded", "Refunded"),
        ],
        required=True, default="open", tracking=True, index=True,
    )
    refund_transaction_id = fields.Many2one(
        "payment.transaction", readonly=True, copy=False, ondelete="restrict",
    )
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    resolved_at = fields.Datetime(readonly=True)

    _transaction_unique = models.Constraint(
        "UNIQUE(transaction_id)",
        "A payment can have only one webshop payment exception.",
    )

    def action_retry_fulfilment(self):
        for exception in self:
            if exception.state != "open":
                raise UserError(_("Only an open payment exception can be retried."))
            try:
                with self.env.cr.savepoint():
                    exception.order_id.with_context(send_email=False).action_confirm()
                    exception.transaction_id.sudo().with_context(
                        mb_webshop_retry_fulfilment=True
                    )._post_process()
            except WebshopStockUnavailable as error:
                raise UserError(_(
                    "Stock is still unavailable. Replenish or substitute the item, "
                    "then retry; otherwise refund the payment."
                )) from error
            exception.write({
                "state": "fulfilled", "resolved_at": fields.Datetime.now(),
            })
        return True

    def action_refund(self):
        for exception in self:
            if exception.state != "open":
                raise UserError(_("Only an open payment exception can be refunded."))
            transaction = exception.transaction_id.sudo()
            if transaction.state != "done":
                raise UserError(_("Only a captured payment can be refunded."))
            with self.env.cr.savepoint():
                refund = transaction._refund(amount_to_refund=transaction.amount)
                if refund.state in ("cancel", "error"):
                    raise UserError(_(
                        "The refund provider rejected the request. Correct the provider "
                        "problem, then try the refund again."
                    ))
            exception.write({
                "refund_transaction_id": refund.id,
                "state": "refunded" if refund.state == "done" else "refund_pending",
                "resolved_at": fields.Datetime.now() if refund.state == "done" else False,
            })
        return True


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    def _check_amount_and_confirm_order(self):
        confirmed = self.env["sale.order"]
        for transaction in self:
            existing = self.env["mb.webshop.payment.exception"].sudo().search([
                ("transaction_id", "=", transaction.id),
            ], limit=1)
            if existing:
                confirmed |= transaction.sale_order_ids
                continue
            try:
                with self.env.cr.savepoint():
                    confirmed |= super(PaymentTransaction, transaction)._check_amount_and_confirm_order()
            except WebshopStockUnavailable:
                order = transaction.sale_order_ids.filtered(
                    lambda candidate: candidate.website_id
                    and candidate.state in ("draft", "sent")
                )
                if len(order) != 1:
                    raise
                self.env["mb.webshop.payment.exception"].sudo().create({
                    "transaction_id": transaction.id,
                    "order_id": order.id,
                    "reason": "stock_unavailable",
                })
        return confirmed

    def _set_done(self, state_message=None, extra_allowed_states=()):
        result = super()._set_done(
            state_message=state_message, extra_allowed_states=extra_allowed_states
        )
        exceptions = self.env["mb.webshop.payment.exception"].sudo().search([
            ("refund_transaction_id", "in", result.ids),
            ("state", "=", "refund_pending"),
        ])
        if exceptions:
            exceptions.write({"state": "refunded", "resolved_at": fields.Datetime.now()})
        return result

    def _set_error(self, state_message, extra_allowed_states=()):
        result = super()._set_error(
            state_message, extra_allowed_states=extra_allowed_states
        )
        exceptions = self.env["mb.webshop.payment.exception"].sudo().search([
            ("refund_transaction_id", "in", result.ids),
            ("state", "=", "refund_pending"),
        ])
        if exceptions:
            exceptions.write({
                "state": "open", "refund_transaction_id": False, "resolved_at": False,
            })
        return result

    def _set_canceled(self, state_message=None, extra_allowed_states=()):
        result = super()._set_canceled(
            state_message=state_message, extra_allowed_states=extra_allowed_states
        )
        exceptions = self.env["mb.webshop.payment.exception"].sudo().search([
            ("refund_transaction_id", "in", result.ids),
            ("state", "=", "refund_pending"),
        ])
        if exceptions:
            exceptions.write({
                "state": "open", "refund_transaction_id": False, "resolved_at": False,
            })
        return result
