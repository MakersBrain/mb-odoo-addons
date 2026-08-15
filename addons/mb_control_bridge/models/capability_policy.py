from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CapabilityPolicy(models.Model):
    _name = "mb.control.capability.policy"
    _description = "Control-plane capability enforcement policy"
    _order = "module_key"

    workshop_id = fields.Char(required=True, readonly=True, index=True)
    module_key = fields.Char(required=True, readonly=True, index=True)
    state = fields.Selection(
        [("restricted", "Restricted")], required=True, readonly=True
    )
    reason = fields.Char(required=True, readonly=True)
    modules = fields.Json(required=True, readonly=True)
    rule_ids = fields.Many2many("ir.rule", readonly=True)
    enforced_at = fields.Datetime(required=True, readonly=True)

    _policy_unique = models.Constraint(
        "UNIQUE(workshop_id, module_key)",
        "A capability has only one control-plane enforcement policy per workshop.",
    )

    @api.model
    def restrict(self, company, payload):
        workshop_id = str(payload.get("workshop_id", "")).lower()
        module_key = str(payload.get("module_key", ""))
        modules = payload.get("modules")
        reason = str(payload.get("reason", ""))
        if workshop_id != company.mb_control_workshop_id:
            raise ValidationError(_("capability policy belongs to another workshop"))
        expected = company.mb_expected_module_bundle(module_key)
        if expected is None or not isinstance(modules, list) or tuple(modules) != expected:
            raise ValidationError(_("unsupported capability policy"))
        if not reason or len(reason) > 64:
            raise ValidationError(_("a bounded restriction reason is required"))

        policies = company.env["mb.control.capability.policy"].sudo()
        existing = policies.search([
            ("workshop_id", "=", workshop_id), ("module_key", "=", module_key)
        ], limit=1)
        if existing:
            if existing.modules != modules or existing.reason != reason:
                raise ValidationError(_("the capability is already restricted differently"))
            return existing._evidence(applied=False)

        # Restrict writes only on models owned by the capability addons. Models
        # merely extended by an addon are intentionally excluded so unrelated
        # Odoo workflows remain available and historical records remain readable.
        model_data = company.env["ir.model.data"].sudo().search([
            ("module", "in", modules), ("model", "=", "ir.model")
        ])
        models_owned = model_data.mapped("res_id")
        if not models_owned:
            raise ValidationError(_("the capability exposes no enforceable owned model"))
        rules = company.env["ir.rule"].sudo()
        created = rules.browse()
        for model_id in sorted(set(models_owned)):
            created |= rules.create({
                "name": f"MakersBrain restricted: {module_key}",
                "model_id": model_id,
                # The canonical match-nothing domain. `[(1, '=', 0)]` meant the
                # same thing to older Odoo and is rejected outright by 19's
                # Domain parser, which accepts only (0, '=', 1) for false and
                # (1, '=', 1) for true.
                "domain_force": "[(0, '=', 1)]",
                "global": True,
                "perm_read": False,
                "perm_write": True,
                "perm_create": True,
                "perm_unlink": True,
            })
        policy = policies.create({
            "workshop_id": workshop_id,
            "module_key": module_key,
            "state": "restricted",
            "reason": reason,
            "modules": modules,
            "rule_ids": [(6, 0, created.ids)],
            "enforced_at": fields.Datetime.now(),
        })
        return policy._evidence(applied=True)

    def _evidence(self, applied):
        self.ensure_one()
        return {
            "applied": applied,
            "adapter": "odoo_write_rules",
            "policy_id": self.id,
            "rule_ids": self.rule_ids.ids,
            "write_blocked": True,
            "historical_read_retained": True,
        }
