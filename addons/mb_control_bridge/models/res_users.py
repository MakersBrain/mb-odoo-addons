import base64
import datetime
import json
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
SUBJECT_RE = re.compile(r"^[A-Za-z0-9._:@/-]{1,255}$")
PUBLIC_ROLES = {"viewer", "artisan", "accountant", "studio_manager", "owner"}
EXPORT_RECORD_LIMIT = 10000
EXPORT_BYTES_LIMIT = 96 * 1024 * 1024

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
    mb_rauthy_subject = fields.Char(string="Rauthy subject", readonly=True, copy=False, index=True)
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
    @api.private
    def mb_reconcile_membership(self, payload):
        user_id, subject, email, name, role, epoch, active = self._mb_validate_membership_payload(
            payload
        )
        company = self.env.company
        workshop_id = str(payload.get("workshop_id", "")).lower()
        if not UUID_RE.fullmatch(workshop_id):
            raise ValidationError(_("workshop_id must be a lowercase UUID"))
        if company.mb_control_workshop_id and company.mb_control_workshop_id != workshop_id:
            raise ValidationError(_("membership belongs to another workshop"))

        user = self.search(
            [
                "|",
                ("mb_control_user_id", "=", user_id),
                ("mb_rauthy_subject", "=", subject),
            ],
            limit=1,
        )
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
                    _(
                        "An unmanaged Odoo user already uses %(email)s; link it explicitly before provisioning.",
                        email=email,
                    )
                )
            user = self.with_context(no_reset_password=True).create(
                {
                    "login": email,
                    "email": email,
                    "name": name,
                    "active": active,
                    "company_id": company.id,
                    "company_ids": [(6, 0, [company.id])],
                    "mb_control_user_id": user_id,
                    "mb_rauthy_subject": subject,
                }
            )

        provider_id = int(
            self.env["ir.config_parameter"].sudo().get_param("mb_control.oidc_provider_id", "0")
            or 0
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
        user.with_context(no_reset_password=True).write(
            {
                "login": email,
                "email": email,
                "name": name,
                "active": active,
                "mb_control_user_id": user_id,
                "mb_rauthy_subject": subject,
                "mb_control_role": role,
                "mb_control_membership_epoch": epoch,
                "group_ids": [(6, 0, sorted(next_groups))],
                **(
                    {
                        "oauth_provider_id": provider_id,
                        "oauth_uid": subject,
                    }
                    if provider_id and {"oauth_provider_id", "oauth_uid"}.issubset(user._fields)
                    else {}
                ),
            }
        )
        if not company.mb_control_workshop_id:
            company.mb_control_workshop_id = workshop_id
        return {"applied": True, "stale": False, "epoch": epoch, "user_id": user_id}

    @api.model
    @api.private
    def mb_replay_erasure(self, payload):
        """Idempotently anonymize the control-managed identity after restore.

        Accounting and other legally retained business rows keep their foreign
        keys, but the login identity and its contact record no longer identify
        the data subject.
        """
        user_id = str(payload.get("user_id", "")).lower()
        subject_key = str(payload.get("subject_key", "")).lower()
        workshop_id = str(payload.get("workshop_id", "")).lower()
        if not all(UUID_RE.fullmatch(value) for value in (user_id, subject_key, workshop_id)):
            raise ValidationError(_("erasure identifiers must be lowercase UUIDs"))
        company = self.env.company
        if company.mb_control_workshop_id != workshop_id:
            raise ValidationError(_("erasure belongs to another workshop"))
        user = self.with_context(active_test=False).search(
            [("mb_control_user_id", "=", user_id)], limit=1
        )
        if not user:
            return {"applied": False, "already_erased": True, "subject_key": subject_key}
        managed = self._mb_managed_group_ids()
        values = {
            "login": f"erased+{subject_key}@invalid",
            "email": False,
            "name": _("Erased data subject"),
            "active": False,
            "mb_control_user_id": False,
            "mb_rauthy_subject": False,
            "mb_control_role": False,
            "group_ids": [(6, 0, sorted(set(user.group_ids.ids) - managed))],
        }
        if "oauth_uid" in user._fields:
            values["oauth_uid"] = False
        if "oauth_provider_id" in user._fields:
            values["oauth_provider_id"] = False
        user.with_context(no_reset_password=True).write(values)
        partner_values = {
            "name": _("Erased data subject"),
            "email": False,
            "phone": False,
            "mobile": False,
            "street": False,
            "street2": False,
            "zip": False,
            "city": False,
        }
        user.partner_id.write(
            {key: value for key, value in partner_values.items() if key in user.partner_id._fields}
        )
        return {"applied": True, "already_erased": False, "subject_key": subject_key}

    @api.model
    @api.private
    def mb_export_personal_data(self, payload):
        """Return an allowlisted, complete tenant-side subject export.

        The result leaves Odoo only through the authenticated internal bridge.
        Binary attachments are base64 encoded for immediate encryption by the
        privacy worker and are never copied into control PostgreSQL.
        """
        user_id = str(payload.get("user_id", "")).lower()
        workshop_id = str(payload.get("workshop_id", "")).lower()
        if not UUID_RE.fullmatch(user_id) or not UUID_RE.fullmatch(workshop_id):
            raise ValidationError(_("privacy export identifiers must be lowercase UUIDs"))
        if self.env.company.mb_control_workshop_id != workshop_id:
            raise ValidationError(_("privacy export belongs to another workshop"))
        user = self.with_context(active_test=False).search(
            [("mb_control_user_id", "=", user_id)], limit=1
        )
        if not user:
            return {
                "format": "makersbrain-odoo-subject-export-v1",
                "workshop_id": workshop_id,
                "user_id": user_id,
                "found": False,
                "datasets": {},
                "attachments": [],
            }
        partner = user.partner_id.commercial_partner_id
        related = {
            "res.users": set(user.ids),
            "res.partner": set((user.partner_id | partner).ids),
        }
        datasets = {}

        def add_dataset(key, model_name, domain, field_names):
            used = len(json.dumps(datasets, ensure_ascii=False, separators=(",", ":")).encode())
            remaining = EXPORT_BYTES_LIMIT - used - 4096
            if remaining <= 0:
                raise ValidationError(_("the Odoo subject export exceeds the secure export limit"))
            datasets[key] = self._mb_export_model(
                model_name, domain, field_names, related, remaining
            )

        add_dataset(
            "users",
            "res.users",
            [("id", "=", user.id)],
            [
                "login",
                "name",
                "email",
                "active",
                "lang",
                "tz",
                "mb_control_role",
                "mb_control_membership_epoch",
                "mb_rauthy_subject",
                "create_date",
                "write_date",
            ],
        )
        add_dataset(
            "partners",
            "res.partner",
            [("id", "child_of", partner.id)],
            [
                "name",
                "email",
                "phone",
                "mobile",
                "street",
                "street2",
                "zip",
                "city",
                "state_id",
                "country_id",
                "vat",
                "website",
                "lang",
                "tz",
                "comment",
                "create_date",
                "write_date",
            ],
        )
        business = {
            "account_moves": (
                "account.move",
                [("commercial_partner_id", "=", partner.id)],
                [
                    "name",
                    "move_type",
                    "date",
                    "invoice_date",
                    "invoice_date_due",
                    "ref",
                    "payment_reference",
                    "amount_untaxed",
                    "amount_tax",
                    "amount_total",
                    "state",
                    "payment_state",
                    "create_date",
                    "write_date",
                ],
            ),
            "sale_orders": (
                "sale.order",
                [("partner_id", "child_of", partner.id)],
                [
                    "name",
                    "client_order_ref",
                    "date_order",
                    "state",
                    "amount_untaxed",
                    "amount_tax",
                    "amount_total",
                    "note",
                    "create_date",
                    "write_date",
                ],
            ),
            "purchase_orders": (
                "purchase.order",
                [("partner_id", "child_of", partner.id)],
                [
                    "name",
                    "partner_ref",
                    "date_order",
                    "date_approve",
                    "state",
                    "amount_untaxed",
                    "amount_tax",
                    "amount_total",
                    "notes",
                    "create_date",
                    "write_date",
                ],
            ),
            "pos_orders": (
                "pos.order",
                [("partner_id", "child_of", partner.id)],
                [
                    "name",
                    "pos_reference",
                    "date_order",
                    "state",
                    "amount_paid",
                    "amount_total",
                    "amount_tax",
                    "create_date",
                    "write_date",
                ],
            ),
            "stock_pickings": (
                "stock.picking",
                [("partner_id", "child_of", partner.id)],
                [
                    "name",
                    "origin",
                    "state",
                    "scheduled_date",
                    "date_done",
                    "note",
                    "create_date",
                    "write_date",
                ],
            ),
            "messages": (
                "mail.message",
                [
                    "|",
                    ("author_id", "child_of", partner.id),
                    ("partner_ids", "in", (user.partner_id | partner).ids),
                ],
                [
                    "model",
                    "res_id",
                    "message_type",
                    "subject",
                    "body",
                    "email_from",
                    "author_id",
                    "partner_ids",
                    "date",
                    "create_date",
                    "write_date",
                ],
            ),
        }
        for key, (model_name, domain, field_names) in business.items():
            add_dataset(key, model_name, domain, field_names)
        lines = {
            "account_move_lines": (
                "account.move.line",
                "move_id",
                "account.move",
                [
                    "name",
                    "display_type",
                    "quantity",
                    "price_unit",
                    "discount",
                    "price_subtotal",
                    "price_total",
                    "debit",
                    "credit",
                    "balance",
                    "date",
                    "date_maturity",
                    "product_id",
                    "create_date",
                    "write_date",
                ],
            ),
            "sale_order_lines": (
                "sale.order.line",
                "order_id",
                "sale.order",
                [
                    "name",
                    "product_id",
                    "product_uom_qty",
                    "qty_delivered",
                    "qty_invoiced",
                    "price_unit",
                    "discount",
                    "price_subtotal",
                    "price_tax",
                    "price_total",
                    "create_date",
                    "write_date",
                ],
            ),
            "purchase_order_lines": (
                "purchase.order.line",
                "order_id",
                "purchase.order",
                [
                    "name",
                    "product_id",
                    "product_qty",
                    "qty_received",
                    "qty_invoiced",
                    "price_unit",
                    "price_subtotal",
                    "price_tax",
                    "price_total",
                    "date_planned",
                    "create_date",
                    "write_date",
                ],
            ),
            "pos_order_lines": (
                "pos.order.line",
                "order_id",
                "pos.order",
                [
                    "full_product_name",
                    "product_id",
                    "qty",
                    "price_unit",
                    "discount",
                    "price_subtotal",
                    "price_subtotal_incl",
                    "create_date",
                    "write_date",
                ],
            ),
            "stock_moves": (
                "stock.move",
                "picking_id",
                "stock.picking",
                [
                    "name",
                    "product_id",
                    "product_uom_qty",
                    "quantity",
                    "state",
                    "origin",
                    "date",
                    "deadline",
                    "create_date",
                    "write_date",
                ],
            ),
        }
        for key, (model_name, parent_field, parent_model, field_names) in lines.items():
            parent_ids = sorted(related.get(parent_model, set()))
            add_dataset(
                key,
                model_name,
                [(parent_field, "in", parent_ids)] if parent_ids else [("id", "=", 0)],
                [parent_field] + field_names,
            )
        attachment_domain = []
        for model_name, record_ids in sorted(related.items()):
            if not record_ids:
                continue
            clause = ["&", ("res_model", "=", model_name), ("res_id", "in", sorted(record_ids))]
            attachment_domain = (
                clause if not attachment_domain else ["|"] + attachment_domain + clause
            )
        remaining = (
            EXPORT_BYTES_LIMIT
            - len(json.dumps(datasets, ensure_ascii=False, separators=(",", ":")).encode())
            - 4096
        )
        attachments = self._mb_export_model(
            "ir.attachment",
            attachment_domain or [("id", "=", 0)],
            [
                "name",
                "res_model",
                "res_id",
                "mimetype",
                "file_size",
                "checksum",
                "description",
                "datas",
                "create_date",
                "write_date",
            ],
            None,
            remaining,
        )
        result = {
            "format": "makersbrain-odoo-subject-export-v1",
            "workshop_id": workshop_id,
            "user_id": user_id,
            "found": True,
            "datasets": datasets,
            "attachments": attachments,
        }
        if (
            len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode())
            > EXPORT_BYTES_LIMIT
        ):
            raise ValidationError(_("the Odoo subject export exceeds the secure export limit"))
        return result

    @api.model
    def _mb_export_model(self, model_name, domain, field_names, related, maximum_bytes):
        if model_name not in self.env:
            return []
        if maximum_bytes <= 2:
            raise ValidationError(_("the Odoo subject export exceeds the secure export limit"))
        model = self.env[model_name].sudo().with_context(active_test=False)
        available = [name for name in field_names if name in model._fields]
        count = model.search_count(domain, limit=EXPORT_RECORD_LIMIT + 1)
        if count > EXPORT_RECORD_LIMIT:
            raise ValidationError(
                _(
                    "the %(model)s subject export exceeds %(limit)s records",
                    model=model_name,
                    limit=EXPORT_RECORD_LIMIT,
                )
            )
        records = model.search(domain, order="id", limit=EXPORT_RECORD_LIMIT)
        if related is not None:
            related.setdefault(model_name, set()).update(records.ids)
        if model_name == "ir.attachment" and "datas" in available:
            raw_bytes = sum(records.mapped("file_size"))
            if raw_bytes > (maximum_bytes - 2) * 3 // 4:
                raise ValidationError(_("the Odoo subject export exceeds the secure export limit"))
        result = []
        used = 2
        for offset in range(0, len(records), 50):
            for row in records[offset : offset + 50].read(available):
                value = self._mb_json_value(row)
                encoded = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
                used += encoded + (1 if result else 0)
                if used > maximum_bytes:
                    raise ValidationError(
                        _("the Odoo subject export exceeds the secure export limit")
                    )
                result.append(value)
        return result

    @api.model
    def _mb_json_value(self, value):
        if isinstance(value, dict):
            return {str(key): self._mb_json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._mb_json_value(item) for item in value]
        if isinstance(value, bytes):
            try:
                return value.decode("ascii")
            except UnicodeDecodeError:
                return base64.b64encode(value).decode("ascii")
        if isinstance(value, (datetime.date, datetime.datetime)):
            return value.isoformat()
        return value
