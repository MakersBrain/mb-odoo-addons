from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDepotStatement(TransactionCase):
    """The statement is the document that settles money, so its arithmetic is
    the part of this module worth pinning down. Every case here is about a
    movement being counted in the right column.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1)
        cls.gallery = cls.env["res.partner"].create({
            "name": "Galerie Test", "is_company": True})

        wizard = cls.env["mb.depot.create"].create({
            "partner_id": cls.gallery.id,
            "commission": 40.0,
            "warehouse_id": cls.warehouse.id,
        })
        wizard.action_create()
        cls.depot = cls.env["stock.location"].search([
            ("depot_partner_id", "=", cls.gallery.id), ("is_depot", "=", True)])

        cls.product = cls.env["product.product"].create({
            "name": "Test bowl", "type": "consu", "is_storable": True,
            "list_price": 100.0, "standard_price": 25.0,
        })
        cls.customers = cls.env.ref("stock.stock_location_customers")

    def _move(self, source, destination, qty, date=None):
        """A done move line, dated. Written straight rather than through a
        picking because the statement reads move lines, and going through the
        UI flow would test Odoo rather than this module.
        """
        move = self.env["stock.move"].create({
            "product_id": self.product.id,
            "product_uom_qty": qty,
            "location_id": source.id,
            "location_dest_id": destination.id,
        })
        move._action_confirm()
        move.move_line_ids = [fields.Command.create({
            "product_id": self.product.id,
            "location_id": source.id,
            "location_dest_id": destination.id,
            "quantity": qty,
        })]
        move.picked = True
        move._action_done()
        if date:
            move.move_line_ids.write({"date": date})
        return move

    def _statement(self, date_from, date_to):
        statement = self.env["mb.depot.statement"].create({
            "depot_id": self.depot.id,
            "date_from": date_from,
            "date_to": date_to,
        })
        statement.action_compute()
        return statement

    def test_depot_is_created_consistently(self):
        self.assertTrue(self.depot.is_depot)
        self.assertEqual(self.depot.usage, "internal",
                         "a depot must stay internal or the stock leaves our books")
        self.assertFalse(self.depot.warehouse_id,
                         "a depot outside WH cannot be reserved by an ordinary delivery")
        rule = self.depot.depot_route_id.rule_ids
        self.assertEqual(rule.location_src_id, self.depot)
        self.assertEqual(rule.location_dest_id, self.customers)
        item = self.depot.depot_pricelist_id.item_ids
        self.assertEqual(
            item.compute_price, "percentage",
            "under 'formula' the commission is folded into the unit price and "
            "never appears on the invoice")
        self.assertEqual(item.percent_price, 40.0)

    def test_placed_sold_returned_and_closing(self):
        stock = self.warehouse.lot_stock_id
        self._move(stock, self.depot, 10, date="2026-08-05 09:00:00")
        self._move(self.depot, self.customers, 3, date="2026-08-12 09:00:00")
        self._move(self.depot, stock, 2, date="2026-08-20 09:00:00")

        line = self._statement("2026-08-01", "2026-08-31").line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.qty_opening, 0)
        self.assertEqual(line.qty_placed, 10)
        self.assertEqual(line.qty_sold, 3, "only moves to a customer are sales")
        self.assertEqual(line.qty_returned, 2, "a move back to stock is a return")
        self.assertEqual(line.qty_closing, 5)

    def test_closing_reconciles_with_the_quants(self):
        """The statement is only trustworthy if it agrees with on-hand stock."""
        stock = self.warehouse.lot_stock_id
        self._move(stock, self.depot, 10, date="2026-08-05 09:00:00")
        self._move(self.depot, self.customers, 3, date="2026-08-12 09:00:00")

        line = self._statement("2026-08-01", "2026-08-31").line_ids
        on_hand = sum(self.env["stock.quant"].search(
            [("location_id", "child_of", self.depot.id)]).mapped("quantity"))
        self.assertEqual(line.qty_closing, on_hand)

    def test_earlier_movements_become_the_opening_balance(self):
        stock = self.warehouse.lot_stock_id
        self._move(stock, self.depot, 6, date="2026-07-10 09:00:00")
        self._move(self.depot, self.customers, 1, date="2026-07-20 09:00:00")
        self._move(stock, self.depot, 4, date="2026-08-03 09:00:00")

        line = self._statement("2026-08-01", "2026-08-31").line_ids
        self.assertEqual(line.qty_opening, 5, "6 placed minus 1 sold before the period")
        self.assertEqual(line.qty_placed, 4)
        self.assertEqual(line.qty_closing, 9)

    def test_movements_after_the_period_are_excluded(self):
        stock = self.warehouse.lot_stock_id
        self._move(stock, self.depot, 5, date="2026-08-10 09:00:00")
        self._move(self.depot, self.customers, 5, date="2026-09-02 09:00:00")

        line = self._statement("2026-08-01", "2026-08-31").line_ids
        self.assertEqual(line.qty_sold, 0, "a September sale is not August business")
        self.assertEqual(line.qty_closing, 5)

    def test_the_last_day_of_the_period_is_included(self):
        """date_to is inclusive; a sale reported on the 31st belongs to August."""
        stock = self.warehouse.lot_stock_id
        self._move(stock, self.depot, 2, date="2026-08-01 08:00:00")
        self._move(self.depot, self.customers, 1, date="2026-08-31 18:00:00")

        line = self._statement("2026-08-01", "2026-08-31").line_ids
        self.assertEqual(line.qty_sold, 1)

    def test_internal_shuffling_is_not_a_movement(self):
        stock = self.warehouse.lot_stock_id
        shelf = self.env["stock.location"].create({
            "name": "Vitrine", "usage": "internal", "location_id": self.depot.id})
        self._move(stock, self.depot, 4, date="2026-08-05 09:00:00")
        self._move(self.depot, shelf, 4, date="2026-08-06 09:00:00")

        line = self._statement("2026-08-01", "2026-08-31").line_ids
        self.assertEqual(line.qty_placed, 4)
        self.assertEqual(line.qty_returned, 0,
                         "moving a piece between two shelves of the same gallery "
                         "is not a return")
        self.assertEqual(line.qty_closing, 4)

    def test_value_falls_back_to_list_price_and_commission(self):
        """A piece that left without a sale order must not value at zero."""
        stock = self.warehouse.lot_stock_id
        self._move(stock, self.depot, 5, date="2026-08-05 09:00:00")
        self._move(self.depot, self.customers, 2, date="2026-08-12 09:00:00")

        statement = self._statement("2026-08-01", "2026-08-31")
        line = statement.line_ids
        self.assertEqual(line.amount_gross, 200.0)
        self.assertEqual(line.amount_net, 120.0, "100 less 40% commission, twice")
        self.assertEqual(line.amount_commission, 80.0)
        self.assertEqual(statement.total_sold, 120.0)

    def test_a_depot_must_be_internal(self):
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.depot.usage = "view"
