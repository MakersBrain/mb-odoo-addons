import base64
import hashlib
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

from odoo import _, models, modules, tools
from odoo.addons.base.models.ir_mail_server import MailDeliveryException
from odoo.exceptions import UserError


APPROVED_MODELS = {
    "account.move",
    "mb.webshop.return",
    "sale.order",
    "stock.picking",
}
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024


class MailMail(models.Model):
    _inherit = "mail.mail"

    def _mb_relay_company(self):
        self.ensure_one()
        if self.model not in APPROVED_MODELS or not self.res_id:
            return self.env["res.company"]
        record = self.env[self.model].sudo().browse(self.res_id).exists()
        company = record.company_id if record and "company_id" in record._fields else False
        if not company or not UUID_RE.fullmatch(company.mb_control_workshop_id or ""):
            return self.env["res.company"]
        if company.mb_webshop_mail_transport != "platform":
            return self.env["res.company"]
        enabled = self.env["website"].sudo().search_count([
            ("company_id", "in", [company.id, False]),
            ("mb_webshop_enabled", "=", True),
        ])
        return company if enabled and tools.email_normalize(company.email or "") else self.env["res.company"]

    def _mb_control_token(self, company):
        root = os.environ.get(
            "MB_ODOO_CLIENT_TOKEN_ROOT", "/run/mb-odoo-client-secrets"
        )
        try:
            token_file = (Path(root) / company.mb_control_workshop_id).resolve(strict=True)
            root_path = Path(root).resolve(strict=True)
            if (
                root_path not in token_file.parents
                or not token_file.is_file()
                or token_file.stat().st_size > 4096
            ):
                raise OSError
            token = token_file.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise UserError(_("Transactional email authentication is unavailable.")) from error
        if len(token) < 32 or any(character in token for character in "\r\n"):
            raise UserError(_("Transactional email authentication is unavailable."))
        return token

    def _mb_submit(self, company, source_key, payload):
        base_url = os.environ.get("MB_CONTROL_API_URL", "").strip().rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise UserError(_("The MakersBrain transactional email service is unavailable."))
        try:
            response = requests.post(
                f"{base_url}/internal/v1/workshops/{company.mb_control_workshop_id}/webshop-mails",
                headers={
                    "Authorization": f"Bearer {self._mb_control_token(company)}",
                    "Idempotency-Key": source_key,
                },
                json=payload,
                timeout=(3.05, 15),
                allow_redirects=False,
            )
            response.raise_for_status()
            result = response.json()
            if response.status_code != 202 or not UUID_RE.fullmatch(
                str(result.get("operation_id") or "").lower()
            ):
                raise ValueError("mail boundary returned an invalid response")
        except (requests.RequestException, ValueError) as error:
            raise UserError(_("The transactional email could not be queued. Try again.")) from error

    def _mb_relay_one(self, company):
        self.ensure_one()
        outgoing = self._prepare_outgoing_list()
        if not outgoing:
            raise UserError(_("The transactional email has no valid recipient."))
        success_pids = []
        success_emails = []
        for index, email in enumerate(outgoing):
            recipients = list(dict.fromkeys(email.get("email_to_normalized") or []))
            if not recipients:
                raise UserError(_("The transactional email has no valid recipient."))
            attachments = []
            total = 0
            for name, raw, mimetype in email.get("attachments") or []:
                total += len(raw)
                if total > MAX_ATTACHMENT_BYTES:
                    raise UserError(_("Transactional email attachments exceed 8 MiB."))
                attachments.append({
                    "name": name,
                    "content_type": mimetype or "application/octet-stream",
                    "content_base64": base64.b64encode(raw).decode("ascii"),
                })
            for recipient in recipients:
                recipient_hash = hashlib.sha256(recipient.encode("utf-8")).hexdigest()[:16]
                source_key = f"odoo:{self.id}:{index}:{recipient_hash}"
                self._mb_submit(company, source_key, {
                    "source_key": source_key,
                    "recipient": recipient,
                    "subject": email.get("subject") or "",
                    "text": email.get("body_alternative") or "",
                    "html": email.get("body") or "",
                    "sender_name": f"{company.name} via MakersBrain",
                    "reply_to": tools.email_normalize(email.get("reply_to") or company.email),
                    "model": self.model,
                    "attachments": attachments,
                })
            partner = email.get("partner_id")
            if partner:
                success_pids.append(partner.id)
            else:
                success_emails.extend(recipients)
        self.write({
            "state": "sent",
            "failure_type": False,
            "failure_reason": False,
        })
        self._postprocess_sent_message(
            success_pids=success_pids,
            success_emails=success_emails,
        )

    def send(self, auto_commit=False, raise_exception=False, post_send_callback=None):
        if modules.module.current_test and not self.env.context.get("mb_force_mail_relay"):
            return super().send(
                auto_commit=auto_commit,
                raise_exception=raise_exception,
                post_send_callback=post_send_callback,
            )
        relay = self.filtered(lambda mail: bool(mail._mb_relay_company()))
        native = self - relay
        if native:
            super(MailMail, native).send(
                auto_commit=auto_commit,
                raise_exception=raise_exception,
                post_send_callback=post_send_callback,
            )
        for mail in relay:
            try:
                mail._mb_relay_one(mail._mb_relay_company())
                if post_send_callback:
                    post_send_callback(mail.ids)
                if auto_commit:
                    self.env.cr.commit()
            except Exception as error:
                mail.write({
                    "state": "exception",
                    "failure_type": "unknown",
                    "failure_reason": _("MakersBrain transactional email submission failed."),
                })
                mail._postprocess_sent_message(
                    success_pids=[],
                    success_emails=[],
                    failure_type="unknown",
                    failure_reason=mail.failure_reason,
                )
                if raise_exception:
                    raise MailDeliveryException(mail.failure_reason) from error
        return True
