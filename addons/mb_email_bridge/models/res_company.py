import ipaddress
import re

from odoo import _, fields, models, tools
from odoo.exceptions import ValidationError


HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


class ResCompany(models.Model):
    _inherit = "res.company"

    mb_webshop_mail_transport = fields.Selection(
        [("platform", "MakersBrain relay"), ("smtp", "Merchant SMTP")],
        string="Webshop mail transport",
        default="platform",
        required=True,
        copy=False,
        groups="base.group_system",
    )
    mb_webshop_smtp_server_id = fields.Many2one(
        "ir.mail_server",
        string="Webshop SMTP server",
        copy=False,
        ondelete="set null",
        groups="base.group_system",
    )

    def _mb_check_smtp_scope(self, payload):
        self.ensure_one()
        workshop_id = str(payload.get("workshop_id") or "").lower()
        if workshop_id != self.mb_control_workshop_id:
            raise ValidationError(_("SMTP workshop scope is invalid."))

    def mb_webshop_smtp_status(self, payload):
        self._mb_check_smtp_scope(payload)
        server = self.mb_webshop_smtp_server_id.sudo().exists()
        return {
            "transport": self.mb_webshop_mail_transport,
            "configured": bool(server and server.active),
            "host": server.smtp_host if server else None,
            "port": server.smtp_port if server else None,
            "encryption": (
                "starttls" if server and server.smtp_encryption == "starttls_strict"
                else "ssl" if server and server.smtp_encryption == "ssl_strict"
                else None
            ),
            "username": server.smtp_user if server else None,
            "from_email": server.from_filter if server else None,
            "password_configured": bool(server and server.smtp_pass),
        }

    def mb_configure_webshop_smtp(self, payload):
        self._mb_check_smtp_scope(payload)
        host = str(payload.get("host") or "").strip().rstrip(".").lower()
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")
        from_email = tools.email_normalize(str(payload.get("from_email") or ""))
        encryption = payload.get("encryption")
        try:
            port = int(payload.get("port"))
        except (TypeError, ValueError) as error:
            raise ValidationError(_("The SMTP port is invalid.")) from error
        try:
            ipaddress.ip_address(host)
        except ValueError:
            is_ip = False
        else:
            is_ip = True
        if (
            not HOSTNAME_RE.fullmatch(host)
            or is_ip
            or host.endswith((".local", ".localhost", ".test", ".invalid"))
            or not 1 <= port <= 65535
            or encryption not in ("starttls", "ssl")
            or not 1 <= len(username) <= 320
            or not 1 <= len(password) <= 512
            or any(character in username + password for character in "\r\n\0")
            or not from_email
        ):
            raise ValidationError(_("The SMTP credential payload is invalid."))

        old_server = self.mb_webshop_smtp_server_id.sudo().exists()
        # The controller converts exceptions into JSON responses, so this savepoint
        # must roll back the candidate even when the outer request keeps running.
        with self.env.cr.savepoint():
            candidate = self.env["ir.mail_server"].sudo().create({
                "name": f"MakersBrain webshop SMTP · {self.name}",
                "from_filter": from_email,
                "smtp_host": host,
                "smtp_port": port,
                "smtp_authentication": "login",
                "smtp_user": username,
                "smtp_pass": password,
                "smtp_encryption": {
                    "starttls": "starttls_strict",
                    "ssl": "ssl_strict",
                }[encryption],
                "sequence": 1,
                "active": True,
                "smtp_debug": False,
                "mb_webshop_smtp": True,
            })
            candidate.test_smtp_connection()
            self.write({
                "email": from_email,
                "mb_webshop_mail_transport": "smtp",
                "mb_webshop_smtp_server_id": candidate.id,
            })
        if old_server and old_server != candidate:
            old_server.unlink()
        return self.mb_webshop_smtp_status(payload)

    def mb_reset_webshop_smtp(self, payload):
        self._mb_check_smtp_scope(payload)
        server = self.mb_webshop_smtp_server_id.sudo().exists()
        self.write({
            "mb_webshop_mail_transport": "platform",
            "mb_webshop_smtp_server_id": False,
        })
        if server:
            server.unlink()
        return self.mb_webshop_smtp_status(payload)
