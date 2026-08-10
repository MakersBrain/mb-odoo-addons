import base64
from datetime import datetime
import io

from PIL import Image
from PyPDF2 import PdfReader

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


def document(*elements):
    return {"schema": 1, "elements": list(elements)}


def text(element_id, value, **extra):
    return {
        "id": element_id, "type": "text", "x": 1, "y": 1,
        "width": 22, "height": 5, "text": value, "font_size": 2.5,
        **extra,
    }


@tagged("post_install", "-at_install")
class TestLabelVerticalSlice(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.env["mb.label.template"].create({
            "name": "Test 40x30", "width_mm": 40, "height_mm": 30,
            "dpi": 203, "company_id": cls.env.company.id,
            "printer_target": "phomemo",
            "qr_url_prefix": "https://instagram.com/username",
        })
        cls.version = cls.template.save_version(document(
            text("name", "{{product.name}}"),
            text("lot", "{{lot.name}}", required=False, y=7),
            {"id": "qr", "type": "qr", "x": 26, "y": 2,
             "width": 11, "height": 11, "data": "{{qr}}"},
        ))
        cls.version = cls.env["mb.label.template.version"].browse(cls.version["id"])
        cls.product = cls.env["product.product"].create({
            "name": "Blue cup", "default_code": "CUP-001", "lst_price": 42.5,
            "tracking": "serial",
        })
        cls.lot = cls.env["stock.lot"].create({
            "name": "PIECE-0001", "product_id": cls.product.id,
            "company_id": cls.env.company.id,
        })

    def test_product_only_label_renders_exact_png_and_pdf_size(self):
        payload = self.env["mb.label.print.job"].create_rendered(
            self.product.id, False, self.template.id, copies=2)
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

    def test_serial_label_mints_durable_alias(self):
        first = self.env["mb.label.print.job"].create_rendered(
            self.product.id, self.lot.id, self.template.id)
        first_job = self.env["mb.label.print.job"].browse(first["id"])
        self.assertEqual(
            first_job.alias_id.value,
            "https://instagram.com/username#CUP-001/PIECE-0001")
        self.template.save_version(document(text("changed", "New {{product.name}}")))
        second = self.env["mb.label.print.job"].create_rendered(
            self.product.id, self.lot.id, self.template.id)
        second_job = self.env["mb.label.print.job"].browse(second["id"])
        self.assertEqual(second_job.alias_id, first_job.alias_id)
        self.assertEqual(first_job.template_version_id.number, 1)
        self.assertEqual(second_job.template_version_id.number, 2)

    def test_qr_prefix_is_normalized_snapshotted_and_url_encodes_identity(self):
        self.template.qr_url_prefix = "HTTPS://Instagram.com/Username/#"
        version_data = self.template.save_version(
            document({"id": "qr2", "type": "qr", "x": 1, "y": 1,
                      "width": 10, "height": 10, "data": "{{qr}}"}),
            qr_url_prefix=self.template.qr_url_prefix)
        version = self.env["mb.label.template.version"].browse(version_data["id"])
        spaced_lot = self.env["stock.lot"].create({
            "name": "PIECE 00/02", "product_id": self.product.id,
            "company_id": self.env.company.id,
        })
        payload = self.env["mb.label.print.job"].create_rendered(
            self.product.id, spaced_lot.id, self.template.id)
        job = self.env["mb.label.print.job"].browse(payload["id"])
        self.assertEqual(version.qr_url_prefix, "https://instagram.com/Username")
        self.assertEqual(
            job.alias_id.value,
            "https://instagram.com/Username#CUP-001/PIECE%2000%2F02")

    def test_invalid_qr_prefix_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "HTTP"):
            self.template.save_version(document(), qr_url_prefix="javascript:alert(1)#x")

    def test_qr_collision_is_rejected_before_artifact(self):
        other = self.env["product.product"].create({
            "name": "Other cup", "default_code": "OTHER-001"})
        self.env["mb.label.qr.alias"].mint(
            "fixed", self.product.id, False, self.version.id)
        with self.assertRaises(ValidationError):
            self.env["mb.label.qr.alias"].mint(
                "fixed", other.id, False, self.version.id)

    def test_missing_required_binding_fails_visibly(self):
        template = self.env["mb.label.template"].create({
            "name": "Lot required", "width_mm": 40, "height_mm": 30, "dpi": 203})
        template.save_version(document(text("lot", "{{lot.name}}")))
        with self.assertRaisesRegex(ValidationError, "lot.name"):
            self.env["mb.label.print.job"].create_rendered(
                self.product.id, False, template.id)

    def test_optional_empty_binding_omits_the_whole_element(self):
        template = self.env["mb.label.template"].create({
            "name": "Optional lot", "width_mm": 40, "height_mm": 30, "dpi": 203})
        payload = template.save_version(document(
            text("optional-lot", "{{lot.name}}", required=False, background="black"),
            {
                "id": "optional-lot-qr", "type": "qr", "x": 25, "y": 2,
                "width": 10, "height": 10, "data": "{{lot.name}}",
                "required": False, "background": "black",
            },
        ))
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
            document({"id": "code", "type": "python", "x": 0, "y": 0,
                      "width": 1, "height": 1}),
        ):
            with self.assertRaises(ValidationError):
                self.template.save_version(invalid)

    def test_saved_versions_and_print_history_cannot_be_mutated_away(self):
        with self.assertRaises(UserError):
            self.version.write({"qr_payload_template": "changed"})
        job_payload = self.env["mb.label.print.job"].create_rendered(
            self.product.id, False, self.template.id)
        with self.assertRaises(UserError):
            self.env["mb.label.print.job"].browse(job_payload["id"]).unlink()
        with self.assertRaises(UserError):
            self.env["mb.label.qr.alias"].search([], limit=1).unlink()

    def test_retired_alias_cannot_silently_be_reprinted(self):
        alias = self.env["mb.label.qr.alias"].mint(
            "retired-piece", self.product.id, self.lot.id, self.version.id)
        alias.action_retire()
        with self.assertRaisesRegex(ValidationError, "retired"):
            self.env["mb.label.qr.alias"].mint(
                "retired-piece", self.product.id, self.lot.id, self.version.id)
        alias.action_reactivate()
        self.assertTrue(alias.active)

    def test_print_job_audit_fields_reject_direct_writes(self):
        payload = self.env["mb.label.print.job"].create_rendered(
            self.product.id, False, self.template.id)
        with self.assertRaises(UserError):
            self.env["mb.label.print.job"].browse(payload["id"]).write({"state": "printed"})

    def test_lot_must_belong_to_product(self):
        other = self.env["product.product"].create({"name": "Plate", "tracking": "serial"})
        with self.assertRaises(ValidationError):
            self.env["mb.label.print.job"].create({
                "product_id": other.id,
                "lot_id": self.lot.id,
                "template_version_id": self.version.id,
                "copies": 1, "dpi": 203, "width_mm": 40, "height_mm": 30,
                "bindings_snapshot": {"pending": True},
            })

    def test_printer_cannot_edit_template_but_designer_can(self):
        users = self.env["res.users"].with_context(no_reset_password=True)
        printer = users.create({
            "name": "Printer", "login": "label-printer",
            "group_ids": [(6, 0, [self.env.ref("mb_label.group_mb_label_user").id])],
        })
        designer = users.create({
            "name": "Designer", "login": "label-designer",
            "group_ids": [(6, 0, [self.env.ref("mb_label.group_mb_label_manager").id])],
        })
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
        wizard_model = self.env["mb.label.print.wizard"].with_context(
            **action["context"]
        )
        defaults = wizard_model.default_get(list(wizard_model._fields))
        wizard = wizard_model.new(defaults)

        wizard._onchange_product_template()

        self.assertEqual(wizard.product_id, self.product)
        self.assertEqual(wizard.lot_id, self.lot)

    def test_label_wizard_preview_escapes_product_name(self):
        malicious_product = self.env["product.product"].create({
            "name": '<img src=x onerror="alert(1)">',
        })
        wizard = self.env["mb.label.print.wizard"].create({
            "product_tmpl_id": malicious_product.product_tmpl_id.id,
            "product_id": malicious_product.id,
            "template_id": self.template.id,
            "company_id": self.env.company.id,
        })

        self.assertNotIn("<img", wizard.preview_html)
        self.assertIn("&lt;img", wizard.preview_html)

    def test_editor_settings_and_parity_features_are_snapshotted(self):
        payload = self.template.save_editor_version(document(
            {
                "id": "ellipse", "type": "ellipse", "x": 1, "y": 1,
                "width": 10, "height": 8, "filled": True, "tint": "50",
                "rotation": 15, "group_id": "shape-group",
            },
            {
                "id": "triangle", "type": "triangle", "x": 12, "y": 1,
                "width": 8, "height": 8, "filled": False, "stroke_width": 0.4,
            },
            {
                "id": "styled", "type": "text", "x": 1, "y": 12,
                "width": 35, "height": 6, "text": "[[date|YYYY-MM-DD]]",
                "font_size": 3, "font": "serif", "bold": True, "italic": True,
                "underline": True, "align": "center", "valign": "bottom",
                "background": "black", "inverted": True, "no_wrap": True,
            },
        ), {
            "width_mm": 42, "height_mm": 31, "dpi": 300,
            "printer_target": "brother", "round_media": True,
            "continuous_media": False, "qr_url_prefix": "https://instagram.com/username",
            "qr_payload_template": "{{qr}}",
        })
        version = self.env["mb.label.template.version"].browse(payload["id"])
        self.assertEqual((version.width_mm, version.height_mm, version.dpi), (42, 31, 300))
        self.assertEqual(version.printer_target, "brother")
        self.assertTrue(version.round_media)
        png = self.env["mb.label.render.service"].render_png(
            version, self.env["mb.label.render.service"].bindings_for(self.product), 300)
        image = Image.open(io.BytesIO(png)).convert("1")
        self.assertEqual(image.size, (496, 366))
        self.assertEqual(image.getpixel((0, 0)), 255)
        self.assertIn(0, image.getdata())

    def test_safe_instant_expressions_match_old_editor(self):
        renderer = self.env["mb.label.render.service"]
        now = datetime(2026, 8, 6, 14, 5, 9)
        self.assertEqual(
            renderer._evaluate_expressions(
                "[[date]] [[time]] [[iso]] [[monthyear]] [[now|DD.MM.YY HH:mm:ss]]", now),
            "06/08/2026 14:05 2026-08-06 août 2026 06.08.26 14:05:09",
        )
        self.assertEqual(renderer._evaluate_expressions("[[unknown]]", now), "[[unknown]]")

    def test_safe_binding_filters_format_money_numbers_defaults_and_text(self):
        renderer = self.env["mb.label.render.service"].with_context(lang="en_US")
        values = renderer.bindings_for(self.product)
        values["product.price.raw"] = 45
        self.assertNotRegex(
            renderer.resolve("{{product.price.raw|money_trim}}", values), r"[.,]00")
        values["product.price.raw"] = 45.5
        self.assertRegex(
            renderer.resolve("{{product.price.raw|money}}", values), r"45[.,]50")
        self.assertEqual(
            renderer.resolve("{{product.price.raw|fixed:1}}", values), "45.5")
        self.assertEqual(
            renderer.resolve("{{manual.note|default:No note|upper}}", values), "NO NOTE")
        self.assertEqual(
            renderer.resolve("{{product.name|trim|upper}}", values), "BLUE CUP")
        with self.assertRaisesRegex(ValidationError, "filter"):
            self.template.save_version(document(text(
                "invalid-filter", "{{product.price|unsafe}}")))

    def test_editor_can_preview_real_product_and_lot_bindings(self):
        options = self.env["mb.label.template"].editor_preview_options()
        self.assertIn(self.product.id, [item["id"] for item in options["products"]])
        values = self.env["mb.label.template"].editor_preview_bindings(
            self.product.id, self.lot.id, "https://instagram.com/username")
        self.assertEqual(values["product.default_code"], "CUP-001")
        self.assertEqual(values["lot.name"], "PIECE-0001")
        self.assertEqual(
            values["qr"], "https://instagram.com/username#CUP-001/PIECE-0001")
