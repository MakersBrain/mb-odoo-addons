import hashlib
import re

from odoo import _, fields, models
from odoo.exceptions import ValidationError


UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
ENTITLEMENT_STATUSES = {"provisioning", "trial", "active", "past_due", "restricted", "suspended"}
MODULE_BUNDLES = {
    "catalogue": ("mb_catalogue_sync",),
    "firings": ("mb_ceramics_firing",),
    "kiln-connectivity": ("mb_kiln_bridge",),
    "labels": ("mb_label", "mb_label_pos"),
    "depot": ("mb_depot",),
    "sumup": ("mb_payment_sumup", "mb_account_payment_sumup", "mb_pos_sumup"),
    "invoice-capture": ("mb_invoice_capture",),
    "inventory-capture": ("mb_inventory_capture",),
    "webshop": ("mb_webshop",),
    "shipping-boxtal": ("mb_webshop_carrier_base", "mb_webshop_carrier_boxtal"),
}


class ResCompany(models.Model):
    _inherit = "res.company"

    mb_control_workshop_id = fields.Char(
        string="Control-plane workshop ID", copy=False, readonly=True, index=True
    )
    mb_control_public_hostname = fields.Char(
        string="Control-plane public hostname",
        copy=False,
        readonly=True,
        index=True,
        help="Exact hostname assigned by the trusted MakersBrain tenant gateway.",
    )
    mb_control_bridge_token_hash = fields.Char(
        string="Control-plane tenant credential hash",
        copy=False,
        readonly=True,
        groups="base.group_system",
    )
    mb_entitlement_version = fields.Integer(
        string="Entitlement version", default=0, readonly=True, copy=False
    )
    mb_entitlement_plan = fields.Char(string="Entitlement plan", readonly=True, copy=False)
    mb_entitlement_status = fields.Selection(
        string="Entitlement status",
        selection=[(value, value.replace("_", " ").title()) for value in sorted(ENTITLEMENT_STATUSES)],
        readonly=True,
        copy=False,
    )
    mb_entitlement_limits = fields.Json(string="Entitlement limits", readonly=True, copy=False)
    mb_entitlement_expires_at = fields.Datetime(
        string="Entitlement expiry", readonly=True, copy=False
    )
    mb_entitlement_signature = fields.Char(
        string="Entitlement signature", readonly=True, copy=False
    )

    _control_workshop_unique = models.Constraint(
        "UNIQUE(mb_control_workshop_id)",
        "A control-plane workshop can be linked to only one company.",
    )

    def mb_bootstrap_tenant(self, payload):
        self.ensure_one()
        new_workshop = not self.mb_control_workshop_id
        workshop_id = str(payload.get("workshop_id", "")).lower()
        client_id = str(payload.get("oidc_client_id", "")).strip()
        issuer = str(payload.get("oidc_issuer", "")).rstrip("/")
        bridge_token = str(payload.get("bridge_token", ""))
        public_hostname = str(payload.get("public_hostname", "")).strip()
        if not UUID_RE.fullmatch(workshop_id):
            raise ValidationError(_("workshop_id must be a lowercase UUID"))
        if self.mb_control_workshop_id and self.mb_control_workshop_id != workshop_id:
            raise ValidationError(_("this company is linked to another workshop"))
        if not HOSTNAME_RE.fullmatch(public_hostname):
            raise ValidationError(_("public_hostname must be a lowercase fully qualified hostname"))
        if (
            self.mb_control_public_hostname
            and self.mb_control_public_hostname != public_hostname
        ):
            raise ValidationError(_("this company is linked to another public hostname"))
        if not client_id or not issuer.startswith(("https://", "http://rauthy.localhost:")):
            raise ValidationError(_("OIDC client and trusted issuer are required"))
        if not 48 <= len(bridge_token) <= 128 or not bridge_token.isalnum():
            raise ValidationError(_("a high-entropy tenant bridge credential is required"))
        if "auth.oauth.provider" not in self.env:
            raise ValidationError(_("the authorization-code OIDC module is not installed"))
        provider_model = self.env["auth.oauth.provider"].sudo()
        required = {"flow", "token_endpoint", "jwks_uri", "client_secret"}
        if not required.issubset(provider_model._fields):
            raise ValidationError(_("the installed OAuth provider does not support authorization-code OIDC"))
        values = {
            "name": "MakersBrain",
            "client_id": client_id,
            "client_secret": False,
            "flow": "id_token_code",
            "enabled": True,
            "auth_endpoint": f"{issuer}/oidc/authorize",
            "token_endpoint": f"{issuer}/oidc/token",
            "jwks_uri": f"{issuer}/oidc/certs",
            "validation_endpoint": f"{issuer}/oidc/userinfo",
            "scope": "openid profile email",
            "token_map": "sub:user_id",
            "body": "Log in with MakersBrain",
            "css_class": "fa fa-fw fa-sign-in",
        }
        provider = provider_model.search([("client_id", "=", client_id)], limit=1)
        if provider:
            provider.write(values)
        else:
            provider = provider_model.create(values)
        if new_workshop:
            self._mb_bootstrap_french_accounting()
        self.write({
            "mb_control_workshop_id": workshop_id,
            "mb_control_public_hostname": public_hostname,
            "mb_control_bridge_token_hash": hashlib.sha256(bridge_token.encode()).hexdigest(),
        })
        if "website" in self.env:
            self.env["website"].sudo().search([
                ("company_id", "=", self.id),
                ("domain", "=", False),
            ]).write({"domain": public_hostname})
        self._mb_configure_login_policy(provider)
        return {
            "applied": True,
            "workshop_id": workshop_id,
            "public_hostname": public_hostname,
            "provider_id": provider.id,
        }

    def _mb_bootstrap_french_accounting(self):
        """Give a newly provisioned workshop a usable French chart immediately."""
        self.ensure_one()
        france = self.env.ref("base.fr")
        self.write({
            "country_id": france.id,
            "account_fiscal_country_id": france.id,
        })
        self.invalidate_recordset(["country_id", "account_fiscal_country_id"])
        if self.chart_template == "fr":
            return
        if self.env["account.move.line"].sudo().search_count([
            ("company_id", "=", self.id),
        ]):
            raise ValidationError(
                _("French accounting cannot be initialized after journal items exist.")
            )
        self.env["account.chart.template"].sudo().try_loading(
            "fr", company=self, install_demo=False
        )

    def _mb_configure_login_policy(self, provider):
        self.ensure_one()
        self.env["auth.oauth.provider"].sudo().search([
            ("enabled", "=", True),
            ("id", "!=", provider.id),
        ]).write({"enabled": False})
        parameters = self.env["ir.config_parameter"].sudo()
        parameters.set_param("mb_control.oidc_provider_id", provider.id)
        parameters.set_param("auth_signup.reset_password", False)
        parameters.set_param("auth_signup.invitation_scope", "b2b")

    def mb_enable_module_bundle(self, payload):
        self.ensure_one()
        workshop_id = str(payload.get("workshop_id", "")).lower()
        module_key = str(payload.get("module_key", ""))
        modules = payload.get("modules")
        if workshop_id != self.mb_control_workshop_id:
            raise ValidationError(_("module bundle belongs to another workshop"))
        expected = MODULE_BUNDLES.get(module_key)
        if expected is None or not isinstance(modules, list) or tuple(modules) != expected:
            raise ValidationError(_("unsupported module bundle"))
        records = self.env["ir.module.module"].sudo().search([
            ("name", "in", list(expected)),
        ])
        if set(records.mapped("name")) != set(expected):
            raise ValidationError(_("a supported module is unavailable in this release"))
        invalid = records.filtered(
            lambda module: module.state not in (
                "uninstalled", "to install", "installed", "to upgrade",
            )
        )
        if invalid:
            raise ValidationError(_("a supported module cannot currently be enabled"))
        policy = self.env["mb.control.capability.policy"].sudo().search([
            ("workshop_id", "=", workshop_id), ("module_key", "=", module_key)
        ], limit=1)
        restriction_removed = bool(policy)
        if policy:
            policy.rule_ids.unlink()
            policy.unlink()
            self._mb_remove_capability_restriction(module_key)
        pending = records.filtered(lambda module: module.state == "uninstalled")
        if pending:
            # Only schedule the native module operation here. Immediate module
            # installation commits and rebuilds the registry in the middle of
            # this HTTP request, before its idempotency receipt can be stored.
            # The deployment worker applies ``to install`` modules through the
            # normal Odoo CLI/registry lifecycle after this transaction commits.
            pending.button_install()
        scheduled = records.filtered(lambda module: module.state == "to install") | pending
        return {
            "applied": bool(pending),
            "status": "scheduled" if scheduled else "installed",
            "module_key": module_key,
            "modules": list(expected),
            "restriction_removed": restriction_removed,
        }

    def _mb_apply_capability_restriction(self, module_key, reason):
        """Extension point for capability-specific runtime enforcement."""
        return {}

    def _mb_remove_capability_restriction(self, module_key):
        """Undo capability-specific enforcement after its policy is removed."""
        return None

    def mb_restrict_module_bundle(self, payload):
        self.ensure_one()
        return self.env["mb.control.capability.policy"].restrict(self, payload)

    def mb_expected_module_bundle(self, module_key):
        return MODULE_BUNDLES.get(module_key)

    def mb_apply_entitlement(self, payload):
        self.ensure_one()
        workshop_id = str(payload.get("workshop_id", "")).lower()
        version = payload.get("version")
        status = payload.get("status")
        plan = payload.get("plan")
        limits = payload.get("limits", {})
        signature = payload.get("signature")
        if not UUID_RE.fullmatch(workshop_id):
            raise ValidationError(_("workshop_id must be a lowercase UUID"))
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValidationError(_("entitlement version must be a positive integer"))
        if status not in ENTITLEMENT_STATUSES:
            raise ValidationError(_("unsupported entitlement status"))
        if not isinstance(plan, str) or not plan.strip():
            raise ValidationError(_("entitlement plan is required"))
        if not isinstance(limits, dict):
            raise ValidationError(_("entitlement limits must be an object"))
        if not isinstance(signature, str) or not signature:
            raise ValidationError(_("entitlement signature is required"))
        if self.mb_control_workshop_id and self.mb_control_workshop_id != workshop_id:
            raise ValidationError(_("this company is linked to another workshop"))
        if version < self.mb_entitlement_version:
            raise ValidationError(_("an older entitlement cannot replace the current version"))
        if version == self.mb_entitlement_version:
            same = (
                self.mb_entitlement_plan == plan
                and self.mb_entitlement_status == status
                and (self.mb_entitlement_limits or {}) == limits
                and self.mb_entitlement_signature == signature
            )
            if not same:
                raise ValidationError(_("the entitlement version already contains different data"))
            return {"applied": False, "version": version, "workshop_id": workshop_id}
        self.write({
            "mb_control_workshop_id": workshop_id,
            "mb_entitlement_version": version,
            "mb_entitlement_plan": plan.strip(),
            "mb_entitlement_status": status,
            "mb_entitlement_limits": limits,
            "mb_entitlement_expires_at": payload.get("expires_at") or False,
            "mb_entitlement_signature": signature,
        })
        return {"applied": True, "version": version, "workshop_id": workshop_id}
