import uuid

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


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

    def test_same_epoch_cannot_change_authority(self):
        self.Users.mb_reconcile_membership(self.membership())
        with self.assertRaises(ValidationError):
            self.Users.mb_reconcile_membership(self.membership(role="owner"))

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
