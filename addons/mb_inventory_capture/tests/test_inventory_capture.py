import base64
import io
import uuid
from unittest.mock import Mock, patch

from PIL import Image

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.mb_inventory_capture.models.identifier import (
    expand_upc_e,
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
        cls.product = cls.env["product.product"].create(
            {
                "name": "Mayco SW-106 Alabaster",
                "is_storable": True,
                "tracking": "lot",
                "barcode": "097539118054",
                "mb_supplier_lot_required": True,
            }
        )
        cls.warehouse = cls.env["stock.warehouse"].search(
            [
                ("company_id", "=", cls.env.company.id),
            ],
            limit=1,
        )

    def capture(self, **values):
        return self.env["mb.inventory.capture"].create(
            {
                "company_id": self.env.company.id,
                **values,
            }
        )

    def test_gtin_and_gs1_are_normalized_without_losing_lot_zeroes(self):
        self.assertEqual(normalize_identifier("gtin_12", "097539118054"), "00097539118054")
        parsed = parse_gs1_element_string("(01)00097539118054(10)001A-09(17)270101(30)12")
        self.assertEqual(parsed["gtin"], "00097539118054")
        self.assertEqual(parsed["lot"], "001A-09")
        self.assertEqual(parsed["expiry"], "2027-01-01")
        self.assertEqual(parsed["quantity"], 12)

    def test_invalid_check_digit_is_rejected(self):
        with self.assertRaises(ValidationError):
            normalize_identifier("gtin_12", "097539118055")

    def test_upc_e_expands_before_product_resolution(self):
        self.assertEqual(expand_upc_e("04252614"), "042100005264")
        self.assertFalse(expand_upc_e("04252615"))

    def test_raw_fnc1_and_invalid_expiry_are_handled_conservatively(self):
        raw = parse_gs1_element_string("]d2010009753911805410007A\x1d3012")
        self.assertEqual(raw["gtin"], "00097539118054")
        self.assertEqual(raw["lot"], "007A")
        self.assertEqual(raw["quantity"], 12)
        invalid = parse_gs1_element_string("(17)271332")
        self.assertFalse(invalid["expiry"])
        self.assertTrue(invalid["warnings"])

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

    def test_retake_replaces_current_role_without_discarding_evidence(self):
        capture = self.capture()
        first = capture.upload_image(image_data((1, 2, 3)), "front")
        capture.upload_image(image_data((4, 5, 6)), "lot_detail")
        crop = capture.create_lot_crop(first["id"], [0.1, 0.1, 0.9, 0.9])
        replacement = capture.upload_image(image_data((7, 8, 9)), "front")

        self.assertEqual(len(capture.asset_ids.filtered("is_current")), 2)
        self.assertFalse(capture.asset_ids.browse(first["id"]).is_current)
        self.assertFalse(capture.asset_ids.browse(crop["id"]).is_current)
        self.assertTrue(capture.asset_ids.browse(replacement["id"]).is_current)
        self.assertEqual(len(capture.asset_ids), 4)

    def test_reviewed_rotated_crop_is_traceable_and_preferred_for_extraction(self):
        capture = self.capture()
        source = capture.upload_image(image_data(), "front")
        capture.action_record_scan("097539118054", "upc_a")
        crop = capture.create_lot_crop(
            source["id"],
            [0.1, 0.2, 0.9, 0.8],
            90,
            enhance=True,
        )

        crop_record = capture.asset_ids.filtered(lambda asset: asset.id == crop["id"])
        self.assertEqual(crop_record.role, "crop")
        self.assertEqual(crop_record.parent_asset_id.id, source["id"])
        self.assertEqual(crop_record.crop_rectangle["rotation"], 90)
        variant = capture.asset_ids.filtered(lambda asset: asset.role == "ocr_variant")
        self.assertEqual(len(variant), 1)
        self.assertEqual(variant.parent_asset_id, crop_record)
        self.assertEqual(variant.mimetype, "image/png")
        self.assertEqual(crop["ocr_variant"]["asset_uuid"], variant.asset_uuid)
        payload = capture.action_prepare_extraction()
        self.assertEqual(payload["assets"][0]["asset_id"], crop["asset_uuid"])
        self.assertEqual(payload["assets"][0]["role"], "crop")
        self.assertEqual(
            {asset["role"] for asset in payload["assets"]},
            {"crop", "front"},
        )

    def test_scan_frame_does_not_silently_choose_between_products(self):
        other = self.env["product.product"].create(
            {
                "name": "Other glaze",
                "is_storable": True,
                "barcode": "4006381333931",
            }
        )
        capture = self.capture()

        result = capture.action_record_scans(
            [
                {"raw_value": "097539118054", "symbology": "upc_a"},
                {"raw_value": "4006381333931", "symbology": "ean_13"},
            ]
        )

        self.assertTrue(result["ambiguous"])
        self.assertEqual(set(result["product_ids"]), {self.product.id, other.id})
        self.assertFalse(capture.product_id)

    def test_manual_only_extraction_remains_in_review(self):
        capture = self.capture()
        capture.upload_image(image_data(), "front")
        capture.company_id.mb_control_workshop_id = False

        result = capture.action_prepare_extraction()

        self.assertEqual(result["outcome"], "manual_only")
        self.assertFalse(result["queued"])
        self.assertEqual(capture.state, "review")

    def test_crop_rejects_unbounded_rectangle(self):
        capture = self.capture()
        source = capture.upload_image(image_data(), "front")
        with self.assertRaises(ValidationError):
            capture.create_lot_crop(source["id"], [-0.1, 0, 1, 1], 0)

    def test_evidence_models_reject_direct_creation(self):
        capture = self.capture()
        user_env = self.env(user=self.env.ref("base.user_admin"))
        with self.assertRaises(AccessError):
            user_env["mb.inventory.capture.asset"].create(
                {
                    "capture_id": capture.id,
                }
            )
        with self.assertRaises(AccessError):
            user_env["mb.inventory.capture.attempt"].create(
                {
                    "capture_id": capture.id,
                }
            )
        with self.assertRaises(AccessError):
            user_env["mb.inventory.capture.candidate"].create(
                {
                    "capture_id": capture.id,
                }
            )

    def test_phone_image_is_downscaled_to_bounded_sanitized_evidence(self):
        image = Image.new("RGB", (4000, 3100), (20, 30, 40))
        output = io.BytesIO()
        image.save(output, "JPEG", quality=80)
        capture = self.capture()
        capture.upload_image(base64.b64encode(output.getvalue()).decode(), "front")
        asset = capture.asset_ids
        self.assertLessEqual(asset.pixel_width * asset.pixel_height, 12_000_000)

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
        self.assertTrue(
            all(candidate.grounding_state == "grounded" for candidate in capture.candidate_ids)
        )

    def test_external_lookup_keeps_normalized_review_candidate_only(self):
        capture = self.capture()
        response = {
            "provider": "upcitemdb",
            "schema_version": 1,
            "gtin14": "00097539118054",
            "cache": "hit",
            "candidates": [
                {
                    "canonical_id": "upcitemdb:00097539118054",
                    "barcode": "00097539118054",
                    "label": "Mayco SW-106 Alabaster",
                    "source": "upcitemdb_exact_gtin",
                    "confidence": 0.7,
                    "grounded": True,
                    "explanation": "Exact identifier; metadata requires review.",
                }
            ],
        }
        gateway = self.env["mb.ai.gateway"]
        with patch.object(type(gateway), "request", autospec=True, return_value=response):
            result = capture.action_external_barcode_lookup("097539118054")
        self.assertEqual(result["candidate_count"], 1)
        candidate = capture.candidate_ids.filtered(
            lambda item: item.source == "upcitemdb_exact_gtin"
        )
        self.assertEqual(candidate.grounding_state, "grounded")
        self.assertFalse(candidate.product_id)

    def test_manager_created_online_product_keeps_verified_exact_gtin(self):
        capture = self.capture()
        capture.action_record_scan("4006381333931", "ean_13")
        response = {
            "provider": "upcitemdb",
            "schema_version": 1,
            "gtin14": "04006381333931",
            "cache": "miss",
            "candidates": [
                {
                    "canonical_id": "upcitemdb:04006381333931",
                    "barcode": "04006381333931",
                    "label": "Reviewed clay product",
                    "brand": "Fixture Clay",
                    "manufacturer_sku": "CL-42",
                    "pack": "10 kg",
                    "source": "upcitemdb_exact_gtin",
                    "confidence": 0.7,
                    "grounded": True,
                }
            ],
        }
        gateway = self.env["mb.ai.gateway"]
        with patch.object(type(gateway), "request", autospec=True, return_value=response):
            capture.action_external_barcode_lookup("4006381333931")
        candidate = capture.candidate_ids.filtered(
            lambda item: item.source == "upcitemdb_exact_gtin"
        )
        manager = self.env.ref("base.user_admin")
        candidate.with_user(manager).write({"decision": "accepted"})
        candidate.with_user(manager).action_create_reviewed_product()
        self.assertEqual(capture.product_id.barcode, "04006381333931")
        self.assertEqual(capture.product_id.description_purchase, "Fixture Clay · CL-42 · 10 kg")
        self.assertEqual(
            capture.product_id.mb_identifier_ids.filtered(
                lambda item: item.comparison_scheme == "gtin"
            ).verification_state,
            "verified",
        )

    def test_review_candidate_can_be_mapped_to_an_existing_product(self):
        capture = self.capture()
        asset = capture.upload_image(image_data(), "front")
        capture.action_prepare_extraction()
        capture.ingest_result(
            {
                "operation_key": f"inventory:{capture.capture_uuid}:map-product",
                "capture_id": capture.capture_uuid,
                "attempt_id": str(uuid.uuid4()),
                "kind": "multimodal",
                "provider": "fixture-ai",
                "model": "fixture-v1",
                "state": "succeeded",
                "input_digests": [asset["content_sha256"]],
                "normalized_response": {
                    "candidates": [
                        {
                            "kind": "product",
                            "raw_value": "Possible Mayco glaze",
                            "confidence": 0.6,
                            "grounding_state": "unverified",
                        }
                    ]
                },
            }
        )
        candidate = capture.candidate_ids
        candidate.mapped_product_id = self.product

        candidate.action_map_reviewed_product()

        self.assertEqual(candidate.product_id, self.product)
        self.assertEqual(candidate.decision, "accepted")
        self.assertEqual(capture.product_id, self.product)

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
            "version": "2026-08-10",
            "state": "succeeded",
            "input_digests": [asset["content_sha256"]],
            "normalized_response": {
                "candidates": [
                    {
                        "kind": "lot",
                        "raw_value": "8O1B",
                        "confidence": 0.78,
                        "reported_region": [0.1, 0.2, 0.5, 0.3],
                        "grounding_state": "unverified",
                        "source": "ai_suggestion",
                        "asset_id": asset["asset_uuid"],
                    }
                ]
            },
            "raw_response": {"fixture": True},
            "usage": {"images": 1},
        }
        with self.assertRaises(ValidationError):
            capture.ingest_result(payload)
        payload["raw_response"] = {"retained": False}
        result = capture.ingest_result(payload)

        self.assertEqual(result["state"], "review")
        self.assertEqual(len(capture.attempt_ids), 1)
        self.assertEqual(capture.attempt_ids.model_version, "2026-08-10")
        self.assertEqual(capture.candidate_ids.grounding_state, "unverified")
        self.assertEqual(capture.candidate_ids.evidence_asset_ids.asset_uuid, asset["asset_uuid"])
        capture.candidate_ids.with_user(self.env.ref("base.user_admin")).write(
            {
                "decision": "accepted",
            }
        )
        self.assertEqual(capture.proposed_lot, "8O1B")
        with self.assertRaises(ValidationError):
            capture.ingest_result(
                dict(
                    payload,
                    attempt_id=str(uuid.uuid4()),
                    operation_key=f"inventory:{capture.capture_uuid}:2",
                    input_digests=["0" * 64],
                )
            )
        with self.assertRaises(ValidationError):
            capture.ingest_result(
                dict(
                    payload,
                    attempt_id=str(uuid.uuid4()),
                    operation_key=f"inventory:{capture.capture_uuid}:wrong-capture",
                    capture_id=str(uuid.uuid4()),
                )
            )
        with self.assertRaises(ValidationError):
            capture.ingest_result(
                dict(
                    payload,
                    attempt_id=str(uuid.uuid4()),
                    operation_key=f"inventory:{capture.capture_uuid}:wrong-parent",
                    parent_attempt_id=str(uuid.uuid4()),
                )
            )

    def test_ocr_barcode_is_grounded_to_local_product(self):
        capture = self.capture()
        asset = capture.upload_image(image_data(), "front")
        capture.action_prepare_extraction()
        capture.ingest_result(
            {
                "operation_key": f"inventory:{capture.capture_uuid}:ocr-code",
                "capture_id": capture.capture_uuid,
                "attempt_id": str(uuid.uuid4()),
                "kind": "ocr",
                "provider": "fixture-azure",
                "model": "prebuilt-read",
                "state": "succeeded",
                "input_digests": [asset["content_sha256"]],
                "normalized_response": {
                    "candidates": [],
                    "codes": [
                        {
                            "value": "097539118054",
                            "kind": "UPCA",
                            "confidence": 0.98,
                            "polygon": [0.1, 0.2, 0.5, 0.3],
                        }
                    ],
                },
            }
        )

        candidate = capture.candidate_ids.filtered(lambda item: item.source == "ocr_barcode")
        self.assertEqual(candidate.product_id, self.product)
        self.assertEqual(candidate.normalized_value, "00097539118054")
        self.assertEqual(candidate.grounding_state, "grounded")

    def test_ai_product_query_is_grounded_by_provider_as_separate_evidence(self):
        capture = self.capture()
        asset = capture.upload_image(image_data(), "front")
        capture.action_prepare_extraction()
        provider = self.env["mb.inventory.capture.lookup.provider"]
        provider_result = [
            {
                "canonical_id": "mayco/sw-106/473ml",
                "label": self.product.display_name,
                "product_id": self.product.id,
                "source": "fixture_catalogue",
                "confidence": 1.0,
                "grounded": True,
            }
        ]
        with patch.object(type(provider), "lookup", return_value=provider_result) as lookup:
            capture.ingest_result(
                {
                    "operation_key": f"inventory:{capture.capture_uuid}:ai-product",
                    "capture_id": capture.capture_uuid,
                    "attempt_id": str(uuid.uuid4()),
                    "kind": "multimodal",
                    "provider": "fixture-ai",
                    "model": "fixture-v1",
                    "state": "succeeded",
                    "input_digests": [asset["content_sha256"]],
                    "normalized_response": {
                        "candidates": [
                            {
                                "kind": "product",
                                "raw_value": "Mayco SW-106 Alabaster",
                                "normalized_value": "Mayco SW-106 Alabaster 473 ml",
                                "confidence": 0.8,
                                "grounding_state": "unverified",
                                "source": "ai_suggestion",
                            }
                        ]
                    },
                }
            )

        self.assertEqual(lookup.call_args.kwargs["query"], "Mayco SW-106 Alabaster 473 ml")
        ai_candidate = capture.candidate_ids.filtered(lambda item: item.source == "ai_suggestion")
        grounded = capture.candidate_ids.filtered(lambda item: item.source == "fixture_catalogue")
        self.assertEqual(ai_candidate.grounding_state, "unverified")
        self.assertEqual(grounded.grounding_state, "grounded")
        self.assertEqual(grounded.product_id, self.product)
        self.assertNotEqual(ai_candidate.attempt_id, grounded.attempt_id)

    def test_manager_can_create_one_product_from_explicitly_reviewed_candidate(self):
        capture = self.capture()
        asset = capture.upload_image(image_data(), "front")
        capture.action_prepare_extraction()
        capture.ingest_result(
            {
                "operation_key": f"inventory:{capture.capture_uuid}:new-product",
                "capture_id": capture.capture_uuid,
                "attempt_id": str(uuid.uuid4()),
                "kind": "multimodal",
                "provider": "fixture-ai",
                "model": "fixture-v1",
                "state": "succeeded",
                "input_digests": [asset["content_sha256"]],
                "normalized_response": {
                    "candidates": [
                        {
                            "kind": "product",
                            "raw_value": "Reviewed unknown glaze 473 ml",
                            "confidence": 0.7,
                            "grounding_state": "unverified",
                            "source": "ai_suggestion",
                        }
                    ]
                },
            }
        )
        candidate = capture.candidate_ids
        manager = self.env.ref("base.user_admin")
        candidate.with_user(manager).write(
            {
                "decision": "edited",
                "reviewed_value": "Reviewed glaze 473 ml",
            }
        )
        before = self.env["product.product"].search_count([])

        first = candidate.with_user(manager).action_create_reviewed_product()
        second = candidate.with_user(manager).action_create_reviewed_product()

        self.assertEqual(self.env["product.product"].search_count([]), before + 1)
        self.assertEqual(first["res_id"], second["res_id"])
        self.assertEqual(capture.product_id.name, "Reviewed glaze 473 ml")
        self.assertFalse(capture.lot_id)

    def test_unknown_enqueue_outcome_can_be_retried_idempotently(self):
        capture = self.capture()
        capture.upload_image(image_data(), "front")
        capture.company_id.mb_control_workshop_id = str(uuid.uuid4())
        timeout = __import__("requests").Timeout("unknown outcome")
        response = Mock(status_code=202)
        response.raise_for_status.return_value = None
        response.json.return_value = {"operation_id": str(uuid.uuid4())}
        with (
            patch.dict(
                "os.environ",
                {
                    "MB_CONTROL_API_URL": "https://control.example.test",
                    "MB_CONTROL_BRIDGE_TOKEN": "fixture-token",
                },
            ),
            patch(
                "odoo.addons.mb_ai_bridge.models.gateway.requests.post",
                side_effect=[timeout, response],
            ) as post,
        ):
            first = capture.action_prepare_extraction()
            second = capture.action_prepare_extraction()

        self.assertEqual(first["outcome"], "unknown")
        self.assertEqual(second["operation_id"], response.json()["operation_id"])
        self.assertEqual(
            post.call_args_list[0].kwargs["headers"]["Idempotency-Key"],
            post.call_args_list[1].kwargs["headers"]["Idempotency-Key"],
        )

    def test_confirmed_capture_applies_native_lot_to_draft_receipt_line(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.in_type_id.id,
                "location_id": self.warehouse.in_type_id.default_location_src_id.id,
                "location_dest_id": self.warehouse.lot_stock_id.id,
            }
        )
        move = self.env["stock.move"].create(
            {
                "picking_id": picking.id,
                "product_id": self.product.id,
                "product_uom_qty": 2,
                "product_uom": self.product.uom_id.id,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
            }
        )
        move._action_confirm()
        line = move.move_line_ids[:1]
        if not line:
            line = self.env["stock.move.line"].create(
                {
                    "move_id": move.id,
                    "picking_id": picking.id,
                    "product_id": self.product.id,
                    "product_uom_id": self.product.uom_id.id,
                    "location_id": picking.location_id.id,
                    "location_dest_id": picking.location_dest_id.id,
                    "quantity": 2,
                }
            )
        capture = self.capture(picking_id=picking.id, move_id=move.id, move_line_id=line.id)
        capture.action_record_scan("(01)00097539118054(10)00042", "data_matrix")
        capture.action_apply()

        self.assertEqual(capture.state, "applied")
        self.assertEqual(capture.lot_id.name, "00042")
        self.assertEqual(capture.lot_id.product_id, self.product)
        self.assertEqual(line.lot_id, capture.lot_id)
        self.assertEqual(capture.lot_id.mb_supplier_lot_origin, "supplier")

    def test_receipt_capture_resolves_and_updates_its_only_move(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.in_type_id.id,
                "location_id": self.warehouse.in_type_id.default_location_src_id.id,
                "location_dest_id": self.warehouse.lot_stock_id.id,
            }
        )
        move = self.env["stock.move"].create(
            {
                "picking_id": picking.id,
                "product_id": self.product.id,
                "product_uom_qty": 2,
                "product_uom": self.product.uom_id.id,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
            }
        )
        move._action_confirm()
        data = self.env["mb.inventory.capture"].create_for_receipt(picking.id)
        capture = self.env["mb.inventory.capture"].browse(data["id"])
        capture.action_record_scan("(01)00097539118054(10)AUTO-42", "data_matrix")

        capture.action_apply()

        self.assertEqual(capture.state, "applied")
        self.assertEqual(capture.move_id, move)
        self.assertTrue(capture.move_line_id)
        self.assertEqual(capture.move_line_id.lot_id, capture.lot_id)

    def test_cancelling_receipt_cancels_unapplied_capture_without_deleting_evidence(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.in_type_id.id,
                "location_id": self.warehouse.in_type_id.default_location_src_id.id,
                "location_dest_id": self.warehouse.lot_stock_id.id,
            }
        )
        capture = self.capture(picking_id=picking.id)
        capture.upload_image(image_data(), "front")

        picking.action_cancel()

        self.assertEqual(capture.state, "cancelled")
        self.assertTrue(capture.asset_ids)

    def test_alternate_gtin_cannot_shadow_primary_barcode(self):
        other = self.env["product.product"].create(
            {
                "name": "Other glaze",
                "is_storable": True,
            }
        )
        with self.assertRaises(ValidationError):
            self.env["mb.product.identifier"].create(
                {
                    "product_id": other.id,
                    "scheme": "gtin_12",
                    "printed_value": "097539118054",
                    "source": "manual",
                    "verification_state": "verified",
                }
            )

    def test_primary_barcode_is_mirrored_into_global_registry(self):
        identifier = self.env["mb.product.identifier"].search(
            [
                ("comparison_scheme", "=", "gtin"),
                ("normalized_value", "=", "00097539118054"),
            ]
        )
        self.assertEqual(identifier.product_id, self.product)
        self.assertFalse(identifier.company_id)
        self.assertEqual(identifier.source, "primary_barcode")

    def test_existing_primary_barcodes_are_backfilled_in_keyset_batches(self):
        with self.assertRaisesRegex(ValueError, "batch_size must be greater than zero"):
            self.env["product.product"]._register_mb_existing_primary_barcodes(batch_size=0)

        other = self.env["product.product"].create(
            {
                "name": "Other barcoded glaze",
                "barcode": "4006381333931",
            }
        )
        products = self.product | other
        products.mb_identifier_ids.filtered(
            lambda identifier: identifier.source == "primary_barcode"
        ).unlink()

        self.env["product.product"]._register_mb_existing_primary_barcodes(batch_size=1)

        identifiers = self.env["mb.product.identifier"].search(
            [
                ("product_id", "in", products.ids),
                ("source", "=", "primary_barcode"),
            ]
        )
        self.assertEqual(identifiers.product_id, products)

    def test_capture_evidence_is_isolated_by_active_company(self):
        other_company = self.env["res.company"].sudo().create({"name": "Other workshop"})
        other_capture = (
            self.env["mb.inventory.capture"]
            .sudo()
            .with_company(other_company)
            .create({"company_id": other_company.id})
        )
        other_capture.action_record_scan("097539118054", "upc_a")
        for model, record_ids in (
            ("mb.inventory.capture", other_capture.ids),
            ("mb.inventory.capture.attempt", other_capture.attempt_ids.ids),
            ("mb.inventory.capture.candidate", other_capture.candidate_ids.ids),
        ):
            restricted = (
                self.env[model]
                .with_user(self.env.ref("base.user_admin"))
                .with_context(allowed_company_ids=[self.env.company.id])
            )
            self.assertFalse(restricted.search([("id", "in", record_ids)]))

    def test_control_queue_payload_contains_digests_not_image_bytes(self):
        capture = self.capture()
        capture.upload_image(image_data(), "front")
        workshop_id = str(uuid.uuid4())
        capture.company_id.mb_control_workshop_id = workshop_id
        capture.company_id.write(
            {
                "mb_inventory_ai_enabled": True,
                "mb_inventory_vision_primary": "gemini",
                "mb_inventory_vision_secondary": "openai",
            }
        )
        response = Mock(status_code=202)
        response.raise_for_status.return_value = None
        response.json.return_value = {"operation_id": str(uuid.uuid4())}
        with (
            patch.dict(
                "os.environ",
                {
                    "MB_CONTROL_API_URL": "https://control.example.test",
                    "MB_CONTROL_BRIDGE_TOKEN": "fixture-token",
                },
            ),
            patch(
                "odoo.addons.mb_ai_bridge.models.gateway.requests.post",
                return_value=response,
            ) as post,
        ):
            result = capture.action_prepare_extraction()

        queued = post.call_args.kwargs["json"]
        self.assertEqual(result["task"], "inventory_label")
        self.assertNotIn("base64", str(queued).lower())
        self.assertNotIn("data", queued["assets"][0])
        self.assertEqual(len(queued["assets"][0]["content_sha256"]), 64)
        self.assertEqual(
            queued["hints"],
            {
                "allow_ai": True,
                "provider_order": ["gemini", "openai"],
            },
        )
        self.assertEqual(post.call_args.kwargs["allow_redirects"], False)

    def test_retention_purges_only_unapplied_binary_evidence(self):
        capture = self.capture()
        capture.upload_image(image_data(), "front")
        self.env.cr.execute(
            "UPDATE mb_inventory_capture SET write_date = now() - interval '31 days' WHERE id = %s",
            [capture.id],
        )
        capture.invalidate_recordset()
        purged = self.env["mb.inventory.capture"]._cron_purge_unapplied_evidence()
        capture.invalidate_recordset(["asset_ids"])
        self.assertEqual(purged, 1)
        self.assertFalse(capture.asset_ids)
        self.assertTrue(capture.exists())

    def test_safe_tracking_cutover_changes_only_future_tracking_policy(self):
        product = self.env["product.product"].create(
            {
                "name": "New clay body",
                "is_storable": True,
                "tracking": "none",
            }
        )
        wizard = self.env["mb.supplier.lot.migration"].create(
            {
                "product_ids": [(6, 0, product.ids)],
            }
        )
        wizard.action_analyze()
        self.assertEqual(wizard.eligible_product_ids, product)
        wizard.action_apply_safe()
        self.assertEqual(product.tracking, "lot")
        self.assertTrue(product.mb_supplier_lot_required)

    def test_tracking_cutover_blocks_products_with_on_hand_stock(self):
        product = self.env["product.product"].create(
            {
                "name": "Existing clay body",
                "is_storable": True,
                "tracking": "none",
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.warehouse.lot_stock_id,
            1,
        )
        wizard = self.env["mb.supplier.lot.migration"].create(
            {
                "product_ids": [(6, 0, product.ids)],
            }
        )
        wizard.action_analyze()

        self.assertNotIn(product, wizard.eligible_product_ids)
        self.assertIn("blocked", wizard.report)
