import base64
import importlib.util
import io
from datetime import datetime
from pathlib import Path
from queue import Queue
from threading import Barrier, Thread

from PIL import Image
from psycopg2.errors import SerializationFailure
from PyPDF2 import PdfReader

from odoo import SUPERUSER_ID, api
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.modules.registry import Registry
from odoo.tests import BaseCase, TransactionCase, get_db_name, tagged
from odoo.tools import SQL
from odoo.tools.convert import convert_file


def document(*elements):
    return {"schema": 1, "elements": list(elements)}


def text(element_id, value, **extra):
    return {
        "id": element_id,
        "type": "text",
        "x": 1,
        "y": 1,
        "width": 22,
        "height": 5,
        "text": value,
        "font_size": 2.5,
        **extra,
    }


@tagged("post_install", "-at_install")
class TestLabelTemplateConcurrency(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.registry = Registry(get_db_name())
        with cls.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            cls.company_id = env.ref("base.main_company").id
            cls.seed_default_id = env.ref("mb_label.template_product_40x30").id

    def _run_locked_pair(self, operation):
        holder_done = Barrier(2)
        release_holder = Barrier(2)
        outcomes = Queue()
        envs = {
            role: api.Environment(self.registry.cursor(), SUPERUSER_ID, {})
            for role in ("holder", "contender")
        }
        pids = {}
        for role, env in envs.items():
            env.cr.execute("SELECT pg_backend_pid()")
            pids[role] = env.cr.fetchone()[0]

        def run(role):
            env = envs[role]
            try:
                result = operation(env, role)
                if role == "holder":
                    holder_done.wait(timeout=10)
                    release_holder.wait(timeout=10)
                env.cr.commit()
                outcomes.put((role, "committed", result))
            except SerializationFailure as error:
                env.cr.rollback()
                outcomes.put((role, "serialization", str(error)))
            except Exception as error:  # pragma: no cover - reported by the main thread
                env.cr.rollback()
                outcomes.put((role, "error", repr(error)))

        holder = Thread(target=run, args=("holder",), daemon=True)
        contender = Thread(target=run, args=("contender",), daemon=True)
        blocked = False
        try:
            holder.start()
            holder_done.wait(timeout=10)
            contender.start()
            for _attempt in range(200):
                with self.registry.cursor() as cr:
                    cr.execute("SELECT pg_blocking_pids(%s)", [pids["contender"]])
                    if pids["holder"] in cr.fetchone()[0]:
                        blocked = True
                        break
                if not contender.is_alive():
                    break
        finally:
            release_holder.wait(timeout=10)
            holder.join(timeout=10)
            contender.join(timeout=10)
            for env in envs.values():
                env.cr.close()

        self.assertTrue(blocked, "contender never waited on the invariant mutex")
        result = {}
        while not outcomes.empty():
            role, status, detail = outcomes.get_nowait()
            result[role] = (status, detail)
        self.assertEqual(result.get("holder", (None,))[0], "committed", result)
        self.assertEqual(result.get("contender", (None,))[0], "serialization", result)

    def _clear_main_company_defaults(self, env):
        env["mb.label.template"].search(
            [("company_id", "=", self.company_id), ("is_default", "=", True)]
        ).write({"is_default": False})

    def _restore_seed_default(self):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env["mb.label.template"].search(
                [("name", "like", "DATA-02 %"), ("company_id", "=", self.company_id)]
            ).unlink()
            seed = env["mb.label.template"].browse(self.seed_default_id).exists()
            if seed:
                seed.active = True
                seed.action_set_default()
            cr.commit()

    def test_concurrent_active_default_creation_serializes(self):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            self._clear_main_company_defaults(env)
            cr.commit()
        try:
            self._run_locked_pair(
                lambda env, role: (
                    env["mb.label.template"]
                    .create(
                        {
                            "name": "DATA-02 concurrent default %s" % role,
                            "company_id": self.company_id,
                            "is_default": True,
                        }
                    )
                    .id
                )
            )
            with self.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                with self.assertRaisesRegex(ValidationError, "only one"):
                    env["mb.label.template"].create(
                        {
                            "name": "DATA-02 concurrent default retry",
                            "company_id": self.company_id,
                            "is_default": True,
                        }
                    )
        finally:
            self._restore_seed_default()

    def test_concurrent_set_default_is_atomic(self):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            self._clear_main_company_defaults(env)
            templates = env["mb.label.template"].create(
                [
                    {"name": "DATA-02 choice holder", "company_id": self.company_id},
                    {"name": "DATA-02 choice contender", "company_id": self.company_id},
                ]
            )
            template_ids = dict(zip(("holder", "contender"), templates.ids, strict=True))
            cr.commit()
        try:
            self._run_locked_pair(
                lambda env, role: (
                    env["mb.label.template"].browse(template_ids[role]).action_set_default()
                )
            )
            with self.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                env["mb.label.template"].browse(template_ids["contender"]).action_set_default()
                defaults = env["mb.label.template"].search(
                    [
                        ("company_id", "=", self.company_id),
                        ("active", "=", True),
                        ("is_default", "=", True),
                    ]
                )
                self.assertEqual(defaults.ids, [template_ids["contender"]])
        finally:
            self._restore_seed_default()

    def test_concurrent_version_saves_serialize_numbering(self):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            template = env["mb.label.template"].create(
                {"name": "DATA-02 version mutex", "company_id": self.company_id}
            )
            template_id = template.id
            cr.commit()
        try:
            self._run_locked_pair(
                lambda env, role: (
                    env["mb.label.template"]
                    .browse(template_id)
                    .save_version(document(text(role, role)))["number"]
                )
            )
            with self.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                result = env["mb.label.template"].browse(template_id).save_version(document())
                self.assertEqual(result["number"], 2)
        finally:
            with self.registry.cursor() as cr:
                cr.execute(
                    "DELETE FROM mb_label_template_version WHERE template_id = %s", [template_id]
                )
                cr.execute("DELETE FROM mb_label_template WHERE id = %s", [template_id])
                cr.commit()


@tagged("post_install", "-at_install")
class TestLabelTemplateDefaultIntegrity(TransactionCase):
    def test_company_seed_provisioning_is_idempotent_and_non_destructive(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        Template = self.env["mb.label.template"]
        company = self.env["res.company"].create({"name": "DATA-03 seed company"})
        seeds = Template.with_context(active_test=False).search(
            [("company_id", "=", company.id), ("seed_key", "!=", False)]
        )
        self.assertEqual(set(seeds.mapped("seed_key")), {"product_40x30", "wip_lot_30x20"})
        product_seed = seeds.filtered(lambda item: item.seed_key == "product_40x30")
        wip_seed = seeds - product_seed
        self.assertTrue(product_seed.is_default)
        self.assertFalse(wip_seed.is_default)
        self.assertEqual(
            (product_seed.current_version_id.number, wip_seed.current_version_id.number), (1, 1)
        )

        original = {
            seed.id: (seed.current_version_id.id, seed.current_version_id.document_json)
            for seed in seeds
        }
        Template._ensure_company_seed_templates(company)
        Template._ensure_company_seed_templates(company)
        rerun = Template.with_context(active_test=False).search(
            [("company_id", "=", company.id), ("seed_key", "!=", False)]
        )
        self.assertEqual(rerun.ids, seeds.ids)
        self.assertEqual(
            {
                seed.id: (seed.current_version_id.id, seed.current_version_id.document_json)
                for seed in rerun
            },
            original,
        )

        custom = Template.create({"name": "DATA-03 custom default", "company_id": company.id})
        with self.assertRaisesRegex(UserError, "managed"):
            Template.create({"name": "Forged seed", "company_id": company.id, "seed_key": "forged"})
        with self.assertRaisesRegex(UserError, "immutable"):
            product_seed.seed_key = "forged"
        custom.action_set_default()
        self.env.cr.execute(
            "UPDATE mb_label_template SET seed_key = NULL WHERE id = %s", [product_seed.id]
        )
        product_seed.invalidate_recordset(["seed_key"])
        Template._ensure_company_seed_templates(company)
        product_seed.invalidate_recordset(["seed_key", "current_version_id", "is_default"])
        self.assertEqual(product_seed.seed_key, "product_40x30")
        self.assertEqual(product_seed.current_version_id.id, original[product_seed.id][0])
        self.assertFalse(product_seed.is_default)
        self.assertTrue(custom.is_default)

        source = self.env.ref("mb_label.template_product_40x30")
        self.assertEqual(
            product_seed.with_context(lang="fr_FR").name,
            source.with_context(lang="fr_FR").name,
        )
        self.assertEqual(
            self.env["ir.model.data"].search_count(
                [
                    ("module", "=", "mb_label"),
                    ("name", "like", "%%_company_%s" % company.id),
                ]
            ),
            4,
        )
        user = self.env["res.users"].create(
            {
                "name": "DATA-03 company user",
                "login": "data03-company-user",
                "company_id": company.id,
                "company_ids": [(6, 0, [company.id])],
                "group_ids": [(6, 0, [self.env.ref("mb_label.group_mb_label_user").id])],
            }
        )
        visible = Template.with_user(user).with_company(company).search([("seed_key", "!=", False)])
        self.assertEqual(visible.ids, seeds.ids)

    def test_archive_reactivate_and_company_scope(self):
        seed = self.env.ref("mb_label.template_product_40x30")
        seed.write({"active": False})
        self.assertFalse(seed.active)
        archived_default = self.env["mb.label.template"].create(
            {"name": "Archived default", "is_default": True, "active": False}
        )
        replacement = self.env["mb.label.template"].create(
            {"name": "Replacement default", "is_default": True}
        )
        with self.assertRaisesRegex(ValidationError, "only one"):
            archived_default.active = True
        with self.assertRaisesRegex(ValidationError, "Archive"):
            archived_default.action_set_default()
        replacement.active = False
        archived_default.active = True

        other_company = self.env["res.company"].create({"name": "DATA-02 other company"})
        other_default = self.env["mb.label.template"].search(
            [
                ("company_id", "=", other_company.id),
                ("seed_key", "=", "product_40x30"),
            ]
        )
        self.assertTrue(other_default.is_default)

    def test_clean_and_dirty_migration_preflight(self):
        path = Path(__file__).parents[1] / "migrations/19.0.1.2.4/pre-migrate.py"
        spec = importlib.util.spec_from_file_location("mb_label_data_02_pre_migrate", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.migrate(self.env.cr, "19.0.1.2.3")

        first, second = self.env["mb.label.template"].create(
            [{"name": "Dirty one"}, {"name": "Dirty two"}]
        )
        index_name = "mb_label_template_active_default_unique"
        with self.env.cr.savepoint():
            self.env.cr.execute(SQL("DROP INDEX %s", SQL.identifier(index_name)))
            self.env.cr.execute(
                "UPDATE mb_label_template SET is_default = TRUE WHERE id IN %s",
                [tuple((first | second).ids)],
            )
            with self.assertRaisesRegex(RuntimeError, "company .*templates"):
                migration.migrate(self.env.cr, "19.0.1.2.3")
            self.env.cr.execute(
                "UPDATE mb_label_template SET is_default = FALSE WHERE id IN %s",
                [tuple((first | second).ids)],
            )
            self.env.cr.execute(
                SQL(
                    "CREATE UNIQUE INDEX %s ON mb_label_template (company_id) "
                    "WHERE active IS TRUE AND is_default IS TRUE",
                    SQL.identifier(index_name),
                )
            )


@tagged("post_install", "-at_install")
class TestLabelVerticalSlice(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.env["mb.label.template"].create(
            {
                "name": "Test 40x30",
                "width_mm": 40,
                "height_mm": 30,
                "dpi": 203,
                "company_id": cls.env.company.id,
                "printer_target": "phomemo",
                "qr_url_prefix": "https://instagram.com/username",
            }
        )
        cls.version = cls.template.save_version(
            document(
                text("name", "{{product.name}}"),
                text("lot", "{{lot.name}}", required=False, y=7),
                {
                    "id": "qr",
                    "type": "qr",
                    "x": 26,
                    "y": 2,
                    "width": 11,
                    "height": 11,
                    "data": "{{qr}}",
                },
            )
        )
        cls.version = cls.env["mb.label.template.version"].browse(cls.version["id"])
        cls.product = cls.env["product.product"].create(
            {
                "name": "Blue cup",
                "default_code": "CUP-001",
                "lst_price": 42.5,
                "tracking": "serial",
            }
        )
        cls.lot = cls.env["stock.lot"].create(
            {
                "name": "PIECE-0001",
                "product_id": cls.product.id,
                "company_id": cls.env.company.id,
            }
        )

    def test_product_only_label_renders_exact_png_and_pdf_size(self):
        payload = self.env["mb.label.print.job"].create_rendered(
            self.product.id, False, self.template.id, copies=2
        )
        job = self.env["mb.label.print.job"].browse(payload["id"])
        self.assertEqual(job.state, "rendered")
        self.assertEqual(payload["printer_target"], "phomemo")
        self.assertEqual(job.alias_id.value, "https://instagram.com/username#CUP-001")
        self.assertEqual(job.bindings_snapshot["qr"], job.alias_id.value)
        device_action = job.action_device_print()
        self.assertEqual(device_action["target"], "new")
        self.assertEqual(device_action["context"]["job_id"], job.id)
        image = Image.open(io.BytesIO(base64.b64decode(job.preview_png)))
        self.assertEqual(image.size, (320, 240))
        pdf = PdfReader(io.BytesIO(base64.b64decode(job.artifact_pdf)))
        self.assertEqual(len(pdf.pages), 2)
        page = pdf.pages[0]
        self.assertAlmostEqual(float(page.mediabox.width) * 25.4 / 72, 40, places=2)
        self.assertAlmostEqual(float(page.mediabox.height) * 25.4 / 72, 30, places=2)

    def test_wip_lot_template_renders_green_or_bisque_batch_at_30x20(self):
        template = self.env.ref("mb_label.template_wip_lot_30x20")
        self.assertEqual((template.width_mm, template.height_mm), (30, 20))
        payload = self.env["mb.label.print.job"].create_rendered(
            self.product.id,
            self.lot.id,
            template.id,
            manual_values={"stage": "BISQUE", "quantity": "4"},
        )
        job = self.env["mb.label.print.job"].browse(payload["id"])
        self.assertEqual(job.bindings_snapshot["manual.stage"], "BISQUE")
        self.assertEqual(job.bindings_snapshot["manual.quantity"], "4")
        image = Image.open(io.BytesIO(base64.b64decode(job.preview_png)))
        self.assertEqual(image.size, (240, 160))

    def test_wip_lot_current_version_survives_repeated_module_updates(self):
        template = self.env.ref("mb_label.template_wip_lot_30x20")
        seeded_version = self.env.ref("mb_label.template_wip_lot_30x20_v1")
        self.assertEqual(template.current_version_id, seeded_version)

        version_data = template.save_version(document(text("updated", "Version 2")))
        current_version = self.env["mb.label.template.version"].browse(version_data["id"])
        self.assertEqual(current_version.number, 2)

        for _update in range(2):
            convert_file(
                self.env,
                "mb_label",
                "data/mb_label_data.xml",
                {},
                mode="update",
            )
            template.invalidate_recordset(["current_version_id", "version_ids"])
            self.assertEqual(template.current_version_id, current_version)

        self.assertEqual(
            self.env["mb.label.template.version"].search_count(
                [("template_id", "=", template.id), ("number", "=", 1)]
            ),
            1,
        )

    def test_serial_label_mints_durable_alias(self):
        first = self.env["mb.label.print.job"].create_rendered(
            self.product.id, self.lot.id, self.template.id
        )
        first_job = self.env["mb.label.print.job"].browse(first["id"])
        self.assertEqual(
            first_job.alias_id.value, "https://instagram.com/username#CUP-001/PIECE-0001"
        )
        self.template.save_version(document(text("changed", "New {{product.name}}")))
        second = self.env["mb.label.print.job"].create_rendered(
            self.product.id, self.lot.id, self.template.id
        )
        second_job = self.env["mb.label.print.job"].browse(second["id"])
        self.assertEqual(second_job.alias_id, first_job.alias_id)
        self.assertEqual(first_job.template_version_id.number, 1)
        self.assertEqual(second_job.template_version_id.number, 2)

    def test_qr_prefix_is_normalized_snapshotted_and_url_encodes_identity(self):
        self.template.qr_url_prefix = "HTTPS://Instagram.com/Username/#"
        version_data = self.template.save_version(
            document(
                {
                    "id": "qr2",
                    "type": "qr",
                    "x": 1,
                    "y": 1,
                    "width": 10,
                    "height": 10,
                    "data": "{{qr}}",
                }
            ),
            qr_url_prefix=self.template.qr_url_prefix,
        )
        version = self.env["mb.label.template.version"].browse(version_data["id"])
        spaced_lot = self.env["stock.lot"].create(
            {
                "name": "PIECE 00/02",
                "product_id": self.product.id,
                "company_id": self.env.company.id,
            }
        )
        payload = self.env["mb.label.print.job"].create_rendered(
            self.product.id, spaced_lot.id, self.template.id
        )
        job = self.env["mb.label.print.job"].browse(payload["id"])
        self.assertEqual(version.qr_url_prefix, "https://instagram.com/Username")
        self.assertEqual(
            job.alias_id.value, "https://instagram.com/Username#CUP-001/PIECE%2000%2F02"
        )

    def test_invalid_qr_prefix_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "HTTP"):
            self.template.save_version(document(), qr_url_prefix="javascript:alert(1)#x")

    def test_qr_collision_is_rejected_before_artifact(self):
        other = self.env["product.product"].create(
            {"name": "Other cup", "default_code": "OTHER-001"}
        )
        self.env["mb.label.qr.alias"].mint("fixed", self.product.id, False, self.version.id)
        with self.assertRaises(ValidationError):
            self.env["mb.label.qr.alias"].mint("fixed", other.id, False, self.version.id)

    def test_missing_required_binding_fails_visibly(self):
        template = self.env["mb.label.template"].create(
            {"name": "Lot required", "width_mm": 40, "height_mm": 30, "dpi": 203}
        )
        template.save_version(document(text("lot", "{{lot.name}}")))
        with self.assertRaisesRegex(ValidationError, "lot.name"):
            self.env["mb.label.print.job"].create_rendered(self.product.id, False, template.id)

    def test_optional_empty_binding_omits_the_whole_element(self):
        template = self.env["mb.label.template"].create(
            {"name": "Optional lot", "width_mm": 40, "height_mm": 30, "dpi": 203}
        )
        payload = template.save_version(
            document(
                text("optional-lot", "{{lot.name}}", required=False, background="black"),
                {
                    "id": "optional-lot-qr",
                    "type": "qr",
                    "x": 25,
                    "y": 2,
                    "width": 10,
                    "height": 10,
                    "data": "{{lot.name}}",
                    "required": False,
                    "background": "black",
                },
            )
        )
        version = self.env["mb.label.template.version"].browse(payload["id"])
        values = self.env["mb.label.render.service"].bindings_for(self.product)
        png = self.env["mb.label.render.service"].render_png(version, values)
        self.assertEqual(Image.open(io.BytesIO(png)).convert("L").getextrema(), (255, 255))

    def test_qr_quiet_zone_and_exact_box_scaling(self):
        renderer = self.env["mb.label.render.service"]
        payload = "https://instagram.com/username#CUP-001/PIECE-0001"
        filled = renderer._qr_image(payload, 81, 81, quiet_zone=0)
        standard = renderer._qr_image(payload, 81, 81, quiet_zone=4)
        self.assertEqual(filled.size, (81, 81))
        self.assertEqual(standard.size, (81, 81))
        self.assertEqual(filled.getpixel((0, 0)), 0)
        self.assertEqual(standard.getpixel((0, 0)), 255)

    def test_unsafe_and_malformed_documents_are_rejected(self):
        for invalid in (
            {"schema": 2, "elements": []},
            document(text("bad", "{{product.env.user.password}}")),
            document({"id": "code", "type": "python", "x": 0, "y": 0, "width": 1, "height": 1}),
        ):
            with self.assertRaises(ValidationError):
                self.template.save_version(invalid)

    def test_saved_versions_and_print_history_cannot_be_mutated_away(self):
        with self.assertRaises(UserError):
            self.version.write({"qr_payload_template": "changed"})
        job_payload = self.env["mb.label.print.job"].create_rendered(
            self.product.id, False, self.template.id
        )
        with self.assertRaises(UserError):
            self.env["mb.label.print.job"].browse(job_payload["id"]).unlink()
        with self.assertRaises(UserError):
            self.env["mb.label.qr.alias"].search([], limit=1).unlink()

    def test_retired_alias_cannot_silently_be_reprinted(self):
        alias = self.env["mb.label.qr.alias"].mint(
            "retired-piece", self.product.id, self.lot.id, self.version.id
        )
        alias.action_retire()
        with self.assertRaisesRegex(ValidationError, "retired"):
            self.env["mb.label.qr.alias"].mint(
                "retired-piece", self.product.id, self.lot.id, self.version.id
            )
        alias.action_reactivate()
        self.assertTrue(alias.active)

    def test_print_job_audit_fields_reject_direct_writes(self):
        payload = self.env["mb.label.print.job"].create_rendered(
            self.product.id, False, self.template.id
        )
        with self.assertRaises(UserError):
            self.env["mb.label.print.job"].browse(payload["id"]).write({"state": "printed"})

    def test_lot_must_belong_to_product(self):
        other = self.env["product.product"].create({"name": "Plate", "tracking": "serial"})
        with self.assertRaises(ValidationError):
            self.env["mb.label.print.job"].create(
                {
                    "product_id": other.id,
                    "lot_id": self.lot.id,
                    "template_version_id": self.version.id,
                    "copies": 1,
                    "dpi": 203,
                    "width_mm": 40,
                    "height_mm": 30,
                    "bindings_snapshot": {"pending": True},
                }
            )

    def test_printer_cannot_edit_template_but_designer_can(self):
        users = self.env["res.users"].with_context(no_reset_password=True)
        printer = users.create(
            {
                "name": "Printer",
                "login": "label-printer",
                "group_ids": [(6, 0, [self.env.ref("mb_label.group_mb_label_user").id])],
            }
        )
        designer = users.create(
            {
                "name": "Designer",
                "login": "label-designer",
                "group_ids": [(6, 0, [self.env.ref("mb_label.group_mb_label_manager").id])],
            }
        )
        with self.assertRaises(AccessError):
            self.template.with_user(printer).write({"name": "Forbidden"})
        self.template.with_user(designer).write({"name": "Allowed"})
        self.assertEqual(self.template.name, "Allowed")

    def test_product_and_lot_expose_create_and_print_actions(self):
        create_product = self.product.action_mb_create_label()
        self.assertEqual(create_product["tag"], "mb_label.editor")
        self.assertEqual(create_product["context"]["default_product_id"], self.product.id)
        print_product = self.product.action_mb_print_label()
        self.assertEqual(print_product["res_model"], "mb.label.print.wizard")
        self.assertEqual(print_product["context"]["default_product_id"], self.product.id)

        create_lot = self.lot.action_mb_create_label()
        self.assertEqual(create_lot["tag"], "mb_label.editor")
        self.assertEqual(create_lot["context"]["default_lot_id"], self.lot.id)
        print_lot = self.lot.action_mb_print_label()
        self.assertEqual(print_lot["context"]["default_lot_id"], self.lot.id)

    def test_label_wizard_preserves_a_valid_preselected_lot_on_initial_onchange(self):
        action = self.lot.action_mb_print_label()
        wizard_model = self.env["mb.label.print.wizard"].with_context(**action["context"])
        defaults = wizard_model.default_get(list(wizard_model._fields))
        wizard = wizard_model.new(defaults)

        wizard._onchange_product_template()

        self.assertEqual(wizard.product_id, self.product)
        self.assertEqual(wizard.lot_id, self.lot)

    def test_label_wizard_preview_escapes_product_name(self):
        malicious_product = self.env["product.product"].create(
            {
                "name": '<img src=x onerror="alert(1)">',
            }
        )
        wizard = self.env["mb.label.print.wizard"].create(
            {
                "product_tmpl_id": malicious_product.product_tmpl_id.id,
                "product_id": malicious_product.id,
                "template_id": self.template.id,
                "company_id": self.env.company.id,
            }
        )

        self.assertNotIn("<img", wizard.preview_html)
        self.assertIn("&lt;img", wizard.preview_html)

    def test_editor_settings_and_parity_features_are_snapshotted(self):
        payload = self.template.save_editor_version(
            document(
                {
                    "id": "ellipse",
                    "type": "ellipse",
                    "x": 1,
                    "y": 1,
                    "width": 10,
                    "height": 8,
                    "filled": True,
                    "tint": "50",
                    "rotation": 15,
                    "group_id": "shape-group",
                },
                {
                    "id": "triangle",
                    "type": "triangle",
                    "x": 12,
                    "y": 1,
                    "width": 8,
                    "height": 8,
                    "filled": False,
                    "stroke_width": 0.4,
                },
                {
                    "id": "styled",
                    "type": "text",
                    "x": 1,
                    "y": 12,
                    "width": 35,
                    "height": 6,
                    "text": "[[date|YYYY-MM-DD]]",
                    "font_size": 3,
                    "font": "serif",
                    "bold": True,
                    "italic": True,
                    "underline": True,
                    "align": "center",
                    "valign": "bottom",
                    "background": "black",
                    "inverted": True,
                    "no_wrap": True,
                },
            ),
            {
                "width_mm": 42,
                "height_mm": 31,
                "dpi": 300,
                "printer_target": "brother",
                "round_media": True,
                "continuous_media": False,
                "qr_url_prefix": "https://instagram.com/username",
                "qr_payload_template": "{{qr}}",
            },
        )
        version = self.env["mb.label.template.version"].browse(payload["id"])
        self.assertEqual((version.width_mm, version.height_mm, version.dpi), (42, 31, 300))
        self.assertEqual(version.printer_target, "brother")
        self.assertTrue(version.round_media)
        png = self.env["mb.label.render.service"].render_png(
            version, self.env["mb.label.render.service"].bindings_for(self.product), 300
        )
        image = Image.open(io.BytesIO(png)).convert("1")
        self.assertEqual(image.size, (496, 366))
        self.assertEqual(image.getpixel((0, 0)), 255)
        self.assertIn(0, image.getdata())

    def test_safe_instant_expressions_match_old_editor(self):
        renderer = self.env["mb.label.render.service"]
        now = datetime(2026, 8, 6, 14, 5, 9)
        self.assertEqual(
            renderer._evaluate_expressions(
                "[[date]] [[time]] [[iso]] [[monthyear]] [[now|DD.MM.YY HH:mm:ss]]", now
            ),
            "06/08/2026 14:05 2026-08-06 août 2026 06.08.26 14:05:09",
        )
        self.assertEqual(renderer._evaluate_expressions("[[unknown]]", now), "[[unknown]]")

    def test_safe_binding_filters_format_money_numbers_defaults_and_text(self):
        renderer = self.env["mb.label.render.service"].with_context(lang="en_US")
        values = renderer.bindings_for(self.product)
        values["product.price.raw"] = 45
        self.assertNotRegex(renderer.resolve("{{product.price.raw|money_trim}}", values), r"[.,]00")
        values["product.price.raw"] = 45.5
        self.assertRegex(renderer.resolve("{{product.price.raw|money}}", values), r"45[.,]50")
        self.assertEqual(renderer.resolve("{{product.price.raw|fixed:1}}", values), "45.5")
        self.assertEqual(
            renderer.resolve("{{manual.note|default:No note|upper}}", values), "NO NOTE"
        )
        self.assertEqual(renderer.resolve("{{product.name|trim|upper}}", values), "BLUE CUP")
        with self.assertRaisesRegex(ValidationError, "filter"):
            self.template.save_version(document(text("invalid-filter", "{{product.price|unsafe}}")))

    def test_editor_can_preview_real_product_and_lot_bindings(self):
        options = self.env["mb.label.template"].editor_preview_options()
        self.assertIn(self.product.id, [item["id"] for item in options["products"]])
        values = self.env["mb.label.template"].editor_preview_bindings(
            self.product.id, self.lot.id, "https://instagram.com/username"
        )
        self.assertEqual(values["product.default_code"], "CUP-001")
        self.assertEqual(values["lot.name"], "PIECE-0001")
        self.assertEqual(values["qr"], "https://instagram.com/username#CUP-001/PIECE-0001")
