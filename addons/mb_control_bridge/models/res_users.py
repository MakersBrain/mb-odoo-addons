import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
SUBJECT_RE = re.compile(r"^[A-Za-z0-9._:@/-]{1,255}$")
PUBLIC_ROLES = {"viewer", "artisan", "accountant", "studio_manager", "owner"}

ROLE_GROUPS = {
    "viewer": {"base.group_user"},
    "artisan": {
        "base.group_user",
        "sales_team.group_sale_salesman",
        "stock.group_stock_user",
        "mrp.group_mrp_user",
        "point_of_sale.group_pos_user",
    },
    "accountant": {
        "base.group_user",
        "account.group_account_invoice",
        "purchase.group_purchase_user",
    },
    "studio_manager": {
        "base.group_user",
        "product.group_product_manager",
        "sales_team.group_sale_manager",
        "stock.group_stock_manager",
        "mrp.group_mrp_manager",
        "point_of_sale.group_pos_manager",
        "purchase.group_purchase_manager",
        "account.group_account_manager",
    },
    "owner": {
        "base.group_user",
        "product.group_product_manager",
        "sales_team.group_sale_manager",
        "stock.group_stock_manager",
        "mrp.group_mrp_manager",
        "point_of_sale.group_pos_manager",
        "purchase.group_purchase_manager",
        "account.group_account_manager",
    },
}


class ResUsers(models.Model):
    _inherit = "res.users"

    mb_control_user_id = fields.Char(
        string="Control-plane user ID", readonly=True, copy=False, index=True
    )
    mb_rauthy_subject = fields.Char(
        string="Rauthy subject", readonly=True, copy=False, index=True
    )
    mb_control_role = fields.Selection(
        string="Workshop role",
        selection=[
            ("viewer", "Viewer"),
            ("artisan", "Craftsperson"),
            ("accountant", "Accountant"),
            ("studio_manager", "Studio manager"),
            ("owner", "Owner"),
        ],
        readonly=True,
        copy=False,
    )
    mb_control_membership_epoch = fields.Integer(
        string="Membership epoch", default=0, readonly=True, copy=False
    )

    _control_user_unique = models.Constraint(
        "UNIQUE(mb_control_user_id)",
        "A control-plane user can be linked to only one Odoo user.",
    )
    _rauthy_subject_unique = models.Constraint(
        "UNIQUE(mb_rauthy_subject)",
        "A Rauthy subject can be linked to only one Odoo user.",
    )

    @api.model
    def _mb_managed_group_ids(self):
        xmlids = set().union(*ROLE_GROUPS.values())
        return {self.env.ref(xmlid).id for xmlid in xmlids}

    @api.model
    def _mb_role_group_ids(self, role):
        return {self.env.ref(xmlid).id for xmlid in ROLE_GROUPS[role]}

    @api.model
    def _mb_validate_membership_payload(self, payload):
        user_id = str(payload.get("user_id", "")).lower()
        subject = str(payload.get("subject", ""))
        email = str(payload.get("email", "")).strip().lower()
        name = str(payload.get("name", "")).strip()
        role = payload.get("role")
        epoch = payload.get("epoch")
        active = payload.get("active")
        if not UUID_RE.fullmatch(user_id):
            raise ValidationError(_("user_id must be a lowercase UUID"))
        if not SUBJECT_RE.fullmatch(subject):
            raise ValidationError(_("subject is invalid"))
        if not email or "@" not in email or email != email.lower():
            raise ValidationError(_("email must be a normalized address"))
        if not name:
            raise ValidationError(_("name is required"))
        if role not in PUBLIC_ROLES:
            raise ValidationError(_("unsupported workshop role"))
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
            raise ValidationError(_("membership epoch must be a positive integer"))
        if not isinstance(active, bool):
            raise ValidationError(_("active must be a boolean"))
        return user_id, subject, email, name, role, epoch, active

    @api.model
    def mb_reconcile_membership(self, payload):
        user_id, subject, email, name, role, epoch, active = (
            self._mb_validate_membership_payload(payload)
        )
        company = self.env.company
        workshop_id = str(payload.get("workshop_id", "")).lower()
        if not UUID_RE.fullmatch(workshop_id):
            raise ValidationError(_("workshop_id must be a lowercase UUID"))
        if company.mb_control_workshop_id and company.mb_control_workshop_id != workshop_id:
            raise ValidationError(_("membership belongs to another workshop"))

        user = self.search([
            "|", ("mb_control_user_id", "=", user_id),
            ("mb_rauthy_subject", "=", subject),
        ], limit=1)
        if user and (
            user.mb_control_user_id not in (False, user_id)
            or user.mb_rauthy_subject not in (False, subject)
        ):
            raise ValidationError(_("control-plane identity links conflict"))
        if not user:
            login_match = self.with_context(active_test=False).search(
                [("login", "=", email)], limit=1
            )
            if login_match and not login_match.mb_control_user_id:
                raise ValidationError(
                    _("An unmanaged Odoo user already uses %(email)s; link it explicitly before provisioning.", email=email)
                )
            user = self.with_context(no_reset_password=True).create({
                "login": email,
                "email": email,
                "name": name,
                "active": active,
                "company_id": company.id,
                "company_ids": [(6, 0, [company.id])],
                "mb_control_user_id": user_id,
                "mb_rauthy_subject": subject,
            })

        provider_id = int(
            self.env["ir.config_parameter"].sudo().get_param(
                "mb_control.oidc_provider_id", "0"
            ) or 0
        )

        if epoch < user.mb_control_membership_epoch:
            return {
                "applied": False,
                "stale": True,
                "epoch": user.mb_control_membership_epoch,
                "user_id": user_id,
            }
        if epoch == user.mb_control_membership_epoch:
            same = (
                user.mb_control_role == role
                and user.active == active
                and user.login == email
                and user.name == name
            )
            if not same:
                raise ValidationError(_("the membership epoch already contains different data"))
            return {"applied": False, "stale": False, "epoch": epoch, "user_id": user_id}

        managed = self._mb_managed_group_ids()
        requested = self._mb_role_group_ids(role) if active else set()
        current = set(user.group_ids.ids)
        next_groups = (current - managed) | requested
        user.with_context(no_reset_password=True).write({
            "login": email,
            "email": email,
            "name": name,
            "active": active,
            "mb_control_user_id": user_id,
            "mb_rauthy_subject": subject,
            "mb_control_role": role,
            "mb_control_membership_epoch": epoch,
            "group_ids": [(6, 0, sorted(next_groups))],
            **({
                "oauth_provider_id": provider_id,
                "oauth_uid": subject,
            } if provider_id and {"oauth_provider_id", "oauth_uid"}.issubset(user._fields) else {}),
        })
        if not company.mb_control_workshop_id:
            company.mb_control_workshop_id = workshop_id
        return {"applied": True, "stale": False, "epoch": epoch, "user_id": user_id}
