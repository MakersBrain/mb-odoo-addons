from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDepotSale(TransactionCase):
    """Creating a depot and selling only what is on the depositary's shelf.
    Both decide what can be sold and at what price, so both are pinned here.
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
            "legal_structure": "resale",
        }, **values))

    def _depot(self):
        return self.env["stock.warehouse"].search([
            ("is_depot", "=", True), ("depot_partner_id", "=", self.gallery.id)])

    def test_mandate_is_recorded_but_resale_order_is_blocked(self):
        gallery = self.env["res.partner"].create({
            "name": "Mandate gallery", "is_company": True,
        })
        self.env["mb.depot.create"].create({
            "partner_id": gallery.id,
            "commission": 40.0,
            "legal_structure": "mandate",
        }).action_create()
        depot = self.env["stock.warehouse"].search([
            ("is_depot", "=", True), ("depot_partner_id", "=", gallery.id),
        ]).ensure_one()
        self.assertEqual(depot.mb_depot_legal_structure, "mandate")
        order = self.env["sale.order"].create({"partner_id": gallery.id})
        self.assertEqual(order.warehouse_id, depot)
        with self.assertRaises(UserError):
            order.action_confirm()

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

    def test_a_depot_is_a_warehouse_with_its_own_stock(self):
        self._wizard(commission=40.0).action_create()
        depot = self._depot()
        self._place(self.held, 3, depot.lot_stock_id)

        self.assertTrue(depot.lot_stock_id, "a depot has a stock location of its own")
        self.assertEqual(depot.lot_stock_id.usage, "internal",
                         "or the pieces leave our balance sheet while unsold")
        self.assertEqual(depot.depot_pricelist_id.item_ids.percent_price, 40.0)
        self.assertEqual(depot.depot_qty, 3)
        self.assertNotEqual(depot, self.warehouse,
                            "the gallery's shelf is not the atelier's")

    def test_creating_a_depot_leaves_the_depositary_sellable(self):
        """stock.warehouse._update_partner_data() points its partner's customer
        location at the inter-warehouse transit, which is right for another site
        of ours and ruinous for the gallery we invoice: every sale to it would
        fail with "no rule to replenish in Inter-warehouse transit". The depot
        warehouse therefore keeps the company's own address.
        """
        before = self.gallery.property_stock_customer

        self._wizard().action_create()

        self.assertEqual(self.gallery.property_stock_customer, before)
        self.assertNotEqual(
            self.gallery.property_stock_customer,
            self.env.company.internal_transit_location_id,
            "a depositary is a customer, not another site of ours")
        self.assertNotEqual(self._depot().partner_id, self.gallery)

    def test_a_confirmed_depot_sale_ships_from_the_gallery(self):
        """End to end, and the reason the warehouse is the whole mechanism: no
        route, no pull rule, no third-party module.
        """
        self._wizard().action_create()
        depot = self._depot()
        self._place(self.held, 2, depot.lot_stock_id)

        order = self.env["sale.order"].create({
            "partner_id": self.gallery.id,
            "order_line": [fields.Command.create({
                "product_id": self.held.id, "product_uom_qty": 1})],
        })
        order.action_confirm()

        picking = order.picking_ids
        self.assertEqual(len(picking), 1)
        self.assertEqual(picking.location_id, depot.lot_stock_id,
                         "the piece ships from the gallery, not the atelier")
        self.assertEqual(picking.location_dest_id.usage, "customer")
        self.assertEqual(picking.move_ids.quantity, 1,
                         "and it reserves, because the stock is really there")

    def test_new_products_invoice_on_delivered_quantities(self):
        """The stock movement out of the depot is what makes the sale real, so
        it has to be what gates the invoice. On ordered quantities a gallery can
        be billed at confirmation - before the movement, and before anything was
        sold at all if the report turns out to be wrong.
        """
        self._wizard().action_create()

        self.assertEqual(
            self.env["ir.default"]._get("product.template", "invoice_policy"),
            "delivery")
        fresh = self.env["product.template"].create({"name": "A piece made later"})
        self.assertEqual(fresh.invoice_policy, "delivery")

    def test_a_depot_sale_cannot_be_invoiced_before_it_ships(self):
        self._wizard().action_create()
        depot = self._depot()
        self._place(self.held, 1, depot.lot_stock_id)
        self.held.invoice_policy = "delivery"

        order = self.env["sale.order"].create({
            "partner_id": self.gallery.id,
            "order_line": [fields.Command.create({
                "product_id": self.held.id, "product_uom_qty": 1})],
        })
        order.action_confirm()
        self.assertEqual(order.invoice_status, "no",
                         "nothing to invoice until the piece leaves the depot")

        picking = order.picking_ids
        picking.move_ids.quantity = 1
        picking.move_ids.picked = True
        picking.button_validate()

        self.assertEqual(order.invoice_status, "to invoice")
        self.assertEqual(order.order_line.qty_delivered, 1)

    def test_an_existing_product_keeps_the_policy_it_had(self):
        """A default, not a rewrite: the wizard has no business changing a
        policy someone already chose.
        """
        self.at_home.invoice_policy = "order"

        self._wizard().action_create()

        self.assertEqual(self.at_home.invoice_policy, "order")

    def test_rerunning_moves_the_commission_rather_than_stacking_it(self):
        """Renegotiating the percentage is the reason to run the wizard twice.
        A second global item beside the first would not deterministically win.
        """
        self._wizard(commission=40.0).action_create()
        depot = self._depot()
        pricelist = depot.depot_pricelist_id

        self._wizard(commission=35.0).action_create()

        self.assertEqual(self._depot(), depot, "no second warehouse")
        self.assertEqual(depot.depot_pricelist_id, pricelist, "no second pricelist")
        self.assertEqual(len(pricelist.item_ids), 1)
        self.assertEqual(pricelist.item_ids.percent_price, 35.0)
        self.assertEqual(depot.depot_commission, 35.0)

    def test_an_order_to_a_depositary_offers_only_what_it_holds(self):
        self._wizard().action_create()
        depot = self._depot()
        self._place(self.held, 2, depot.lot_stock_id)
        self.env["stock.quant"]._update_available_quantity(
            self.at_home, self.stock, 5)

        order = self.env["sale.order"].create({"partner_id": self.gallery.id})

        self.assertEqual(order.warehouse_id, depot,
                         "the depot follows from the customer")
        self.assertIn(self.held, order.mb_depot_product_ids)
        self.assertNotIn(self.at_home, order.mb_depot_product_ids,
                         "a piece at the atelier cannot be sold by the gallery")

    def test_a_reserved_piece_is_no_longer_on_offer(self):
        """Unreserved rather than merely on hand: a unique piece offered twice
        is a piece that cannot be delivered twice.
        """
        self._wizard().action_create()
        depot = self._depot()
        self._place(self.held, 1, depot.lot_stock_id)

        order = self.env["sale.order"].create({"partner_id": self.gallery.id})
        self.assertIn(self.held, order.mb_depot_product_ids)

        outgoing = self.env["stock.move"].create({
            "product_id": self.held.id,
            "product_uom_qty": 1,
            "location_id": depot.lot_stock_id.id,
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
        self.assertFalse(order.warehouse_id.is_depot)
        self.assertFalse(order.mb_depot_product_ids,
                         "with no depot the line domain adds no clause at all")

    def test_availability_is_read_at_the_depot(self):
        """No override backs this any more.

        sale_stock reads its three quantities with the order's warehouse in the
        context, and the order's warehouse is the gallery - so the piece on the
        gallery's shelf is the piece the widget counts. This test passed under a
        patched _read_qties() before; it passes here on stock Odoo.
        """
        self._wizard().action_create()
        depot = self._depot()
        self._place(self.held, 2, depot.lot_stock_id)

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

        self.assertFalse(order.warehouse_id.is_depot)
        self.assertEqual(order.order_line.qty_available_today, 7,
                         "an order with no depot still reads the warehouse")
