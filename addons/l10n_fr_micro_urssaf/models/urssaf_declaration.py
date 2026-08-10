from collections import defaultdict
from datetime import datetime, time

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .urssaf_rule import URSSAF_CATEGORIES
from .internal import internal_context, is_internal


FAR_FUTURE = fields.Date.to_date("9999-12-31")


class L10nFrMicroUrssafDeclaration(models.Model):
	_name = "l10n.fr.micro.urssaf.declaration"
	_description = "Micro-enterprise URSSAF turnover declaration"
	_inherit = ["mail.thread", "mail.activity.mixin"]
	_order = "date_from desc, id desc"

	name = fields.Char(compute="_compute_name", store=True)
	company_id = fields.Many2one(
		"res.company", required=True, default=lambda self: self.env.company,
		index=True, tracking=True,
	)
	currency_id = fields.Many2one(related="company_id.currency_id")
	date_from = fields.Date(required=True, default=lambda self: fields.Date.context_today(self).replace(day=1), tracking=True)
	date_to = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
	due_date = fields.Date(compute="_compute_due_date", store=True)
	periodicity = fields.Selection(
		selection=[("monthly", "Monthly"), ("quarterly", "Quarterly")],
		required=True,
		default=lambda self: self.env.company.l10n_fr_micro_urssaf_periodicity,
		tracking=True,
	)
	state = fields.Selection(
		selection=[("draft", "Draft"), ("filed", "Filed")],
		default="draft", required=True, copy=False, index=True, tracking=True,
	)
	line_ids = fields.One2many(
		"l10n.fr.micro.urssaf.declaration.line", "declaration_id", copy=False,
	)
	source_ids = fields.One2many(
		"l10n.fr.micro.urssaf.declaration.source", "declaration_id", copy=False,
	)
	anomaly_text = fields.Text(readonly=True, copy=False)
	blocking_anomaly = fields.Boolean(readonly=True, copy=False)
	filed_at = fields.Datetime(readonly=True, copy=False)
	filed_by_id = fields.Many2one("res.users", readonly=True, copy=False)
	reset_reason = fields.Text(copy=False)
	total_declared = fields.Monetary(compute="_compute_totals", store=True)
	total_estimated = fields.Monetary(compute="_compute_totals", store=True)
	micro_ytd_global = fields.Monetary(readonly=True, copy=False)
	micro_ytd_services = fields.Monetary(readonly=True, copy=False)
	vat_ytd_global = fields.Monetary(readonly=True, copy=False)
	vat_ytd_services = fields.Monetary(readonly=True, copy=False)
	threshold_status = fields.Text(readonly=True, copy=False)

	_company_period_unique = models.Constraint(
		"unique(company_id, date_from, date_to)",
		"A declaration already exists for this company and period.",
	)

	@api.model
	def default_get(self, field_names):
		values = super().default_get(field_names)
		company = self.env["res.company"].browse(values.get("company_id")) \
			if values.get("company_id") else self.env.company
		periodicity = values.get("periodicity") or company.l10n_fr_micro_urssaf_periodicity
		previous = self.search([("company_id", "=", company.id)], order="date_to desc", limit=1)
		if previous:
			date_from = previous.date_to + relativedelta(days=1)
			first_period = False
		else:
			date_from = company.l10n_fr_micro_urssaf_tracking_start_date \
				or company.l10n_fr_micro_activity_start_date or fields.Date.context_today(company)
			first_period = bool(
				company.l10n_fr_micro_activity_start_date
				and date_from == company.l10n_fr_micro_activity_start_date
			)
		if periodicity == "quarterly":
			quarter_start = date_from.replace(month=((date_from.month - 1) // 3) * 3 + 1, day=1)
			date_to = quarter_start + relativedelta(months=6 if first_period else 3, days=-1)
		else:
			date_to = date_from + relativedelta(months=3 if first_period else 0, day=31)
		if "default_periodicity" not in self.env.context:
			values["periodicity"] = periodicity
		if "default_date_from" not in self.env.context:
			values["date_from"] = date_from
		if "default_date_to" not in self.env.context:
			values["date_to"] = date_to
		return values

	@api.depends("company_id", "date_from", "date_to", "periodicity")
	def _compute_name(self):
		for declaration in self:
			if declaration.date_from and declaration.date_to:
				declaration.name = _(
					"URSSAF %(from)s — %(to)s",
					**{"from": declaration.date_from, "to": declaration.date_to},
				)
			else:
				declaration.name = _("URSSAF declaration")

	@api.depends("date_to")
	def _compute_due_date(self):
		for declaration in self:
			declaration.due_date = declaration.date_to and (
				declaration.date_to + relativedelta(months=1, day=31)
			) or False

	@api.depends("line_ids.declared_turnover", "line_ids.total_estimated")
	def _compute_totals(self):
		for declaration in self:
			declaration.total_declared = sum(declaration.line_ids.mapped("declared_turnover"))
			declaration.total_estimated = sum(declaration.line_ids.mapped("total_estimated"))

	@api.constrains("date_from", "date_to", "company_id")
	def _check_period(self):
		for declaration in self:
			if declaration.date_from and declaration.date_to and declaration.date_to < declaration.date_from:
				raise ValidationError(_("The declaration end date precedes its start date."))
			if declaration.date_from and declaration.date_to and self.search_count([
				("id", "!=", declaration.id),
				("company_id", "=", declaration.company_id.id),
				("date_from", "<=", declaration.date_to),
				("date_to", ">=", declaration.date_from),
			]):
				raise ValidationError(_("URSSAF declaration periods cannot overlap."))
			previous = self.search([
				("id", "!=", declaration.id),
				("company_id", "=", declaration.company_id.id),
				("date_to", "<", declaration.date_from),
			], order="date_to desc", limit=1)
			if previous and declaration.date_from != previous.date_to + relativedelta(days=1):
				raise ValidationError(_(
					"The period must start on %(expected)s, immediately after %(previous)s.",
					expected=previous.date_to + relativedelta(days=1), previous=previous.display_name,
				))
			following = self.search([
				("id", "!=", declaration.id),
				("company_id", "=", declaration.company_id.id),
				("date_from", ">", declaration.date_to),
			], order="date_from", limit=1)
			if following and following.date_from != declaration.date_to + relativedelta(days=1):
				raise ValidationError(_(
					"The next period %(following)s must begin immediately after this one.",
					following=following.display_name,
				))

	def _check_manager(self):
		if not self.env.is_superuser() and not self.env.user.has_group("account.group_account_manager"):
			raise AccessError(_("Only an Accounting Administrator can perform this declaration action."))

	def write(self, values):
		filed = self.filtered(lambda declaration: declaration.state == "filed")
		reset_reason_only = set(values) <= {"reset_reason"}
		if "state" in values and not is_internal(self.env):
			raise AccessError(_("Use the manager-only file or reset action to change declaration state."))
		if filed and not reset_reason_only and not is_internal(self.env):
			raise UserError(_("A filed URSSAF declaration is immutable. Reset it to draft with a reason first."))
		if filed and reset_reason_only:
			self._check_manager()
		return super().write(values)

	def unlink(self):
		if self.filtered(lambda declaration: declaration.state == "filed"):
			raise UserError(_("A filed URSSAF declaration cannot be deleted."))
		return super().unlink()

	def _mandate_blockers(self):
		self.ensure_one()
		return self.env["stock.warehouse"].search([
			("company_id", "=", self.company_id.id),
			("is_depot", "=", True),
			("mb_depot_legal_structure", "=", "mandate"),
			"|",
			("mb_depot_mandate_reviewed_through", "=", False),
			("mb_depot_mandate_reviewed_through", "<", self.date_to),
		])

	@api.model
	def _categories_on_line(self, line):
		return set(filter(None, line.tax_ids.mapped("l10n_fr_micro_urssaf_category")))

	@api.model
	def _journal_receipt_method(self, journal):
		if journal.l10n_fr_micro_receipt_method:
			return journal.l10n_fr_micro_receipt_method
		if journal.type == "cash":
			return "cash"
		return "unknown"

	@api.model
	def _counterpart_for_partial(self, partial, origin):
		if partial.debit_move_id.move_id == origin:
			return partial.credit_move_id
		if partial.credit_move_id.move_id == origin:
			return partial.debit_move_id
		return partial.debit_move_id

	@api.model
	def _receipt_details(self, engine, move_line=None, partial=None, origin=None, pos_order=None):
		if engine == "pos" and pos_order:
			payments = pos_order.payment_ids
			methods = payments.payment_method_id
			if len(methods) > 1:
				return "mixed", ", ".join(methods.mapped("name"))
			if methods:
				method = methods[0]
				if method.is_cash_count:
					return "cash", method.name
				name = method.name.lower()
				return ("card" if "card" in name or "carte" in name else "other"), method.name
		if partial and origin:
			counterpart = self._counterpart_for_partial(partial, origin)
			method = self._journal_receipt_method(counterpart.move_id.journal_id)
			return method, counterpart.move_id.journal_id.display_name
		if move_line:
			journal = move_line.move_id.journal_id
			return self._journal_receipt_method(journal), journal.display_name
		return "unknown", False

	@api.model
	def _foreign_details(self, company_amount, move_line=None, partial=None, origin=None):
		currency = self.env["res.currency"]
		foreign_amount = 0.0
		if partial and origin and partial.amount:
			if partial.debit_move_id.move_id == origin:
				currency = partial.debit_currency_id
				matched_foreign = partial.debit_amount_currency
			else:
				currency = partial.credit_currency_id
				matched_foreign = partial.credit_amount_currency
			foreign_amount = matched_foreign * abs(company_amount) / partial.amount
			if company_amount < 0:
				foreign_amount = -foreign_amount
		elif move_line and move_line.currency_id:
			currency = move_line.currency_id
			foreign_amount = -move_line.amount_currency
		company_currency = origin.company_id.currency_id if origin else (
			move_line.company_id.currency_id if move_line else self.env.company.currency_id
		)
		if not currency or currency == company_currency:
			return False, 0.0, 1.0
		rate = abs(company_amount / foreign_amount) if foreign_amount else 0.0
		return currency.id, foreign_amount, rate

	@api.model
	def _caba_events(self, company, date_from, date_to):
		lines = self.env["account.move.line"].search([
			("parent_state", "=", "posted"),
			("company_id", "=", company.id),
			("date", ">=", date_from),
			("date", "<=", date_to),
			("tax_ids.l10n_fr_micro_urssaf_category", "!=", False),
		])
		events = []
		for line in lines:
			move = line.move_id
			if move.tax_cash_basis_rec_id:
				engine = "caba"
				origin = move.tax_cash_basis_origin_move_id
				partial = move.tax_cash_basis_rec_id
			elif move.pos_session_ids:
				# Ticket-level POS events are built separately below. Keeping the
				# session base line as well would count the same taking twice.
				continue
			elif move.always_tax_exigible and not move.is_invoice(include_receipts=True):
				engine = "direct"
				origin = move
				partial = self.env["account.partial.reconcile"]
			else:
				continue
			for category in self._categories_on_line(line):
				method, detail = self._receipt_details(
					engine, move_line=line, partial=partial, origin=origin,
				)
				amount = -line.balance
				foreign_currency_id, foreign_amount, exchange_rate = self._foreign_details(
					amount, move_line=line, partial=partial, origin=origin,
				)
				events.append({
					"event_key": f"caba:aml:{line.id}:{origin.id}:{category}",
					"date": line.date,
					"category": category,
					"amount": amount,
					"source_currency_id": foreign_currency_id,
					"source_amount_currency": foreign_amount,
					"exchange_rate": exchange_rate,
					"engine": "caba",
					"source_move_line_id": line.id,
					"partial_id": partial.id or False,
					"origin_move_id": origin.id,
					"pos_order_id": False,
					"receipt_method": method,
					"receipt_method_detail": detail,
					"description": line.name or origin.name,
				})
		return events

	@api.model
	def _pos_events(self, company, date_from, date_to):
		orders = self.env["pos.order"].sudo().search([
			("company_id", "=", company.id),
			("state", "in", ("paid", "done")),
			("session_id.move_id.date", ">=", date_from),
			("session_id.move_id.date", "<=", date_to),
		])
		events = []
		for order in orders:
			totals = defaultdict(float)
			for line in order.lines:
				categories = set(filter(None, line.tax_ids_after_fiscal_position.mapped(
					"l10n_fr_micro_urssaf_category"
				)))
				for category in categories:
					totals[category] += line.price_subtotal
			method, detail = self._receipt_details("pos", pos_order=order)
			for category, amount in totals.items():
				events.append({
					"event_key": f"pos:{order.id}:{category}",
					"date": order.session_id.move_id.date,
					"category": category,
					"amount": company.currency_id.round(amount),
					"source_currency_id": False,
					"source_amount_currency": 0.0,
					"exchange_rate": 1.0,
					"engine": "pos",
					"source_move_line_id": False,
					"partial_id": False,
					"origin_move_id": order.account_move.id or False,
					"pos_order_id": order.id,
					"receipt_method": method,
					"receipt_method_detail": detail,
					"description": order.name,
				})
		return events

	@api.model
	def _invoice_category_totals(self, invoice):
		totals = defaultdict(float)
		for line in invoice.invoice_line_ids.filtered(lambda item: item.display_type == "product"):
			for category in self._categories_on_line(line):
				totals[category] += -line.balance
		return totals

	@api.model
	def _reconciliation_events(self, company, date_from, date_to):
		invoices = self.env["account.move"].search([
			("company_id", "=", company.id),
			("state", "=", "posted"),
			("move_type", "in", ("out_invoice", "out_refund", "out_receipt")),
			("line_ids.tax_ids.l10n_fr_micro_urssaf_category", "!=", False),
		])
		events = []
		for invoice in invoices:
			category_totals = self._invoice_category_totals(invoice)
			if not category_totals:
				continue
			cash_basis_categories = set()
			for line in invoice.invoice_line_ids.filtered(lambda item: item.display_type == "product"):
				cash_basis_categories.update(
					tax.l10n_fr_micro_urssaf_category
					for tax in line.tax_ids
					if tax.l10n_fr_micro_urssaf_category and tax.tax_exigibility == "on_payment"
				)
			terms = invoice.line_ids.filtered(
				lambda line: line.account_type == "asset_receivable"
			)
			total = abs(sum(terms.mapped("balance")))
			if company.currency_id.is_zero(total):
				continue
			partials = (terms.matched_debit_ids | terms.matched_credit_ids).filtered(
				lambda partial: date_from <= partial.max_date <= date_to
			).sorted(lambda partial: (partial.max_date, partial.id))
			all_partials = (terms.matched_debit_ids | terms.matched_credit_ids).filtered(
				lambda partial: partial.max_date <= date_to
			).sorted(lambda partial: (partial.max_date, partial.id))
			allocated = defaultdict(float)
			for partial in all_partials:
				is_last = partial == all_partials[-1] and company.currency_id.is_zero(
					total - sum(item.amount for item in all_partials)
				)
				for category, category_total in category_totals.items():
					if category in cash_basis_categories:
						continue
					amount = category_total * partial.amount / total
					amount = company.currency_id.round(amount)
					if is_last:
						amount = company.currency_id.round(category_total - allocated[category])
					allocated[category] += amount
					if partial not in partials:
						continue
					method, detail = self._receipt_details(
						"reconciliation", partial=partial, origin=invoice,
					)
					foreign_currency_id, foreign_amount, exchange_rate = self._foreign_details(
						amount, partial=partial, origin=invoice,
					)
					events.append({
						"event_key": f"reconciliation:partial:{partial.id}:{invoice.id}:{category}",
						"date": partial.max_date,
						"category": category,
						"amount": amount,
						"source_currency_id": foreign_currency_id,
						"source_amount_currency": foreign_amount,
						"exchange_rate": exchange_rate,
						"engine": "reconciliation",
						"source_move_line_id": False,
						"partial_id": partial.id,
						"origin_move_id": invoice.id,
						"pos_order_id": invoice.pos_order_ids[:1].id or False,
						"receipt_method": method,
						"receipt_method_detail": detail,
						"description": invoice.name,
					})
		return events

	@api.model
	def _normalize_caba_events(self, company, events, date_to):
		groups = defaultdict(list)
		for event in events:
			if event["engine"] == "caba" and event["origin_move_id"]:
				groups[(event["origin_move_id"], event["category"])].append(event)
		for (origin_id, category), grouped in groups.items():
			origin = self.env["account.move"].browse(origin_id)
			if not origin.is_invoice(include_receipts=True):
				continue
			later_count = self.env["account.move.line"].search_count([
				("move_id.tax_cash_basis_origin_move_id", "=", origin.id),
				("date", ">", date_to),
				("tax_ids.l10n_fr_micro_urssaf_category", "=", category),
			])
			if later_count or origin.payment_state not in ("paid", "in_payment"):
				continue
			target = self._invoice_category_totals(origin).get(category)
			if target is None:
				continue
			grouped.sort(key=lambda event: (event["date"], event["source_move_line_id"]))
			last_event = grouped[-1]
			all_caba_lines = self.env["account.move.line"].search([
				("parent_state", "=", "posted"),
				("company_id", "=", company.id),
				("move_id.tax_cash_basis_origin_move_id", "=", origin.id),
				("date", "<=", date_to),
				("tax_ids.l10n_fr_micro_urssaf_category", "=", category),
			])
			previous = sum(
				-line.balance for line in all_caba_lines
				if line.id != last_event["source_move_line_id"]
			)
			last_event["amount"] = company.currency_id.round(target - previous)
			partial = self.env["account.partial.reconcile"].browse(last_event["partial_id"])
			currency_id, foreign_amount, exchange_rate = self._foreign_details(
				last_event["amount"], partial=partial, origin=origin,
			)
			last_event.update({
				"source_currency_id": currency_id,
				"source_amount_currency": foreign_amount,
				"exchange_rate": exchange_rate,
			})
		return events

	@api.model
	def _recognition_events(self, company, date_from, date_to):
		events = self._caba_events(company, date_from, date_to)
		events = self._normalize_caba_events(company, events, date_to)
		events += self._reconciliation_events(company, date_from, date_to)
		events += self._pos_events(company, date_from, date_to)
		return sorted(events, key=lambda event: (event["date"], event["event_key"]))

	def _pos_daily_summaries(self):
		"""Group the receipt book by local accounting day and payment method.

		Ticket and session identifiers remain attached for the audit trail while the
		printed subtotal has the day/method shape expected from a receipt book.
		"""
		self.ensure_one()
		groups = {}
		for source in self.source_ids.filtered(lambda item: item.engine == "pos"):
			pos_order = source.sudo().pos_order_id
			key = (source.recognition_date, source.receipt_method, source.category)
			group = groups.setdefault(key, {
				"date": source.recognition_date,
				"method": dict(source._fields["receipt_method"].selection).get(source.receipt_method),
				"category": dict(URSSAF_CATEGORIES).get(source.category),
				"amount": 0.0,
				"sessions": set(),
				"tickets": set(),
			})
			group["amount"] += source.amount
			if pos_order.session_id:
				group["sessions"].add(pos_order.session_id.display_name)
			if pos_order:
				group["tickets"].add(pos_order.display_name)
		result = []
		for group in groups.values():
			group["amount"] = self.currency_id.round(group["amount"])
			group["sessions"] = ", ".join(sorted(group["sessions"]))
			group["tickets"] = ", ".join(sorted(group["tickets"]))
			result.append(group)
		return sorted(result, key=lambda group: (group["date"], group["method"] or "", group["category"] or ""))

	@api.model
	def _vat_goods_events_for_line(self, line):
		line = line.sudo()
		amount = -line.balance
		if line.l10n_fr_micro_vat_operation_date:
			return [{
				"date": line.l10n_fr_micro_vat_operation_date,
				"category": "bic_goods",
				"amount": amount,
				"event_key": f"vat-manual-aml:{line.id}",
			}]
		moves = line.sale_line_ids.move_ids.filtered(
			lambda move: move.state == "done" and move.location_dest_id.usage == "customer"
		).sorted(lambda move: (move.date, move.id))
		invoice_quantity = abs(line.quantity)
		if not moves or not invoice_quantity:
			return []
		invoice_lines = self.env["account.move.line"].sudo().search([
			("id", "!=", line.id),
			("parent_state", "=", "posted"),
			("move_id.move_type", "in", ("out_invoice", "out_receipt")),
			("display_type", "=", "product"),
			("sale_line_ids", "in", line.sale_line_ids.ids),
		])
		line_key = (line.move_id.invoice_date or line.date, line.move_id.id, line.id)
		prior_quantity = 0.0
		for prior_line in invoice_lines:
			prior_key = (
				prior_line.move_id.invoice_date or prior_line.date,
				prior_line.move_id.id,
				prior_line.id,
			)
			if prior_key < line_key:
				prior_quantity += abs(prior_line.product_uom_id._compute_quantity(
					prior_line.quantity, line.product_uom_id,
				))
		remaining = invoice_quantity
		skip_quantity = prior_quantity
		allocated = 0.0
		events = []
		for move in moves:
			move_quantity = abs(move.product_uom._compute_quantity(
				move.quantity, line.product_uom_id,
			))
			if skip_quantity >= move_quantity:
				skip_quantity -= move_quantity
				continue
			available_quantity = move_quantity - skip_quantity
			skip_quantity = 0.0
			quantity = min(remaining, available_quantity)
			if not quantity:
				continue
			remaining -= quantity
			value = line.company_id.currency_id.round(amount * quantity / invoice_quantity)
			if not remaining:
				value = line.company_id.currency_id.round(amount - allocated)
			allocated += value
			events.append({
				"date": move.date.date(),
				"category": "bic_goods",
				"amount": value,
				"event_key": f"vat-delivery:{line.id}:{move.id}",
			})
			if not remaining:
				break
		return events

	@api.model
	def _vat_operation_date(self, line):
		events = self._vat_goods_events_for_line(line)
		return min((event["date"] for event in events), default=False)

	@api.model
	def _vat_threshold_events(self, company, date_from, date_to):
		events = [
			event for event in self._recognition_events(company, date_from, date_to)
			if event["category"] != "bic_goods"
		]
		invoice_lines = self.env["account.move.line"].search([
			("company_id", "=", company.id),
			("parent_state", "=", "posted"),
			("move_id.move_type", "in", ("out_invoice", "out_refund", "out_receipt")),
			("display_type", "=", "product"),
			("tax_ids.l10n_fr_micro_urssaf_category", "=", "bic_goods"),
		])
		for line in invoice_lines:
			if line.move_id.pos_order_ids:
				continue
			for event in self._vat_goods_events_for_line(line):
				if date_from <= event["date"] <= date_to:
					events.append(event)
		orders = self.env["pos.order"].sudo().search([
			("company_id", "=", company.id),
			("state", "in", ("paid", "done", "invoiced")),
			("date_order", ">=", datetime.combine(date_from - relativedelta(days=1), time.min)),
			("date_order", "<=", datetime.combine(date_to + relativedelta(days=1), time.max)),
		])
		for order in orders:
			operation_date = fields.Datetime.context_timestamp(self, order.date_order).date()
			if not date_from <= operation_date <= date_to:
				continue
			for line in order.lines:
				if "bic_goods" in line.tax_ids_after_fiscal_position.mapped("l10n_fr_micro_urssaf_category"):
					events.append({
						"date": operation_date,
						"category": "bic_goods",
						"amount": line.price_subtotal,
						"event_key": f"vat-pos:{line.id}",
					})
		return sorted(events, key=lambda event: (event["date"], event["event_key"]))

	def _configuration_anomalies(self):
		self.ensure_one()
		anomalies = []
		company = self.company_id
		if not company.l10n_fr_micro_activity_start_date:
			anomalies.append(_("Company activity start date is missing."))
		if not company.l10n_fr_micro_urssaf_tracking_start_date:
			anomalies.append(_("URSSAF tracking start date is missing."))
		if not company.l10n_fr_micro_accounting_responsible_id:
			anomalies.append(_("URSSAF accounting responsible is missing."))
		if not self.env["l10n.fr.micro.urssaf.threshold"].threshold_for(self.date_to):
			anomalies.append(_("No threshold rule applies on the declaration end date."))
		if company.l10n_fr_micro_activity_start_date \
				and self.date_to.year > company.l10n_fr_micro_activity_start_date.year \
				and not self.env["l10n.fr.micro.urssaf.annual"].search_count([
					("company_id", "=", company.id),
					("year", "=", self.date_to.year - 1),
				]):
			anomalies.append(_(
				"Annual evidence for %(year)s is missing; prior-year thresholds and any chamber-tax exemption cannot be decided.",
				year=self.date_to.year - 1,
			))
		return anomalies

	def _unclassified_anomalies(self):
		self.ensure_one()
		lines = self.env["account.move.line"].search([
			("company_id", "=", self.company_id.id),
			("parent_state", "=", "posted"),
			("move_id.move_type", "in", ("out_invoice", "out_refund", "out_receipt")),
			("display_type", "=", "product"),
			("date", ">=", self.company_id.l10n_fr_micro_urssaf_tracking_start_date or self.date_from),
			("date", "<=", self.date_to),
		])
		return [
			_("Posted sale line %(move)s / %(line)s has no URSSAF tax category.", move=line.move_id.name, line=line.name)
			for line in lines if not self._categories_on_line(line)
		]

	def _pos_anomalies(self):
		self.ensure_one()
		anomalies = []
		sessions = self.env["pos.session"].sudo().search([
			("company_id", "=", self.company_id.id),
			("move_id.date", ">=", self.date_from),
			("move_id.date", "<=", self.date_to),
			("move_id", "!=", False),
		])
		for session in sessions:
			local_start = fields.Datetime.context_timestamp(self, session.start_at).date()
			if local_start != session.move_id.date:
				anomalies.append(_(
					"POS session %(session)s opened on %(opened)s and posted takings on %(closed)s.",
					session=session.name, opened=local_start, closed=session.move_id.date,
				))
			for order in session.order_ids.filtered(lambda item: item.state in ("paid", "done")):
				for line in order.lines:
					if not line.tax_ids_after_fiscal_position.mapped("l10n_fr_micro_urssaf_category"):
						anomalies.append(_(
							"POS ticket %(ticket)s / %(line)s has no URSSAF tax category.",
							ticket=order.name, line=line.full_product_name,
						))
		return anomalies

	def _missing_vat_dates(self):
		self.ensure_one()
		tracking_start = self.company_id.l10n_fr_micro_urssaf_tracking_start_date or self.date_from
		lines = self.env["account.move.line"].search([
			("company_id", "=", self.company_id.id),
			("parent_state", "=", "posted"),
			("move_id.move_type", "in", ("out_invoice", "out_refund", "out_receipt")),
			("display_type", "=", "product"),
			("tax_ids.l10n_fr_micro_urssaf_category", "=", "bic_goods"),
			("move_id.pos_order_ids", "=", False),
			("move_id.invoice_date", ">=", tracking_start),
			("move_id.invoice_date", "<=", self.date_to),
		])
		return [
			_("Goods line %(move)s / %(line)s has no provable VAT-threshold delivery date.", move=line.move_id.name, line=line.name)
			for line in lines if not self._vat_operation_date(line)
		]

	def _chamber_applies(self, date, category=None):
		self.ensure_one()
		company = self.company_id
		if category == "bnc" or company.l10n_fr_micro_chamber_kind == "none" \
				or not company.l10n_fr_micro_activity_start_date:
			return False
		if date.year <= company.l10n_fr_micro_activity_start_date.year:
			return False
		previous = self.env["l10n.fr.micro.urssaf.annual"].search([
			("company_id", "=", company.id), ("year", "=", date.year - 1),
		], limit=1)
		return bool(previous and previous.urssaf_total > 5000)

	def _source_rate_values(self, event):
		self.ensure_one()
		Rate = self.env["l10n.fr.micro.urssaf.rate"]
		date = event["date"]
		category = event["category"]
		amount = event["amount"]
		cotisation = Rate.rate_for("cotisation", category, date, self.company_id)
		cfp = Rate.rate_for("cfp", category, date, self.company_id)
		chamber = Rate.rate_for("chamber", category, date, self.company_id) \
			if self._chamber_applies(date, category) else Rate
		liberatoire = Rate.rate_for("liberatoire", category, date, self.company_id) \
			if self.company_id._l10n_fr_micro_has_versement_on(date) else Rate
		acre = self.company_id._l10n_fr_micro_acre_coefficient_on(date)
		return {
			"cotisation_rate_id": cotisation.id or False,
			"cotisation_rate": cotisation.rate if cotisation else 0.0,
			"acre_coefficient": acre,
			"cotisation_amount": self.currency_id.round(amount * (cotisation.rate if cotisation else 0.0) / 100 * acre),
			"cfp_rate_id": cfp.id or False,
			"cfp_rate": cfp.rate if cfp else 0.0,
			"cfp_amount": self.currency_id.round(amount * (cfp.rate if cfp else 0.0) / 100),
			"chamber_rate_id": chamber.id or False,
			"chamber_rate": chamber.rate if chamber else 0.0,
			"chamber_amount": self.currency_id.round(amount * (chamber.rate if chamber else 0.0) / 100),
			"liberatoire_rate_id": liberatoire.id or False,
			"liberatoire_rate": liberatoire.rate if liberatoire else 0.0,
			"liberatoire_amount": self.currency_id.round(amount * (liberatoire.rate if liberatoire else 0.0) / 100),
		}

	def _missing_rate_anomalies(self, event, rate_values):
		self.ensure_one()
		category = dict(URSSAF_CATEGORIES)[event["category"]]
		missing = []
		if not rate_values["cotisation_rate_id"]:
			missing.append(_("social-contribution"))
		if not rate_values["cfp_rate_id"]:
			missing.append(_("professional-training"))
		if self._chamber_applies(event["date"], event["category"]) and not rate_values["chamber_rate_id"]:
			missing.append(_("consular-chamber"))
		if self.company_id._l10n_fr_micro_has_versement_on(event["date"]) \
				and not rate_values["liberatoire_rate_id"]:
			missing.append(_("versement-libératoire"))
		return [
			_(
				"No applicable %(levy)s rate exists for %(category)s on %(date)s.",
				levy=levy, category=category, date=event["date"],
			)
			for levy in missing
		]

	def _threshold_values(self, all_events):
		self.ensure_one()
		year_start = self.date_to.replace(month=1, day=1)
		micro_events = [event for event in all_events if year_start <= event["date"] <= self.date_to]
		vat_events = self._vat_threshold_events(self.company_id, year_start, self.date_to)
		micro_global = sum(event["amount"] for event in micro_events)
		micro_services = sum(event["amount"] for event in micro_events if event["category"] != "bic_goods")
		vat_global = sum(event["amount"] for event in vat_events)
		vat_services = sum(event["amount"] for event in vat_events if event["category"] != "bic_goods")
		threshold = self.env["l10n.fr.micro.urssaf.threshold"].threshold_for(self.date_to)
		status = []
		if threshold:
			year_end = self.date_to.replace(month=12, day=31)
			activity_start = self.company_id.l10n_fr_micro_activity_start_date
			factor = 1.0
			if activity_start and activity_start.year == self.date_to.year:
				factor = ((year_end - activity_start).days + 1) / ((year_end - year_start).days + 1)
			micro_global_limit = threshold.micro_global * factor
			micro_service_limit = threshold.micro_service * factor
			vat_global_base = threshold.vat_global_base * factor
			vat_global_major = threshold.vat_global_major * factor
			vat_service_base = threshold.vat_service_base * factor
			vat_service_major = threshold.vat_service_major * factor
			status = [
				_("Micro: %(global).2f / %(global_limit).2f globally; %(services).2f / %(service_limit).2f services.",
					**{"global": micro_global, "global_limit": micro_global_limit,
						"services": micro_services, "service_limit": micro_service_limit}),
				_("VAT franchise: %(global).2f (base %(global_base).2f; major %(global_major).2f); services %(services).2f (base %(service_base).2f; major %(service_major).2f).",
					**{"global": vat_global, "global_base": vat_global_base, "global_major": vat_global_major,
						"services": vat_services, "service_base": vat_service_base, "service_major": vat_service_major}),
			]
			previous = self.env["l10n.fr.micro.urssaf.annual"].search([
				("company_id", "=", self.company_id.id), ("year", "=", self.date_to.year - 1),
			], limit=1)
			if previous:
				status.append(_(
					"Prior year: micro %(micro).2f globally / %(services).2f services; VAT %(vat).2f globally / %(vat_services).2f services.",
					micro=previous.urssaf_total, services=previous.urssaf_services,
					vat=previous.vat_global, vat_services=previous.vat_services,
				))
				previous_threshold = self.env["l10n.fr.micro.urssaf.threshold"].threshold_for(
					year_start - relativedelta(days=1)
				) or threshold
				if previous.vat_global > previous_threshold.vat_global_base \
						or previous.vat_services > previous_threshold.vat_service_base:
					status.append(_("The prior year exceeded a VAT-franchise base threshold; verify continued eligibility."))
				if (
					(previous.urssaf_total > previous_threshold.micro_global
					 or previous.urssaf_services > previous_threshold.micro_service)
					and (micro_global > micro_global_limit or micro_services > micro_service_limit)
				):
					status.append(_("The micro-regime ceiling has been exceeded in two consecutive years; review the mandatory regime exit."))
		self.write({
			"micro_ytd_global": micro_global,
			"micro_ytd_services": micro_services,
			"vat_ytd_global": vat_global,
			"vat_ytd_services": vat_services,
			"threshold_status": "\n".join(status),
		})
		if threshold and (
			vat_global > vat_global_major
			or vat_services > vat_service_major
		):
			cross_global = cross_services = 0.0
			crossing_date = False
			for event in vat_events:
				cross_global += event["amount"]
				if event["category"] != "bic_goods":
					cross_services += event["amount"]
				if cross_global > vat_global_major or cross_services > vat_service_major:
					crossing_date = event["date"]
					break
			self._ensure_vat_activity(crossing_date)

	def _ensure_vat_activity(self, crossing_date):
		self.ensure_one()
		responsible = self.company_id.l10n_fr_micro_accounting_responsible_id
		if not responsible or not crossing_date:
			return
		model_id = self.env["ir.model"]._get_id("res.company")
		summary = _("Review VAT-franchise threshold crossing")
		activity = self.env["mail.activity"].search([
			("res_model_id", "=", model_id),
			("res_id", "=", self.company_id.id),
			("summary", "=", summary),
		], limit=1)
		values = {
			"activity_type_id": self.env.ref("mail.mail_activity_data_todo").id,
			"summary": summary,
			"note": _("Verify the source events and switch VAT from the actual crossing date: %s", crossing_date),
			"date_deadline": crossing_date,
			"user_id": responsible.id,
			"res_model_id": model_id,
			"res_id": self.company_id.id,
		}
		if activity:
			activity.write(values)
		else:
			self.env["mail.activity"].create(values)

	def action_compute(self):
		for declaration in self:
			if declaration.state == "filed":
				raise UserError(_("Reset the filed declaration before recomputing it."))
			blockers = declaration._mandate_blockers()
			if blockers:
				raise UserError(_(
					"Mandate accounting has not been reviewed through %(date)s for: %(depots)s",
					date=declaration.date_to,
					depots=", ".join(blockers.mapped("display_name")),
				))
			tracking_start = declaration.company_id.l10n_fr_micro_urssaf_tracking_start_date
			if not tracking_start:
				tracking_start = declaration.date_from
			adjustments = {
				line.category: (line.manual_adjustment, line.manual_adjustment_reason)
				for line in declaration.line_ids
			}
			declaration.source_ids.with_context(**internal_context()).unlink()
			declaration.line_ids.with_context(**internal_context()).unlink()
			lines = {}
			for category, _label in URSSAF_CATEGORIES:
				manual_adjustment, reason = adjustments.get(category, (0.0, False))
				lines[category] = self.env["l10n.fr.micro.urssaf.declaration.line"].with_context(
					**internal_context()
				).create({
					"declaration_id": declaration.id,
					"category": category,
					"manual_adjustment": manual_adjustment,
					"manual_adjustment_reason": reason,
				})
			claimed_sources = self.env["l10n.fr.micro.urssaf.declaration.source"].search([
				("declaration_id", "!=", declaration.id),
			])
			claimed = {source.event_key: source for source in claimed_sources}
			all_events = declaration._recognition_events(
				declaration.company_id, tracking_start, declaration.date_to,
			)
			anomalies = declaration._configuration_anomalies()
			anomalies += declaration._unclassified_anomalies()
			anomalies += declaration._pos_anomalies()
			anomalies += declaration._missing_vat_dates()
			for event in all_events:
				if event["event_key"] in claimed:
					claim = claimed[event["event_key"]]
					if claim.declaration_state != "filed":
						anomalies.append(_(
							"Receipt %(description)s is already claimed by draft declaration %(declaration)s.",
							description=event["description"], declaration=claim.declaration_id.display_name,
						))
					continue
				values = {
					"declaration_id": declaration.id,
					"declaration_line_id": lines[event["category"]].id,
					"event_key": event["event_key"],
					"recognition_date": event["date"],
					"category": event["category"],
					"amount": event["amount"],
					"source_currency_id": event.get("source_currency_id"),
					"source_amount_currency": event.get("source_amount_currency", 0.0),
					"exchange_rate": event.get("exchange_rate", 1.0),
					"is_prior_period": event["date"] < declaration.date_from,
					"engine": event["engine"],
					"source_move_line_id": event["source_move_line_id"],
					"partial_id": event["partial_id"],
					"origin_move_id": event["origin_move_id"],
					"pos_order_id": event["pos_order_id"],
					"receipt_method": event["receipt_method"],
					"receipt_method_detail": event["receipt_method_detail"],
					"description": event["description"],
				}
				rate_values = declaration._source_rate_values(event)
				values.update(rate_values)
				anomalies += declaration._missing_rate_anomalies(event, rate_values)
				self.env["l10n.fr.micro.urssaf.declaration.source"].with_context(
					**internal_context()
				).create(values)
				if event["receipt_method"] == "unknown":
					anomalies.append(_("Receipt method is unproven for %(description)s.", description=event["description"]))
			for line in declaration.line_ids:
				line._refresh_amounts()
				if line.computed_turnover < 0:
					anomalies.append(_(
						"%(category)s is negative (%(amount).2f); obtain URSSAF treatment and enter a reasoned adjustment.",
						category=dict(URSSAF_CATEGORIES)[line.category], amount=line.computed_turnover,
					))
			declaration.write({
				"anomaly_text": "\n".join(dict.fromkeys(anomalies)),
				"blocking_anomaly": bool(anomalies),
			})
			declaration._threshold_values(all_events)
		return True

	def action_file(self):
		self._check_manager()
		for declaration in self:
			declaration.action_compute()
			if declaration.blocking_anomaly:
				raise UserError(_("Resolve every declaration anomaly before filing."))
			declaration.company_id._l10n_fr_micro_advance_depot_sale_horizon(
				declaration.date_to
			)
			declaration.with_context(**internal_context()).write({
				"state": "filed",
				"filed_at": fields.Datetime.now(),
				"filed_by_id": self.env.user.id,
				"reset_reason": False,
			})
		return True

	def action_reset_to_draft(self):
		self._check_manager()
		for declaration in self:
			if declaration.state != "filed":
				continue
			if not declaration.reset_reason:
				raise UserError(_("Enter a reset reason before reopening a filed declaration."))
			reason = declaration.reset_reason
			declaration.with_context(**internal_context()).write({
				"state": "draft", "filed_at": False, "filed_by_id": False,
			})
			declaration.message_post(body=_("Filed declaration reopened: %s", reason))
		return True

	def action_print(self):
		self.ensure_one()
		if not self.line_ids:
			self.action_compute()
		return self.env.ref("l10n_fr_micro_urssaf.action_report_urssaf_declaration").report_action(self)


class L10nFrMicroUrssafDeclarationLine(models.Model):
	_name = "l10n.fr.micro.urssaf.declaration.line"
	_description = "URSSAF declaration turnover box"
	_order = "category"

	declaration_id = fields.Many2one(
		"l10n.fr.micro.urssaf.declaration", required=True, ondelete="cascade", index=True,
	)
	company_id = fields.Many2one(related="declaration_id.company_id", store=True, index=True)
	declaration_state = fields.Selection(related="declaration_id.state", store=True)
	currency_id = fields.Many2one(related="declaration_id.currency_id")
	category = fields.Selection(URSSAF_CATEGORIES, required=True, index=True)
	source_ids = fields.One2many(
		"l10n.fr.micro.urssaf.declaration.source", "declaration_line_id",
	)
	current_turnover = fields.Monetary(readonly=True)
	prior_period_adjustment = fields.Monetary(readonly=True)
	manual_adjustment = fields.Monetary()
	manual_adjustment_reason = fields.Text()
	computed_turnover = fields.Monetary(readonly=True)
	declared_turnover = fields.Monetary(readonly=True)
	cotisation_amount = fields.Monetary(readonly=True)
	cfp_amount = fields.Monetary(readonly=True)
	chamber_amount = fields.Monetary(readonly=True)
	liberatoire_amount = fields.Monetary(readonly=True)
	total_estimated = fields.Monetary(readonly=True)
	rate_summary = fields.Text(readonly=True)

	_declaration_category_unique = models.Constraint(
		"unique(declaration_id, category)",
		"A declaration can contain one line per category.",
	)

	def _check_manager(self):
		if not self.env.is_superuser() and not self.env.user.has_group("account.group_account_manager"):
			raise AccessError(_("Only an Accounting Administrator can adjust a declaration."))

	@api.model_create_multi
	def create(self, values_list):
		declarations = self.env["l10n.fr.micro.urssaf.declaration"].browse(
			[values.get("declaration_id") for values in values_list if values.get("declaration_id")]
		)
		if declarations.filtered(lambda declaration: declaration.state == "filed") \
				and not is_internal(self.env):
			raise UserError(_("Filed declaration lines are immutable."))
		if not is_internal(self.env):
			self._check_manager()
		return super().create(values_list)

	def write(self, values):
		if self.filtered(lambda line: line.declaration_state == "filed") and not is_internal(self.env):
			raise UserError(_("Filed declaration lines are immutable."))
		if {"manual_adjustment", "manual_adjustment_reason"}.intersection(values):
			self._check_manager()
		elif not is_internal(self.env):
			self._check_manager()
		result = super().write(values)
		if {"manual_adjustment", "manual_adjustment_reason"}.intersection(values):
			for line in self:
				if line.manual_adjustment and not line.manual_adjustment_reason:
					raise ValidationError(_("A manual declaration adjustment requires a reason."))
				line._refresh_amounts()
		return result

	def unlink(self):
		if self.filtered(lambda line: line.declaration_state == "filed"):
			raise UserError(_("Filed declaration lines cannot be deleted."))
		if not is_internal(self.env):
			self._check_manager()
		return super().unlink()

	def _refresh_amounts(self):
		for line in self:
			current = sum(line.source_ids.filtered(lambda source: not source.is_prior_period).mapped("amount"))
			prior = sum(line.source_ids.filtered("is_prior_period").mapped("amount"))
			computed = line.currency_id.round(current + prior + line.manual_adjustment)
			declared = max(0.0, computed)
			bases = {
				"cotisation": defaultdict(float),
				"cfp": defaultdict(float),
				"chamber": defaultdict(float),
				"liberatoire": defaultdict(float),
			}
			for source in line.source_ids:
				bases["cotisation"][(source.cotisation_rate, source.acre_coefficient)] += source.amount
				bases["cfp"][(source.cfp_rate, 1.0)] += source.amount
				bases["chamber"][(source.chamber_rate, 1.0)] += source.amount
				bases["liberatoire"][(source.liberatoire_rate, 1.0)] += source.amount
			if line.manual_adjustment:
				event = {"date": line.declaration_id.date_to, "category": line.category, "amount": line.manual_adjustment}
				rates = line.declaration_id._source_rate_values(event)
				bases["cotisation"][(rates["cotisation_rate"], rates["acre_coefficient"])] += line.manual_adjustment
				bases["cfp"][(rates["cfp_rate"], 1.0)] += line.manual_adjustment
				bases["chamber"][(rates["chamber_rate"], 1.0)] += line.manual_adjustment
				bases["liberatoire"][(rates["liberatoire_rate"], 1.0)] += line.manual_adjustment
			levies = {
				levy: sum(
					line.currency_id.round(base * rate / 100 * coefficient)
					for (rate, coefficient), base in rate_bases.items()
				)
				for levy, rate_bases in bases.items()
			}
			cotisation = levies["cotisation"]
			cfp = levies["cfp"]
			chamber = levies["chamber"]
			liberatoire = levies["liberatoire"]
			summaries = sorted({
				_("%(date)s: cot. %(cot)s%% × ACRE %(acre)s; CFP %(cfp)s%%; chamber %(chamber)s%%; VFL %(vfl)s%%",
					date=source.recognition_date, cot=source.cotisation_rate,
					acre=source.acre_coefficient, cfp=source.cfp_rate,
					chamber=source.chamber_rate, vfl=source.liberatoire_rate)
				for source in line.source_ids
			})
			line.with_context(**internal_context()).write({
				"current_turnover": current,
				"prior_period_adjustment": prior,
				"computed_turnover": computed,
				"declared_turnover": declared,
				"cotisation_amount": cotisation,
				"cfp_amount": cfp,
				"chamber_amount": chamber,
				"liberatoire_amount": liberatoire,
				"total_estimated": cotisation + cfp + chamber + liberatoire,
				"rate_summary": "\n".join(summaries),
			})


class L10nFrMicroUrssafDeclarationSource(models.Model):
	_name = "l10n.fr.micro.urssaf.declaration.source"
	_description = "Recognised turnover event claimed by an URSSAF declaration"
	_order = "recognition_date, id"

	declaration_id = fields.Many2one(
		"l10n.fr.micro.urssaf.declaration", required=True, ondelete="cascade", index=True,
	)
	declaration_line_id = fields.Many2one(
		"l10n.fr.micro.urssaf.declaration.line", required=True, ondelete="cascade", index=True,
	)
	company_id = fields.Many2one(related="declaration_id.company_id", store=True, index=True)
	declaration_state = fields.Selection(related="declaration_id.state", store=True, index=True)
	currency_id = fields.Many2one(related="declaration_id.currency_id")
	source_currency_id = fields.Many2one("res.currency", string="Receipt currency", ondelete="restrict")
	source_amount_currency = fields.Monetary(string="Receipt foreign amount", currency_field="source_currency_id")
	exchange_rate = fields.Float(string="Company-currency rate", digits=(12, 6))
	event_key = fields.Char(required=True, index=True, copy=False)
	recognition_date = fields.Date(required=True, index=True)
	category = fields.Selection(URSSAF_CATEGORIES, required=True, index=True)
	amount = fields.Monetary(required=True)
	is_prior_period = fields.Boolean(index=True)
	engine = fields.Selection(
		selection=[
			("caba", "Cash-basis journal"),
			("reconciliation", "Receivable reconciliation"),
			("pos", "Point of Sale"),
		],
		required=True,
	)
	source_move_line_id = fields.Many2one("account.move.line", ondelete="restrict")
	partial_id = fields.Many2one("account.partial.reconcile", ondelete="restrict")
	origin_move_id = fields.Many2one("account.move", ondelete="restrict")
	pos_order_id = fields.Many2one("pos.order", ondelete="restrict")
	description = fields.Char()
	receipt_method = fields.Selection(
		selection=[
			("transfer", "Bank transfer"), ("card", "Card"),
			("cash", "Cash"), ("cheque", "Cheque"),
			("mixed", "Mixed POS methods"), ("other", "Other / manual"),
			("unknown", "Unproven"),
		],
		required=True,
	)
	receipt_method_detail = fields.Char()
	cotisation_rate_id = fields.Many2one("l10n.fr.micro.urssaf.rate", string="Contribution rule", ondelete="restrict")
	cotisation_rate = fields.Float(string="Contribution rate (%)", digits=(8, 4))
	acre_coefficient = fields.Float(digits=(5, 4), default=1.0)
	cotisation_amount = fields.Monetary()
	cfp_rate_id = fields.Many2one("l10n.fr.micro.urssaf.rate", string="CFP rule", ondelete="restrict")
	cfp_rate = fields.Float(string="CFP rate (%)", digits=(8, 4))
	cfp_amount = fields.Monetary()
	chamber_rate_id = fields.Many2one("l10n.fr.micro.urssaf.rate", string="Chamber-tax rule", ondelete="restrict")
	chamber_rate = fields.Float(string="Chamber-tax rate (%)", digits=(8, 4))
	chamber_amount = fields.Monetary()
	liberatoire_rate_id = fields.Many2one("l10n.fr.micro.urssaf.rate", string="Versement-libératoire rule", ondelete="restrict")
	liberatoire_rate = fields.Float(string="Versement-libératoire rate (%)", digits=(8, 4))
	liberatoire_amount = fields.Monetary()

	_company_event_unique = models.Constraint(
		"unique(company_id, event_key)",
		"A recognised event can be claimed only once.",
	)

	@api.constrains("declaration_id", "declaration_line_id", "category")
	def _check_source_integrity(self):
		for source in self:
			if source.declaration_line_id.declaration_id != source.declaration_id:
				raise ValidationError(_("Receipt evidence and its turnover box must belong to the same declaration."))
			if source.declaration_line_id.category != source.category:
				raise ValidationError(_("Receipt evidence category must match its turnover box."))

	@api.model_create_multi
	def create(self, values_list):
		declarations = self.env["l10n.fr.micro.urssaf.declaration"].browse(
			[values.get("declaration_id") for values in values_list if values.get("declaration_id")]
		)
		if declarations.filtered(lambda declaration: declaration.state == "filed") \
				and not is_internal(self.env):
			raise UserError(_("Filed declaration sources are immutable."))
		if not is_internal(self.env) and not self.env.is_superuser() \
				and not self.env.user.has_group("account.group_account_manager"):
			raise AccessError(_("Only an Accounting Administrator can alter declaration evidence."))
		return super().create(values_list)

	def write(self, values):
		if self.filtered(lambda source: source.declaration_state == "filed") and not is_internal(self.env):
			raise UserError(_("Filed declaration sources are immutable."))
		if not is_internal(self.env) and not self.env.is_superuser() \
				and not self.env.user.has_group("account.group_account_manager"):
			raise AccessError(_("Only an Accounting Administrator can alter declaration evidence."))
		return super().write(values)

	def unlink(self):
		if self.filtered(lambda source: source.declaration_state == "filed"):
			raise UserError(_("Filed declaration sources cannot be deleted."))
		if not is_internal(self.env) and not self.env.is_superuser() \
				and not self.env.user.has_group("account.group_account_manager"):
			raise AccessError(_("Only an Accounting Administrator can alter declaration evidence."))
		return super().unlink()
