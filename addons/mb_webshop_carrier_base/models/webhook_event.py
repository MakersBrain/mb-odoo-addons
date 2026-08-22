import time
from datetime import timedelta

from odoo import _, api, fields, models

from ..provider import ProviderError, ProviderWebhookEvent, TrackingSnapshot


class CarrierWebhookEvent(models.Model):
    _name = "mb.carrier.webhook.event"
    _description = "Durable carrier webhook inbox"
    _order = "create_date, id"

    company_id = fields.Many2one("res.company", required=True, index=True, ondelete="cascade")
    carrier_id = fields.Many2one("delivery.carrier", required=True, index=True, ondelete="restrict")
    provider_code = fields.Char(required=True, index=True)
    subscription_id = fields.Char(required=True, index=True)
    event_key = fields.Char(required=True, index=True)
    provider_ref = fields.Char(required=True, index=True)
    kind = fields.Selection([("document", "Document"), ("tracking", "Tracking")], required=True)
    tracking_number = fields.Char()
    tracking_url = fields.Char()
    document_ref = fields.Char(groups="base.group_system")
    occurred_at = fields.Char()
    status_code = fields.Char()
    status_category = fields.Char()
    status_message = fields.Char()
    state = fields.Selection(
        [
            ("received", "Received"),
            ("processing", "Processing"),
            ("done", "Done"),
            ("retry", "Retry"),
            ("failed", "Failed"),
        ],
        default="received",
        required=True,
        index=True,
    )
    attempts = fields.Integer(default=0)
    next_attempt_at = fields.Datetime(default=fields.Datetime.now, index=True)
    last_error = fields.Char()
    processed_at = fields.Datetime()

    _event_unique = models.Constraint(
        "UNIQUE(carrier_id, subscription_id, event_key)",
        "A provider webhook event is accepted only once.",
    )

    @api.model
    def receive(self, carrier, event: ProviderWebhookEvent, event_key):
        values = {
            "company_id": carrier.company_id.id,
            "carrier_id": carrier.id,
            "provider_code": carrier.mb_provider_code,
            "subscription_id": carrier.mb_subscription_id,
            "event_key": event_key,
            "provider_ref": event.provider_ref,
            "kind": event.kind,
            "tracking_number": event.tracking_number or False,
            "tracking_url": event.tracking_url or False,
            "document_ref": event.document_ref or False,
            "occurred_at": event.occurred_at or False,
            "status_code": event.status_code or False,
            "status_category": event.status_category or False,
            "status_message": (event.status_message or "")[:512] or False,
        }
        # Avoid raising/logging an expected uniqueness error for normal webhook
        # retries. The normalized inbox has no create hooks or computed fields.
        now = fields.Datetime.now()
        self.env.cr.execute(
            """
            INSERT INTO mb_carrier_webhook_event (
                company_id, carrier_id, provider_code, subscription_id,
                event_key, provider_ref, kind, tracking_number, tracking_url,
                document_ref, occurred_at, status_code, status_category,
                status_message, state, attempts, next_attempt_at,
                create_uid, create_date, write_uid, write_date
            ) VALUES (
                %(company_id)s, %(carrier_id)s, %(provider_code)s, %(subscription_id)s,
                %(event_key)s, %(provider_ref)s, %(kind)s, %(tracking_number)s,
                %(tracking_url)s, %(document_ref)s, %(occurred_at)s,
                %(status_code)s, %(status_category)s, %(status_message)s, 'received', 0,
                %(now)s, %(uid)s, %(now)s, %(uid)s, %(now)s
            ) ON CONFLICT (carrier_id, subscription_id, event_key) DO NOTHING
            RETURNING id
        """,
            {**values, "uid": self.env.uid, "now": now},
        )
        inserted = self.env.cr.fetchone()
        if inserted:
            return self.sudo().browse(inserted[0]), True
        existing = self.sudo().search(
            [
                ("carrier_id", "=", carrier.id),
                ("subscription_id", "=", carrier.mb_subscription_id),
                ("event_key", "=", event_key),
            ],
            limit=1,
        )
        return existing, False

    def _provider_event(self):
        self.ensure_one()
        return ProviderWebhookEvent(
            event_id=self.event_key,
            provider_ref=self.provider_ref,
            kind=self.kind,
            tracking_number=self.tracking_number or "",
            tracking_url=self.tracking_url or "",
            document_ref=self.document_ref or "",
            occurred_at=self.occurred_at or "",
            status_code=self.status_code or "",
            status_category=self.status_category or "",
            status_message=self.status_message or "",
        )

    def _process_one(self):
        self.ensure_one()
        shipment = (
            self.env["mb.carrier.shipment"]
            .sudo()
            .search(
                [
                    ("carrier_id", "=", self.carrier_id.id),
                    "|",
                    ("provider_ref", "=", self.provider_ref),
                    ("tracking_number", "=", self.tracking_number),
                ],
                limit=1,
            )
        )
        if not shipment:
            attempts = self.attempts + 1
            self.write(
                {
                    "state": "failed" if attempts >= 10 else "retry",
                    "attempts": attempts,
                    "next_attempt_at": fields.Datetime.now()
                    + timedelta(minutes=min(60, 2**attempts)),
                    "last_error": "shipment_not_visible_yet",
                }
            )
            return
        started = time.monotonic()
        try:
            if self.kind == "document":
                document = self.carrier_id._mb_provider(
                    purpose="document_recovery"
                ).fetch_webhook_document(self._provider_event())
                shipment._store_document(document)
                shipment.write(
                    {
                        "state": "label_ready",
                        "completed_at": fields.Datetime.now(),
                        "last_event_at": fields.Datetime.now(),
                    }
                )
                shipment._log(started, "success", operation="webhook_document")
                shipment.picking_id.message_post(body=_("The carrier label document is ready."))
            else:
                try:
                    occurred_at = (
                        fields.Datetime.to_datetime(
                            self.occurred_at.replace("Z", "+00:00")
                        ).replace(tzinfo=None)
                        if self.occurred_at
                        else None
                    )
                except (TypeError, ValueError):
                    occurred_at = None
                shipment._apply_tracking_snapshot(
                    TrackingSnapshot(
                        status_code=self.status_code or "webhook_update",
                        category=self.status_category or "unknown",
                        message=self.status_message or "",
                        tracking_number=self.tracking_number or shipment.tracking_number or "",
                        tracking_url=self.tracking_url or shipment.tracking_url or "",
                        event_at=occurred_at,
                    )
                )
                shipment.last_event_at = fields.Datetime.now()
            self.write(
                {
                    "state": "done",
                    "processed_at": fields.Datetime.now(),
                    "document_ref": False,
                    "last_error": False,
                }
            )
        except ProviderError:
            attempts = self.attempts + 1
            shipment._log(
                started,
                "unavailable",
                "provider_document_unavailable",
                operation="webhook_document",
            )
            self.write(
                {
                    "state": "failed" if attempts >= 10 else "retry",
                    "attempts": attempts,
                    "next_attempt_at": fields.Datetime.now()
                    + timedelta(minutes=min(60, 2**attempts)),
                    "last_error": "provider_document_unavailable",
                }
            )

    @api.model
    def _cron_process(self, limit=50):
        self.env.cr.execute(
            """
            SELECT id FROM mb_carrier_webhook_event
             WHERE state IN ('received', 'retry') AND next_attempt_at <= now()
             ORDER BY create_date, id
             FOR UPDATE SKIP LOCKED LIMIT %s
        """,
            [limit],
        )
        events = self.sudo().browse([row[0] for row in self.env.cr.fetchall()])
        for event in events:
            event.write({"state": "processing"})
            event._process_one()
        return len(events)

    @api.model
    def _cron_purge(self):
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=30)
        self.sudo().search(
            [("state", "in", ("done", "failed")), ("create_date", "<", cutoff)]
        ).unlink()
