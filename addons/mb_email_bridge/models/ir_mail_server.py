"""Pin managed SMTP connections to an address that was checked to be public.

The threat is DNS rebinding. `_mb_check_public_smtp_host` resolves the
configured SMTP host and refuses any answer that is not globally routable, but
between that check and smtplib's own connect there is a second resolution, and
a hostile DNS server is free to answer differently the second time -- returning
a link-local or RFC1918 address and turning the mail server into a probe of the
internal network. Closing that window means the address checked has to be the
address connected to, and smtplib offers no seam for supplying one.

Scope of the patch, stated plainly
----------------------------------
This module replaces `socket.create_connection` -- a *standard library*
function, not an Odoo one -- for the whole worker process. Every socket opened
by every library in the process passes through `_create_connection_to_pinned_smtp`
afterwards, including all the HTTP clients in the other MakersBrain addons.

That is acceptable only because the hook is inert by default. It reads a
`ContextVar` that is set solely by `_connect__`, around the single `super()`
call, and reset in a `finally`. With no pin set the hook forwards its arguments
to the original function unchanged, and with a pin set it rewrites only an
address that matches the pinned `(host, port)` exactly. Anything else -- a
different host, a different port, any socket opened by any other code -- is
passed through untouched. `test_socket_hook_is_inert_when_no_pin_is_set` and
`test_pin_does_not_affect_unrelated_connections` hold that line.

The original function is stashed on the `socket` module itself rather than in a
module global, so that reloading this module during development re-wraps the
true original instead of wrapping the previous wrapper.

Only the TCP destination is substituted. smtplib keeps the configured hostname
for TLS SNI and certificate validation, so pinning the address does not weaken
certificate checking.
"""

import ipaddress
import socket
from contextvars import ContextVar

from odoo import _, fields, models
from odoo.exceptions import ValidationError

_SMTP_PIN = ContextVar("mb_webshop_smtp_pin", default=None)
_ORIGINAL_CREATE_CONNECTION = getattr(
    socket, "_mb_webshop_original_create_connection", socket.create_connection
)
# mypy cannot know about an attribute stashed on a stdlib module at import
# time. The stash is deliberate; see the reload note in the module docstring.
socket._mb_webshop_original_create_connection = _ORIGINAL_CREATE_CONNECTION  # type: ignore[attr-defined]


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
                raise ValidationError(
                    _("The SMTP connection did not use an approved public address.")
                )
        return connection
