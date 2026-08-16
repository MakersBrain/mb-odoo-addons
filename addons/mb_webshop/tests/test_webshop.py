import uuid
import re
from datetime import timedelta

from odoo import fields
from odoo.addons.website_sale.tests.common import MockRequest
from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged

from .. import post_init_hook
from ..models.ir_http import webshop_path_is_gated


@tagged("post_install", "-at_install")
class TestWebshopPack(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company.sudo()
        cls.website = cls.env["website"].sudo().search([
            ("company_id", "=", cls.company.id),
        ], limit=1)
        cls.workshop_id = str(uuid.uuid4())
        cls.company.mb_control_workshop_id = cls.workshop_id

    def test_shop_and_checkout_routes_are_gated_but_backend_is_not(self):
        self.assertTrue(webshop_path_is_gated("/shop"))
        self.assertTrue(webshop_path_is_gated("/shop/cart"))
        self.assertTrue(webshop_path_is_gated("/shop/payment/validate"))
        self.assertTrue(webshop_path_is_gated("/shop/<model('product.template'):product>"))
        self.assertFalse(webshop_path_is_gated("/"))
        self.assertFalse(webshop_path_is_gated("/odoo/settings"))
        self.assertFalse(webshop_path_is_gated("/my/orders"))

    def test_capability_restriction_and_enable_toggle_the_whole_storefront(self):
        payload = {
            "workshop_id": self.workshop_id,
            "module_key": "webshop",
            "modules": ["mb_webshop"],
            "reason": "entitlement_inactive",
        }

        restricted = self.company.mb_restrict_module_bundle(payload)
        replay = self.company.mb_restrict_module_bundle(payload)
        self.website.invalidate_recordset(["mb_webshop_enabled"])

        self.assertTrue(restricted["applied"])
        self.assertFalse(replay["applied"])
        self.assertEqual(restricted["adapter"], "odoo_storefront_gate")
        self.assertTrue(restricted["storefront_blocked"])
        self.assertTrue(restricted["checkout_blocked"])
        self.assertFalse(self.website.mb_webshop_enabled)
        policy = self.env["mb.control.capability.policy"].sudo().search([
            ("workshop_id", "=", self.workshop_id),
            ("module_key", "=", "webshop"),
        ])
        self.assertFalse(policy.rule_ids)

        enabled = self.company.mb_enable_module_bundle({
            "workshop_id": self.workshop_id,
            "module_key": "webshop",
            "modules": ["mb_webshop"],
        })
        self.website.invalidate_recordset(["mb_webshop_enabled"])

        self.assertTrue(enabled["restriction_removed"])
        self.assertTrue(self.website.mb_webshop_enabled)

    def test_native_editor_contains_all_three_craft_palettes_and_snippets(self):
        variables = self.env["ir.asset"]._get_asset_paths(
            "web._assets_primary_variables", {}
        )
        self.assertTrue(any(
            "mb_webshop/static/src/scss/primary_variables.scss" in asset[1]
            for asset in variables
        ))
        stylesheet_links = self.env["ir.qweb"]._generate_asset_links(
            "web.assets_frontend", css=True, js=False, debug_assets=False
        )
        self.assertTrue(stylesheet_links)
        snippets = self.env.ref("mb_webshop.snippets").arch_db
        self.assertIn("mb_webshop.s_maker_hero", snippets)
        self.assertIn("mb_webshop.s_material_story", snippets)

    def test_launch_readiness_uses_strict_native_configuration_evidence(self):
        self.env["product.template"].sudo().search([]).write({"is_published": False})
        self.env["payment.provider"].sudo().search([]).write({
            "is_published": False,
            "state": "disabled",
        })
        self.env["delivery.carrier"].sudo().search([]).write({"is_published": False})
        self.env["ir.mail_server"].sudo().search([]).write({"active": False})
        self.company.email = False
        self.website.domain = "http://localhost:8169"

        empty = self.website._mb_webshop_readiness()

        self.assertFalse(empty["catalog"])
        self.assertFalse(empty["online_payment"])
        self.assertFalse(empty["fulfilment"])
        self.assertFalse(empty["sender"])
        self.assertFalse(empty["domain"])
        self.assertFalse(empty["launch_ready"])

        product = self.env["product.template"].sudo().create({
            "name": "Published launch-readiness piece",
            "sale_ok": True,
            "is_published": True,
            "website_id": self.website.id,
            "company_id": self.company.id,
        })
        delivery_product = self.env["product.product"].sudo().create({
            "name": "Launch-readiness delivery",
            "type": "service",
            "sale_ok": True,
        })
        self.env["delivery.carrier"].sudo().create({
            "name": "Published fixed delivery",
            "delivery_type": "fixed",
            "product_id": delivery_product.id,
            "fixed_price": 5,
            "is_published": True,
            "website_id": self.website.id,
            "company_id": self.company.id,
        })
        self.company.email = "orders@makersbrain.fr"
        self.env["ir.mail_server"].sudo().create({
            "name": "Qualified SMTP",
            "smtp_host": "smtp.makersbrain.fr",
            "active": True,
        })
        self.website.domain = "https://shop.makersbrain.fr"

        configured = self.website._mb_webshop_readiness()

        self.assertEqual(configured["product_count"], 1)
        self.assertEqual(product.website_id, self.website)
        self.assertTrue(configured["catalog"])
        self.assertTrue(configured["fulfilment"])
        self.assertTrue(configured["sender"])
        self.assertTrue(configured["domain"])
        self.assertTrue(configured["returns"])
        self.assertFalse(configured["online_payment"])
        self.assertFalse(configured["launch_ready"])

        # The native click-and-collect fallback confirms orders for payment at
        # pickup. It must never satisfy the production online-payment check.
        on_site = self.env.ref(
            "website_sale_collect.payment_provider_on_site"
        ).sudo()
        on_site.write({
            "state": "enabled",
            "is_published": True,
            "website_id": self.website.id,
            "company_id": self.company.id,
        })
        offline_only = self.website._mb_webshop_readiness()
        self.assertEqual(offline_only["payment_count"], 0)
        self.assertFalse(offline_only["online_payment"])
        self.assertFalse(offline_only["launch_ready"])

    def test_public_store_url_check_rejects_placeholder_and_private_hosts(self):
        rejected = (
            "localhost",
            "http://127.0.0.1:8169",
            "shop.local",
            "shop.example.com",
            "shop.makersbrain.test",
        )
        for domain in rejected:
            self.website.domain = domain
            self.assertFalse(self.website._mb_has_public_domain(), domain)
        self.website.domain = "https://shop.makersbrain.fr"
        self.assertTrue(self.website._mb_has_public_domain())

    def test_platform_hostname_projects_on_install_without_replacing_custom_domain(self):
        self.company.mb_control_public_hostname = "atelier.makersbrain.fr"
        self.website.domain = False

        post_init_hook(self.env)

        self.assertEqual(self.website.domain, "https://atelier.makersbrain.fr")
        self.website.domain = "shop.artisan.fr"
        post_init_hook(self.env)
        self.assertEqual(self.website.domain, "https://shop.artisan.fr")

    def test_launch_readiness_links_open_native_odoo_operations(self):
        settings = self.env["res.config.settings"].create({
            "website_id": self.website.id,
        })
        expectations = {
            "action_mb_open_products": "product.template",
            "action_mb_open_payment_providers": "payment.provider",
            "action_mb_open_delivery_methods": "delivery.carrier",
            "action_mb_open_mail_servers": "ir.mail_server",
        }
        for method, model in expectations.items():
            self.assertEqual(getattr(settings, method)()["res_model"], model)

    def _one_piece_product(self, quantity=1):
        product = self.env["product.product"].sudo().create({
            "name": "One-off test piece",
            "is_storable": True,
            "allow_out_of_stock_order": False,
            "list_price": 80,
        })
        warehouse = self.website.warehouse_id or self.env["stock.warehouse"].search([
            ("company_id", "=", self.company.id),
        ], limit=1)
        self.website.warehouse_id = warehouse
        self.env["stock.quant"].sudo()._update_available_quantity(
            product, warehouse.lot_stock_id, quantity
        )
        return product, warehouse

    def _cart(self):
        return self.env["sale.order"].sudo().create({
            "partner_id": self.website.user_id.partner_id.id,
            "website_id": self.website.id,
            "company_id": self.company.id,
        })

    def _delivered_order(self, quantity=2):
        product, warehouse = self._one_piece_product(quantity)
        order = self._cart()
        with MockRequest(self.env, website=self.website, sale_order_id=order.id):
            order._cart_add(product.id, quantity)
        order.action_confirm()
        delivery = order.picking_ids.filtered(
            lambda picking: picking.picking_type_code == "outgoing"
        )
        self.assertEqual(len(delivery), 1)
        delivery.button_validate()
        self.assertEqual(delivery.state, "done")
        return order, product, warehouse, delivery

    def test_cart_hold_is_a_real_stock_reservation_shared_with_pos(self):
        product, warehouse = self._one_piece_product()
        cart = self._cart()

        with MockRequest(self.env, website=self.website, sale_order_id=cart.id):
            result = cart._cart_add(product.id, 1)

        hold = self.env["mb.webshop.stock.hold"].sudo().search([
            ("order_id", "=", cart.id), ("product_id", "=", product.id)
        ])
        self.assertEqual(result["quantity"], 1)
        self.assertEqual(hold.state, "active")
        self.assertEqual(hold.move_id.state, "assigned")
        self.assertEqual(hold.move_id.quantity, 1)
        self.assertEqual(product.with_context(warehouse_id=warehouse.id).free_qty, 0)

        # POS and every other stock channel see the same reserved quant; this
        # is not merely a row in a private webshop table.
        competing_move = self.env["stock.move"].sudo().create({
            "product_id": product.id,
            "product_uom_qty": 1,
            "product_uom": product.uom_id.id,
            "location_id": warehouse.lot_stock_id.id,
            "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            "company_id": self.company.id,
            "procure_method": "make_to_stock",
        })
        competing_move._action_confirm(merge=False)
        competing_move._action_assign()
        self.assertNotEqual(competing_move.state, "assigned")
        self.assertEqual(competing_move.quantity, 0)

    def test_second_cart_cannot_hold_the_last_piece_and_release_makes_it_available(self):
        product, warehouse = self._one_piece_product()
        first_cart = self._cart()
        second_cart = self._cart()

        with MockRequest(self.env, website=self.website, sale_order_id=first_cart.id):
            first_cart._cart_add(product.id, 1)
        with MockRequest(self.env, website=self.website, sale_order_id=second_cart.id):
            second = second_cart._cart_add(product.id, 1)

        self.assertEqual(second["quantity"], 0)
        self.assertTrue(second["warning"])
        self.assertFalse(second_cart.order_line)

        with MockRequest(self.env, website=self.website, sale_order_id=first_cart.id):
            first_cart._cart_update_line_quantity(first_cart.order_line.id, 0)
        self.assertEqual(product.with_context(warehouse_id=warehouse.id).free_qty, 1)

        with MockRequest(self.env, website=self.website, sale_order_id=second_cart.id):
            retried = second_cart._cart_add(product.id, 1)
        self.assertEqual(retried["quantity"], 1)

    def test_expired_hold_releases_quant_and_is_reacquired_before_payment(self):
        product, warehouse = self._one_piece_product()
        cart = self._cart()
        with MockRequest(self.env, website=self.website, sale_order_id=cart.id):
            cart._cart_add(product.id, 1)
        hold = self.env["mb.webshop.stock.hold"].sudo().search([
            ("order_id", "=", cart.id), ("product_id", "=", product.id)
        ])
        hold.expires_at = fields.Datetime.now() - timedelta(seconds=1)

        expired = hold._expire_due()

        self.assertEqual(expired, 1)
        self.assertEqual(hold.state, "expired")
        self.assertEqual(hold.move_id.state, "cancel")
        self.assertEqual(product.with_context(warehouse_id=warehouse.id).free_qty, 1)
        cart._mb_sync_stock_hold(product)
        self.assertEqual(hold.state, "active")
        self.assertEqual(hold.move_id.state, "assigned")

    def test_confirmation_converts_hold_to_native_sale_reservation(self):
        product, warehouse = self._one_piece_product()
        cart = self._cart()
        with MockRequest(self.env, website=self.website, sale_order_id=cart.id):
            cart._cart_add(product.id, 1)
        hold = self.env["mb.webshop.stock.hold"].sudo().search([
            ("order_id", "=", cart.id), ("product_id", "=", product.id)
        ])

        cart.action_confirm()

        self.assertEqual(cart.state, "sale")
        self.assertEqual(hold.state, "converted")
        self.assertEqual(hold.move_id.state, "cancel")
        sale_moves = cart.order_line.move_ids.filtered(
            lambda move: move.product_id == product and move.state != "cancel"
        )
        self.assertTrue(sale_moves)
        self.assertEqual(sum(sale_moves.mapped("quantity")), 1)
        self.assertEqual(product.with_context(warehouse_id=warehouse.id).free_qty, 0)

    def test_late_confirmation_cannot_oversell_after_hold_expiry(self):
        product, _warehouse = self._one_piece_product()
        late_cart = self._cart()
        winning_cart = self._cart()
        with MockRequest(self.env, website=self.website, sale_order_id=late_cart.id):
            late_cart._cart_add(product.id, 1)
        late_hold = self.env["mb.webshop.stock.hold"].sudo().search([
            ("order_id", "=", late_cart.id), ("product_id", "=", product.id)
        ])
        late_hold.expires_at = fields.Datetime.now() - timedelta(seconds=1)
        late_hold._expire_due()
        with MockRequest(self.env, website=self.website, sale_order_id=winning_cart.id):
            winning_cart._cart_add(product.id, 1)

        with self.assertRaises(ValidationError):
            late_cart.action_confirm()

        self.assertEqual(late_cart.state, "draft")
        self.assertEqual(winning_cart.order_line.product_uom_qty, 1)

    def test_return_request_uses_delivered_quantity_and_prevents_duplicates(self):
        order, _product, _warehouse, _delivery = self._delivered_order(2)
        order.partner_id.email = "return-customer@example.com"
        line = order.order_line.filtered(lambda candidate: not candidate.is_delivery)
        mail_count = self.env["mail.mail"].sudo().search_count([])

        first = self.env["mb.webshop.return"].sudo().create_from_portal(
            order, {line.id: 1}, "The glaze is not what I expected."
        )

        self.assertEqual(first.state, "requested")
        self.assertEqual(first.line_ids.quantity, 1)
        self.assertEqual(order._mb_returnable_quantity(line), 1)
        self.assertEqual(
            self.env["mail.mail"].sudo().search_count([]), mail_count + 1
        )
        with self.assertRaises(ValidationError):
            self.env["mb.webshop.return"].sudo().create_from_portal(
                order, {line.id: 2}, "Trying to return too many."
            )

        with self.assertRaises(ValidationError):
            first.action_reject()
        first.decision_note = "Customer kept the piece after care advice."
        first.action_reject()
        self.assertEqual(order._mb_returnable_quantity(line), 2)

    def test_return_line_cannot_reference_another_order(self):
        order, _product, _warehouse, _delivery = self._delivered_order(1)
        other_order = self._cart()
        return_request = self.env["mb.webshop.return"].sudo().create({
            "order_id": other_order.id,
            "reason": "Invalid ownership test",
        })

        with self.assertRaises(ValidationError):
            self.env["mb.webshop.return.line"].sudo().create({
                "return_id": return_request.id,
                "order_line_id": order.order_line.id,
                "quantity": 1,
            })

    def test_return_approval_receipt_and_replacement_use_native_documents(self):
        order, product, warehouse, delivery = self._delivered_order(2)
        line = order.order_line.filtered(lambda candidate: not candidate.is_delivery)
        return_request = self.env["mb.webshop.return"].sudo().create_from_portal(
            order, {line.id: 1}, "One item arrived damaged."
        )

        return_request.action_approve()

        self.assertEqual(return_request.state, "approved")
        self.assertEqual(len(return_request.return_picking_ids), 1)
        return_picking = return_request.return_picking_ids
        self.assertEqual(return_picking.origin, return_request.name)
        self.assertEqual(return_picking.return_id, delivery)
        self.assertEqual(return_picking.move_ids.origin_returned_move_id.picking_id, delivery)
        self.assertEqual(return_picking.move_ids.quantity, 1)

        return_picking.button_validate()
        return_request.action_mark_received()
        self.assertEqual(return_request.state, "received")
        self.assertEqual(
            product.with_context(warehouse_id=warehouse.id).free_qty, 1
        )

        return_request.resolution = "replacement"
        return_request.action_create_replacement()
        replacement = return_request.replacement_order_id
        self.assertEqual(replacement.state, "draft")
        self.assertFalse(replacement.website_id)
        self.assertEqual(replacement.order_line.product_uom_qty, 1)
        return_request.action_resolve()
        self.assertEqual(return_request.state, "resolved")

    def test_return_window_and_refund_resolution_are_enforced(self):
        order, _product, _warehouse, _delivery = self._delivered_order(1)
        line = order.order_line.filtered(lambda candidate: not candidate.is_delivery)
        invoice = order._create_invoices()
        invoice.action_post()
        return_request = self.env["mb.webshop.return"].sudo().create_from_portal(
            order, {line.id: 1}, "Changed my mind."
        )
        return_request.action_approve()
        return_request.return_picking_ids.button_validate()
        return_request.action_mark_received()
        return_request.resolution = "refund"
        with self.assertRaises(ValidationError):
            return_request.action_resolve()

        reversal_action = return_request.action_open_credit_note()
        reversal = self.env["account.move.reversal"].with_context(
            **reversal_action["context"]
        ).create({"reason": return_request.name})
        reversal.refund_moves()
        reversal.new_move_ids.action_post()
        return_request.invalidate_recordset(["refund_move_ids"])
        self.assertEqual(return_request.refund_move_ids.reversed_entry_id, invoice)
        return_request.action_resolve()
        self.assertEqual(return_request.state, "resolved")

        old_order, _product, _warehouse, old_delivery = self._delivered_order(1)
        old_delivery.date_done = fields.Datetime.now() - timedelta(
            days=self.website.mb_return_window_days + 1
        )
        self.assertFalse(old_order._mb_returnable_lines())


@tagged("post_install", "-at_install")
class TestWebshopReturnPortal(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env["website"].search([], limit=1)
        cls.website.mb_webshop_enabled = True
        warehouse = cls.website.warehouse_id or cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.website.warehouse_id = warehouse
        partner = cls.env["res.partner"].create({
            "name": "Portal Return Customer",
            "email": "portal-return@example.com",
        })
        product = cls.env["product.product"].create({
            "name": "Portal return piece",
            "is_storable": True,
            "allow_out_of_stock_order": False,
            "list_price": 50,
        })
        cls.env["stock.quant"]._update_available_quantity(
            product, warehouse.lot_stock_id, 1
        )
        cls.order = cls.env["sale.order"].create({
            "partner_id": partner.id,
            "website_id": cls.website.id,
            "warehouse_id": warehouse.id,
            "order_line": [fields.Command.create({
                "product_id": product.id,
                "product_uom_qty": 1,
            })],
        })
        cls.order.action_confirm()
        cls.order.picking_ids.button_validate()
        cls.line = cls.order.order_line.filtered(
            lambda candidate: not candidate.is_delivery
        )

    def test_anonymous_access_token_can_render_and_submit_return(self):
        url = self.order.get_portal_url(suffix="/return")
        response = self.url_open(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Request a return", response.text)
        self.assertIn("Portal return piece", response.text)
        csrf_match = re.search(
            r'name="csrf_token"[^>]*value="([^"]+)"', response.text
        )
        self.assertTrue(csrf_match)

        response = self.url_open(
            url,
            data={
                "csrf_token": csrf_match.group(1),
                f"line_{self.line.id}": "1",
                "reason": "Portal journey return",
            },
            allow_redirects=False,
        )

        self.assertIn(response.status_code, (302, 303))
        self.env.invalidate_all()
        return_request = self.env["mb.webshop.return"].search([
            ("order_id", "=", self.order.id),
        ])
        self.assertEqual(len(return_request), 1)
        self.assertEqual(return_request.reason, "Portal journey return")
