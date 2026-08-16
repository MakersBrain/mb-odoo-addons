from __future__ import annotations

import hashlib
import time

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..provider import (
    Parcel,
    ProviderAuthError,
    ProviderError,
    ProviderTransientError,
    ProviderUnavailableError,
    ProviderValidationError,
    ShipmentDocument,
    ShipmentRequest,
    provider_class,
)


SHIPMENT_STATES = [
    ("draft", "Queued"),
    ("submitting", "Submitting"),
    ("awaiting_document", "Awaiting document"),
    ("label_ready", "Label ready"),
    ("cancel_pending", "Cancellation queued"),
    ("cancelled", "Cancelled"),
    ("failed", "Failed"),
    ("unknown", "Unknown outcome"),
]


class CarrierShipment(models.Model):
    _name = "mb.carrier.shipment"
    _description = "Durable carrier shipment journal"
    _order = "create_date desc, parcel_index, id"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", required=True, index=True, ondelete="cascade")
    carrier_id = fields.Many2one("delivery.carrier", required=True, index=True, ondelete="restrict")
    picking_id = fields.Many2one("stock.picking", required=True, index=True, ondelete="restrict")
    direction = fields.Selection(
        [("outbound", "Outbound"), ("return", "Return")], required=True, index=True
    )
    parcel_index = fields.Integer(required=True, default=0)
    idempotency_key = fields.Char(required=True, index=True, copy=False)
    state = fields.Selection(SHIPMENT_STATES, required=True, default="draft", index=True, copy=False)
    operation = fields.Selection(
        [("create", "Create"), ("cancel", "Cancel")], required=True, default="create", copy=False
    )
    provider_ref = fields.Char(index=True, copy=False)
    tracking_number = fields.Char(copy=False)
    tracking_url = fields.Char(copy=False)
    exact_price = fields.Float(copy=False)
    document_ids = fields.Many2many(
        "ir.attachment", "mb_carrier_shipment_attachment_rel",
        "shipment_id", "attachment_id", string="Documents", copy=False,
    )
    last_error = fields.Char(copy=False)
    submitted_at = fields.Datetime(copy=False)
    completed_at = fields.Datetime(copy=False)
    last_event_at = fields.Datetime(copy=False)

    _idempotency_unique = models.Constraint(
        "UNIQUE(carrier_id, idempotency_key)",
        "A carrier operation can create only one shipment.",
    )
    _provider_ref_unique = models.Constraint(
        "UNIQUE(carrier_id, provider_ref)",
        "A provider shipment reference can be linked only once.",
    )

    @api.depends("picking_id.name", "direction", "parcel_index")
    def _compute_name(self):
        for shipment in self:
            shipment.name = "%s / %s %s" % (
                shipment.picking_id.name or _("Transfer"),
                dict(self._fields["direction"].selection).get(shipment.direction, ""),
                shipment.parcel_index + 1,
            )

    @api.model
    def create_or_get(self, values):
        existing = self.search([
            ("carrier_id", "=", values["carrier_id"]),
            ("idempotency_key", "=", values["idempotency_key"]),
        ], limit=1)
        if existing:
            return existing
        try:
            with self.env.cr.savepoint():
                return self.create(values)
        except IntegrityError:
            return self.search([
                ("carrier_id", "=", values["carrier_id"]),
                ("idempotency_key", "=", values["idempotency_key"]),
            ], limit=1)

    @staticmethod
    def _partner_payload(partner):
        return {
            "name": partner.name or "",
            "company": partner.commercial_company_name or "",
            "street": partner.street or "",
            "street2": partner.street2 or "",
            "zip": partner.zip or "",
            "city": partner.city or "",
            "country_code": partner.country_id.code or "",
            "phone": partner.phone or getattr(partner, "mobile", "") or "",
            "email": partner.email or "",
        }

    def _shipment_request(self):
        self.ensure_one()
        picking = self.picking_id
        sender = picking.picking_type_id.warehouse_id.partner_id or picking.company_id.partner_id
        recipient = picking.partner_id
        if not sender.country_id or not recipient.country_id:
            raise ProviderValidationError("sender and recipient countries are required")
        weight = picking.shipping_weight or picking.weight or picking._get_estimated_weight()
        if weight <= 0:
            raise ProviderValidationError("parcel weight must be greater than zero")
        pickup_code = ""
        if self.carrier_id._mb_uses_pickup_locations() and not recipient.mb_pickup_ref:
            raise ProviderValidationError("pickup point is required for this carrier service")
        if getattr(recipient, "mb_pickup_ref", False):
            pickup_code = recipient.mb_pickup_ref
            if (
                recipient.mb_pickup_provider != self.carrier_id.mb_provider_code
                or recipient.mb_pickup_service != self.carrier_id.mb_provider_service_code
            ):
                raise ProviderValidationError("pickup point does not match the carrier service")
            # A point may close after checkout. Resolve it again immediately
            # before purchase and require its authoritative address to match.
            point = self.carrier_id._mb_get_pickup_point(pickup_code, recipient)
            if (
                point.zip != recipient.zip
                or point.city.casefold() != (recipient.city or "").casefold()
                or point.street.casefold() != (recipient.street or "").casefold()
            ):
                raise ProviderValidationError("pickup point address changed after checkout")
        declared_value = picking.sale_id.amount_untaxed if picking.sale_id else 0
        return ShipmentRequest(
            idempotency_key=self.idempotency_key,
            service_code=self.carrier_id.mb_provider_service_code,
            sender=self._partner_payload(sender),
            recipient=self._partner_payload(recipient),
            parcels=(Parcel(weight_kg=weight, value=max(0, declared_value)),),
            pickup_code=pickup_code,
            provider_ref=self.provider_ref or "",
            metadata={"picking": picking.name or ""},
        )

    def _log(self, started, outcome, diagnostic="", status=0, operation=None):
        self.ensure_one()
        # Provider exception text is bounded but may still contain echoed input;
        # keep only a stable class/code, never a response body.
        safe_diagnostic = diagnostic if diagnostic.replace("_", "").isalnum() else ""
        self.env["mb.carrier.request.log"].sudo().create({
            "company_id": self.company_id.id,
            "provider_code": self.carrier_id.mb_provider_code,
            "operation": operation or self.operation,
            "shipment_id": self.id,
            "picking_id": self.picking_id.id,
            "http_status": status,
            "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
            "outcome": outcome,
            "diagnostic": safe_diagnostic[:128],
            "correlation_id": hashlib.sha256(self.idempotency_key.encode()).hexdigest()[:24],
        })

    def _post_operation_failure(self, ambiguous=False):
        """Post a fixed, translated message; provider response text is never chatter-safe."""
        self.ensure_one()
        if ambiguous:
            body = _(
                "The carrier operation has an unknown outcome. Verify it with the "
                "provider before retrying."
            )
        else:
            body = _(
                "The carrier operation failed. Review the shipment journal before retrying."
            )
        self.picking_id.message_post(body=body)

    def _store_document(self, document: ShipmentDocument):
        self.ensure_one()
        carrier = self.carrier_id
        if document.kind == "return_label" or self.direction == "return":
            prefix = carrier.get_return_label_prefix()
        elif document.kind == "manifest":
            prefix = carrier._get_delivery_doc_prefix()
        else:
            prefix = carrier._get_delivery_label_prefix()
        extension = "zpl" if document.format == "ZPL" else "pdf"
        attachment = self.env["ir.attachment"].sudo().create({
            "name": f"{prefix}-{self.provider_ref or self.id}.{extension}",
            "raw": document.content,
            "mimetype": "text/plain" if extension == "zpl" else "application/pdf",
            "res_model": "stock.picking",
            "res_id": self.picking_id.id,
        })
        self.document_ids = [(4, attachment.id)]
        if (
            (document.kind == "return_label" or self.direction == "return")
            and carrier.get_return_label_from_portal
        ):
            attachment.generate_access_token()
        return attachment

    def _apply_submission(self, submission):
        self.ensure_one()
        values = {
            "provider_ref": submission.provider_ref,
            "tracking_number": submission.tracking_number or False,
            "tracking_url": submission.tracking_url or False,
            "exact_price": submission.exact_price,
            "last_error": False,
        }
        self.write(values)
        for document in submission.documents:
            self._store_document(document)
        if submission.documents or submission.state == "complete":
            self.write({"state": "label_ready", "completed_at": fields.Datetime.now()})
        else:
            self.write({"state": "awaiting_document"})
        self._sync_tracking_to_picking()

    def _sync_tracking_to_picking(self):
        self.ensure_one()
        if not self.tracking_number:
            return
        refs = [part for part in (self.picking_id.carrier_tracking_ref or "").split(",") if part]
        if self.tracking_number not in refs:
            refs.append(self.tracking_number)
            self.picking_id.sudo().carrier_tracking_ref = ",".join(refs)

    def _remove_tracking_from_picking(self):
        self.ensure_one()
        if not self.tracking_number:
            return
        refs = [
            part for part in (self.picking_id.carrier_tracking_ref or "").split(",")
            if part and part != self.tracking_number
        ]
        self.picking_id.sudo().carrier_tracking_ref = ",".join(refs) or False

    def _process_create(self):
        self.ensure_one()
        started = time.monotonic()
        try:
            request = self._shipment_request()
            provider = self.carrier_id._mb_provider()
        except ProviderAuthError:
            self.write({"state": "failed", "last_error": "authentication_failed"})
            self._log(started, "auth", "authentication_failed")
            self._post_operation_failure()
            return
        except ProviderValidationError:
            self.write({"state": "failed", "last_error": "validation_failed"})
            self._log(started, "validation", "validation_failed")
            self._post_operation_failure()
            return
        except ProviderError:
            self.write({"state": "failed", "last_error": "provider_error"})
            self._log(started, "unavailable", "provider_error")
            self._post_operation_failure()
            return
        # A second mutation is safe only when the provider explicitly promises
        # that the supplied key deduplicates purchases. Other adapters remain
        # unknown after the first ambiguous response.
        attempts = 2 if getattr(provider, "supports_idempotency", False) else 1
        for attempt in range(attempts):
            started = time.monotonic()
            try:
                submission = (
                    provider.create_return_label(request)
                    if self.direction == "return"
                    else provider.create_shipment(request)
                )
                if not submission.provider_ref:
                    raise ProviderValidationError("provider returned no shipment reference")
                self._apply_submission(submission)
                self._log(started, "success")
                self.picking_id.message_post(body=_("Carrier label purchase accepted."))
                return
            except ProviderAuthError:
                self.write({"state": "failed", "last_error": "authentication_failed"})
                self._log(started, "auth", "authentication_failed")
                self._post_operation_failure()
                return
            except ProviderValidationError:
                self.write({"state": "failed", "last_error": "validation_failed"})
                self._log(started, "validation", "validation_failed")
                self._post_operation_failure()
                return
            except (ProviderTransientError, ProviderUnavailableError):
                final_attempt = attempt + 1 >= attempts
                self._log(
                    started,
                    "unknown" if final_attempt else "transient",
                    "ambiguous_provider_outcome" if final_attempt else "safe_retry_scheduled",
                )
                if final_attempt:
                    self.write({
                        "state": "unknown",
                        "last_error": "ambiguous_provider_outcome",
                    })
                    self._post_operation_failure(ambiguous=True)
                    return
            except ProviderError:
                self.write({"state": "failed", "last_error": "provider_error"})
                self._log(started, "unavailable", "provider_error")
                self._post_operation_failure()
                return

    def _process_cancel(self):
        self.ensure_one()
        if not self.provider_ref:
            self.write({"state": "failed", "last_error": "missing_provider_reference"})
            return
        started = time.monotonic()
        try:
            provider = self.carrier_id._mb_provider()
        except ProviderError:
            self.write({"state": "failed", "last_error": "provider_error"})
            self._log(started, "unavailable", "provider_error")
            self._post_operation_failure()
            return
        attempts = 2 if getattr(provider, "supports_idempotency", False) else 1
        for attempt in range(attempts):
            started = time.monotonic()
            try:
                provider.cancel_shipment(self.provider_ref)
                self.write({
                    "state": "cancelled", "completed_at": fields.Datetime.now(),
                    "last_error": False,
                })
                self._remove_tracking_from_picking()
                self._log(started, "success")
                self.picking_id.message_post(body=_("Provider cancellation confirmed."))
                return
            except (ProviderTransientError, ProviderUnavailableError):
                final_attempt = attempt + 1 >= attempts
                self._log(
                    started,
                    "unknown" if final_attempt else "transient",
                    "ambiguous_cancel_outcome" if final_attempt else "safe_retry_scheduled",
                )
                if final_attempt:
                    self.write({"state": "unknown", "last_error": "ambiguous_cancel_outcome"})
                    self._post_operation_failure(ambiguous=True)
                    return
            except ProviderError:
                self.write({"state": "failed", "last_error": "cancellation_failed"})
                self._log(started, "unavailable", "cancellation_failed")
                self._post_operation_failure()
                return

    def _process_one(self):
        self.ensure_one()
        if self.operation == "cancel":
            self._process_cancel()
        else:
            self._process_create()

    def action_queue_cancellation(self):
        for shipment in self:
            if shipment.state == "cancelled":
                continue
            if not shipment.provider_ref:
                raise UserError(_("The provider has not accepted this shipment yet."))
            shipment.write({"operation": "cancel", "state": "cancel_pending", "last_error": False})
        return True

    def action_retry(self):
        for shipment in self:
            if shipment.state != "failed":
                raise UserError(_("Only a definitely failed operation can be retried."))
            shipment.write({
                "state": "cancel_pending" if shipment.operation == "cancel" else "draft",
                "last_error": False,
            })
        return True

    def action_reconcile(self):
        for shipment in self:
            if shipment.state != "unknown" or shipment.operation != "create":
                raise UserError(_("Only an unknown creation outcome can be reconciled."))
            provider = shipment.carrier_id._mb_provider()
            if not getattr(provider, "supports_reconciliation", False):
                raise UserError(_("This provider cannot reconcile an ambiguous purchase automatically."))
            started = time.monotonic()
            try:
                submission = provider.reconcile_shipment(shipment._shipment_request())
                if submission is None:
                    shipment.write({"state": "failed", "last_error": "provider_confirmed_absent"})
                else:
                    shipment._apply_submission(submission)
                shipment._log(started, "success", operation="reconcile")
            except ProviderError:
                shipment._log(started, "unavailable", "reconciliation_failed", operation="reconcile")
                raise
        return True

    def action_confirm_absent(self):
        """Merchant acknowledgement for providers with no safe lookup API."""
        for shipment in self:
            if shipment.state != "unknown" or shipment.operation != "create":
                raise UserError(_("Only an unknown creation outcome can be resolved this way."))
            provider_type = provider_class(shipment.carrier_id.mb_provider_code or "")
            if getattr(provider_type, "supports_reconciliation", False):
                raise UserError(_("Use provider reconciliation for this shipment."))
            shipment.write({
                "state": "failed",
                "last_error": "merchant_confirmed_provider_absent",
            })
            shipment.picking_id.message_post(
                body=_("Merchant confirmed that no provider shipment exists; retry is now available.")
            )
        return True

    def action_confirm_cancelled(self):
        for shipment in self:
            if shipment.state != "unknown" or shipment.operation != "cancel":
                raise UserError(_("Only an unknown cancellation can be resolved this way."))
            shipment.write({
                "state": "cancelled",
                "completed_at": fields.Datetime.now(),
                "last_error": "merchant_confirmed_provider_cancelled",
            })
            shipment._remove_tracking_from_picking()
            shipment.picking_id.message_post(
                body=_("Merchant verified the cancellation in the provider portal.")
            )
        return True

    def action_confirm_not_cancelled(self):
        for shipment in self:
            if shipment.state != "unknown" or shipment.operation != "cancel":
                raise UserError(_("Only an unknown cancellation can be resolved this way."))
            shipment.write({
                "state": "failed",
                "last_error": "merchant_confirmed_provider_not_cancelled",
            })
        return True

    @api.model
    def _recover_stale_submissions(self, stale_minutes=15):
        """Never replay a mutation whose worker died after its durable claim."""
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), minutes=stale_minutes)
        stale = self.sudo().search([
            ("state", "=", "submitting"),
            "|", ("submitted_at", "=", False), ("submitted_at", "<", cutoff),
        ])
        for shipment in stale:
            shipment.write({
                "state": "unknown",
                "last_error": (
                    "worker_interrupted_cancel"
                    if shipment.operation == "cancel"
                    else "worker_interrupted_create"
                ),
            })
            shipment._post_operation_failure(ambiguous=True)
        return len(stale)

    @api.model
    def _cron_progress_active(self):
        # Odoo 19 uses ir_cron_progress_id/cron_id. Keep the legacy key for
        # compatibility with older installations and explicit test contexts.
        context = self.env.context
        return bool(
            context.get("ir_cron_progress_id")
            or context.get("cron_id")
            or context.get("ir_cron_id")
        )

    @api.model
    def _cron_process(self, limit=20):
        self._recover_stale_submissions()
        processed = 0
        cron_progress = self._cron_progress_active()
        while processed < limit:
            # Claim one row at a time. Committing a batch claim would release
            # the locks on the unprocessed rows and let another worker buy the
            # same label.
            self.env.cr.execute("""
                SELECT id FROM mb_carrier_shipment
                 WHERE state IN ('draft', 'cancel_pending')
                 ORDER BY create_date, id
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
            """)
            row = self.env.cr.fetchone()
            if not row:
                break
            shipment = self.sudo().browse(row[0])
            shipment.write({"state": "submitting", "submitted_at": fields.Datetime.now()})
            if cron_progress:
                # This commit is the crash-safety boundary: a process death at
                # any later point leaves a durable, non-replayable claim.
                self.env["ir.cron"]._commit_progress(0)
            shipment.invalidate_recordset()
            shipment._process_one()
            processed += 1
            if cron_progress:
                remaining = self.search_count([("state", "in", ("draft", "cancel_pending"))])
                if not self.env["ir.cron"]._commit_progress(1, remaining=remaining):
                    break
        return processed
