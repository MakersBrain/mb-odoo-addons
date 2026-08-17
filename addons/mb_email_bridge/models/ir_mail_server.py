import ipaddress
import socket
from contextvars import ContextVar

from odoo import _, fields, models
from odoo.exceptions import ValidationError


_SMTP_PIN = ContextVar("mb_webshop_smtp_pin", default=None)
_ORIGINAL_CREATE_CONNECTION = getattr(
    socket, "_mb_webshop_original_create_connection", socket.create_connection
)
socket._mb_webshop_original_create_connection = _ORIGINAL_CREATE_CONNECTION


def _create_connection_to_pinned_smtp(address, *args, **kwargs):
    pin = _SMTP_PIN.get()
    if pin and address == pin[:2]:
        address = (pin[2], address[1])
    return _ORIGINAL_CREATE_CONNECTION(address, *args, **kwargs)


# smtplib retains the original hostname for TLS SNI and certificate validation,
# while this context-local socket hook substitutes only the TCP destination.
socket.create_connection = _create_connection_to_pinned_smtp


class IrMailServer(models.Model):
    _inherit = "ir.mail_server"

    mb_webshop_smtp = fields.Boolean(
        string="MakersBrain webshop SMTP",
        default=False,
        copy=False,
        groups="base.group_system",
    )

    def _mb_check_public_smtp_host(self):
        approved = set()
        for server in self.filtered("mb_webshop_smtp"):
            host = (server.smtp_host or "").strip().rstrip(".")
            try:
                addresses = socket.getaddrinfo(host, server.smtp_port, type=socket.SOCK_STREAM)
            except socket.gaierror as error:
                raise ValidationError(_("The SMTP hostname could not be resolved.")) from error
            if not addresses or any(
                not ipaddress.ip_address(address[4][0]).is_global for address in addresses
            ):
                raise ValidationError(_("The SMTP hostname must resolve only to public addresses."))
            approved.update(address[4][0] for address in addresses)
        return approved

    def _connect__(self, *args, **kwargs):
        args = list(args)
        # Odoo's signature permits mail_server_id as the tenth positional argument.
        server_id = kwargs.get("mail_server_id") or (args[9] if len(args) > 9 else None)
        host = kwargs.get("host") if "host" in kwargs else (args[0] if args else None)
        if not server_id and not host:
            smtp_from = (
                kwargs.get("smtp_from")
                if "smtp_from" in kwargs
                else (args[5] if len(args) > 5 else None)
            )
            selected, selected_smtp_from = self.sudo()._find_mail_server(smtp_from)
            if selected and selected.mb_webshop_smtp:
                # Bind the server selected by Odoo into the actual connection call.
                # Otherwise core selects it a second time after this guard, leaving
                # the normal no-mail_server_id path outside the DNS pin.
                server_id = selected.id
                if len(args) > 9:
                    args[9] = server_id
                else:
                    kwargs["mail_server_id"] = server_id
                if len(args) > 5:
                    args[5] = selected_smtp_from
                else:
                    kwargs["smtp_from"] = selected_smtp_from
        approved_addresses = set()
        pin_token = None
        pinned_address = None
        if server_id:
            server = self.sudo().browse(server_id).exists()
            if server and server.mb_webshop_smtp:
                approved_addresses = server._mb_check_public_smtp_host()
                # smtplib connects using the field value verbatim. Keep that exact value
                # for the context pin while the resolver check uses its normalized form.
                hostname = server.smtp_host
                pinned_address = sorted(approved_addresses)[0]
                pin_token = _SMTP_PIN.set((hostname, server.smtp_port, pinned_address))
        try:
            connection = super()._connect__(*args, **kwargs)
        finally:
            if pin_token is not None:
                _SMTP_PIN.reset(pin_token)
        if pinned_address and connection and getattr(connection, "sock", None):
            peer = connection.sock.getpeername()[0]
            if peer != pinned_address or not ipaddress.ip_address(peer).is_global:
                connection.close()
                raise ValidationError(_(
                    "The SMTP connection did not use an approved public address."
                ))
        return connection
