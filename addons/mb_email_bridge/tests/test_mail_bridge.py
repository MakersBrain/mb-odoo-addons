import os
import tempfile
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

from odoo.exceptions import AccessError, ValidationError
from odoo.service.model import get_public_method
from odoo.tests import TransactionCase, tagged

from ..controllers import main as smtp_controller


@tagged("post_install", "-at_install")
class TestTransactionalMailBridge(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company.sudo()
        cls.workshop_id = str(uuid.uuid4())
        cls.company.write(
            {
                "email": "orders@atelier.test",
                "mb_control_workshop_id": cls.workshop_id,
            }
        )
        website = (
            cls.env["website"]
            .sudo()
            .search(
                [
                    ("company_id", "in", [cls.company.id, False]),
                ],
                limit=1,
            )
        )
        website.write(
            {
                "company_id": cls.company.id,
                "mb_webshop_enabled": True,
            }
        )
        partner = cls.env["res.partner"].create(
            {
                "name": "Webshop customer",
                "email": "customer@example.fr",
            }
        )
        cls.order = cls.env["sale.order"].create(
            {
                "partner_id": partner.id,
                "company_id": cls.company.id,
            }
        )

    def test_smtp_control_services_are_private_to_rpc(self):
        for method_name in (
            "mb_webshop_smtp_status",
            "mb_configure_webshop_smtp",
            "mb_reset_webshop_smtp",
        ):
            with self.subTest(method=method_name):
                with self.assertRaises(AccessError):
                    get_public_method(self.env["res.company"], method_name)

    def test_controller_receipt_failure_is_local_and_retryable(self):
        operation_key = f"smtp:test:{uuid.uuid4()}"
        payload = {
            "operation_key": operation_key,
            "workshop_id": self.workshop_id,
            "host": "smtp.example.fr",
            "port": 587,
            "encryption": "starttls",
            "username": "orders@example.fr",
            "password": "application-password",
            "from_email": "orders@example.fr",
        }
        initial_values = (
            self.company.mb_webshop_mail_transport,
            self.company.mb_webshop_smtp_server_id,
            self.company.email,
        )
        server_domain = [("mb_webshop_smtp", "=", True)]
        servers = self.env["ir.mail_server"].sudo()
        before_servers = servers.search_count(server_domain)
        unrelated = self.env["res.partner"].create({"name": f"Unrelated {uuid.uuid4()}"})
        receipts = self.env["mb.control.operation.receipt"].sudo()
        receipt_payload = dict(payload)
        receipt_payload.pop("operation_key")
        digest = smtp_controller.payload_digest(receipt_payload)

        def make_json_response(body, status=200):
            return SimpleNamespace(body=body, status_code=status, headers={})

        fake_request = SimpleNamespace(env=self.env, make_json_response=make_json_response)
        controller = smtp_controller.WebshopSmtpBridge()

        def configure(company, body):
            return company.mb_configure_webshop_smtp(body)

        with (
            patch.object(smtp_controller, "request", fake_request),
            patch.object(smtp_controller, "authenticate_control_request"),
            patch.object(smtp_controller, "json_body", side_effect=lambda: dict(payload)),
            patch("odoo.addons.base.models.ir_mail_server.IrMail_Server.test_smtp_connection"),
            patch.object(
                type(receipts),
                "record",
                side_effect=ValidationError("receipt persistence failed"),
            ),
        ):
            response = controller._handle("webshop.smtp.configure", configure)

        self.assertEqual(response.status_code, 422)
        self.assertTrue(unrelated.exists())
        self.company.invalidate_recordset()
        self.assertEqual(
            (
                self.company.mb_webshop_mail_transport,
                self.company.mb_webshop_smtp_server_id,
                self.company.email,
            ),
            initial_values,
        )
        self.assertEqual(servers.search_count(server_domain), before_servers)
        self.assertFalse(receipts.for_replay(operation_key, "webshop.smtp.configure", digest))

        with (
            patch.object(smtp_controller, "request", fake_request),
            patch.object(smtp_controller, "authenticate_control_request"),
            patch.object(smtp_controller, "json_body", side_effect=lambda: dict(payload)),
            patch(
                "odoo.addons.base.models.ir_mail_server.IrMail_Server.test_smtp_connection"
            ) as connection_test,
        ):
            success = controller._handle("webshop.smtp.configure", configure)
            replay = controller._handle("webshop.smtp.configure", configure)

        self.assertEqual(success.status_code, 200)
        self.assertEqual(replay.body, success.body)
        self.assertEqual(connection_test.call_count, 1)

    def _mail(self):
        return (
            self.env["mail.mail"]
            .sudo()
            .create(
                {
                    "model": "sale.order",
                    "res_id": self.order.id,
                    "email_from": "orders@atelier.test",
                    "email_to": "customer@example.fr",
                    "reply_to": "studio@atelier.test",
                    "subject": "Order confirmed",
                    "body_html": "<p>Your order is confirmed.</p>",
                }
            )
        )

    def test_approved_webshop_mail_is_durably_submitted_before_marking_sent(self):
        mail = self._mail()
        response = Mock(status_code=202)
        response.raise_for_status.return_value = None
        response.json.return_value = {"operation_id": str(uuid.uuid4())}
        with tempfile.TemporaryDirectory() as root:
            token_path = os.path.join(root, self.workshop_id)
            with open(token_path, "w", encoding="utf-8") as token_file:
                token_file.write("t" * 48)
            environment = {
                "MB_CONTROL_API_URL": "http://control-api:8080",
                "MB_ODOO_CLIENT_TOKEN_ROOT": root,
            }
            with (
                patch.dict(os.environ, environment),
                patch(
                    "odoo.addons.mb_email_bridge.models.mail_mail.requests.post",
                    return_value=response,
                ) as submit,
            ):
                mail.with_context(mb_force_mail_relay=True).send(raise_exception=True)

        mail.invalidate_recordset()
        self.assertEqual(mail.state, "sent")
        request = submit.call_args
        self.assertIn(self.workshop_id, request.args[0])
        payload = request.kwargs["json"]
        self.assertEqual(payload["model"], "sale.order")
        self.assertEqual(payload["recipient"], "customer@example.fr")
        self.assertEqual(payload["reply_to"], "studio@atelier.test")
        self.assertEqual(payload["sender_name"], f"{self.company.name} via MakersBrain")
        self.assertEqual(request.kwargs["headers"]["Idempotency-Key"], payload["source_key"])

    def test_unavailable_boundary_keeps_mail_in_exception_state(self):
        mail = self._mail()
        with patch.dict(os.environ, {"MB_CONTROL_API_URL": ""}):
            mail.with_context(mb_force_mail_relay=True).send()
        mail.invalidate_recordset()
        self.assertEqual(mail.state, "exception")
        self.assertNotIn("http", mail.failure_reason.lower())

    def test_merchant_smtp_uses_strict_starttls_and_never_relays(self):
        payload = {
            "workshop_id": self.workshop_id,
            "host": "smtp.example.fr",
            "port": 587,
            "encryption": "starttls",
            "username": "orders@example.fr",
            "password": "application-password",
            "from_email": "orders@example.fr",
        }
        with patch(
            "odoo.addons.base.models.ir_mail_server.IrMail_Server.test_smtp_connection"
        ) as connection_test:
            status = self.company.mb_configure_webshop_smtp(payload)
        server = self.company.mb_webshop_smtp_server_id.sudo()
        self.assertTrue(connection_test.called)
        self.assertEqual(server.smtp_encryption, "starttls_strict")
        self.assertEqual(server.smtp_pass, "application-password")
        self.assertTrue(status["password_configured"])
        self.assertNotIn("password", status)
        self.assertFalse(self._mail()._mb_relay_company())

    def test_merchant_smtp_supports_implicit_tls_and_reset(self):
        payload = {
            "workshop_id": self.workshop_id,
            "host": "smtp.example.fr",
            "port": 465,
            "encryption": "ssl",
            "username": "orders@example.fr",
            "password": "application-password",
            "from_email": "orders@example.fr",
        }
        with patch("odoo.addons.base.models.ir_mail_server.IrMail_Server.test_smtp_connection"):
            self.company.mb_configure_webshop_smtp(payload)
        server = self.company.mb_webshop_smtp_server_id.sudo()
        self.assertEqual(server.smtp_encryption, "ssl_strict")
        status = self.company.mb_reset_webshop_smtp({"workshop_id": self.workshop_id})
        self.assertEqual(status["transport"], "platform")
        self.assertFalse(status["password_configured"])
        self.assertFalse(server.exists())

    def test_plaintext_smtp_is_rejected_without_storing_password(self):
        payload = {
            "workshop_id": self.workshop_id,
            "host": "smtp.example.fr",
            "port": 25,
            "encryption": "none",
            "username": "orders@example.fr",
            "password": "application-password",
            "from_email": "orders@example.fr",
        }
        with self.assertRaises(Exception):
            self.company.mb_configure_webshop_smtp(payload)
        self.assertFalse(self.company.mb_webshop_smtp_server_id)

    def test_managed_smtp_rejects_private_dns_answers(self):
        server = (
            self.env["ir.mail_server"]
            .sudo()
            .create(
                {
                    "name": "Unsafe SMTP",
                    "smtp_host": "smtp.example.fr",
                    "smtp_port": 587,
                    "smtp_encryption": "starttls_strict",
                    "mb_webshop_smtp": True,
                }
            )
        )
        answer = [(2, 1, 6, "", ("127.0.0.1", 587))]
        with (
            patch(
                "odoo.addons.mb_email_bridge.models.ir_mail_server.socket.getaddrinfo",
                return_value=answer,
            ),
            self.assertRaises(Exception),
        ):
            server._mb_check_public_smtp_host()

    def test_managed_smtp_rejects_dns_rebinding_and_positional_server_id(self):
        server = (
            self.env["ir.mail_server"]
            .sudo()
            .create(
                {
                    "name": "Rebinding SMTP",
                    "smtp_host": "smtp.example.fr",
                    "smtp_port": 587,
                    "smtp_encryption": "starttls_strict",
                    "mb_webshop_smtp": True,
                }
            )
        )
        answer = [(2, 1, 6, "", ("8.8.8.8", 587))]
        connection = Mock()
        connection.sock.getpeername.return_value = ("127.0.0.1", 587)
        positional = (None, None, None, None, None, None, None, None, False, server.id)
        with (
            patch(
                "odoo.addons.mb_email_bridge.models.ir_mail_server.socket.getaddrinfo",
                return_value=answer,
            ),
            patch(
                "odoo.addons.base.models.ir_mail_server.IrMail_Server._connect__",
                return_value=connection,
            ),
            self.assertRaises(ValidationError),
        ):
            server._connect__(*positional)
        connection.close.assert_called_once()

    def test_default_managed_smtp_selection_is_bound_to_dns_pin(self):
        server = (
            self.env["ir.mail_server"]
            .sudo()
            .create(
                {
                    "name": "Default managed SMTP",
                    "smtp_host": "smtp.example.fr",
                    "smtp_port": 587,
                    "smtp_encryption": "starttls_strict",
                    "mb_webshop_smtp": True,
                }
            )
        )
        answer = [(2, 1, 6, "", ("8.8.8.8", 587))]
        connection = Mock()
        connection.sock.getpeername.return_value = ("8.8.8.8", 587)
        with (
            patch.object(
                type(server),
                "_find_mail_server",
                return_value=(server, "notifications@example.fr"),
            ),
            patch(
                "odoo.addons.mb_email_bridge.models.ir_mail_server.socket.getaddrinfo",
                return_value=answer,
            ),
            patch(
                "odoo.addons.base.models.ir_mail_server.IrMail_Server._connect__",
                return_value=connection,
            ) as connect,
        ):
            result = server._connect__(smtp_from="orders@example.fr")

        self.assertEqual(result, connection)
        self.assertEqual(connect.call_args.kwargs["mail_server_id"], server.id)
        self.assertEqual(connect.call_args.kwargs["smtp_from"], "notifications@example.fr")

    def test_explicit_standard_smtp_server_is_not_subject_to_managed_pin(self):
        server = (
            self.env["ir.mail_server"]
            .sudo()
            .create(
                {
                    "name": "Standard SMTP",
                    "smtp_host": "smtp.example.fr",
                    "smtp_port": 587,
                    "smtp_encryption": "starttls_strict",
                    "mb_webshop_smtp": False,
                }
            )
        )
        connection = Mock()
        with (
            patch(
                "odoo.addons.mb_email_bridge.models.ir_mail_server.socket.getaddrinfo"
            ) as resolve,
            patch(
                "odoo.addons.base.models.ir_mail_server.IrMail_Server._connect__",
                return_value=connection,
            ) as connect,
        ):
            result = server._connect__(mail_server_id=server.id)

        self.assertEqual(result, connection)
        resolve.assert_not_called()
        self.assertEqual(connect.call_args.kwargs["mail_server_id"], server.id)

    def test_smtp_socket_is_pinned_without_changing_the_tls_hostname(self):
        from odoo.addons.mb_email_bridge.models import ir_mail_server as guard

        pin = guard._SMTP_PIN.set(("smtp.example.fr", 587, "8.8.8.8"))
        try:
            with patch.object(guard, "_ORIGINAL_CREATE_CONNECTION") as connect:
                guard._create_connection_to_pinned_smtp(("smtp.example.fr", 587), 3)
            connect.assert_called_once_with(("8.8.8.8", 587), 3)
        finally:
            guard._SMTP_PIN.reset(pin)

    def test_socket_hook_is_inert_when_no_pin_is_set(self):
        """The hook sits under every socket in the worker, so with no pin set
        it must forward its arguments to the original function untouched.
        """
        from odoo.addons.mb_email_bridge.models import ir_mail_server as guard

        self.assertIsNone(guard._SMTP_PIN.get(), "a previous test leaked a pin")
        with patch.object(guard, "_ORIGINAL_CREATE_CONNECTION") as connect:
            guard._create_connection_to_pinned_smtp(
                ("example.invalid", 443), 7, source_address=("0.0.0.0", 0)
            )
        connect.assert_called_once_with(("example.invalid", 443), 7, source_address=("0.0.0.0", 0))

    def test_pin_does_not_affect_unrelated_connections(self):
        """An active pin rewrites only the address it pinned. Any other host or
        port -- an HTTP client in another addon, say -- passes through.
        """
        from odoo.addons.mb_email_bridge.models import ir_mail_server as guard

        pin = guard._SMTP_PIN.set(("smtp.example.fr", 587, "8.8.8.8"))
        try:
            for label, address in [
                ("different host", ("api.example.fr", 587)),
                ("different port", ("smtp.example.fr", 465)),
            ]:
                with self.subTest(case=label):
                    with patch.object(guard, "_ORIGINAL_CREATE_CONNECTION") as connect:
                        guard._create_connection_to_pinned_smtp(address)
                    connect.assert_called_once_with(address)
        finally:
            guard._SMTP_PIN.reset(pin)

    def test_failed_company_projection_does_not_leave_smtp_candidate(self):
        payload = {
            "workshop_id": self.workshop_id,
            "host": "smtp.example.fr",
            "port": 587,
            "encryption": "starttls",
            "username": "orders@example.fr",
            "password": "application-password",
            "from_email": "orders@example.fr",
        }
        before = (
            self.env["ir.mail_server"]
            .sudo()
            .search_count(
                [
                    ("mb_webshop_smtp", "=", True),
                ]
            )
        )
        with (
            patch("odoo.addons.base.models.ir_mail_server.IrMail_Server.test_smtp_connection"),
            patch.object(
                type(self.company), "write", side_effect=ValidationError("projection failed")
            ),
            self.assertRaises(ValidationError),
        ):
            self.company.mb_configure_webshop_smtp(payload)
        self.assertEqual(
            self.env["ir.mail_server"]
            .sudo()
            .search_count(
                [
                    ("mb_webshop_smtp", "=", True),
                ]
            ),
            before,
        )
