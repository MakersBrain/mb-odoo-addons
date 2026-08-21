from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCeramicsWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock = cls.env.ref("stock.stock_location_stock")
        cls.damp = cls.env["stock.location"].create({
            "name": "Damp box",
            "location_id": cls.stock.id,
        })
        cls.finished = cls.env["stock.location"].create({
            "name": "Finished ceramics",
            "location_id": cls.stock.id,
        })
        cls.bisque_stock = cls.env["stock.location"].create({
            "name": "Bisque stock",
            "location_id": cls.stock.id,
        })
        cls.seconds = cls.env["stock.location"].create({
            "name": "Ceramics seconds",
            "location_id": cls.stock.id,
        })
        cls.costing_available = "property_cost_method" in cls.env[
            "product.category"
        ]._fields
        cls.ceramics_cost_category = False
        cls.glaze_cost_category = cls.env.ref("mb_ceramics_base.categ_glaze")
        if cls.costing_available:
            cls.ceramics_cost_category = cls.env["product.category"].create({
                "name": "Ceramics FIFO test",
                "property_cost_method": "fifo",
                "property_valuation": "periodic",
            })
            cls.glaze_cost_category = cls.env["product.category"].create({
                "name": "Glaze FIFO test",
                "parent_id": cls.env.ref("mb_ceramics_base.categ_glaze").id,
                "property_cost_method": "fifo",
                "property_valuation": "periodic",
            })
        cls.clay = cls._product("Clay", tracking="lot")
        cls.blank = cls._product("Small box blank", tracking="lot")
        cls.article = cls._product("Small decorated box", tracking="serial")
        cls.second = cls._product("Small decorated box - second", tracking="serial")
        cls.article.product_tmpl_id.mb_second_product_tmpl_id = (
            cls.second.product_tmpl_id
        )
        cls.blank.product_tmpl_id.mb_ceramics_stage = "green"
        cls.bisque_product = cls._product("Small box bisque", tracking="lot")
        cls.bisque_product.product_tmpl_id.mb_ceramics_stage = "bisque"
        cls.article.product_tmpl_id.mb_ceramics_stage = "finished"
        cls.glaze = cls._product("AMACO PC test glaze", tracking="lot")
        cls.glaze.categ_id = cls.glaze_cost_category
        cls.glaze_additive = cls._product("Glaze additive")
        cls.glaze_water = cls._product("Glaze water")
        if cls.ceramics_cost_category:
            (cls.clay | cls.blank | cls.bisque_product | cls.article | cls.second
             | cls.glaze_additive | cls.glaze_water).categ_id = cls.ceramics_cost_category
        cls.clay.standard_price = 2
        cls.glaze.standard_price = 4
        cls.glaze_additive.standard_price = 1
        cls.glaze_lot_a = cls.env["stock.lot"].create({
            "name": "AMACO-PC-A",
            "product_id": cls.glaze.id,
            "company_id": cls.env.company.id,
        })
        cls.glaze_lot_b = cls.env["stock.lot"].create({
            "name": "AMACO-PC-B",
            "product_id": cls.glaze.id,
            "company_id": cls.env.company.id,
        })
        cls.env["stock.quant"]._update_available_quantity(
            cls.glaze, cls.stock, 10, lot_id=cls.glaze_lot_a
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.glaze, cls.stock, 10, lot_id=cls.glaze_lot_b
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.glaze_additive, cls.stock, 10
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.glaze_water, cls.stock, 10
        )
        cls.glaze_recipe = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.glaze.product_tmpl_id.id,
            "product_qty": 1,
            "mb_is_glaze_recipe": True,
            "bom_line_ids": [
                Command.create({
                    "product_id": cls.glaze_additive.id,
                    "mb_quantity_mode": "dry_percent",
                    "mb_formula_percent": 100,
                }),
                Command.create({
                    "product_id": cls.glaze_water.id,
                    "mb_quantity_mode": "water_percent",
                    "mb_formula_percent": 50,
                }),
            ],
        })
        cls.glaze_recipe.action_mb_approve_recipe()
        (cls.glaze_lot_a | cls.glaze_lot_b).mb_bom_revision_id = cls.glaze_recipe
        cls.clay_lot = cls.env["stock.lot"].create({
            "name": "CLAY-2026-08",
            "product_id": cls.clay.id,
            "company_id": cls.env.company.id,
        })
        cls.env["stock.quant"]._update_available_quantity(
            cls.clay, cls.stock, 100, lot_id=cls.clay_lot
        )
        cls.board_type = cls.env.ref(
            "mb_ceramics_workflow.mb_package_type_ware_board"
        )
        cls.board = cls.env["stock.package"].create({
            "name": "BOARD-01",
            "package_type_id": cls.board_type.id,
            "company_id": cls.env.company.id,
        })
        cls.throw_bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.blank.product_tmpl_id.id,
            "product_qty": 1,
            "bom_line_ids": [Command.create({
                "product_id": cls.clay.id,
                "product_qty": 1,
            })],
        })
        cls.kiln = cls.env["mb.kiln"].create({
            "name": "Test kiln",
            "max_temperature": 1300,
            "pieces_per_load": 40,
        })
        cls.bisque_program = cls.env["mb.kiln.program"].create({
            "name": "Bisque 980",
            "kiln_id": cls.kiln.id,
            "kind": "bisque",
            "peak_temperature": 980,
            "firing_hours": 1,
            "cooling_hours": 1,
        })
        cls.glaze_program = cls.env["mb.kiln.program"].create({
            "name": "Glaze 1220",
            "kiln_id": cls.kiln.id,
            "kind": "glaze",
            "peak_temperature": 1220,
            "firing_hours": 1,
            "cooling_hours": 1,
        })
        cls.bisque_bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.bisque_product.product_tmpl_id.id,
            "product_qty": 1,
            "allow_operation_dependencies": True,
            "bom_line_ids": [Command.create({
                "product_id": cls.blank.id,
                "product_qty": 1,
            })],
        })
        cls.bisque_prepare_op = cls._operation(
            "Decorate green ware",
            cls.env.ref("mb_ceramics_base.mb_workcenter_decorating"),
            bom=cls.bisque_bom,
        )
        cls.bisque_dry_op = cls._operation(
            "Dry green ware",
            cls.env.ref("mb_ceramics_base.mb_workcenter_drying"),
            cls.bisque_prepare_op,
            bom=cls.bisque_bom,
        )
        cls.bisque_only_fire_op = cls._operation(
            "Bisque firing",
            cls.kiln.workcenter_id,
            cls.bisque_dry_op,
            cls.bisque_program,
            bom=cls.bisque_bom,
        )
        cls.glazing_bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.article.product_tmpl_id.id,
            "product_qty": 1,
            "allow_operation_dependencies": True,
            "bom_line_ids": [
                Command.create({
                    "product_id": cls.bisque_product.id,
                    "product_qty": 1,
                }),
                Command.create({
                    "product_id": cls.glaze.id,
                    "product_qty": 0.5,
                }),
                Command.create({
                    "product_id": cls.glaze_additive.id,
                    "product_qty": 0.1,
                }),
            ],
        })
        cls.glazing_apply_op = cls._operation(
            "Apply glaze",
            cls.env.ref("mb_ceramics_base.mb_workcenter_glazing"),
            bom=cls.glazing_bom,
        )
        cls.glazing_fire_op = cls._operation(
            "Glaze firing",
            cls.kiln.workcenter_id,
            cls.glazing_apply_op,
            cls.glaze_program,
            bom=cls.glazing_bom,
        )
        cls.glazing_inspect_op = cls._operation(
            "Final inspection",
            cls.env.ref("mb_ceramics_base.mb_workcenter_decorating"),
            cls.glazing_fire_op,
            bom=cls.glazing_bom,
        )

    @classmethod
    def _product(cls, name, tracking="none"):
        return cls.env["product.product"].create({
            "name": name,
            "is_storable": True,
            "tracking": tracking,
        })

    @classmethod
    def _operation(cls, name, workcenter, previous=False, program=False, bom=False):
        values = {
            "name": name,
            "bom_id": bom.id,
            "workcenter_id": workcenter.id,
            "time_cycle_manual": 10,
        }
        if previous:
            values["blocked_by_operation_ids"] = [Command.link(previous.id)]
        if program:
            values["mb_kiln_program_id"] = program.id
        return cls.env["mrp.routing.workcenter"].create(values)

    def _throw(self, quantity=10):
        session = self.env["mb.throwing.session"].create({
            "clay_product_id": self.clay.id,
            "clay_lot_id": self.clay_lot.id,
            "source_location_id": self.stock.id,
            "damp_location_id": self.damp.id,
            "line_ids": [Command.create({
                "blank_product_id": self.blank.id,
                "quantity": quantity,
                "clay_quantity": quantity,
                "bom_id": self.throw_bom.id,
            })],
        })
        session.action_confirm()
        return session

    def _start_bisque(self, blank_lot, quantity=4):
        session = self.env["mb.bisque.session"].create({
            "board_id": self.board.id,
            "source_location_id": self.damp.id,
            "bisque_location_id": self.bisque_stock.id,
            "line_ids": [Command.create({
                "green_product_id": self.blank.id,
                "green_lot_id": blank_lot.id,
                "quantity": quantity,
                "bisque_product_id": self.bisque_product.id,
                "bom_id": self.bisque_bom.id,
            })],
        })
        session.action_start()
        return session, session.production_ids

    def _produce_bisque(self, quantity=4, accepted=None, loss=0):
        accepted = quantity - loss if accepted is None else accepted
        throwing = self._throw(quantity)
        session, production = self._start_bisque(
            throwing.line_ids.blank_lot_id, quantity
        )
        self._finish_until(production, self.bisque_only_fire_op)
        firing = self._fire_board(
            production, self.bisque_only_fire_op, self.bisque_program
        )
        wizard = self.env["mb.bisque.inspection"].create({
            "production_id": production.id,
            "accepted_quantity": accepted,
            "loss_quantity": loss,
            "loss_reason": "Cracked during bisque" if loss else False,
            "loss_operation_id": production.workorder_ids.filtered(
                lambda order: order.operation_id == self.bisque_only_fire_op
            ).id,
        })
        action = wizard.action_confirm()
        return session, production, production.lot_producing_ids, firing, action

    def _finish_until(self, production, target_operation):
        for workorder in production.workorder_ids:
            if workorder.operation_id == target_operation:
                return workorder
            if workorder.state not in ("done", "cancel"):
                workorder.button_finish()
        self.fail("Target operation was not found")

    def _fire_board(self, production, operation, program):
        workorder = production.workorder_ids.filtered(
            lambda order: order.operation_id == operation
        )
        self.assertEqual(workorder.state, "ready")
        firing = self.env["mb.firing"].create({
            "kiln_id": self.kiln.id,
            "program_id": program.id,
            "kind": program.kind,
            "state": "draft",
        })
        loader = self.env["mb.firing.load"].create({
            "firing_id": firing.id,
            "board_ids": [Command.link(self.board.id)],
        })
        loader.action_load()
        self.assertEqual(workorder.mb_firing_id, firing)
        firing.action_start()
        firing.action_finish()
        firing.cooling_end = fields.Datetime.now() - timedelta(minutes=1)
        firing.action_unload()
        firing.action_unload()
        self.assertEqual(workorder.state, "done")
        return firing

    def test_bisque_board_split_retains_workflow_session(self):
        throwing = self._throw(4)
        session, production = self._start_bisque(
            throwing.line_ids.blank_lot_id, 4
        )
        first_content = production.mb_board_content_ids
        first_content.quantity = 2
        second_board = self.env["stock.package"].create({
            "name": "BOARD-BISQUE-SPLIT",
            "package_type_id": self.board_type.id,
            "company_id": self.env.company.id,
        })
        deferred_content = self.env["mb.board.content"].create({
            "board_id": second_board.id,
            "production_id": production.id,
            "quantity": 2,
            "current_workorder_id": first_content.current_workorder_id.id,
        })
        deferred = deferred_content.action_split_for_later()
        self.assertEqual(deferred.mb_workflow_kind, "bisque")
        self.assertEqual(deferred.mb_bisque_session_id, session)
        self.assertIn(deferred, session.production_ids)

    def test_firing_rejects_wrong_program(self):
        throwing = self._throw(2)
        _session, production = self._start_bisque(
            throwing.line_ids.blank_lot_id, 2
        )
        workorder = self._finish_until(production, self.bisque_only_fire_op)
        wrong = self.env["mb.firing"].create({
            "kiln_id": self.kiln.id,
            "program_id": self.glaze_program.id,
            "kind": "glaze",
            "state": "draft",
        })
        with self.assertRaises(ValidationError):
            workorder.mb_assign_firing(wrong)

    def test_loss_records_are_immutable(self):
        production = self.env["mrp.production"].create({
            "product_id": self.bisque_product.id,
            "product_qty": 1,
            "product_uom_id": self.bisque_product.uom_id.id,
            "bom_id": self.bisque_bom.id,
            "mb_workflow_kind": "bisque",
        })
        loss = self.env["mb.production.loss"].create({
            "production_id": production.id,
            "quantity": 1,
            "reason": "Test loss",
        })
        with self.assertRaises(UserError):
            loss.write({"reason": "Changed"})
        with self.assertRaises(UserError):
            loss.unlink()

    def test_food_contact_release_requires_tested_glaze_lot(self):
        self.article.product_tmpl_id.mb_food_contact = True
        _bisque_session, _bisque_mo, bisque_lot, _firing, _action = (
            self._produce_bisque(quantity=2)
        )
        glazing = self.env["mb.glazing.session"].create({
            "board_id": self.board.id,
            "source_location_id": self.bisque_stock.id,
            "material_location_id": self.stock.id,
            "finished_location_id": self.finished.id,
            "line_ids": [Command.create({
                "bisque_product_id": self.bisque_product.id,
                "bisque_lot_id": bisque_lot.id,
                "quantity": 2,
                "finished_product_id": self.article.id,
                "bom_id": self.glazing_bom.id,
                "allocation_ids": [Command.create({
                    "product_id": self.glaze.id,
                    "lot_id": self.glaze_lot_a.id,
                    "quantity": 1,
                    "uom_id": self.glaze.uom_id.id,
                })],
            })],
        })
        glazing.action_start()
        production = glazing.production_ids
        self._finish_until(production, self.glazing_fire_op)
        self._fire_board(production, self.glazing_fire_op, self.glaze_program)
        values = {
            "production_id": production.id,
            "accepted_quantity": 2,
            "loss_operation_id": production.workorder_ids.filtered(
                lambda order: order.operation_id == self.glazing_inspect_op
            ).id,
        }
        with self.env.cr.savepoint(), self.assertRaises(UserError):
            self.env["mb.inspection"].create(values).action_confirm()
        self.env["mb.migration.test"].create({
            "lot_id": self.glaze_lot_a.id,
            "migration_limit_class": "cat2",
            "passed": True,
        })
        self.env["mb.inspection"].create(values).action_confirm()
        self.assertEqual(production.state, "done")
        self.assertEqual(
            production.lot_producing_ids.mb_glaze_lot_ids,
            self.glaze_lot_a,
        )

    def test_bisque_stock_boundary_and_wip_label(self):
        throwing = self._throw(10)
        blank_lot = throwing.line_ids.blank_lot_id
        session, production = self._start_bisque(blank_lot, 4)
        self.assertEqual(session.state, "progress")
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.blank, self.damp, lot_id=blank_lot, strict=True
            ),
            6,
        )
        self._finish_until(production, self.bisque_only_fire_op)
        firing = self._fire_board(
            production, self.bisque_only_fire_op, self.bisque_program
        )
        wizard = self.env["mb.bisque.inspection"].create({
            "production_id": production.id,
            "accepted_quantity": 3,
            "loss_quantity": 1,
            "loss_reason": "One cracked while cooling",
            "loss_operation_id": production.workorder_ids.filtered(
                lambda order: order.operation_id == self.bisque_only_fire_op
            ).id,
        })
        action = wizard.action_confirm()
        bisque_lot = production.lot_producing_ids
        self.assertEqual(action["res_model"], "mb.label.print.wizard")
        self.assertEqual(action["context"]["default_manual_values_json"], {
            "stage": "BISQUE",
            "quantity": "3.0",
        })
        self.assertEqual(session.state, "done")
        self.assertTrue(production.mb_bisque_inspected)
        self.assertEqual(production.mb_loss_ids.quantity, 1)
        self.assertEqual(production.mb_loss_ids.firing_id, firing)
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.bisque_product,
                self.bisque_stock,
                lot_id=bisque_lot,
                strict=True,
            ),
            3,
        )
        self.assertIn(self.clay_lot, bisque_lot.mb_related_lot_ids)
        self.assertIn(blank_lot, bisque_lot.mb_related_lot_ids)

    def test_total_bisque_loss_is_completed_then_scrapped(self):
        session, production, lots, _firing, action = self._produce_bisque(
            quantity=2, accepted=0, loss=2
        )
        self.assertEqual(session.state, "done")
        self.assertEqual(production.state, "done")
        self.assertTrue(lots)
        scrap = self.env["stock.scrap"].search([
            ("origin", "=", production.name),
            ("product_id", "=", self.bisque_product.id),
        ])
        self.assertEqual(scrap.state, "done")
        self.assertEqual(scrap.scrap_qty, 2)
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.bisque_product,
                self.bisque_stock,
                lot_id=lots,
                strict=True,
            ),
            0,
        )
        self.assertEqual(action["type"], "ir.actions.act_window_close")

    def test_recorded_throwing_session_and_lines_are_immutable(self):
        session = self._throw(2)

        with self.assertRaises(UserError):
            session.write({"note": "rewritten evidence"})
        with self.assertRaises(UserError):
            session.line_ids.write({"quantity": 3})

    def test_shared_firing_charges_one_physical_duration(self):
        throwing = self._throw(4)
        first_session, first = self._start_bisque(
            throwing.line_ids.blank_lot_id, 1)
        second_session, second = self._start_bisque(
            throwing.line_ids.blank_lot_id, 1)
        self._finish_until(first, self.bisque_only_fire_op)
        self._finish_until(second, self.bisque_only_fire_op)
        workorders = (
            first.workorder_ids | second.workorder_ids
        ).filtered(lambda order: order.operation_id == self.bisque_only_fire_op)
        # The MOs remain marked as planned after their earlier work orders
        # finish, so the public MO planning button correctly becomes a no-op.
        # Replan the two ready kiln operations to model existing independent
        # reservations before they are joined into one physical firing.
        for workorder in workorders:
            workorder._plan_workorder(replan=True)
        self.assertEqual(len(workorders.mapped("leave_id")), 2)
        firing = self.env["mb.firing"].create({
            "kiln_id": self.kiln.id,
            "program_id": self.bisque_program.id,
            "kind": "bisque",
            "state": "draft",
        })

        self.env["mb.firing.load"].create({
            "firing_id": firing.id,
            "workorder_ids": [Command.set(workorders.ids)],
        }).action_load()

        self.assertEqual(
            sum(workorders.mapped("duration_expected")),
            self.bisque_program._occupied_minutes(True),
        )
        self.assertEqual(
            len(workorders.filtered(lambda order: order.duration_expected)), 1)
        self.assertEqual(len(workorders.mapped("leave_id")), 1)
        reservation = workorders.mapped("leave_id")
        self.assertEqual(
            (reservation.date_to - reservation.date_from).total_seconds() / 60,
            self.bisque_program._occupied_minutes(True),
        )
        self.assertEqual(first_session.state, "progress")
        self.assertEqual(second_session.state, "progress")

    def test_glazing_reserves_exact_multiple_glaze_lots(self):
        _bisque_session, bisque_mo, bisque_lot, _firing, _action = (
            self._produce_bisque(quantity=4)
        )
        session = self.env["mb.glazing.session"].create({
            "board_id": self.board.id,
            "source_location_id": self.bisque_stock.id,
            "material_location_id": self.stock.id,
            "finished_location_id": self.finished.id,
            "line_ids": [Command.create({
                "bisque_product_id": self.bisque_product.id,
                "bisque_lot_id": bisque_lot.id,
                "quantity": 4,
                "finished_product_id": self.article.id,
                "bom_id": self.glazing_bom.id,
                "allocation_ids": [
                    Command.create({
                        "product_id": self.glaze.id,
                        "lot_id": self.glaze_lot_a.id,
                        "quantity": 1,
                        "uom_id": self.glaze.uom_id.id,
                    }),
                    Command.create({
                        "product_id": self.glaze.id,
                        "lot_id": self.glaze_lot_b.id,
                        "quantity": 1,
                        "uom_id": self.glaze.uom_id.id,
                    }),
                ],
            })],
        })
        session.action_start()
        production = session.production_ids
        glaze_move = production.move_raw_ids.filtered(
            lambda move: move.product_id == self.glaze
        )
        self.assertEqual(set(glaze_move.move_line_ids.lot_id.ids), {
            self.glaze_lot_a.id,
            self.glaze_lot_b.id,
        })
        self.assertEqual(sum(glaze_move.move_line_ids.mapped("quantity")), 2)
        additive_move = production.move_raw_ids.filtered(
            lambda move: move.product_id == self.glaze_additive
        )
        self.assertEqual(additive_move.location_id, self.stock)
        self.assertEqual(sum(additive_move.move_line_ids.mapped("quantity")), 0.4)
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.bisque_product,
                self.bisque_stock,
                lot_id=bisque_lot,
                strict=True,
            ),
            0,
        )
        self._finish_until(production, self.glazing_fire_op)
        glaze_firing = self._fire_board(
            production, self.glazing_fire_op, self.glaze_program
        )
        self.env["mb.inspection"].create({
            "production_id": production.id,
            "accepted_quantity": 4,
            "loss_operation_id": production.workorder_ids.filtered(
                lambda order: order.operation_id == self.glazing_inspect_op
            ).id,
        }).action_confirm()
        self.assertEqual(session.state, "done")
        self.assertEqual(production.state, "done")
        if self.costing_available:
            bisque_output = bisque_mo.move_finished_ids.filtered(
                lambda move: move.product_id == self.bisque_product
            )
            finished_output = production.move_finished_ids.filtered(
                lambda move: move.product_id == self.article
            )
            self.assertGreater(bisque_output.price_unit, 0)
            self.assertGreater(finished_output.price_unit, bisque_output.price_unit)
        self.assertEqual(
            set(production.lot_producing_ids.mb_glaze_lot_ids.ids),
            {self.glaze_lot_a.id, self.glaze_lot_b.id},
        )
        self.assertIn(bisque_mo, production.lot_producing_ids.mb_production_ids)
        self.assertIn(glaze_firing, production.lot_producing_ids.mb_firing_ids)
        with self.assertRaises(UserError):
            self.env["mb.glazing.material.allocation"].create({
                "session_line_id": session.line_ids.id,
                "product_id": self.glaze.id,
                "lot_id": self.glaze_lot_a.id,
                "quantity": 0.1,
                "uom_id": self.glaze.uom_id.id,
            })

    def test_glazing_allocation_mismatch_rolls_back(self):
        _session, _production, bisque_lot, _firing, _action = self._produce_bisque(
            quantity=2
        )
        glazing = self.env["mb.glazing.session"].create({
            "board_id": self.board.id,
            "source_location_id": self.bisque_stock.id,
            "material_location_id": self.stock.id,
            "finished_location_id": self.finished.id,
            "line_ids": [Command.create({
                "bisque_product_id": self.bisque_product.id,
                "bisque_lot_id": bisque_lot.id,
                "quantity": 2,
                "finished_product_id": self.article.id,
                "bom_id": self.glazing_bom.id,
                "allocation_ids": [Command.create({
                    "product_id": self.glaze.id,
                    "lot_id": self.glaze_lot_a.id,
                    "quantity": 0.5,
                    "uom_id": self.glaze.uom_id.id,
                })],
            })],
        })
        with self.env.cr.savepoint(), self.assertRaises(UserError):
            glazing.action_start()
        self.assertFalse(self.env["mrp.production"].search([
            ("origin", "=", glazing.name),
            ("mb_workflow_kind", "=", "glazing"),
        ]))
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                self.bisque_product,
                self.bisque_stock,
                lot_id=bisque_lot,
                strict=True,
            ),
            2,
        )

    def test_green_and_bisque_stage_requires_tracking(self):
        product = self._product("Untracked green candidate")
        with self.assertRaises(ValidationError):
            product.product_tmpl_id.mb_ceramics_stage = "green"

    def test_glaze_formula_uses_dry_weight_as_water_denominator(self):
        dry = self.glaze_recipe.bom_line_ids.filtered(
            lambda line: line.mb_quantity_mode == "dry_percent"
        )
        water = self.glaze_recipe.bom_line_ids.filtered(
            lambda line: line.mb_quantity_mode == "water_percent"
        )
        self.assertEqual(dry.product_qty, 1.0)
        self.assertEqual(water.product_qty, 0.5)

    def test_approved_recipe_is_immutable_and_revision_is_linked(self):
        with self.assertRaises(UserError):
            self.glaze_recipe.bom_line_ids[:1].write({"mb_formula_percent": 90})
        action = self.glaze_recipe.action_mb_new_recipe_revision()
        successor = self.env["mrp.bom"].browse(action["res_id"])
        self.assertEqual(self.glaze_recipe.mb_recipe_state, "historical")
        self.assertEqual(successor.mb_recipe_state, "draft")
        self.assertEqual(successor.mb_previous_revision_id, self.glaze_recipe)
        self.assertEqual(successor.mb_revision, self.glaze_recipe.mb_revision + 1)

    def test_manufacturing_order_snapshots_approved_recipe(self):
        production = self.env["mrp.production"].create({
            "product_id": self.glaze.id,
            "product_qty": 1,
            "product_uom_id": self.glaze.uom_id.id,
            "bom_id": self.glaze_recipe.id,
        })
        production.action_confirm()
        self.assertEqual(production.mb_bom_revision_id, self.glaze_recipe)

    def test_confirmed_unstarted_order_can_return_to_draft(self):
        production = self.env["mrp.production"].create({
            "product_id": self.blank.id,
            "product_qty": 1,
            "product_uom_id": self.blank.uom_id.id,
            "bom_id": self.throw_bom.id,
        })
        production.action_confirm()
        production.action_mb_return_to_draft()
        self.assertEqual(production.state, "draft")
        self.assertTrue(all(move.state == "draft" for move in production.move_raw_ids))

    def test_recipe_documents_are_available_from_every_work_order(self):
        attachment = self.env["ir.attachment"].create({
            "name": "firing-sheet.pdf",
            "res_model": "mrp.bom",
            "res_id": self.glazing_bom.id,
            "raw": b"firing sheet",
        })
        production = self.env["mrp.production"].create({
            "product_id": self.article.id,
            "product_qty": 1,
            "product_uom_id": self.article.uom_id.id,
            "bom_id": self.glazing_bom.id,
        })
        production.action_confirm()
        for workorder in production.workorder_ids:
            action = workorder.action_mb_recipe_documents()
            self.assertIn(attachment.id, self.env["ir.attachment"].search(
                action["domain"]
            ).ids)
