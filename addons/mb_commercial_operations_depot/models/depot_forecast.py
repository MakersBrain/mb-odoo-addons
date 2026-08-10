from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MbDepotAssortmentRule(models.Model):
    _name = "mb.depot.assortment.rule"
    _description = "Depot Assortment and Refill Policy"
    _order = "contract_id, priority, id"
    _check_company_auto = True

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    priority = fields.Integer(default=10)
    contract_id = fields.Many2one(
        "mb.commercial.contract", required=True, check_company=True,
        ondelete="cascade", index=True,
    )
    company_id = fields.Many2one(related="contract_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    depot_warehouse_id = fields.Many2one(
        related="contract_id.depot_warehouse_id", store=True, index=True,
    )
    target_type = fields.Selection(
        [("product", "Exact Product"), ("bucket", "Assortment Bucket")],
        required=True, default="product",
    )
    product_id = fields.Many2one("product.product", check_company=True)
    category_id = fields.Many2one("product.category")
    price_min = fields.Monetary()
    price_max = fields.Monetary()
    minimum_quantity = fields.Float(required=True, default=1)
    target_quantity = fields.Float(required=True, default=3)
    safety_days = fields.Integer(default=7)
    target_days = fields.Integer(default=30)
    demand_window_days = fields.Integer(required=True, default=90)
    season_start = fields.Date()
    season_end = fields.Date()
    forecast_ids = fields.One2many("mb.depot.refill.forecast", "rule_id")

    _quantity_policy = models.Constraint(
        "CHECK(minimum_quantity >= 0 AND target_quantity >= minimum_quantity)",
        "Target quantity must be at least the non-negative minimum quantity.",
    )
    _day_policy = models.Constraint(
        "CHECK(safety_days >= 0 AND target_days >= safety_days AND demand_window_days > 0)",
        "Refill day policies must be non-negative and the demand window positive.",
    )
    _price_policy = models.Constraint(
        "CHECK(price_min >= 0 AND price_max >= 0 AND (price_max = 0 OR price_max >= price_min))",
        "Assortment price bands must be non-negative and ordered.",
    )

    @api.constrains("target_type", "product_id", "category_id")
    def _check_target(self):
        for rule in self:
            if rule.target_type == "product" and not rule.product_id:
                raise ValidationError(_("Choose a product for an exact-product depot rule."))
            if rule.target_type == "bucket" and not rule.category_id:
                raise ValidationError(_("Choose a category for an assortment-bucket depot rule."))

    def _matching_products(self):
        self.ensure_one()
        if self.target_type == "product":
            return self.product_id
        domain = [
            ("categ_id", "child_of", self.category_id.id),
            ("is_storable", "=", True),
            ("list_price", ">=", self.price_min),
        ]
        if self.price_max:
            domain.append(("list_price", "<=", self.price_max))
        return self.env["product.product"].search(domain)

    def _company_local_day(self, value):
        self.ensure_one()
        timezone = self.company_id.partner_id.tz or "UTC"
        instant = fields.Datetime.to_datetime(value).replace(tzinfo=pytz.UTC)
        return instant.astimezone(pytz.timezone(timezone)).date()

    def _forecast_values(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        window_start = today - timedelta(days=self.demand_window_days - 1)
        products = self._matching_products()
        depot_location = self.depot_warehouse_id.lot_stock_id
        quant_rows = self.env["stock.quant"]._read_group(
            [("product_id", "in", products.ids), ("location_id", "child_of", depot_location.id)],
            [], ["quantity:sum", "reserved_quantity:sum"],
        )
        current_quantity = sum(row[0] for row in quant_rows)
        reserved_quantity = sum(row[1] for row in quant_rows)
        available_now = current_quantity - reserved_quantity

        timezone = pytz.timezone(self.company_id.partner_id.tz or "UTC")
        start_utc = timezone.localize(datetime.combine(window_start, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        move_lines = self.env["stock.move.line"].search([
            ("product_id", "in", products.ids),
            ("state", "=", "done"),
            ("date", ">=", start_utc),
            "|", ("location_id", "child_of", depot_location.id),
                 ("location_dest_id", "child_of", depot_location.id),
        ])
        net_by_day = defaultdict(float)
        for line in move_lines:
            source_inside = line.location_id._child_of(depot_location)
            destination_inside = line.location_dest_id._child_of(depot_location)
            if source_inside == destination_inside:
                continue
            quantity = line.quantity_product_uom
            net_by_day[self._company_local_day(line.date)] += quantity if destination_inside else -quantity

        opening = current_quantity - sum(net_by_day.values())
        balance = opening
        exposed_days = 0
        cursor = window_start
        while cursor <= today:
            closing = balance + net_by_day[cursor]
            if balance > 0 or closing > 0:
                exposed_days += 1
            balance = closing
            cursor += timedelta(days=1)

        report_lines = self.env["mb.depot.sale.report.line"].search([
            ("report_id.depot_warehouse_id", "=", self.depot_warehouse_id.id),
            ("report_id.state", "in", ("processed", "reversal_required")),
            ("product_id", "in", products.ids),
            ("sold_at", ">=", start_utc),
        ])
        sold_quantity = sum(report_lines.mapped("quantity"))
        original_moves = self.env["stock.move"].search([
            ("move_line_ids.mb_depot_sale_report_line_id", "in", report_lines.ids),
            ("state", "=", "done"),
        ])
        returned_moves = self.env["stock.move"].search([
            ("origin_returned_move_id", "in", original_moves.ids),
            ("state", "=", "done"),
            ("date", ">=", start_utc),
        ]) if original_moves else self.env["stock.move"]
        returned_quantity = sum(returned_moves.mapped("quantity"))
        net_sold = max(0.0, sold_quantity - returned_quantity)
        average_daily_sales = net_sold / exposed_days if exposed_days else 0.0

        visit_date = self.contract_id.refill_review_date or today
        days_until_visit = max(0, (visit_date - today).days)
        projected = available_now - average_daily_sales * days_until_visit
        suggested = max(0.0, self.target_quantity - projected)
        days_of_cover = available_now / average_daily_sales if average_daily_sales else 0.0
        due_date = (
            today + timedelta(days=max(0, int((available_now - self.minimum_quantity) / average_daily_sales)))
            if average_daily_sales else False
        )
        if not net_sold:
            confidence = "policy"
        elif exposed_days < max(14, self.demand_window_days // 3):
            confidence = "low"
        else:
            confidence = "forecast"
        return {
            "contract_id": self.contract_id.id,
            "snapshot_date": today,
            "window_start": window_start,
            "window_end": today,
            "current_quantity": current_quantity,
            "reserved_quantity": reserved_quantity,
            "available_now": available_now,
            "sold_quantity": sold_quantity,
            "returned_quantity": returned_quantity,
            "exposed_days": exposed_days,
            "stockout_days": self.demand_window_days - exposed_days,
            "average_daily_sales": average_daily_sales,
            "forecast_visit_date": visit_date,
            "forecast_stock_on_visit": projected,
            "suggested_quantity": suggested,
            "days_of_cover": days_of_cover,
            "refill_due_date": due_date,
            "confidence": confidence,
            "stockout_biased": exposed_days < self.demand_window_days,
            "calculated_at": fields.Datetime.now(),
        }

    def _refresh_forecast(self):
        forecast_model = self.env["mb.depot.refill.forecast"]
        for rule in self.filtered(lambda item: item.active and item.depot_warehouse_id):
            values = rule._forecast_values()
            forecast = forecast_model.search([
                ("rule_id", "=", rule.id),
                ("snapshot_date", "=", values["snapshot_date"]),
            ], limit=1)
            if forecast:
                forecast.write(values)
            else:
                forecast_model.create({"rule_id": rule.id, **values})
        return True

    @api.model
    def _cron_refresh_forecasts(self):
        rules = self.search([("active", "=", True), ("depot_warehouse_id", "!=", False)])
        processed = 0
        for rule in rules:
            rule._refresh_forecast()
            processed += 1
            if self.env.context.get("cron_id"):
                remaining = len(rules) - processed
                if not self.env["ir.cron"]._commit_progress(1, remaining=remaining):
                    break


class MbDepotRefillForecast(models.Model):
    _name = "mb.depot.refill.forecast"
    _description = "Depot Refill Forecast Snapshot"
    _order = "snapshot_date desc, rule_id"
    _check_company_auto = True

    rule_id = fields.Many2one(
        "mb.depot.assortment.rule", required=True, check_company=True,
        ondelete="cascade", index=True,
    )
    contract_id = fields.Many2one(
        "mb.commercial.contract", required=True, check_company=True,
        ondelete="cascade", index=True,
    )
    company_id = fields.Many2one(related="contract_id.company_id", store=True, index=True)
    depot_warehouse_id = fields.Many2one(related="contract_id.depot_warehouse_id", store=True)
    snapshot_date = fields.Date(required=True, index=True)
    calculated_at = fields.Datetime(required=True)
    window_start = fields.Date(required=True)
    window_end = fields.Date(required=True)
    current_quantity = fields.Float()
    reserved_quantity = fields.Float()
    available_now = fields.Float()
    sold_quantity = fields.Float()
    returned_quantity = fields.Float()
    exposed_days = fields.Integer()
    stockout_days = fields.Integer()
    average_daily_sales = fields.Float(digits=(16, 4))
    forecast_visit_date = fields.Date()
    forecast_stock_on_visit = fields.Float()
    suggested_quantity = fields.Float()
    days_of_cover = fields.Float(digits=(16, 2))
    refill_due_date = fields.Date()
    confidence = fields.Selection(
        [("policy", "Policy Based"), ("low", "Low Confidence"), ("forecast", "Forecast Based")],
        required=True,
    )
    stockout_biased = fields.Boolean()

    _snapshot_unique = models.Constraint(
        "UNIQUE(rule_id, snapshot_date)", "A rule already has a forecast snapshot for this date.",
    )

    def _stock_plan_values(self):
        self.ensure_one()
        rule = self.rule_id
        values = {
            "target_type": rule.target_type,
            "desired_opening_qty": self.suggested_quantity,
            "supply_method": "stock",
            "priority": rule.priority,
            "expected_unit_price": rule.product_id.list_price if rule.product_id else 0,
        }
        if rule.target_type == "product":
            values["product_id"] = rule.product_id.id
        else:
            values.update({
                "category_id": rule.category_id.id,
                "price_min": rule.price_min,
                "price_max": rule.price_max,
            })
        return values
