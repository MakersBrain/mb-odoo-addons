import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MbSumupLinkWizard(models.TransientModel):
    _name = "mb.sumup.link.wizard"
    _description = "Invoice payment link and QR code"

    move_id = fields.Many2one(
        comodel_name="account.move",
        string="Invoice",
        required=True,
        readonly=True,
    )
    currency_id = fields.Many2one(related="move_id.currency_id")
    amount = fields.Monetary(
        currency_field="currency_id",
        required=True,
        help="What the customer is asked to pay now. Defaults to what is left on the invoice.",
    )
    amount_max = fields.Monetary(currency_field="currency_id", readonly=True)
    destination = fields.Selection(
        string="Payment destination",
        selection=[
            ("sumup", "SumUp checkout"),
            ("portal", "Customer portal"),
        ],
        default="sumup",
        required=True,
        help="SumUp: the customer pays on SumUp's own page, and never has to "
        "reach this server. Customer portal: they land on the invoice "
        "here and choose how to pay.",
    )
    link = fields.Char(string="Payment link", readonly=True)
    qr_code = fields.Binary(string="QR code", compute="_compute_qr_code")
    warning_message = fields.Char(compute="_compute_warning_message")

    # === DEFAULTS === #

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        move_id = res.get("move_id") or self.env.context.get("default_move_id")
        if move_id:
            move = self.env["account.move"].browse(move_id)
            residual = move.amount_residual or move.amount_total
            res.setdefault("amount", residual)
            res.setdefault("amount_max", residual)
        return res

    # === COMPUTE METHODS === #

    @api.depends("amount", "amount_max")
    def _compute_warning_message(self):
        for wizard in self:
            wizard.warning_message = ""
            if wizard.amount <= 0:
                wizard.warning_message = _("Set a positive amount.")
            elif wizard.amount_max and wizard.amount > wizard.amount_max:
                wizard.warning_message = _(
                    "This is more than the %s still due on the invoice.",
                    wizard.currency_id.format(wizard.amount_max),
                )

    @api.depends("link")
    def _compute_qr_code(self):
        """Render the link as a QR code with Odoo's own barcode endpoint.

        Locally rendered on purpose: an invoice PDF that fetches an image from
        somebody else's server is an invoice that stops printing the day that
        server moves.
        """
        for wizard in self:
            if not wizard.link:
                wizard.qr_code = False
                continue
            barcode = self.env["ir.actions.report"].barcode(
                "QR", wizard.link, width=256, height=256, barLevel="M"
            )
            wizard.qr_code = base64.b64encode(barcode)

    # === ACTIONS === #

    def action_generate(self):
        """Produce the link and stay open so it can be copied or scanned."""
        self.ensure_one()

        if self.amount <= 0:
            raise UserError(_("Set a positive amount."))

        if self.destination == "sumup":
            self.move_id.invalidate_recordset(["amount_residual"])
            if self.currency_id.compare_amounts(self.amount, self.move_id.amount_residual) > 0:
                raise UserError(
                    _(
                        "The amount cannot exceed the %s still due on the invoice.",
                        self.currency_id.format(self.move_id.amount_residual),
                    )
                )
            tx_sudo = self.move_id._mb_sumup_get_or_create_transaction(self.amount)
            self.link = tx_sudo.sumup_checkout_url
        else:
            self.link = self._mb_portal_link()

        return {
            "type": "ir.actions.act_window",
            "name": _("Payment link"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _mb_portal_link(self):
        """Return Odoo's own payment link for this invoice.

        Built by `payment.link.wizard` rather than by hand: the access token it
        signs is what makes the URL usable by someone who is not logged in, and
        reimplementing that is how signature schemes drift apart.

        Note: `self.ensure_one()`

        :return: The portal payment URL.
        :rtype: str
        """
        self.ensure_one()

        link_wizard = (
            self.env["payment.link.wizard"]
            .with_context(active_model="account.move", active_id=self.move_id.id)
            .create({"amount": self.amount})
        )
        return link_wizard.link
