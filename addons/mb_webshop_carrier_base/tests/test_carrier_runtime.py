from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from ..provider import (
    CredentialStatus,
    PickupPoint,
    ProviderValidationError,
    ProviderTransientError,
    ProviderWebhookEvent,
    ShipmentDocument,
    ShipmentSubmission,
    ShippingService,
    TrackingSnapshot,
    register_provider,
)
from ..models.delivery_carrier import DeliveryCarrier


@register_provider
class FixtureProvider:
    code = "fixture"
    supports_pickup_points = True
    supports_own_contract = False
    supports_manifest = False
    supports_return_label = True
    supports_tracking_lookup = False
    supports_contextual_options = False
    supports_idempotency = True
    supports_reconciliation = True

    def __init__(self, credentials=None, production=False, carrier=None):
        self.credentials = credentials or {}
        self.production = production
        self.carrier = carrier
        self.create_result = ShipmentSubmission("fixture-order", "pending")
        self.reconcile_result = None
        self.create_calls = 0

    def check_credentials(self):
        return CredentialStatus(True, "production" if self.production else "test")

    def list_services(self):
        return [ShippingService("relay", "Fixture relay", supports_pickup_points=True)]

    def search_pickup_points(self, query):
        return [self.get_pickup_point("POINT-1", query.service_code)]

    def get_pickup_point(self, code, service_code="", query=None):
        return PickupPoint(
            code=code,
            name="Fixture Point",
            street="12 rue du Test",
            zip="75011",
            city="Paris",
            country_code="FR",
        )

    def create_shipment(self, request):
        self.create_calls += 1
        if isinstance(self.create_result, Exception):
            raise self.create_result
        return self.create_result

    def reconcile_shipment(self, request):
        return self.reconcile_result

    def cancel_shipment(self, provider_ref):
        return None

    def create_return_label(self, request):
        return self.create_shipment(request)

    def build_manifest(self, provider_refs):
        raise NotImplementedError

    def verify_webhook(self, raw_body, headers, secret):
        return True

    def parse_webhook(self, raw_body):
        raise NotImplementedError

    def fetch_webhook_document(self, event):
        return ShipmentDocument(b"%PDF-1.4 fixture", "PDF", "label", "label.pdf")


@tagged("post_install", "-at_install")
class TestCarrierRuntime(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.mb_control_workshop_id = "00000000-0000-4000-8000-000000000001"
        country = cls.env.ref("base.fr")
        cls.recipient = cls.env["res.partner"].create({
            "name": "Recipient",
            "street": "3 rue Oberkampf",
            "zip": "75011",
            "city": "Paris",
            "country_id": country.id,
            "email": "recipient@example.test",
        })
        warehouse = cls.env["stock.warehouse"].search([
            ("company_id", "=", cls.company.id),
        ], limit=1)
        warehouse.partner_id.write({
            "street": "1 rue de l'Atelier",
            "zip": "75011",
            "city": "Paris",
            "country_id": country.id,
        })
        delivery_product = cls.env["product.product"].create({
            "name": "Fixture delivery",
            "type": "service",
            "sale_ok": True,
        })
        cls.carrier = cls.env["delivery.carrier"].create({
            "name": "Fixture carrier",
            "delivery_type": "fixed",
            "product_id": delivery_product.id,
            "fixed_price": 5,
            "company_id": cls.company.id,
            "mb_provider_code": "fixture",
            "mb_provider_service_code": "relay",
            "mb_secret_ref": "carrier-secret-fixture",
        })
        cls.picking = cls.env["stock.picking"].create({
            "partner_id": cls.recipient.id,
            "picking_type_id": warehouse.out_type_id.id,
            "location_id": warehouse.lot_stock_id.id,
            "location_dest_id": cls.env.ref("stock.stock_location_customers").id,
            "company_id": cls.company.id,
            "carrier_id": cls.carrier.id,
            "shipping_weight": 1.2,
        })

    def setUp(self):
        super().setUp()
        self.provider = FixtureProvider(carrier=self.carrier)
        self.provider_patch = patch.object(
            type(self.carrier), "_mb_provider", autospec=True, return_value=self.provider
        )
        self.provider_patch.start()
        self.addCleanup(self.provider_patch.stop)

    def _shipment(self, direction="outbound", suffix="one"):
        return self.env["mb.carrier.shipment"].create_or_get({
            "company_id": self.company.id,
            "carrier_id": self.carrier.id,
            "picking_id": self.picking.id,
            "direction": direction,
            "parcel_index": 0,
            "idempotency_key": f"fixture-{direction}-{suffix}",
        })

    def test_repeated_queueing_returns_one_journal_row(self):
        first = self._shipment()
        second = self._shipment()

        self.assertEqual(first, second)
        self.assertEqual(self.env["mb.carrier.shipment"].search_count([
            ("carrier_id", "=", self.carrier.id),
            ("idempotency_key", "=", first.idempotency_key),
        ]), 1)

    def test_pending_submission_is_completed_by_deduplicated_document_event(self):
        shipment = self._shipment(suffix="webhook")
        shipment._process_create()
        self.assertEqual(shipment.state, "awaiting_document")
        self.assertEqual(self.provider.create_calls, 1)

        self.carrier.mb_subscription_id = "fixture_subscription_0001"
        event = ProviderWebhookEvent(
            event_id="evt-1",
            provider_ref="fixture-order",
            kind="document",
            document_ref="doc-1",
        )
        inbox, created = self.env["mb.carrier.webhook.event"].receive(
            self.carrier, event, event.event_id
        )
        replay, replay_created = self.env["mb.carrier.webhook.event"].receive(
            self.carrier, event, event.event_id
        )
        inbox._process_one()

        self.assertTrue(created)
        self.assertFalse(replay_created)
        self.assertEqual(inbox, replay)
        self.assertEqual(inbox.state, "done")
        self.assertEqual(shipment.state, "label_ready")
        self.assertEqual(len(shipment.document_ids), 1)
        self.assertTrue(shipment.document_ids.name.startswith(
            self.carrier._get_delivery_label_prefix()
        ))
        self.assertFalse(shipment.document_ids.access_token)
        webhook_log = self.env["mb.carrier.request.log"].search([
            ("shipment_id", "=", shipment.id),
            ("operation", "=", "webhook_document"),
        ])
        self.assertEqual(webhook_log.outcome, "success")
        self.assertTrue(self.env["mail.message"].search_count([
            ("model", "=", "stock.picking"),
            ("res_id", "=", self.picking.id),
            ("body", "ilike", "label document is ready"),
        ]))

    def test_idempotent_purchase_has_one_bounded_safe_retry(self):
        shipment = self._shipment(suffix="timeout")
        self.provider.create_result = ProviderTransientError("secret echoed response")

        shipment._process_create()
        # The scratch database may retain unrelated queued fixtures after an
        # interrupted test run; this assertion is about this row's eligibility.
        self.env["mb.carrier.shipment"].search([
            ("id", "!=", shipment.id),
            ("state", "in", ("draft", "cancel_pending")),
        ]).unlink()
        self.env["mb.carrier.shipment"]._cron_process()

        self.assertEqual(shipment.state, "unknown")
        self.assertEqual(self.provider.create_calls, 2)
        self.assertEqual(shipment.last_error, "ambiguous_provider_outcome")
        request_log = self.env["mb.carrier.request.log"].search([
            ("shipment_id", "=", shipment.id),
        ], order="id")
        self.assertEqual(request_log.mapped("outcome"), ["transient", "unknown"])
        self.assertFalse(any("secret" in (value or "") for value in request_log.mapped("diagnostic")))
        self.assertTrue(self.env["mail.message"].search_count([
            ("model", "=", "stock.picking"),
            ("res_id", "=", self.picking.id),
            ("body", "ilike", "unknown outcome"),
        ]))

    def test_provider_without_idempotency_is_never_automatically_replayed(self):
        shipment = self._shipment(suffix="unsafe-timeout")
        self.provider.create_result = ProviderTransientError("timeout")
        original = FixtureProvider.supports_idempotency
        FixtureProvider.supports_idempotency = False
        self.addCleanup(setattr, FixtureProvider, "supports_idempotency", original)

        shipment._process_create()

        self.assertEqual(shipment.state, "unknown")
        self.assertEqual(self.provider.create_calls, 1)

    def test_return_creation_never_inherits_outbound_retry_safety(self):
        shipment = self._shipment(direction="return", suffix="unsafe-return-timeout")
        self.provider.create_result = ProviderTransientError("timeout")

        shipment._process_create()

        self.assertEqual(shipment.state, "unknown")
        self.assertEqual(self.provider.create_calls, 1)

    def test_return_request_reverses_customer_and_workshop_addresses(self):
        shipment = self._shipment(direction="return", suffix="direction")

        request = shipment._shipment_request()

        self.assertEqual(request.sender["name"], "Recipient")
        self.assertNotEqual(request.recipient["name"], "Recipient")
        self.assertFalse(request.pickup_code)

    def test_idempotent_retry_can_complete_without_duplicate_journal(self):
        shipment = self._shipment(suffix="safe-retry-success")
        with patch.object(
            self.provider,
            "create_shipment",
            side_effect=[
                ProviderTransientError("timeout"),
                ShipmentSubmission("fixture-retried-order", "pending"),
            ],
        ) as create:
            shipment._process_create()

        self.assertEqual(create.call_count, 2)
        self.assertEqual(shipment.state, "awaiting_document")
        self.assertEqual(shipment.provider_ref, "fixture-retried-order")
        self.assertEqual(self.env["mb.carrier.request.log"].search_count([
            ("shipment_id", "=", shipment.id),
        ]), 2)

    def test_stale_durable_claim_becomes_unknown_instead_of_replaying(self):
        shipment = self._shipment(suffix="stale-claim")
        shipment.write({
            "state": "submitting",
            "submitted_at": fields.Datetime.subtract(fields.Datetime.now(), minutes=20),
        })

        recovered = self.env["mb.carrier.shipment"]._recover_stale_submissions()

        self.assertGreaterEqual(recovered, 1)
        self.assertEqual(shipment.state, "unknown")
        self.assertEqual(shipment.last_error, "worker_interrupted_create")
        self.assertEqual(self.provider.create_calls, 0)

    def test_odoo_19_cron_context_is_detected(self):
        shipments = self.env["mb.carrier.shipment"]

        self.assertTrue(shipments.with_context(ir_cron_progress_id=7)._cron_progress_active())
        self.assertTrue(shipments.with_context(cron_id=7)._cron_progress_active())
        self.assertFalse(shipments.with_context(
            ir_cron_progress_id=False, cron_id=False, ir_cron_id=False
        )._cron_progress_active())

    def test_orphan_webhook_becomes_terminal_after_bounded_retries(self):
        self.carrier.mb_subscription_id = "fixture_subscription_orphan"
        event = ProviderWebhookEvent(
            event_id="evt-orphan",
            provider_ref="missing-provider-order",
            kind="document",
            document_ref="doc-orphan",
        )
        inbox, _created = self.env["mb.carrier.webhook.event"].receive(
            self.carrier, event, event.event_id
        )

        for _attempt in range(10):
            inbox._process_one()

        self.assertEqual(inbox.state, "failed")
        self.assertEqual(inbox.attempts, 10)
        self.assertEqual(inbox.last_error, "shipment_not_visible_yet")

    def test_reconciliation_can_prove_an_ambiguous_purchase_absent(self):
        shipment = self._shipment(suffix="reconcile")
        shipment.state = "unknown"

        shipment.action_reconcile()

        self.assertEqual(shipment.state, "failed")
        self.assertEqual(shipment.last_error, "provider_confirmed_absent")

    def test_merchant_can_explicitly_resolve_unknown_for_provider_without_lookup(self):
        shipment = self._shipment(suffix="manual-resolution")
        shipment.state = "unknown"
        original = FixtureProvider.supports_reconciliation
        FixtureProvider.supports_reconciliation = False
        self.addCleanup(setattr, FixtureProvider, "supports_reconciliation", original)

        shipment.action_confirm_absent()

        self.assertEqual(shipment.state, "failed")
        self.assertEqual(shipment.last_error, "merchant_confirmed_provider_absent")

    def test_ambiguous_cancellation_keeps_tracking_until_explicit_confirmation(self):
        shipment = self._shipment(suffix="cancel-resolution")
        shipment.write({
            "state": "unknown",
            "operation": "cancel",
            "tracking_number": "TRACK-1",
        })
        self.picking.carrier_tracking_ref = "TRACK-1"

        self.assertEqual(self.picking.carrier_tracking_ref, "TRACK-1")
        shipment.action_confirm_cancelled()

        self.assertEqual(shipment.state, "cancelled")
        self.assertFalse(self.picking.carrier_tracking_ref)

    def test_older_tracking_update_cannot_regress_terminal_state(self):
        shipment = self._shipment(suffix="tracking-order")
        delivered_at = datetime(2026, 8, 18, 12, 0, 0)
        shipment._apply_tracking_snapshot(TrackingSnapshot(
            status_code="DELIVERED",
            category="delivered",
            message="Delivered",
            tracking_number="TRACK-TERMINAL",
            event_at=delivered_at,
        ))

        changed = shipment._apply_tracking_snapshot(TrackingSnapshot(
            status_code="IN_TRANSIT",
            category="in_transit",
            message="Older event",
            tracking_number="TRACK-TERMINAL",
            event_at=delivered_at - timedelta(hours=2),
        ))

        self.assertFalse(changed)
        self.assertEqual(shipment.provider_tracking_code, "DELIVERED")
        self.assertEqual(shipment.provider_tracking_status, "delivered")

    def test_return_document_alone_gets_portal_token(self):
        self.carrier.get_return_label_from_portal = True
        shipment = self._shipment(direction="return", suffix="return")
        shipment.provider_ref = "return-order"

        attachment = shipment._store_document(ShipmentDocument(
            b"%PDF-1.4 return", "PDF", "return_label", "return.pdf"
        ))

        self.assertTrue(attachment.name.startswith(self.carrier.get_return_label_prefix()))
        self.assertTrue(attachment.access_token)

    def test_pickup_address_is_resolved_again_before_purchase(self):
        point = self.provider.get_pickup_point("POINT-1", "relay")
        self.recipient.write({
            "name": point.name,
            "street": point.street,
            "zip": point.zip,
            "city": point.city,
            "mb_pickup_ref": point.code,
            "mb_pickup_provider": "fixture",
            "mb_pickup_service": "relay",
        })
        shipment = self._shipment(suffix="pickup")

        request = shipment._shipment_request()

        self.assertEqual(request.pickup_code, "POINT-1")

    def test_pickup_service_refuses_purchase_without_a_classified_point(self):
        shipment = self._shipment(suffix="pickup-required")
        with patch.object(
            type(self.carrier), "_mb_uses_pickup_locations", autospec=True, return_value=True
        ):
            with self.assertRaises(ProviderValidationError):
                shipment._shipment_request()

    def test_forged_pickup_address_is_rejected_before_payment(self):
        order = self.env["sale.order"].create({
            "partner_id": self.recipient.id,
            "carrier_id": self.carrier.id,
            "pickup_location_data": {
                "id": "POINT-1",
                "name": "Fixture Point",
                "street": "99 forged street",
                "zip_code": "75011",
                "city": "Paris",
                "country_code": "FR",
                "additional_data": {
                    "provider_code": "fixture",
                    "service_code": "relay",
                },
            },
            "mb_delivery_recipient_partner_id": self.recipient.id,
            "mb_delivery_recipient_snapshot": {"name": "Recipient", "country_code": "FR"},
        })
        with patch.object(
            type(self.carrier), "_mb_uses_pickup_locations", autospec=True, return_value=True
        ):
            with self.assertRaises(ValidationError):
                order._check_mb_pickup_consistency()

    def test_confirmation_does_not_convert_an_ordinary_address_to_pickup(self):
        ordinary = self.env["res.partner"].create({
            "parent_id": self.recipient.id,
            "type": "delivery",
            "name": "Ordinary address",
            "street": "12 rue du Test",
            "zip": "75011",
            "city": "Paris",
            "country_id": self.env.ref("base.fr").id,
        })
        order = self.env["sale.order"].create({
            "partner_id": self.recipient.id,
            "partner_shipping_id": self.recipient.id,
            "carrier_id": self.carrier.id,
            "pickup_location_data": {
                "id": "POINT-1",
                "name": "Fixture Point",
                "street": "12 rue du Test",
                "zip_code": "75011",
                "city": "Paris",
                "country_code": "FR",
                "state": "",
                "additional_data": {
                    "provider_code": "fixture",
                    "service_code": "relay",
                },
            },
        })
        with patch.object(
            type(self.carrier), "_mb_uses_pickup_locations", autospec=True, return_value=True
        ):
            order._action_confirm()

        self.assertFalse(ordinary.mb_pickup_ref)
        self.assertNotEqual(order.partner_shipping_id, ordinary)
        self.assertEqual(order.partner_shipping_id.mb_pickup_ref, "POINT-1")
        self.assertFalse(order.partner_shipping_id._can_be_edited_by_current_customer())

    def test_switching_carrier_clears_pickup_selection_and_partner(self):
        pickup = self.env["res.partner"].create({
            "parent_id": self.recipient.id,
            "type": "delivery",
            "name": "Fixture Point",
            "street": "12 rue du Test",
            "zip": "75011",
            "city": "Paris",
            "country_id": self.env.ref("base.fr").id,
            "is_pickup_location": True,
            "mb_pickup_ref": "POINT-1",
            "mb_pickup_provider": "fixture",
            "mb_pickup_service": "relay",
        })
        other_product = self.env["product.product"].create({
            "name": "Home delivery",
            "type": "service",
        })
        other_carrier = self.env["delivery.carrier"].create({
            "name": "Home carrier",
            "delivery_type": "fixed",
            "product_id": other_product.id,
            "fixed_price": 6,
            "company_id": self.company.id,
        })
        order = self.env["sale.order"].create({
            "partner_id": self.recipient.id,
            "partner_shipping_id": pickup.id,
            "carrier_id": self.carrier.id,
            "pickup_location_data": {
                "id": "POINT-1",
                "additional_data": {
                    "provider_code": "fixture",
                    "service_code": "relay",
                },
            },
        })

        order.write({"carrier_id": other_carrier.id})

        self.assertFalse(order.pickup_location_data)
        self.assertEqual(order.partner_shipping_id, self.recipient)
        self.assertFalse(order.mb_delivery_recipient_partner_id)
        self.assertFalse(order.mb_delivery_recipient_snapshot)

    def test_capability_deactivation_keeps_history_and_blocks_mutation(self):
        shipment = self._shipment(suffix="capability")
        evidence = self.company._mb_apply_capability_restriction(
            "shipping-fixture", "entitlement_inactive"
        )
        self.carrier.invalidate_recordset([
            "mb_provider_enabled", "mb_provider_restricted",
        ])

        self.assertEqual(evidence["adapter"], "odoo_carrier_mutation_gate")
        self.assertTrue(self.carrier.mb_provider_enabled)
        self.assertTrue(self.carrier.mb_provider_restricted)
        self.assertTrue(shipment.exists())
        with self.assertRaises(UserError):
            DeliveryCarrier._mb_provider(self.carrier)
        with self.assertRaises(UserError):
            self.carrier.write({"mb_provider_service_code": "other"})
        with patch.object(
            DeliveryCarrier, "_mb_resolve_credentials", autospec=True, return_value={}
        ):
            provider = DeliveryCarrier._mb_provider(
                self.carrier, purpose="cancellation"
            )
        self.assertIsInstance(provider, FixtureProvider)

        self.company._mb_remove_capability_restriction("shipping-fixture")
        self.carrier.invalidate_recordset([
            "mb_provider_enabled", "mb_provider_restricted",
        ])
        self.assertTrue(self.carrier.mb_provider_enabled)
        self.assertFalse(self.carrier.mb_provider_restricted)

    def test_retention_boundary_uses_sanitized_metadata_only(self):
        shipment = self._shipment(suffix="retention")
        shipment._log(0, "validation", "not safe: recipient@example.test")
        request_log = self.env["mb.carrier.request.log"].search([
            ("shipment_id", "=", shipment.id),
        ])

        self.assertFalse(request_log.diagnostic)
        self.assertNotIn(self.recipient.email, request_log.display_name)

    def test_local_handover_is_explicitly_not_an_official_manifest(self):
        shipment = self._shipment(suffix="handover")
        shipment.state = "label_ready"
        handover = self.env["mb.carrier.manifest"].create({
            "company_id": self.company.id,
            "carrier_id": self.carrier.id,
            "shipment_ids": [(6, 0, shipment.ids)],
        })

        action = handover.with_context(discard_logo_check=True).action_ready()

        self.assertEqual(handover.state, "ready")
        self.assertIn("Local handover worksheet", handover.name)
        self.assertEqual(action["type"], "ir.actions.report")
        self.assertEqual(action["report_type"], "qweb-pdf")
        self.assertTrue(handover.document_id)
        self.assertEqual(handover.document_id.mimetype, "application/pdf")
        self.assertEqual(handover.document_id.res_model, handover._name)
        self.assertEqual(handover.document_id.res_id, handover.id)
