import base64
import hashlib
import uuid
from unittest.mock import patch

from odoo.addons.base.models.ir_module import IrModuleModule
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from ..controllers.auth import credential_matches
from ..controllers.login import should_redirect_to_makersbrain


@tagged("post_install", "-at_install")
class TestControlBridge(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Users = cls.env["res.users"].sudo()
        cls.company = cls.env.company.sudo()
        cls.workshop_id = str(uuid.uuid4())
        cls.user_id = str(uuid.uuid4())
        cls.subject = "rauthy-subject-control-1"

    def membership(self, **changes):
        payload = {
            "workshop_id": self.workshop_id,
            "user_id": self.user_id,
            "subject": self.subject,
            "email": "artisan@example.test",
            "name": "Test Artisan",
            "role": "artisan",
            "epoch": 1,
            "active": True,
        }
        payload.update(changes)
        return payload

    def test_membership_reconciliation_is_monotonic_and_idempotent(self):
        first = self.Users.mb_reconcile_membership(self.membership(epoch=2))
        replay = self.Users.mb_reconcile_membership(self.membership(epoch=2))
        stale = self.Users.mb_reconcile_membership(self.membership(epoch=1))
        user = self.Users.search([("mb_control_user_id", "=", self.user_id)])

        self.assertTrue(first["applied"])
        self.assertFalse(replay["applied"])
        self.assertTrue(stale["stale"])
        self.assertEqual(user.mb_rauthy_subject, self.subject)
        self.assertEqual(user.mb_control_role, "artisan")
        self.assertIn(self.env.ref("point_of_sale.group_pos_user"), user.group_ids)

    def test_normal_login_redirects_but_break_glass_and_errors_do_not(self):
        self.assertTrue(should_redirect_to_makersbrain("GET", False, {}))
        self.assertFalse(
            should_redirect_to_makersbrain("GET", False, {"local": "1"})
        )
        self.assertFalse(
            should_redirect_to_makersbrain("GET", False, {"oauth_error": "2"})
        )
        self.assertFalse(should_redirect_to_makersbrain("POST", False, {}))
        self.assertFalse(should_redirect_to_makersbrain("GET", True, {}))

    def test_login_policy_keeps_only_makersbrain_and_disables_password_reset(self):
        if "auth.oauth.provider" not in self.env:
            self.skipTest("optional auth_oauth module is not installed")
        providers = self.env["auth.oauth.provider"].sudo()
        other = providers.create({
            "name": "Other",
            "client_id": "other-client",
            "enabled": True,
            "auth_endpoint": "https://other.example.test/authorize",
            "body": "Log in with Other",
            "scope": "openid",
            "validation_endpoint": "https://other.example.test/userinfo",
        })
        makersbrain = providers.create({
            "name": "MakersBrain",
            "client_id": "makersbrain-test-client",
            "enabled": True,
            "auth_endpoint": "https://auth.example.test/authorize",
            "body": "Log in with MakersBrain",
            "scope": "openid profile email",
            "validation_endpoint": "https://auth.example.test/userinfo",
        })
        self.company._mb_configure_login_policy(makersbrain)
        parameters = self.env["ir.config_parameter"].sudo()

        self.assertFalse(other.enabled)
        self.assertEqual(
            int(parameters.get_param("mb_control.oidc_provider_id")),
            makersbrain.id,
        )
        self.assertFalse(parameters.get_param("auth_signup.reset_password"))
        self.assertEqual(parameters.get_param("auth_signup.invitation_scope"), "b2b")

    def test_new_workshop_bootstraps_french_accounting(self):
        company = self.env["res.company"].sudo().create({"name": "French workshop"})

        company._mb_bootstrap_french_accounting()

        self.assertEqual(company.country_id, self.env.ref("base.fr"))
        self.assertEqual(company.account_fiscal_country_id, self.env.ref("base.fr"))
        self.assertEqual(company.chart_template, "fr")
        self.assertTrue(self.env["account.tax"].sudo().search_count([
            ("company_id", "=", company.id),
            ("country_id", "=", self.env.ref("base.fr").id),
        ]))

    def test_tenant_bootstrap_stores_only_the_bridge_credential_hash(self):
        if "auth.oauth.provider" not in self.env:
            self.skipTest("optional auth_oauth module is not installed")
        required = {"flow", "token_endpoint", "jwks_uri", "client_secret"}
        if not required.issubset(self.env["auth.oauth.provider"]._fields):
            self.skipTest("authorization-code OIDC provider is unavailable")
        workshop = str(uuid.uuid4())
        token = "A" * 64
        self.company.write({"mb_control_workshop_id": workshop})

        self.company.mb_bootstrap_tenant({
            "workshop_id": workshop,
            "oidc_client_id": f"makersbrain-odoo-{workshop}",
            "oidc_issuer": "https://identity.example.test",
            "bridge_token": token,
            "public_hostname": "atelier.makersbrain.fr",
        })

        self.assertEqual(
            self.company.mb_control_bridge_token_hash,
            hashlib.sha256(token.encode()).hexdigest(),
        )
        self.assertNotEqual(self.company.mb_control_bridge_token_hash, token)
        self.assertEqual(
            self.company.mb_control_public_hostname,
            "atelier.makersbrain.fr",
        )

    def test_tenant_public_hostname_is_strict_and_immutable(self):
        from ..models.res_company import HOSTNAME_RE

        self.assertTrue(HOSTNAME_RE.fullmatch("atelier.makersbrain.fr"))
        for hostname in (
            "ATELIER.makersbrain.fr",
            "atelier",
            "-atelier.makersbrain.fr",
            "atelier..makersbrain.fr",
            "atelier.makersbrain.fr;return 200",
        ):
            self.assertFalse(HOSTNAME_RE.fullmatch(hostname), hostname)

    def test_global_bridge_credential_is_valid_only_before_tenant_bootstrap(self):
        tenant_token = "T" * 64
        global_token = "G" * 64
        tenant_hash = hashlib.sha256(tenant_token.encode()).hexdigest()

        self.assertTrue(credential_matches(global_token, "", global_token, True))
        self.assertFalse(credential_matches(tenant_token, "", global_token, True))
        self.assertTrue(
            credential_matches(tenant_token, tenant_hash, global_token, True)
        )
        self.assertFalse(
            credential_matches(global_token, tenant_hash, global_token, True)
        )

    def test_same_epoch_cannot_change_authority(self):
        self.Users.mb_reconcile_membership(self.membership())
        with self.assertRaises(ValidationError):
            self.Users.mb_reconcile_membership(self.membership(role="owner"))

    def test_owner_can_create_inventory_products(self):
        self.Users.mb_reconcile_membership(self.membership(role="owner"))
        user = self.Users.search([("mb_control_user_id", "=", self.user_id)])

        self.assertTrue(user.has_group("product.group_product_manager"))
        self.assertIsNone(self.env["product.template"].with_user(user).check_access("create"))

    def test_new_epoch_replaces_only_managed_groups_and_can_revoke(self):
        self.Users.mb_reconcile_membership(self.membership())
        user = self.Users.search([("mb_control_user_id", "=", self.user_id)])
        unrelated = self.env.ref("base.group_allow_export")
        user.group_ids = [(4, unrelated.id)]

        self.Users.mb_reconcile_membership(self.membership(epoch=2, active=False))
        user = self.Users.with_context(active_test=False).browse(user.id)
        self.assertFalse(user.active)
        self.assertIn(unrelated, user.group_ids)
        self.assertNotIn(self.env.ref("point_of_sale.group_pos_user"), user.group_ids)

    def test_identity_collision_is_rejected(self):
        self.Users.mb_reconcile_membership(self.membership())
        with self.assertRaises(ValidationError):
            self.Users.mb_reconcile_membership(self.membership(
                user_id=str(uuid.uuid4()), epoch=2
            ))

    def test_erasure_replay_anonymizes_identity_and_is_idempotent(self):
        self.company.mb_control_workshop_id = self.workshop_id
        self.Users.mb_reconcile_membership(self.membership())
        user = self.Users.search([("mb_control_user_id", "=", self.user_id)])
        partner = user.partner_id
        subject_key = str(uuid.uuid4())
        payload = {
            "workshop_id": self.workshop_id,
            "user_id": self.user_id,
            "subject_key": subject_key,
        }

        first = self.Users.mb_replay_erasure(payload)
        replay = self.Users.mb_replay_erasure(payload)
        user = self.Users.with_context(active_test=False).browse(user.id)

        self.assertTrue(first["applied"])
        self.assertTrue(replay["already_erased"])
        self.assertFalse(user.active)
        self.assertFalse(user.mb_control_user_id)
        self.assertFalse(user.mb_rauthy_subject)
        self.assertEqual(user.login, f"erased+{subject_key}@invalid")
        self.assertFalse(partner.email)
        self.assertFalse(partner.phone)

    def test_privacy_export_is_tenant_bound_and_includes_related_attachments(self):
        self.company.mb_control_workshop_id = self.workshop_id
        self.Users.mb_reconcile_membership(self.membership())
        user = self.Users.search([("mb_control_user_id", "=", self.user_id)])
        attachments = self.env["ir.attachment"].sudo()
        attachments.create({
            "name": "subject-proof.txt",
            "res_model": "res.partner",
            "res_id": user.partner_id.id,
            "type": "binary",
            "datas": base64.b64encode(b"subject content"),
            "mimetype": "text/plain",
        })
        unrelated = self.env["res.partner"].sudo().create({"name": "Unrelated"})
        attachments.create({
            "name": "unrelated.txt",
            "res_model": "res.partner",
            "res_id": unrelated.id,
            "type": "binary",
            "datas": base64.b64encode(b"must not leak"),
            "mimetype": "text/plain",
        })

        result = self.Users.mb_export_personal_data({
            "workshop_id": self.workshop_id,
            "user_id": self.user_id,
        })

        self.assertTrue(result["found"])
        self.assertEqual(result["user_id"], self.user_id)
        names = {item["name"] for item in result["attachments"]}
        self.assertIn("subject-proof.txt", names)
        self.assertNotIn("unrelated.txt", names)
        with self.assertRaises(ValidationError):
            self.Users.mb_export_personal_data({
                "workshop_id": str(uuid.uuid4()),
                "user_id": self.user_id,
            })

    def test_entitlements_are_monotonic(self):
        payload = {
            "workshop_id": self.workshop_id,
            "version": 1,
            "plan": "studio",
            "status": "active",
            "limits": {"azure_pages_month": 100},
            "signature": "fixture-signature",
        }
        self.assertTrue(self.company.mb_apply_entitlement(payload)["applied"])
        self.assertFalse(self.company.mb_apply_entitlement(payload)["applied"])
        with self.assertRaises(ValidationError):
            self.company.mb_apply_entitlement(dict(payload, plan="other"))

    def test_operation_key_cannot_be_reused_for_another_payload(self):
        receipts = self.env["mb.control.operation.receipt"].sudo()
        receipts.record("membership:test", "membership.reconcile", "abc", {"ok": True})
        self.assertTrue(receipts.for_replay("membership:test", "membership.reconcile", "abc"))
        with self.assertRaises(ValidationError):
            receipts.for_replay("membership:test", "membership.reconcile", "def")

    def test_module_catalog_rejects_arbitrary_odoo_modules(self):
        self.company.mb_control_workshop_id = self.workshop_id
        self.assertEqual(
            self.company.mb_expected_module_bundle("shop-catalogue-import"),
            ("mb_shop_import",),
        )

        with self.assertRaises(ValidationError):
            self.company.mb_enable_module_bundle({
                "workshop_id": self.workshop_id,
                "module_key": "system",
                "modules": ["base"],
            })

    def test_module_enable_is_scheduled_without_immediate_registry_rebuild(self):
        self.company.mb_control_workshop_id = self.workshop_id
        module = self.env["ir.module.module"].sudo().search([
            ("name", "=", "mb_ceramics_firing"),
        ], limit=1)
        # Simulate the lifecycle state this endpoint handles. The addon may
        # already be installed when the full repository suite runs.
        module.write({"state": "uninstalled"})
        self.assertEqual(module.state, "uninstalled")

        with patch.object(
            IrModuleModule, "button_install", autospec=True,
        ) as button_install, patch.object(
            IrModuleModule, "button_immediate_install", autospec=True,
        ) as immediate_install:
            result = self.company.mb_enable_module_bundle({
                "workshop_id": self.workshop_id,
                "module_key": "firings",
                "modules": ["mb_ceramics_firing"],
            })

        button_install.assert_called_once()
        immediate_install.assert_not_called()
        self.assertTrue(result["applied"])
        self.assertEqual(result["status"], "scheduled")

    def test_module_restriction_blocks_writes_and_retains_historical_reads(self):
        self.company.mb_control_workshop_id = self.workshop_id
        owned_models = self.env["ir.model.data"].sudo().search([
            ("module", "=", "mb_ceramics_firing"), ("model", "=", "ir.model")
        ])
        if not owned_models:
            self.skipTest("the post-install firing models are not loaded")
        payload = {
            "workshop_id": self.workshop_id,
            "module_key": "firings",
            "modules": ["mb_ceramics_firing"],
            "reason": "entitlement_inactive",
        }
        first = self.company.mb_restrict_module_bundle(payload)
        replay = self.company.mb_restrict_module_bundle(payload)
        policy = self.env["mb.control.capability.policy"].sudo().search([
            ("workshop_id", "=", self.workshop_id), ("module_key", "=", "firings")
        ])

        self.assertTrue(first["applied"])
        self.assertFalse(replay["applied"])
        self.assertTrue(first["write_blocked"])
        self.assertTrue(first["historical_read_retained"])
        self.assertTrue(policy.rule_ids)
        self.assertTrue(all(policy.rule_ids.mapped("global")))
        self.assertFalse(any(policy.rule_ids.mapped("perm_read")))
        self.assertTrue(all(policy.rule_ids.mapped("perm_write")))
        self.assertTrue(all(policy.rule_ids.mapped("perm_create")))
        self.assertTrue(all(policy.rule_ids.mapped("perm_unlink")))
        rule_ids = policy.rule_ids.ids

        enabled = self.company.mb_enable_module_bundle({
            "workshop_id": self.workshop_id,
            "module_key": "firings",
            "modules": ["mb_ceramics_firing"],
        })
        self.assertTrue(enabled["restriction_removed"])
        self.assertFalse(policy.exists())
        self.assertFalse(self.env["ir.rule"].sudo().browse(rule_ids).exists())
