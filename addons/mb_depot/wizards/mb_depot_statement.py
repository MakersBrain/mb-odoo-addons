from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MbDepotStatement(models.TransientModel):
    _name = "mb.depot.statement"
    _description = "Dépôt-vente statement"

    depot_id = fields.Many2one(
        comodel_name="stock.location",
        string="Depot",
        required=True,
        domain=[("is_depot", "=", True)],
    )
    partner_id = fields.Many2one(
        related="depot_id.depot_partner_id", string="Depositary")
    date_from = fields.Date(
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
    )
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    line_ids = fields.One2many(
        comodel_name="mb.depot.statement.line",
        inverse_name="statement_id",
        string="Lines",
        readonly=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        default=lambda self: self.env.company.currency_id,
    )
    total_sold = fields.Monetary(compute="_compute_totals")
    total_gross = fields.Monetary(compute="_compute_totals")
    total_commission = fields.Monetary(compute="_compute_totals")

    @api.depends("line_ids.amount_net", "line_ids.amount_gross")
    def _compute_totals(self):
        for statement in self:
            statement.total_sold = sum(statement.line_ids.mapped("amount_net"))
            statement.total_gross = sum(statement.line_ids.mapped("amount_gross"))
            statement.total_commission = sum(
                statement.line_ids.mapped("amount_commission"))

    @api.constrains("date_from", "date_to")
    def _check_period(self):
        for statement in self:
            if statement.date_to < statement.date_from:
                raise UserError(_("The period ends before it starts."))

    def _bounds(self):
        """Half-open [from, to) in UTC, which is how stock.move.line.date is stored.

        A move stamped late in the evening of the last day of the month belongs
        to that month for the depositary even if UTC has already rolled over;
        that discrepancy is at most a few hours and is accepted here rather than
        pretending to a precision the reported sale dates do not have.
        """
        self.ensure_one()
        dt_from = fields.Datetime.to_datetime(self.date_from)
        dt_to = fields.Datetime.to_datetime(self.date_to) + timedelta(days=1)
        return dt_from, dt_to

    def _crossing_moves(self):
        """Done move lines entering and leaving the depot.

        Moves with both ends inside the depot are excluded on purpose: shuffling
        a piece between two shelves of the same gallery is not a movement of the
        statement.
        """
        self.ensure_one()
        MoveLine = self.env["stock.move.line"]
        depot = self.depot_id.id
        incoming = MoveLine.search([
            "&",
            ("state", "=", "done"),
            "&",
            ("location_dest_id", "child_of", depot),
            "!", ("location_id", "child_of", depot),
        ])
        outgoing = MoveLine.search([
            "&",
            ("state", "=", "done"),
            "&",
            ("location_id", "child_of", depot),
            "!", ("location_dest_id", "child_of", depot),
        ])
        return incoming, outgoing

    def _values(self, move_line):
        """Gross and net for one sold move line.

        The sale order line is the truth when there is one: it carries the list
        price and the commission as a discount. Falling back to the product's
        list price and the depot's recorded commission keeps a piece that left
        without a sale order from silently valuing at zero.
        """
        qty = move_line.quantity
        sale_line = move_line.move_id.sale_line_id
        if sale_line:
            gross = sale_line.price_unit * qty
            net = sale_line.price_unit * (1.0 - (sale_line.discount or 0.0) / 100.0) * qty
        else:
            gross = move_line.product_id.list_price * qty
            net = gross * (1.0 - (self.depot_id.depot_commission or 0.0) / 100.0)
        return gross, net

    def action_compute(self):
        self.ensure_one()
        self.line_ids.unlink()
        dt_from, dt_to = self._bounds()
        incoming, outgoing = self._crossing_moves()

        rows = {}

        def row(move_line):
            key = (move_line.product_id.id, move_line.lot_id.id)
            if key not in rows:
                rows[key] = {
                    "statement_id": self.id,
                    "product_id": move_line.product_id.id,
                    "lot_id": move_line.lot_id.id or False,
                    "qty_opening": 0.0, "qty_placed": 0.0, "qty_sold": 0.0,
                    "qty_returned": 0.0, "amount_gross": 0.0, "amount_net": 0.0,
                }
            return rows[key]

        for ml in incoming:
            if ml.date >= dt_to:
                continue
            target = "qty_opening" if ml.date < dt_from else "qty_placed"
            row(ml)[target] += ml.quantity

        for ml in outgoing:
            if ml.date >= dt_to:
                continue
            if ml.date < dt_from:
                row(ml)["qty_opening"] -= ml.quantity
                continue
            # Sold and returned are both moves out of the depot. The destination
            # is what tells them apart, and anchoring the split there is what
            # makes the statement reconcile against the quants.
            if ml.location_dest_id.usage == "customer":
                values = row(ml)
                values["qty_sold"] += ml.quantity
                gross, net = self._values(ml)
                values["amount_gross"] += gross
                values["amount_net"] += net
            else:
                row(ml)["qty_returned"] += ml.quantity

        self.env["mb.depot.statement.line"].create(list(rows.values()))
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_print(self):
        self.ensure_one()
        if not self.line_ids:
            self.action_compute()
        return self.env.ref("mb_depot.action_report_depot_statement").report_action(self)


class MbDepotStatementLine(models.TransientModel):
    _name = "mb.depot.statement.line"
    _description = "Dépôt-vente statement line"
    _order = "product_id, lot_name"

    statement_id = fields.Many2one(
        comodel_name="mb.depot.statement", required=True, ondelete="cascade")
    product_id = fields.Many2one(comodel_name="product.product", string="Piece")
    lot_id = fields.Many2one(comodel_name="stock.lot", string="Serial")
    lot_name = fields.Char(related="lot_id.name", store=True)
    currency_id = fields.Many2one(related="statement_id.currency_id")

    qty_opening = fields.Float("Opening", digits="Product Unit of Measure")
    qty_placed = fields.Float("Placed", digits="Product Unit of Measure")
    qty_sold = fields.Float("Sold", digits="Product Unit of Measure")
    qty_returned = fields.Float("Returned", digits="Product Unit of Measure")
    qty_closing = fields.Float(
        "Closing", compute="_compute_qty_closing", digits="Product Unit of Measure")

    amount_gross = fields.Monetary("Retail", help="At the price the piece sold for.")
    amount_net = fields.Monetary("Due to us", help="After the depositary's commission.")
    amount_commission = fields.Monetary(compute="_compute_amount_commission")

    @api.depends("qty_opening", "qty_placed", "qty_sold", "qty_returned")
    def _compute_qty_closing(self):
        for line in self:
            line.qty_closing = (
                line.qty_opening + line.qty_placed - line.qty_sold - line.qty_returned)

    @api.depends("amount_gross", "amount_net")
    def _compute_amount_commission(self):
        for line in self:
            line.amount_commission = line.amount_gross - line.amount_net
