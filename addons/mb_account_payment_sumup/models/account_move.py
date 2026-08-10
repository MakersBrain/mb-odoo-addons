import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tools.image import image_data_uri


class AccountMove(models.Model):
    _inherit = "account.move"

    mb_sumup_transaction_id = fields.Many2one(
        comodel_name="payment.transaction",
        string="SumUp Checkout",
        readonly=True,
        copy=False,
        help="The transaction behind this invoice's SumUp payment link.",
    )
    mb_sumup_checkout_url = fields.Char(
        string="SumUp Payment Link",
        related="mb_sumup_transaction_id.sumup_checkout_url",
        readonly=True,
    )

    # === COMPUTE METHODS === #

    @api.depends("company_id", "mb_sumup_checkout_url")
    def _compute_display_link_qr_code(self):
        """Override of `account` to print one QR code rather than two.

        Odoo already prints a QR code for its own portal link. A SumUp checkout
        answers the same question - how do I pay this? - so when one exists it
        takes the space: two QR codes on an invoice is a question, not an
        instruction.
        """
        super()._compute_display_link_qr_code()
        for move in self:
            if move.mb_sumup_checkout_url:
                move.display_link_qr_code = False

    # === ACTIONS === #

    def action_mb_sumup_payment_link(self):
        """Open the wizard that turns this invoice into something scannable."""
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": _("Payment link"),
            "res_model": "mb.sumup.link.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_move_id": self.id},
        }

    # === BUSINESS METHODS === #

    def _mb_sumup_payment_qr(self):
        """Return the SumUp checkout link as an image to print.

        Note: `self.ensure_one()`

        :return: A data URI, or an empty string when there is no link.
        :rtype: str
        """
        self.ensure_one()

        if not self.mb_sumup_checkout_url:
            return ""
        barcode = self.env["ir.actions.report"].barcode(
            "QR", self.mb_sumup_checkout_url, width=128, height=128,
            quiet=False, barLevel="M",
        )
        return image_data_uri(base64.b64encode(barcode))

    def _mb_sumup_provider(self):
        """Return the SumUp provider that may take this invoice's payment.

        Note: `self.ensure_one()`

        :return: The provider record.
        :rtype: recordset of `payment.provider`
        :raise UserError: If this company has no usable SumUp provider.
        """
        self.ensure_one()

        provider_model = self.env["payment.provider"].sudo()
        # One provider record per company, which is the point: the money has to
        # land in the account belonging to the company invoicing.
        provider = provider_model.search([
            ("code", "=", "sumup"),
            ("state", "in", ("enabled", "test")),
            *provider_model._check_company_domain(self.company_id),
        ], limit=1)
        if not provider:
            raise UserError(_(
                "No SumUp payment provider is enabled for %s.", self.company_id.display_name
            ))
        return provider

    def _mb_sumup_get_or_create_transaction(self, amount):
        """Return the transaction holding this invoice's SumUp checkout.

        An open checkout for the same amount is reused rather than replaced: a
        link printed on a PDF that has already left the building has to keep
        working, and every extra checkout is a line in the merchant's reporting
        that nobody will ever reconcile.

        Note: `self.ensure_one()`

        :param float amount: The amount to be paid.
        :return: The transaction.
        :rtype: recordset of `payment.transaction`
        :raise UserError: If SumUp refuses to create the checkout.
        """
        self.ensure_one()

        # Checkout creation is an external side effect.  Serialize it per
        # invoice so two workers cannot both observe an empty field and mint
        # two independently payable links.
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            [0x4D425355, self.id],
        )
        self.invalidate_recordset(["amount_residual", "mb_sumup_transaction_id"])

        if self.state != "posted" or self.move_type not in ("out_invoice", "out_refund"):
            raise UserError(_("Only a posted customer invoice can have a SumUp payment link."))
        residual = self.amount_residual
        if residual <= 0:
            raise UserError(_("This invoice has nothing left to pay."))
        if amount <= 0 or self.currency_id.compare_amounts(amount, residual) > 0:
            raise UserError(_(
                "The SumUp checkout amount cannot exceed the amount still due (%s).",
                self.currency_id.format(residual),
            ))

        existing = self.mb_sumup_transaction_id
        if (
            existing.state in ("draft", "pending")
            and existing.sumup_checkout_url
            and self.currency_id.compare_amounts(existing.amount, amount) == 0
        ):
            return existing

        if existing.state in ("draft", "pending") and existing.provider_reference:
            # A replaced QR/link must stop being payable before its successor
            # exists.  SumUp refuses DELETE once a checkout was processed; in
            # that case abort and let polling reconcile it rather than risk an
            # overpayment through two live checkouts.
            existing.sudo()._sumup_deactivate_checkout()

        provider = self._mb_sumup_provider()
        payment_method = provider.payment_method_ids.filtered(
            lambda pm: pm.code == "card"
        )[:1] or provider.payment_method_ids[:1]
        if not self.partner_id:
            raise UserError(_("Set a customer on the invoice before asking them to pay."))

        tx_sudo = self.env["payment.transaction"].sudo().create({
            "provider_id": provider.id,
            "payment_method_id": payment_method.id,
            "partner_id": self.partner_id.id,
            "amount": amount,
            "currency_id": self.currency_id.id,
            # The customer follows a link to a hosted page, which is a redirect
            # flow whether the link was clicked or scanned off a sheet of paper.
            "operation": "online_redirect",
            "invoice_ids": [Command.set(self.ids)],
        })
        if not tx_sudo._sumup_create_checkout():
            raise UserError(
                tx_sudo.state_message or _("SumUp did not return a payment link.")
            )

        self.sudo().mb_sumup_transaction_id = tx_sudo
        return tx_sudo
