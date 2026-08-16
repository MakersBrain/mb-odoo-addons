import ipaddress
from urllib.parse import urlsplit

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class Website(models.Model):
    _inherit = "website"

    mb_webshop_enabled = fields.Boolean(
        string="MakersBrain webshop enabled",
        default=True,
        copy=False,
        help="Controlled by the MakersBrain webshop capability.",
    )
    mb_cart_hold_minutes = fields.Integer(
        string="Cart stock hold (minutes)",
        default=15,
        help="How long checkout stock remains reserved after cart activity.",
    )
    mb_return_window_days = fields.Integer(
        string="Customer return window (days)",
        default=30,
        help="Days after delivery during which a customer can request a return.",
    )
    mb_ready_catalog = fields.Boolean(
        string="Published catalogue",
        compute="_compute_mb_launch_readiness",
    )
    mb_ready_online_payment = fields.Boolean(
        string="Production online payment",
        compute="_compute_mb_launch_readiness",
    )
    mb_ready_fulfilment = fields.Boolean(
        string="Published fulfilment method",
        compute="_compute_mb_launch_readiness",
    )
    mb_ready_sender = fields.Boolean(
        string="Transactional email sender",
        compute="_compute_mb_launch_readiness",
    )
    mb_ready_domain = fields.Boolean(
        string="Public store URL",
        compute="_compute_mb_launch_readiness",
    )
    mb_ready_returns = fields.Boolean(
        string="Returns policy",
        compute="_compute_mb_launch_readiness",
    )
    mb_launch_ready = fields.Boolean(
        string="Application launch ready",
        compute="_compute_mb_launch_readiness",
        help=(
            "All application configuration checks pass. DNS, TLS, provider "
            "webhooks, email deliverability and a live checkout still require "
            "deployment qualification."
        ),
    )
    mb_ready_product_count = fields.Integer(compute="_compute_mb_launch_readiness")
    mb_ready_payment_count = fields.Integer(compute="_compute_mb_launch_readiness")
    mb_ready_fulfilment_count = fields.Integer(compute="_compute_mb_launch_readiness")

    def _mb_has_public_domain(self):
        self.ensure_one()
        value = (self.domain or "").strip()
        if not value:
            return False
        parsed = urlsplit(value if "://" in value else f"//{value}")
        hostname = (parsed.hostname or "").rstrip(".").lower()
        if (
            not hostname
            or "." not in hostname
            or hostname == "localhost"
            or hostname in {"example.com", "example.net", "example.org"}
            or hostname.endswith((
                ".localhost", ".local", ".test", ".invalid",
                ".example.com", ".example.net", ".example.org",
            ))
        ):
            return False
        try:
            return ipaddress.ip_address(hostname).is_global
        except ValueError:
            return True

    def _mb_webshop_readiness(self):
        """Return strict, application-level evidence for a production launch.

        This intentionally does not replace deployment qualification. In
        particular, a configured domain is not proof that DNS and TLS work,
        and an enabled provider is not proof that its webhook is reachable.
        """
        self.ensure_one()
        website_scope = [False, self.id]
        company_scope = [False, self.company_id.id]
        products = self.env["product.template"].sudo().search_count([
            ("active", "=", True),
            ("sale_ok", "=", True),
            ("is_published", "=", True),
            ("website_id", "in", website_scope),
            ("company_id", "in", company_scope),
        ])
        payments = self.env["payment.provider"].sudo().search_count([
            ("state", "=", "enabled"),
            ("is_published", "=", True),
            ("code", "not in", ["none", "custom", "demo"]),
            ("website_id", "in", website_scope),
            ("company_id", "=", self.company_id.id),
        ])
        fulfilment = self.env["delivery.carrier"].sudo().search_count([
            ("active", "=", True),
            ("is_published", "=", True),
            ("website_id", "in", website_scope),
            ("company_id", "in", company_scope),
        ])
        sender_ready = bool(
            self.company_id.email
            and self.env["ir.mail_server"].sudo().search_count([
                ("active", "=", True),
                ("smtp_host", "!=", False),
            ])
        )
        result = {
            "catalog": bool(products),
            "online_payment": bool(payments),
            "fulfilment": bool(fulfilment),
            "sender": sender_ready,
            "domain": self._mb_has_public_domain(),
            "returns": 7 <= self.mb_return_window_days <= 90,
            "product_count": products,
            "payment_count": payments,
            "fulfilment_count": fulfilment,
        }
        result["launch_ready"] = self.mb_webshop_enabled and all(
            result[key]
            for key in (
                "catalog", "online_payment", "fulfilment", "sender", "domain", "returns"
            )
        )
        return result

    @api.depends(
        "company_id",
        "company_id.email",
        "domain",
        "mb_return_window_days",
        "mb_webshop_enabled",
    )
    def _compute_mb_launch_readiness(self):
        for website in self:
            readiness = website._mb_webshop_readiness()
            website.mb_ready_catalog = readiness["catalog"]
            website.mb_ready_online_payment = readiness["online_payment"]
            website.mb_ready_fulfilment = readiness["fulfilment"]
            website.mb_ready_sender = readiness["sender"]
            website.mb_ready_domain = readiness["domain"]
            website.mb_ready_returns = readiness["returns"]
            website.mb_launch_ready = readiness["launch_ready"]
            website.mb_ready_product_count = readiness["product_count"]
            website.mb_ready_payment_count = readiness["payment_count"]
            website.mb_ready_fulfilment_count = readiness["fulfilment_count"]

    @api.constrains("mb_cart_hold_minutes")
    def _check_mb_cart_hold_minutes(self):
        for website in self:
            if not 5 <= website.mb_cart_hold_minutes <= 60:
                raise ValidationError(_(
                    "Cart stock holds must last between 5 and 60 minutes."
                ))

    @api.constrains("mb_return_window_days")
    def _check_mb_return_window_days(self):
        for website in self:
            if not 7 <= website.mb_return_window_days <= 90:
                raise ValidationError(_(
                    "The customer return window must be between 7 and 90 days."
                ))
