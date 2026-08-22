import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sendcloud_qualification as qualification


class FakeClient:
    def __init__(self):
        self.calls = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if path.endswith("/metadata"):
            return {"data": {"integration": "fixture"}}
        if "sender-addresses" in path:
            return {"data": [{"id": 41}, {"id": 42}]}
        if "service-points" in path:
            return {"data": {"results": [{"id": 1}]}}
        raise AssertionError(path)


class SendcloudQualificationTest(unittest.TestCase):
    def test_env_parser_reads_only_sendcloud_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sendcloud.env"
            path.write_text(
                "SENDCLOUD_PUBLIC_KEY=public-123\n"
                "SENDCLOUD_PRIVATE_KEY='private-123456789'\n"
                "UNRELATED_SECRET=do-not-read\n",
                encoding="utf-8",
            )
            values = qualification.load_env(path)
        self.assertEqual(set(values), set(qualification.REQUIRED_KEYS))

    def test_qualification_is_read_only_and_returns_sanitized_summary(self):
        client = FakeClient()
        result = qualification.qualify(
            {
                "SENDCLOUD_QUALIFICATION_COUNTRY": "FR",
                "SENDCLOUD_QUALIFICATION_POSTAL_CODE": "75011",
                "SENDCLOUD_QUALIFICATION_CITY": "Paris",
            },
            client,
        )
        self.assertEqual(result["sender_address_ids"], ["41", "42"])
        self.assertEqual(result["service_point_count"], 1)
        self.assertEqual(result["mutations_performed"], 0)
        self.assertTrue(all(method == "GET" for method, _, _ in client.calls))
        self.assertNotIn("public_key", result)
        self.assertNotIn("private_key", result)


if __name__ == "__main__":
    unittest.main()
