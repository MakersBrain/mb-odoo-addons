import re

from odoo import fields, models
from odoo.exceptions import ValidationError


UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
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
}


class ResCompany(models.Model):
    _inherit = "res.company"

    mb_control_workshop_id = fields.Char(
        string="Control-plane workshop ID", copy=False, readonly=True, index=True
    )
    mb_entitlement_version = fields.Integer(default=0, readonly=True, copy=False)
    mb_entitlement_plan = fields.Char(readonly=True, copy=False)
    mb_entitlement_status = fields.Selection(
        selection=[(value, value.replace("_", " ").title()) for value in sorted(ENTITLEMENT_STATUSES)],
        readonly=True,
        copy=False,
    )
    mb_entitlement_limits = fields.Json(readonly=True, copy=False)
    mb_entitlement_expires_at = fields.Datetime(readonly=True, copy=False)
    mb_entitlement_signature = fields.Char(readonly=True, copy=False)

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
        if not UUID_RE.fullmatch(workshop_id):
            raise ValidationError("workshop_id must be a lowercase UUID")
        if self.mb_control_workshop_id and self.mb_control_workshop_id != workshop_id:
            raise ValidationError("this company is linked to another workshop")
        if not client_id or not issuer.startswith(("https://", "http://rauthy.localhost:")):
            raise ValidationError("OIDC client and trusted issuer are required")
        if "auth.oauth.provider" not in self.env:
            raise ValidationError("the authorization-code OIDC module is not installed")
        provider_model = self.env["auth.oauth.provider"].sudo()
        required = {"flow", "token_endpoint", "jwks_uri", "client_secret"}
        if not required.issubset(provider_model._fields):
            raise ValidationError("the installed OAuth provider does not support authorization-code OIDC")
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
        self.mb_control_workshop_id = workshop_id
        self._mb_configure_login_policy(provider)
        return {"applied": True, "workshop_id": workshop_id, "provider_id": provider.id}

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
                "French accounting cannot be initialized after journal items exist."
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
            raise ValidationError("module bundle belongs to another workshop")
        expected = MODULE_BUNDLES.get(module_key)
        if expected is None or not isinstance(modules, list) or tuple(modules) != expected:
            raise ValidationError("unsupported module bundle")
        records = self.env["ir.module.module"].sudo().search([
            ("name", "in", list(expected)),
        ])
        if set(records.mapped("name")) != set(expected):
            raise ValidationError("a supported module is unavailable in this release")
        pending = records.filtered(lambda module: module.state not in ("installed", "to upgrade"))
        if pending:
            pending.button_immediate_install()
        return {
            "applied": bool(pending),
            "module_key": module_key,
            "modules": list(expected),
        }

    def mb_apply_entitlement(self, payload):
        self.ensure_one()
        workshop_id = str(payload.get("workshop_id", "")).lower()
        version = payload.get("version")
        status = payload.get("status")
        plan = payload.get("plan")
        limits = payload.get("limits", {})
        signature = payload.get("signature")
        if not UUID_RE.fullmatch(workshop_id):
            raise ValidationError("workshop_id must be a lowercase UUID")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValidationError("entitlement version must be a positive integer")
        if status not in ENTITLEMENT_STATUSES:
            raise ValidationError("unsupported entitlement status")
        if not isinstance(plan, str) or not plan.strip():
            raise ValidationError("entitlement plan is required")
        if not isinstance(limits, dict):
            raise ValidationError("entitlement limits must be an object")
        if not isinstance(signature, str) or not signature:
            raise ValidationError("entitlement signature is required")
        if self.mb_control_workshop_id and self.mb_control_workshop_id != workshop_id:
            raise ValidationError("this company is linked to another workshop")
        if version < self.mb_entitlement_version:
            raise ValidationError("an older entitlement cannot replace the current version")
        if version == self.mb_entitlement_version:
            same = (
                self.mb_entitlement_plan == plan
                and self.mb_entitlement_status == status
                and (self.mb_entitlement_limits or {}) == limits
                and self.mb_entitlement_signature == signature
            )
            if not same:
                raise ValidationError("the entitlement version already contains different data")
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
