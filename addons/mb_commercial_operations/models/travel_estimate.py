from urllib.parse import urlparse

import requests

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

ALLOWED_TOLLQUOTE_HOSTS = {"api.stage.tollquote.com", "api.tollquote.com"}


class MbTollquoteConnector(models.Model):
    _name = "mb.tollquote.connector"
    _description = "TollQuote Connector"
    _inherit = ["mail.thread"]
    _check_company_auto = True

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        tracking=True,
    )
    environment = fields.Selection(
        [("staging", "Staging"), ("production", "Production")],
        required=True,
        default="staging",
        tracking=True,
    )
    base_url = fields.Char(
        required=True,
        default="https://api.stage.tollquote.com",
        tracking=True,
    )
    api_token = fields.Char(
        string="Bearer token",
        copy=False,
        groups="base.group_system",
        help="Odoo has no secret store. This field is restricted to Settings administrators and is never logged or copied.",
    )
    timeout_seconds = fields.Integer(required=True, default=15)
    last_health_at = fields.Datetime(readonly=True, copy=False)
    last_health_status = fields.Char(readonly=True, copy=False)

    _timeout_positive = models.Constraint(
        "CHECK(timeout_seconds > 0 AND timeout_seconds <= 60)",
        "The TollQuote timeout must be between 1 and 60 seconds.",
    )

    @api.constrains("base_url", "environment")
    def _check_base_url(self):
        expected = {
            "staging": "api.stage.tollquote.com",
            "production": "api.tollquote.com",
        }
        for connector in self:
            parsed = urlparse(connector.base_url)
            if parsed.scheme != "https" or parsed.hostname not in ALLOWED_TOLLQUOTE_HOSTS:
                raise ValidationError(_("Use an allow-listed TollQuote HTTPS host."))
            if parsed.hostname != expected[connector.environment]:
                raise ValidationError(
                    _("The TollQuote host does not match the selected environment.")
                )

    def _headers(self):
        self.ensure_one()
        token = self.sudo().api_token
        if not token and self.environment != "staging":
            raise ValidationError(_("Configure the TollQuote bearer token."))
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _request(self, method, path, *, payload=None, params=None):
        self.ensure_one()
        try:
            request_values = {
                "headers": self._headers(),
                "json": payload,
                "params": params,
                "timeout": self.timeout_seconds,
            }
            if self.sudo().api_token:
                response = requests.request(
                    method,
                    f"{self.base_url.rstrip('/')}{path}",
                    **request_values,
                )
            else:
                with requests.Session() as session:
                    bootstrap = session.get(
                        f"{self.base_url.rstrip('/')}/v1/client/bootstrap",
                        timeout=self.timeout_seconds,
                    )
                    bootstrap.raise_for_status()
                    response = session.request(
                        method,
                        f"{self.base_url.rstrip('/')}{path}",
                        **request_values,
                    )
            response.raise_for_status()
            return response.json()
        except requests.Timeout as exc:
            raise UserError(
                _("TollQuote timed out. Try again later or enter a manual travel cost.")
            ) from exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            if status == 401:
                message = _("TollQuote rejected the credential.")
            elif status == 429:
                message = _("TollQuote quota was exceeded. Try again later.")
            else:
                message = _("TollQuote returned HTTP %(status)s.", status=status)
            raise UserError(message) from exc
        except (requests.RequestException, ValueError) as exc:
            raise UserError(_("TollQuote is unavailable or returned an invalid response.")) from exc

    def action_check_health(self):
        if not self.env.user.has_group(
            "mb_commercial_operations.group_commercial_operations_manager"
        ):
            raise AccessError(_("Only a Commercial Operations Manager can test connectors."))
        for connector in self:
            response = connector._request("GET", "/ready")
            connector.write(
                {
                    "last_health_at": fields.Datetime.now(),
                    "last_health_status": response.get("status", "unknown"),
                }
            )
        return True


class MbTravelEstimate(models.Model):
    _name = "mb.travel.estimate"
    _description = "Travel Cost Estimate"
    _inherit = ["mail.thread"]
    _order = "calculated_at desc, id desc"
    _check_company_auto = True

    name = fields.Char(required=True, default=lambda self: _("Travel estimate"), tracking=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        tracking=True,
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    connector_id = fields.Many2one(
        "mb.tollquote.connector",
        required=True,
        check_company=True,
        ondelete="restrict",
    )
    operation_id = fields.Many2one(
        "mb.commercial.operation",
        check_company=True,
        copy=False,
        ondelete="set null",
        index=True,
    )
    project_id = fields.Many2one(
        related="operation_id.project_id",
        store=True,
    )
    task_id = fields.Many2one(related="operation_id.task_id", store=True)
    origin_partner_id = fields.Many2one("res.partner", check_company=True)
    destination_partner_id = fields.Many2one("res.partner", check_company=True)
    origin_latitude = fields.Float(required=True, digits=(10, 7))
    origin_longitude = fields.Float(required=True, digits=(10, 7))
    destination_latitude = fields.Float(required=True, digits=(10, 7))
    destination_longitude = fields.Float(required=True, digits=(10, 7))
    round_trip = fields.Boolean(default=True)
    departure_at = fields.Datetime(required=True, default=fields.Datetime.now)
    vehicle_class = fields.Integer(required=True, default=1)
    payment_option = fields.Integer(required=True, default=1)
    fuel_consumption_l_per_100km = fields.Float(default=7.0)
    fuel_price_eur_per_l = fields.Monetary(default=1.80)
    driver_cost_eur_per_hour = fields.Monetary(default=0.0)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("quoted", "Quoted"),
            ("accepted", "Accepted"),
            ("superseded", "Superseded"),
            ("failed", "Failed"),
        ],
        required=True,
        default="draft",
        copy=False,
        tracking=True,
        index=True,
    )
    revision = fields.Integer(required=True, default=1, copy=False)
    previous_revision_id = fields.Many2one("mb.travel.estimate", copy=False, ondelete="set null")
    request_id = fields.Char(copy=False, readonly=True, index=True)
    provider_version = fields.Char(copy=False, readonly=True)
    calculated_at = fields.Datetime(copy=False, readonly=True)
    distance_km = fields.Float(copy=False, readonly=True)
    duration_hours = fields.Float(copy=False, readonly=True)
    toll_cost = fields.Monetary(copy=False, readonly=True)
    provider_toll_amount = fields.Float(copy=False, readonly=True)
    conversion_rate = fields.Float(copy=False, readonly=True, digits=(12, 6))
    conversion_date = fields.Date(copy=False, readonly=True)
    fuel_cost = fields.Monetary(copy=False, readonly=True)
    driver_cost = fields.Monetary(copy=False, readonly=True)
    ferry_cost = fields.Monetary(copy=False, readonly=True)
    zone_cost = fields.Monetary(copy=False, readonly=True)
    other_route_cost = fields.Monetary(copy=False, readonly=True)
    total_operating_cost = fields.Monetary(copy=False, readonly=True)
    reporting_currency = fields.Char(copy=False, readonly=True)
    incomplete = fields.Boolean(copy=False, readonly=True)
    incomplete_acknowledged = fields.Boolean(copy=False, tracking=True)
    warning_text = fields.Text(copy=False, readonly=True)
    request_snapshot = fields.Json(copy=False, readonly=True)
    response_snapshot = fields.Json(copy=False, readonly=True)

    _assumptions_nonnegative = models.Constraint(
        "CHECK(fuel_consumption_l_per_100km >= 0 AND fuel_price_eur_per_l >= 0 "
        "AND driver_cost_eur_per_hour >= 0)",
        "Travel cost assumptions cannot be negative.",
    )
    _coordinate_ranges = models.Constraint(
        "CHECK(origin_latitude >= -90 AND origin_latitude <= 90 "
        "AND destination_latitude >= -90 AND destination_latitude <= 90 "
        "AND origin_longitude >= -180 AND origin_longitude <= 180 "
        "AND destination_longitude >= -180 AND destination_longitude <= 180)",
        "Travel coordinates are outside the valid latitude/longitude range.",
    )

    def _route_request(self, reverse=False):
        self.ensure_one()
        origin = {
            "lat": self.destination_latitude if reverse else self.origin_latitude,
            "lon": self.destination_longitude if reverse else self.origin_longitude,
        }
        destination = {
            "lat": self.origin_latitude if reverse else self.destination_latitude,
            "lon": self.origin_longitude if reverse else self.destination_longitude,
        }
        return {"locations": [origin, destination], "costing": "auto"}

    def _price_route(self, route_payload):
        self.ensure_one()
        response = route_payload.get("response", route_payload)
        trip = response.get("trip", response)
        legs = trip.get("legs") or []
        if len(legs) != 1 or not legs[0].get("shape"):
            raise UserError(_("TollQuote returned a route without a usable polyline."))
        quote_request = {
            "vehicle": {"class": self.vehicle_class, "payment_option": self.payment_option},
            "passage_date": fields.Datetime.to_string(self.departure_at).replace(" ", "T") + "Z",
            "reporting_currency": self.currency_id.name,
            "route": {"polyline6": legs[0]["shape"]},
            "mode": "consumer_estimate",
        }
        quote = self.connector_id._request("POST", "/v1/toll/quote", payload=quote_request)
        return quote_request, quote

    @staticmethod
    def _route_summary(route_payload):
        response = route_payload.get("response", route_payload)
        trip = response.get("trip", response)
        summary = trip.get("summary", {})
        return float(summary.get("length", 0.0)), float(summary.get("time", 0.0))

    @staticmethod
    def _money_value(value):
        if not value:
            return 0.0
        if isinstance(value, dict):
            value = value.get("value", 0.0)
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _calculate_current_revision(self):
        self.ensure_one()
        if self.state not in ("draft", "quoted", "failed"):
            raise UserError(_("Only a draft, failed, or unaccepted quote can be calculated."))
        requests_snapshot = []
        responses_snapshot = []
        total_distance = total_seconds = total_toll = 0.0
        total_provider_toll = 0.0
        warnings = []
        incomplete = False
        request_id = False
        reporting_currency = self.currency_id.name
        conversion_rates = []
        provider_versions = set()
        directions = [False, True] if self.round_trip else [False]
        try:
            for reverse in directions:
                route_request = self._route_request(reverse=reverse)
                route = self.connector_id._request("POST", "/v1/route/plan", payload=route_request)
                quote_request, quote = self._price_route(route)
                distance, seconds = self._route_summary(route)
                totals = quote.get("totals", {})
                payable = totals.get("estimated_payable") or totals.get("gross")
                provider_amount = self._money_value(payable)
                quote_currency_name = (
                    quote.get("reporting_currency")
                    or (payable.get("currency") if isinstance(payable, dict) else False)
                    or self.currency_id.name
                )
                total_distance += distance
                total_seconds += seconds
                total_provider_toll += provider_amount
                quote_currency = self.env["res.currency"].search(
                    [
                        ("name", "=", quote_currency_name),
                    ],
                    limit=1,
                )
                if not quote_currency:
                    incomplete = True
                    warnings.append(
                        _(
                            "Unknown provider currency %(currency)s; enter the toll cost manually.",
                            currency=quote_currency_name,
                        )
                    )
                else:
                    converted = quote_currency._convert(
                        provider_amount,
                        self.currency_id,
                        self.company_id,
                        fields.Date.to_date(self.departure_at),
                    )
                    total_toll += converted
                    if provider_amount:
                        conversion_rates.append(converted / provider_amount)
                request_id = request_id or quote.get("request_id")
                reporting_currency = quote_currency_name
                provider_versions.add(
                    str(quote.get("api_version") or quote.get("version") or "0.1.0")
                )
                quote_warnings = quote.get("warnings") or []
                warnings.extend(str(item) for item in quote_warnings)
                if (
                    quote.get("unpriced")
                    or quote.get("unpriced_countries")
                    or not payable
                    or distance <= 0
                    or seconds <= 0
                ):
                    incomplete = True
                requests_snapshot.append({"route": route_request, "quote": quote_request})
                responses_snapshot.append({"route": route, "quote": quote})
            fuel = (
                total_distance
                / 100.0
                * self.fuel_consumption_l_per_100km
                * self.fuel_price_eur_per_l
            )
            driver = total_seconds / 3600.0 * self.driver_cost_eur_per_hour
            total = total_toll + fuel + driver
            if provider_versions - {"0.1.0"}:
                incomplete = True
                warnings.append(
                    _(
                        "TollQuote API revision %(versions)s has not been validated.",
                        versions=", ".join(sorted(provider_versions)),
                    )
                )
            self.write(
                {
                    "state": "quoted",
                    "request_id": request_id,
                    "provider_version": ", ".join(sorted(provider_versions)) or "0.1.0",
                    "calculated_at": fields.Datetime.now(),
                    "distance_km": total_distance,
                    "duration_hours": total_seconds / 3600.0,
                    "toll_cost": self.currency_id.round(total_toll),
                    "provider_toll_amount": total_provider_toll,
                    "conversion_rate": (
                        sum(conversion_rates) / len(conversion_rates) if conversion_rates else 0.0
                    ),
                    "conversion_date": fields.Date.to_date(self.departure_at),
                    "fuel_cost": self.currency_id.round(fuel),
                    "driver_cost": self.currency_id.round(driver),
                    "total_operating_cost": self.currency_id.round(total),
                    "reporting_currency": reporting_currency,
                    "incomplete": incomplete,
                    "incomplete_acknowledged": False,
                    "warning_text": "\n".join(warnings),
                    "request_snapshot": requests_snapshot,
                    "response_snapshot": responses_snapshot,
                }
            )
        except UserError:
            self.state = "failed"
            raise
        return self

    def action_calculate(self):
        self.ensure_one()
        if self.state == "accepted":
            revision = self.copy(
                {
                    "state": "draft",
                    "revision": self.revision + 1,
                    "previous_revision_id": self.id,
                    "request_id": False,
                    "calculated_at": False,
                    "request_snapshot": False,
                    "response_snapshot": False,
                    "incomplete_acknowledged": False,
                }
            )
            revision._calculate_current_revision()
            return {
                "type": "ir.actions.act_window",
                "res_model": self._name,
                "res_id": revision.id,
                "view_mode": "form",
                "target": "current",
            }
        self._calculate_current_revision()
        return True

    def action_accept(self):
        for estimate in self:
            if estimate.state != "quoted":
                raise UserError(_("Only a quoted estimate can be accepted."))
            if estimate.incomplete and not estimate.incomplete_acknowledged:
                raise ValidationError(
                    _(
                        "TollQuote reported incomplete pricing. Acknowledge it or use manual travel cost."
                    )
                )
            estimate.previous_revision_id.filtered(
                lambda old: old.state == "accepted"
            ).state = "superseded"
            estimate.state = "accepted"
            if estimate.operation_id:
                estimate.operation_id.travel_estimate_id = estimate
        return True

    def write(self, vals):
        input_fields = {
            "connector_id",
            "origin_partner_id",
            "destination_partner_id",
            "origin_latitude",
            "origin_longitude",
            "destination_latitude",
            "destination_longitude",
            "round_trip",
            "departure_at",
            "vehicle_class",
            "payment_option",
            "fuel_consumption_l_per_100km",
            "fuel_price_eur_per_l",
            "driver_cost_eur_per_hour",
        }
        if input_fields.intersection(vals) and self.filtered(
            lambda estimate: estimate.state in ("accepted", "superseded")
        ):
            raise UserError(_("Accepted travel estimates are immutable; calculate a new revision."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_unaccepted_only(self):
        if self.filtered(lambda estimate: estimate.state in ("accepted", "superseded")):
            raise UserError(_("Accepted travel estimate evidence cannot be deleted."))
