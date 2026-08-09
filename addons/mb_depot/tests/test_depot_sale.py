from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDepotSale(TransactionCase):
    """Completing a depot that already exists, and selling only what is on the
    depositary's shelf. Both decide what can be sold and at what price, so both
    are pinned here.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        cls.customers = cls.env.ref("stock.stock_location_customers")
        cls.gallery = cls.env["res.partner"].create({
            "name": "Galerie Sale Test", "is_company": True})
        cls.held = cls.env["product.product"].create({
            "name": "Held bowl", "type": "consu", "is_storable": True,
            "list_price": 100.0,
        })
        cls.at_home = cls.env["product.product"].create({
            "name": "Bowl still at the atelier", "type": "consu",
            "is_storable": True, "list_price": 100.0,
        })

    def _wizard(self, commission=40.0, **values):
        return self.env["mb.depot.create"].create(dict({
            "partner_id": self.gallery.id,
            "commission": commission,
            "warehouse_id": self.warehouse.id,
        }, **values))

    def _place(self, product, qty, location):
        move = self.env["stock.move"].create({
            "product_id": product.id,
            "product_uom_qty": qty,
            "location_id": self.stock.id,
            "location_dest_id": location.id,
        })
        move._action_confirm()
        move.move_line_ids = [fields.Command.create({
            "product_id": product.id,
            "location_id": self.stock.id,
            "location_dest_id": location.id,
            "quantity": qty,
        })]
        move.picked = True
        move._action_done()

    def test_a_depot_made_by_hand_is_completed_not_duplicated(self):
        """The ordinary case when this module arrives after the shelf does. A
        second location beside the first would strand the stock already at the
        gallery outside every statement.
        """
        by_hand = self.env["stock.location"].create({
            "name": "Galerie Sale Test", "usage": "internal",
            "location_id": self.stock.location_id.id,
            "is_depot": True, "depot_partner_id": self.gallery.id,
            "depot_commission": 5.0,
        })
        self._place(self.held, 3, by_hand)

        self._wizard(commission=40.0).action_create()

        depots = self.env["stock.location"].search([
            ("is_depot", "=", True), ("depot_partner_id", "=", self.gallery.id)])
        self.assertEqual(depots, by_hand, "the existing depot is adopted")
        self.assertEqual(by_hand.depot_commission, 40.0)
        self.assertTrue(by_hand.depot_route_id, "the missing route is created")
        self.assertEqual(by_hand.depot_route_id.rule_ids.location_src_id, by_hand)
        self.assertEqual(by_hand.depot_pricelist_id.item_ids.percent_price, 40.0)
        self.assertEqual(by_hand.depot_qty, 3, "the stock already there stays there")

    def test_rerunning_moves_the_commission_rather_than_stacking_it(self):
        """Renegotiating the percentage is the reason to run the wizard twice.
        A second global item beside the first would not deterministically win.
        """
        self._wizard(commission=40.0).action_create()
        depot = self.env["stock.location"].search([
            ("is_depot", "=", True), ("depot_partner_id", "=", self.gallery.id)])
        route, pricelist = depot.depot_route_id, depot.depot_pricelist_id

        self._wizard(commission=35.0).action_create()

        self.assertEqual(depot.depot_route_id, route, "no second route")
        self.assertEqual(len(route.rule_ids), 1, "no second pull rule")
        self.assertEqual(depot.depot_pricelist_id, pricelist, "no second pricelist")
        self.assertEqual(len(pricelist.item_ids), 1)
        self.assertEqual(pricelist.item_ids.percent_price, 35.0)
        self.assertEqual(depot.depot_commission, 35.0)

    def test_an_order_to_a_depositary_offers_only_what_it_holds(self):
        self._wizard().action_create()
        depot = self.env["stock.location"].search([
            ("is_depot", "=", True), ("depot_partner_id", "=", self.gallery.id)])
        self._place(self.held, 2, depot)
        self.env["stock.quant"]._update_available_quantity(
            self.at_home, self.stock, 5)

        order = self.env["sale.order"].create({"partner_id": self.gallery.id})

        self.assertEqual(order.mb_depot_id, depot,
                         "the depot follows from the customer")
        self.assertIn(self.held, order.mb_depot_product_ids)
        self.assertNotIn(self.at_home, order.mb_depot_product_ids,
                         "a piece at the atelier cannot be sold by the gallery")

    def test_a_reserved_piece_is_no_longer_on_offer(self):
        """Unreserved rather than merely on hand: a unique piece offered twice
        is a piece that cannot be delivered twice.
        """
        self._wizard().action_create()
        depot = self.env["stock.location"].search([
            ("is_depot", "=", True), ("depot_partner_id", "=", self.gallery.id)])
        self._place(self.held, 1, depot)

        order = self.env["sale.order"].create({"partner_id": self.gallery.id})
        self.assertIn(self.held, order.mb_depot_product_ids)

        outgoing = self.env["stock.move"].create({
            "product_id": self.held.id,
            "product_uom_qty": 1,
            "location_id": depot.id,
            "location_dest_id": self.customers.id,
        })
        outgoing._action_confirm()
        outgoing._action_assign()
        self.assertTrue(outgoing.move_line_ids, "the piece is reserved at the depot")

        order.invalidate_recordset(["mb_depot_product_ids"])
        self.assertNotIn(self.held, order.mb_depot_product_ids)

    def test_an_ordinary_customer_restricts_nothing(self):
        walk_in = self.env["res.partner"].create({"name": "Walk-in"})
        order = self.env["sale.order"].create({"partner_id": walk_in.id})
        self.assertFalse(order.mb_depot_id)
        self.assertFalse(order.mb_depot_product_ids,
                         "with no depot the line domain adds no clause at all")

    def test_availability_is_read_at_the_depot_not_the_warehouse(self):
        """A depot is outside WH by design, so the warehouse-scoped quantities
        sale_stock reads report nothing on hand for a piece that is standing on
        the gallery's shelf.
        """
        self._wizard().action_create()
        depot = self.env["stock.location"].search([
            ("is_depot", "=", True), ("depot_partner_id", "=", self.gallery.id)])
        self._place(self.held, 2, depot)

        order = self.env["sale.order"].create({
            "partner_id": self.gallery.id,
            "order_line": [fields.Command.create({
                "product_id": self.held.id, "product_uom_qty": 1})],
        })
        line = order.order_line

        self.assertEqual(line.qty_available_today, 2,
                         "the piece is on the shelf being sold from")
        self.assertEqual(line.free_qty_today, 2)

    def test_availability_of_an_ordinary_order_is_untouched(self):
        # Straight onto the quant rather than through _place: that helper moves
        # out of WH/Stock, so using it to stock WH/Stock nets to nothing.
        self.env["stock.quant"]._update_available_quantity(
            self.at_home, self.stock, 7)
        walk_in = self.env["res.partner"].create({"name": "Walk-in availability"})

        order = self.env["sale.order"].create({
            "partner_id": walk_in.id,
            "order_line": [fields.Command.create({
                "product_id": self.at_home.id, "product_uom_qty": 1})],
        })

        self.assertFalse(order.mb_depot_id)
        self.assertEqual(order.order_line.qty_available_today, 7,
                         "an order with no depot still reads the warehouse")
