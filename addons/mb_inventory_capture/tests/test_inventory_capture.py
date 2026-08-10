import base64
import io
import uuid
from unittest.mock import Mock, patch

from PIL import Image

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.mb_inventory_capture.models.identifier import (
    normalize_identifier,
    parse_gs1_element_string,
)


def image_data(color=(190, 40, 20), exif=False):
    image = Image.new("RGB", (40, 30), color)
    output = io.BytesIO()
    metadata = None
    if exif:
        metadata = Image.Exif()
        metadata[274] = 6
        metadata[315] = "must be stripped"
    save_options = {"quality": 95}
    if metadata is not None:
        save_options["exif"] = metadata
    image.save(output, "JPEG", **save_options)
    return base64.b64encode(output.getvalue()).decode()


@tagged("post_install", "-at_install")
class TestInventoryCapture(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create({
            "name": "Mayco SW-106 Alabaster",
            "is_storable": True,
            "tracking": "lot",
            "barcode": "097539118054",
            "mb_supplier_lot_required": True,
        })
        cls.warehouse = cls.env["stock.warehouse"].search([
            ("company_id", "=", cls.env.company.id),
        ], limit=1)

    def capture(self, **values):
        return self.env["mb.inventory.capture"].create({
            "company_id": self.env.company.id,
            **values,
        })

    def test_gtin_and_gs1_are_normalized_without_losing_lot_zeroes(self):
        self.assertEqual(normalize_identifier("gtin_12", "097539118054"), "00097539118054")
        parsed = parse_gs1_element_string(
            "(01)00097539118054(10)001A-09(17)270101(30)12"
        )
        self.assertEqual(parsed["gtin"], "00097539118054")
        self.assertEqual(parsed["lot"], "001A-09")
        self.assertEqual(parsed["expiry"], "2027-01-01")
        self.assertEqual(parsed["quantity"], 12)

    def test_invalid_check_digit_is_rejected(self):
        with self.assertRaises(ValidationError):
            normalize_identifier("gtin_12", "097539118055")

    def test_upload_is_oriented_sanitized_and_idempotent(self):
        capture = self.capture()
        first = capture.upload_image(image_data(exif=True), "front", "phone.jpg")
        replay = capture.upload_image(image_data(exif=True), "front", "phone.jpg")
        asset = capture.asset_ids

        self.assertEqual(first["asset_uuid"], replay["asset_uuid"])
        self.assertEqual(len(asset), 1)
        self.assertEqual((asset.pixel_width, asset.pixel_height), (30, 40))
        sanitized = base64.b64decode(asset.attachment_id.with_context(bin_size=False).datas)
        with Image.open(io.BytesIO(sanitized)) as image:
            self.assertFalse(image.getexif())

    def test_only_two_source_images_are_accepted(self):
        capture = self.capture()
        capture.upload_image(image_data((1, 2, 3)), "front")
        capture.upload_image(image_data((4, 5, 6)), "lot_detail")
        with self.assertRaises(ValidationError):
            capture.upload_image(image_data((7, 8, 9)), "front")

    def test_local_barcode_and_gs1_create_review_candidates(self):
        capture = self.capture()
        result = capture.action_record_scan(
            "(01)00097539118054(10)24111042(17)270101", "data_matrix"
        )

        self.assertEqual(capture.state, "review")
        self.assertEqual(capture.product_id, self.product)
        self.assertEqual(capture.proposed_lot, "24111042")
        self.assertEqual(capture.proposed_expiry, fields.Date.to_date("2027-01-01"))
        self.assertEqual(result["gtin"], "00097539118054")
        self.assertEqual(set(capture.candidate_ids.mapped("kind")), {"product", "lot"})
        self.assertTrue(all(
            candidate.grounding_state == "grounded" for candidate in capture.candidate_ids
        ))

    def test_provider_result_is_append_only_and_unknown_digest_is_rejected(self):
        capture = self.capture()
        asset = capture.upload_image(image_data(), "front")
        capture.action_prepare_extraction()
        payload = {
            "operation_key": f"inventory:{capture.capture_uuid}:1",
            "capture_id": capture.capture_uuid,
            "attempt_id": str(uuid.uuid4()),
            "kind": "multimodal",
            "provider": "fixture-ai",
            "model": "fixture-v1",
            "state": "succeeded",
            "input_digests": [asset["content_sha256"]],
            "normalized_response": {"candidates": [{
                "kind": "lot",
                "raw_value": "8O1B",
                "confidence": 0.78,
                "reported_region": [0.1, 0.2, 0.5, 0.3],
                "grounding_state": "unverified",
                "source": "ai_suggestion",
            }]},
            "raw_response": {"fixture": True},
            "usage": {"images": 1},
        }
        result = capture.ingest_result(payload)

        self.assertEqual(result["state"], "review")
        self.assertEqual(len(capture.attempt_ids), 1)
        self.assertEqual(capture.candidate_ids.grounding_state, "unverified")
        with self.assertRaises(ValidationError):
            capture.ingest_result(dict(
                payload,
                attempt_id=str(uuid.uuid4()),
                operation_key=f"inventory:{capture.capture_uuid}:2",
                input_digests=["0" * 64],
            ))

    def test_confirmed_capture_applies_native_lot_to_draft_receipt_line(self):
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.in_type_id.id,
            "location_id": self.warehouse.in_type_id.default_location_src_id.id,
            "location_dest_id": self.warehouse.lot_stock_id.id,
        })
        move = self.env["stock.move"].create({
            "picking_id": picking.id,
            "product_id": self.product.id,
            "product_uom_qty": 2,
            "product_uom": self.product.uom_id.id,
            "location_id": picking.location_id.id,
            "location_dest_id": picking.location_dest_id.id,
        })
        move._action_confirm()
        line = move.move_line_ids[:1]
        if not line:
            line = self.env["stock.move.line"].create({
                "move_id": move.id,
                "picking_id": picking.id,
                "product_id": self.product.id,
                "product_uom_id": self.product.uom_id.id,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
                "quantity": 2,
            })
        capture = self.capture(picking_id=picking.id, move_id=move.id, move_line_id=line.id)
        capture.action_record_scan("(01)00097539118054(10)00042", "data_matrix")
        capture.action_apply()

        self.assertEqual(capture.state, "applied")
        self.assertEqual(capture.lot_id.name, "00042")
        self.assertEqual(capture.lot_id.product_id, self.product)
        self.assertEqual(line.lot_id, capture.lot_id)
        self.assertEqual(capture.lot_id.mb_supplier_lot_origin, "supplier")

    def test_alternate_gtin_cannot_shadow_primary_barcode(self):
        other = self.env["product.product"].create({
            "name": "Other glaze", "is_storable": True,
        })
        with self.assertRaises(ValidationError):
            self.env["mb.product.identifier"].create({
                "product_id": other.id,
                "scheme": "gtin_12",
                "printed_value": "097539118054",
                "source": "manual",
                "verification_state": "verified",
            })

    def test_primary_barcode_is_mirrored_into_global_registry(self):
        identifier = self.env["mb.product.identifier"].search([
            ("comparison_scheme", "=", "gtin"),
            ("normalized_value", "=", "00097539118054"),
        ])
        self.assertEqual(identifier.product_id, self.product)
        self.assertFalse(identifier.company_id)
        self.assertEqual(identifier.source, "primary_barcode")

    def test_control_queue_payload_contains_digests_not_image_bytes(self):
        capture = self.capture()
        capture.upload_image(image_data(), "front")
        workshop_id = str(uuid.uuid4())
        capture.company_id.mb_control_workshop_id = workshop_id
        response = Mock(status_code=202)
        response.raise_for_status.return_value = None
        response.json.return_value = {"operation_id": str(uuid.uuid4())}
        with patch.dict("os.environ", {
            "MB_CONTROL_API_URL": "https://control.example.test",
            "MB_CONTROL_BRIDGE_TOKEN": "fixture-token",
        }), patch(
            "odoo.addons.mb_inventory_capture.models.inventory_capture.requests.post",
            return_value=response,
        ) as post:
            result = capture.action_prepare_extraction()

        queued = post.call_args.kwargs["json"]
        self.assertEqual(result["task"], "inventory_label")
        self.assertNotIn("base64", str(queued).lower())
        self.assertNotIn("data", queued["assets"][0])
        self.assertEqual(len(queued["assets"][0]["content_sha256"]), 64)
        self.assertEqual(post.call_args.kwargs["allow_redirects"], False)

    def test_retention_purges_only_unapplied_binary_evidence(self):
        capture = self.capture()
        capture.upload_image(image_data(), "front")
        self.env.cr.execute(
            "UPDATE mb_inventory_capture SET write_date = now() - interval '31 days' "
            "WHERE id = %s", [capture.id],
        )
        capture.invalidate_recordset()
        purged = self.env["mb.inventory.capture"]._cron_purge_unapplied_evidence()
        capture.invalidate_recordset(["asset_ids"])
        self.assertEqual(purged, 1)
        self.assertFalse(capture.asset_ids)
        self.assertTrue(capture.exists())

    def test_safe_tracking_cutover_changes_only_future_tracking_policy(self):
        product = self.env["product.product"].create({
            "name": "New clay body", "is_storable": True, "tracking": "none",
        })
        wizard = self.env["mb.supplier.lot.migration"].create({
            "product_ids": [(6, 0, product.ids)],
        })
        wizard.action_analyze()
        self.assertEqual(wizard.eligible_product_ids, product)
        wizard.action_apply_safe()
        self.assertEqual(product.tracking, "lot")
        self.assertTrue(product.mb_supplier_lot_required)
