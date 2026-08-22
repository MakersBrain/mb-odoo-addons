from __future__ import annotations

import hashlib

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..provider import PickupQuery, ProviderError


class CarrierPickupPoint(models.Model):
    _name = "mb.carrier.pickup.point"
    _description = "Short-lived carrier pickup-point cache"
    _order = "distance_m, name, id"

    company_id = fields.Many2one("res.company", required=True, index=True, ondelete="cascade")
    carrier_id = fields.Many2one("delivery.carrier", required=True, index=True, ondelete="cascade")
    provider_code = fields.Char(required=True, index=True)
    service_code = fields.Char(required=True, index=True)
    # Nullable only for zero-downtime upgrade of the short-lived pre-field cache;
    # every newly fetched row sets it and old rows expire within an hour.
    query_country_id = fields.Many2one("res.country", index=True, ondelete="cascade")
    query_zip = fields.Char(required=True, index=True)
    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    street = fields.Char(required=True)
    zip = fields.Char(required=True)
    city = fields.Char(required=True)
    country_id = fields.Many2one("res.country", required=True, ondelete="restrict")
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    opening_hours = fields.Json(default=dict)
    distance_m = fields.Integer()
    fetched_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)

    _cache_unique = models.Constraint(
        "UNIQUE(carrier_id, service_code, query_country_id, query_zip, code)",
        "A pickup point occurs once in a carrier search result.",
    )

    def _checkout_value(self):
        self.ensure_one()
        return {
            "id": self.code,
            "name": self.name,
            "street": self.street,
            "city": self.city,
            "zip_code": self.zip,
            "state": "",
            "country_code": self.country_id.code,
            "latitude": str(self.latitude),
            "longitude": str(self.longitude),
            "openingHours": self.opening_hours or {},
            "additional_data": {
                "provider_code": self.provider_code,
                "service_code": self.service_code,
            },
        }

    @api.model
    def for_checkout(self, carrier, partner_address):
        carrier.ensure_one()
        zip_code = (partner_address.zip or "").strip().upper()
        country = partner_address.country_id
        if not zip_code or len(zip_code) > 16 or not country.code:
            raise UserError(_("A valid delivery country and postal code are required."))
        service = carrier.mb_provider_service_code or ""
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), minutes=10)
        domain = [
            ("carrier_id", "=", carrier.id),
            ("service_code", "=", service),
            ("query_country_id", "=", country.id),
            ("query_zip", "=", zip_code),
            ("fetched_at", ">=", cutoff),
        ]
        cached = self.search(domain, limit=20)
        if cached:
            return [point._checkout_value() for point in cached]
        try:
            points = carrier._mb_provider().search_pickup_points(
                PickupQuery(
                    country_code=country.code,
                    zip=zip_code,
                    city=partner_address.city or "",
                    service_code=service,
                    limit=20,
                )
            )
        except ProviderError as error:
            raise UserError(_("Pickup points are temporarily unavailable.")) from error
        country_by_code = {
            record.code: record
            for record in self.env["res.country"].search(
                [("code", "in", list({point.country_code for point in points}))]
            )
        }
        self.search(
            [
                ("carrier_id", "=", carrier.id),
                ("service_code", "=", service),
                ("query_country_id", "=", country.id),
                ("query_zip", "=", zip_code),
            ]
        ).unlink()
        records = self.browse()
        for point in points[:20]:
            point_country = country_by_code.get(point.country_code)
            if not point_country:
                continue
            records |= self.create(
                {
                    "company_id": carrier.company_id.id,
                    "carrier_id": carrier.id,
                    "provider_code": carrier.mb_provider_code,
                    "service_code": service,
                    "query_country_id": country.id,
                    "query_zip": zip_code,
                    "code": point.code[:128],
                    "name": point.name[:255],
                    "street": point.street[:255],
                    "zip": point.zip[:16],
                    "city": point.city[:128],
                    "country_id": point_country.id,
                    "latitude": point.latitude,
                    "longitude": point.longitude,
                    "opening_hours": point.opening_hours,
                    "distance_m": point.distance_m or 0,
                    "fetched_at": fields.Datetime.now(),
                }
            )
        return [point._checkout_value() for point in records]

    @api.model
    def _cron_purge(self):
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), hours=1)
        self.sudo().search([("fetched_at", "<", cutoff)]).unlink()


class CarrierPublicRate(models.Model):
    _name = "mb.carrier.public.rate"
    _description = "Carrier public-route rate-limit bucket"

    key_hash = fields.Char(required=True, index=True)
    route = fields.Char(required=True, index=True)
    window_start = fields.Datetime(required=True, index=True)
    count = fields.Integer(required=True, default=0)

    _bucket_unique = models.Constraint(
        "UNIQUE(key_hash, route, window_start)", "A rate-limit bucket is unique."
    )

    @api.model
    def consume(self, identity, route, maximum):
        now = fields.Datetime.now().replace(second=0, microsecond=0)
        key_hash = hashlib.sha256(identity.encode()).hexdigest()
        self.env.cr.execute(
            """
            INSERT INTO mb_carrier_public_rate(key_hash, route, window_start, count,
                                               create_uid, create_date, write_uid, write_date)
            VALUES (%s, %s, %s, 1, %s, now(), %s, now())
            ON CONFLICT (key_hash, route, window_start)
            DO UPDATE SET count = mb_carrier_public_rate.count + 1,
                          write_uid = EXCLUDED.write_uid, write_date = now()
            RETURNING count
        """,
            [key_hash, route, now, self.env.uid, self.env.uid],
        )
        if self.env.cr.fetchone()[0] > maximum:
            raise UserError(_("Too many pickup-point requests. Please wait a minute."))

    @api.model
    def _cron_purge(self):
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), hours=2)
        self.sudo().search([("window_start", "<", cutoff)]).unlink()
