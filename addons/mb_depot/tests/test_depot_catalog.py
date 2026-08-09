from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDepotCatalog(TransactionCase):
    """The catalog on a placement transfer. Odoo puts no catalog on a picking,
    so every hook it needs is ours and none of it is covered upstream.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        cls.gallery = cls.env["res.partner"].create({
            "name": "Galerie Catalog Test", "is_company": True})
        cls.env["mb.depot.create"].create({
            "partner_id": cls.gallery.id,
            "commission": 40.0,
        }).action_create()
        cls.depot_warehouse = cls.env["stock.warehouse"].search([
            ("is_depot", "=", True), ("depot_partner_id", "=", cls.gallery.id)])
        cls.depot = cls.depot_warehouse.lot_stock_id
        cls.bowl = cls.env["product.product"].create({
            "name": "Catalog bowl", "type": "consu", "is_storable": True,
            "list_price": 120.0, "standard_price": 30.0,
        })
        cls.service = cls.env["product.product"].create({
            "name": "Firing service", "type": "service", "list_price": 50.0,
        })
        # int_type_id rather than a search: the internal operation type is
        # deactivated while multi-location is off, so a plain search finds
        # nothing on a database where the wizard has only just switched it on.
        cls.internal_type = cls.warehouse.int_type_id

    def _placement(self):
        return self.env["stock.picking"].create({
            "picking_type_id": self.internal_type.id,
            "location_id": self.stock.id,
            "location_dest_id": self.depot.id,
        })

    def test_the_placement_is_recognised_as_one(self):
        self.assertTrue(self._placement().is_depot_placement,
                        "the Catalogue button hangs off this flag")

    def test_adding_a_piece_creates_the_move_between_the_right_locations(self):
        picking = self._placement()

        price = picking._update_order_line_info(self.bowl.id, 3)

        move = picking.move_ids
        self.assertEqual(len(move), 1)
        self.assertEqual(move.product_id, self.bowl)
        self.assertEqual(move.product_uom_qty, 3)
        self.assertEqual(move.location_id, self.stock)
        self.assertEqual(move.location_dest_id, self.depot,
                         "a piece added from the catalog still goes to the depot")
        self.assertEqual(price, 120.0,
                         "the catalog quotes prix public, which is what the bon "
                         "de dépôt and the statement value a placement at")

    def test_changing_a_quantity_moves_the_existing_line(self):
        picking = self._placement()
        picking._update_order_line_info(self.bowl.id, 3)

        picking._update_order_line_info(self.bowl.id, 5)

        self.assertEqual(len(picking.move_ids), 1, "no second line for one product")
        self.assertEqual(picking.move_ids.product_uom_qty, 5)

    def test_zeroing_a_quantity_removes_the_line(self):
        picking = self._placement()
        picking._update_order_line_info(self.bowl.id, 2)

        picking._update_order_line_info(self.bowl.id, 0)

        self.assertFalse(picking.move_ids)

    def test_the_catalog_reports_what_is_already_on_the_transfer(self):
        picking = self._placement()
        picking._update_order_line_info(self.bowl.id, 4)

        info = picking._get_product_catalog_order_line_info(
            [self.bowl.id], child_field="move_ids")

        self.assertEqual(info[self.bowl.id]["quantity"], 4)
        self.assertEqual(info[self.bowl.id]["price"], 120.0)

    def test_only_storable_products_are_offered(self):
        picking = self._placement()

        products = self.env["product.product"].search(
            picking._get_product_catalog_domain())

        self.assertIn(self.bowl, products)
        self.assertNotIn(self.service, products,
                         "a service cannot stand on a gallery shelf")

    def test_the_on_hand_badge_counts_the_source_location(self):
        picking = self._placement()

        context = picking._get_action_add_from_catalog_extra_context()

        self.assertTrue(context["display_stock"])
        self.assertEqual(context["location"], self.stock.id,
                         "on hand company-wide is the wrong question for a "
                         "placement: what matters is what can go in the van")

    def test_a_done_transfer_is_read_only_to_the_catalog(self):
        picking = self._placement()
        self.assertFalse(picking._is_readonly())
        picking.action_cancel()
        self.assertTrue(picking._is_readonly())
