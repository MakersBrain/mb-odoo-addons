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
            "legal_structure": "resale",
        })
        wizard.action_create()
        cls.depot_warehouse = cls.env["stock.warehouse"].search([
            ("depot_partner_id", "=", cls.gallery.id), ("is_depot", "=", True)])
        # The statement is warehouse-scoped; the moves below still need the one
        # location the pieces actually stand in.
        cls.depot = cls.depot_warehouse.lot_stock_id

        cls.product = cls.env["product.product"].create({
            "name": "Test bowl", "type": "consu", "is_storable": True,
            "list_price": 100.0, "standard_price": 25.0,
        })
        cls.customers = cls.env.ref("stock.stock_location_customers")

    def _move(self, source, destination, qty, date=None, sale_date=None):
        """A done move line, dated. Written straight rather than through a
        picking because the statement reads move lines, and going through the
        UI flow would test Odoo rather than this module.

        `date` is when the transfer was validated here, `sale_date` what the
        depositary reports. They differ whenever a gallery reports after the
        fact, which is the ordinary case.
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
        if sale_date:
            move.move_line_ids.write({"mb_depot_sale_date": sale_date})
        return move

    def _statement(self, date_from, date_to):
        statement = self.env["mb.depot.statement"].create({
            "depot_id": self.depot_warehouse.id,
            "date_from": date_from,
            "date_to": date_to,
        })
        action = statement.action_compute()
        self.assertEqual(action["target"], "current")
        return statement

    def test_depot_is_created_consistently(self):
        depot = self.depot_warehouse
        self.assertTrue(depot.is_depot)
        self.assertEqual(self.depot.usage, "internal",
                         "a depot must stay internal or the stock leaves our books")
        self.assertEqual(self.depot.warehouse_id, depot,
                         "the pieces stand in the depot's own warehouse, which is "
                         "what keeps an ordinary delivery from reserving them")
        self.assertEqual(depot.reception_steps, "one_step")
        self.assertEqual(depot.delivery_steps, "ship_only",
                         "multi-step would split one sale into two moves")
        item = depot.depot_pricelist_id.item_ids
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

    def test_a_reported_sale_date_decides_the_period(self):
        """The gallery sold in August and told us in September. It is August
        business, and September must not claim it.
        """
        stock = self.warehouse.lot_stock_id
        self._move(stock, self.depot, 5, date="2026-08-05 09:00:00")
        self._move(self.depot, self.customers, 2,
                   date="2026-09-04 11:00:00", sale_date="2026-08-20")

        august = self._statement("2026-08-01", "2026-08-31").line_ids
        self.assertEqual(august.qty_sold, 2, "a sale reported late is still an "
                                             "August sale")
        self.assertEqual(august.qty_closing, 3)

        september = self._statement("2026-09-01", "2026-09-30").line_ids
        self.assertEqual(september.qty_sold, 0)
        self.assertEqual(september.qty_opening, 3,
                         "August's closing has to be September's opening")

    def test_a_reported_date_also_moves_a_placement(self):
        """The date is applied to every crossing move, not only to sales. A
        placement keyed in a week late would otherwise land in the wrong period
        and take the opening balance with it.
        """
        stock = self.warehouse.lot_stock_id
        self._move(stock, self.depot, 4,
                   date="2026-08-03 09:00:00", sale_date="2026-07-28")

        line = self._statement("2026-08-01", "2026-08-31").line_ids
        self.assertEqual(line.qty_placed, 0)
        self.assertEqual(line.qty_opening, 4)
        self.assertEqual(line.qty_closing, 4)

    def test_the_statement_reports_the_day_a_piece_sold(self):
        stock = self.warehouse.lot_stock_id
        self._move(stock, self.depot, 3, date="2026-08-01 09:00:00")
        self._move(self.depot, self.customers, 1,
                   date="2026-09-04 11:00:00", sale_date="2026-08-14")

        line = self._statement("2026-08-01", "2026-08-31").line_ids
        self.assertEqual(line.date_sold, fields.Date.to_date("2026-08-14"))

    def test_no_day_is_reported_when_a_row_covers_several(self):
        """One aggregate row, three sales, three days: any single date on it
        would be a lie, so it stays blank.
        """
        stock = self.warehouse.lot_stock_id
        self._move(stock, self.depot, 5, date="2026-08-01 09:00:00")
        self._move(self.depot, self.customers, 1, sale_date="2026-08-14",
                   date="2026-09-04 11:00:00")
        self._move(self.depot, self.customers, 1, sale_date="2026-08-19",
                   date="2026-09-04 11:00:00")

        line = self._statement("2026-08-01", "2026-08-31").line_ids
        self.assertEqual(line.qty_sold, 2)
        self.assertFalse(line.date_sold)

    def test_the_move_line_date_still_applies_without_a_reported_one(self):
        """Nothing reported, nothing changed: the validation date decides."""
        stock = self.warehouse.lot_stock_id
        self._move(stock, self.depot, 5, date="2026-08-05 09:00:00")
        move = self._move(self.depot, self.customers, 1, date="2026-08-12 09:00:00")
        self.assertFalse(move.move_line_ids.mb_depot_sale_date)

        line = self._statement("2026-08-01", "2026-08-31").line_ids
        self.assertEqual(line.qty_sold, 1)
        self.assertEqual(line.date_sold, fields.Date.to_date("2026-08-12"))

    def test_the_transfer_carries_the_date_down_to_its_lines(self):
        """Setting it once on the transfer is the ordinary case; it only shows
        back on the transfer when the lines agree.
        """
        stock = self.warehouse.lot_stock_id
        other = self.env["product.product"].create({
            "name": "Test mug", "type": "consu", "is_storable": True,
            "list_price": 40.0,
        })
        self._move(stock, self.depot, 5, date="2026-08-01 09:00:00")
        self.env["stock.quant"]._update_available_quantity(other, self.depot, 5)

        picking = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.out_type_id.id,
            "location_id": self.depot.id,
            "location_dest_id": self.customers.id,
            "move_ids": [
                fields.Command.create({
                    "product_id": product.id,
                    "product_uom_qty": 1,
                    "location_id": self.depot.id,
                    "location_dest_id": self.customers.id,
                })
                for product in (self.product, other)
            ],
        })
        picking.action_confirm()
        picking.action_assign()
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(len(picking.move_line_ids), 2)

        picking.mb_depot_sale_date = "2026-08-15"
        self.assertEqual(
            set(picking.move_line_ids.mapped("mb_depot_sale_date")),
            {fields.Date.to_date("2026-08-15")})
        self.assertEqual(picking.mb_depot_sale_date,
                         fields.Date.to_date("2026-08-15"))

        picking.move_line_ids[0].mb_depot_sale_date = "2026-08-16"
        self.assertFalse(
            picking.mb_depot_sale_date,
            "lines that disagree leave the transfer with no single date to show")

    def test_a_depot_receives_and_delivers_in_one_step(self):
        """Multi-step would put a receiving bay and a packing table inside the
        depositary's shop, and split one reported sale into two moves whose
        first leg leaves the depot for a sibling location.
        """
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.depot_warehouse.delivery_steps = "pick_ship"
