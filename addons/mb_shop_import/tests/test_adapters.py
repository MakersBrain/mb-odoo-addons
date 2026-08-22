import gzip
import io
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from odoo.tests import TransactionCase, tagged

from ..models.adapters import AdapterError, detect, parse
from ..models.image_fetch import ImageFetchError, _sanitize, _validated_address

FIXTURES = Path(__file__).parent / "fixtures"


@tagged("post_install", "-at_install")
class TestShopImportAdapters(TransactionCase):
    def test_catalogue_v2_and_gzip_normalize_exact_variant_identity(self):
        data = (FIXTURES / "emily-sample.ndjson").read_bytes()
        self.assertEqual(detect(data, "sample.ndjson"), "catalogue_v2")
        plain = parse(data, "sample.ndjson", "emily-alarcon")
        compressed = parse(gzip.compress(data), "sample.ndjson.gz", "emily-alarcon")
        self.assertEqual(len(plain.rows), 5)
        self.assertEqual(plain.rows, compressed.rows)
        self.assertFalse(plain.rows[0]["identity_is_fallback"])
        self.assertTrue(plain.rows[0]["stock_is_tracked"])
        self.assertFalse(plain.rows[1]["stock_is_tracked"])
        self.assertEqual(plain.rows[3]["variant_title"], "Bleu")
        self.assertEqual(plain.currency, "EUR")

    def test_scraper_csv_marks_fallback_identity_and_preserves_null_stock(self):
        data = (FIXTURES / "emily-sample.csv").read_bytes()
        self.assertEqual(detect(data, "sample.csv"), "catalogue_csv")
        artifact = parse(data, "sample.csv", "emily-alarcon")
        self.assertEqual(len(artifact.rows), 3)
        self.assertTrue(all(row["identity_is_fallback"] for row in artifact.rows))
        self.assertFalse(artifact.rows[1]["stock_is_tracked"])
        self.assertIsNone(artifact.rows[1]["stock_quantity"])

    def test_mixed_sources_and_duplicate_external_ids_are_rejected(self):
        row = (FIXTURES / "emily-sample.ndjson").read_text().splitlines()[0]
        duplicate = (row + "\n" + row + "\n").encode()
        with self.assertRaisesRegex(AdapterError, "duplicate external IDs"):
            parse(duplicate, "duplicate.ndjson", "emily-alarcon")
        other = duplicate.replace(b'"source":"emily-alarcon"', b'"source":"other"', 1)
        with self.assertRaisesRegex(AdapterError, "mixes more than one source"):
            parse(other, "mixed.ndjson", "emily-alarcon")

    def test_missing_source_and_non_finite_price_are_rejected(self):
        row = (FIXTURES / "emily-sample.ndjson").read_text().splitlines()[0]
        with self.assertRaisesRegex(AdapterError, "no scraper source"):
            parse(
                row.replace('"source":"emily-alarcon"', '"source":""').encode(),
                "missing-source.ndjson",
                "emily-alarcon",
            )
        with self.assertRaisesRegex(AdapterError, "finite number"):
            parse(
                row.replace('"price":28.0', '"price":"NaN"').encode(), "nan.ndjson", "emily-alarcon"
            )

    def test_image_address_validation_rejects_internal_destinations(self):
        with patch(
            "socket.getaddrinfo",
            return_value=[
                (2, 1, 6, "", ("127.0.0.1", 443)),
            ],
        ):
            with self.assertRaisesRegex(ImageFetchError, "non-public"):
                _validated_address("images.example")

    def test_image_decode_normalizes_a_real_png(self):
        output = io.BytesIO()
        Image.new("RGB", (8, 8), "blue").save(output, "PNG")
        data, media_type = _sanitize(output.getvalue(), "image/png")
        self.assertEqual(media_type, "image/jpeg")
        self.assertTrue(data.startswith(b"\xff\xd8"))
