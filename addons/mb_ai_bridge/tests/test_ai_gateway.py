import os
import uuid
from unittest.mock import Mock, patch

import requests

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


class FixtureAiGateway:
    """Mixin attached to the abstract model registry by the test module."""


@tagged("post_install", "-at_install")
class TestAiGateway(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.mb_control_workshop_id = str(uuid.uuid4())
        cls.gateway = cls.env["mb.ai.gateway"]

    def contracts(self):
        return {
            "fixture": {
                "path": "internal/v1/workshops/{workshop_id}/fixture-ai",
                "connect_timeout": 1,
                "read_timeout": 2,
            },
            "fixture-request": {
                "path": "internal/v1/workshops/{workshop_id}/fixture-request",
                "mode": "request",
            },
        }

    def test_descriptor_job_is_submitted_with_idempotency(self):
        response = Mock(status_code=202)
        response.raise_for_status.return_value = None
        operation_id = str(uuid.uuid4())
        response.json.return_value = {"operation_id": operation_id}
        with (
            patch.object(type(self.gateway), "_task_contracts", autospec=True,
                         return_value=self.contracts()),
            patch.dict(os.environ, {
                "MB_CONTROL_API_URL": "https://control.internal",
                "MB_CONTROL_BRIDGE_TOKEN": "secret",
            }),
            patch("odoo.addons.mb_ai_bridge.models.gateway.requests.post",
                  return_value=response) as post,
        ):
            result = self.gateway.submit(
                company=self.company,
                task="fixture",
                operation_key="fixture:1",
                payload={"assets": [{"asset_id": str(uuid.uuid4())}]},
            )
        self.assertEqual(result, {"outcome": "accepted", "operation_id": operation_id})
        self.assertEqual(post.call_args.kwargs["headers"]["Idempotency-Key"], "fixture:1")
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_image_bytes_and_credentials_are_rejected(self):
        for payload in (
            {"source_base64": "AAAA"},
            {"nested": {"api_key": "secret"}},
        ):
            with self.assertRaises(ValidationError):
                self.gateway._validate_payload(payload)

    def test_timeout_has_unknown_outcome_for_safe_retry(self):
        with (
            patch.object(type(self.gateway), "_task_contracts", autospec=True,
                         return_value=self.contracts()),
            patch.dict(os.environ, {
                "MB_CONTROL_API_URL": "https://control.internal",
                "MB_CONTROL_BRIDGE_TOKEN": "secret",
            }),
            patch("odoo.addons.mb_ai_bridge.models.gateway.requests.post",
                  side_effect=requests.Timeout),
        ):
            result = self.gateway.submit(
                company=self.company,
                task="fixture",
                operation_key="fixture:timeout",
                payload={"assets": [{"asset_id": str(uuid.uuid4())}]},
            )
        self.assertEqual(result["outcome"], "unknown")

    def test_callback_rejects_raw_provider_body(self):
        payload = {
            "kind": "multimodal",
            "provider": "fixture",
            "model": "fixture-v1",
            "attempt_id": str(uuid.uuid4()),
            "raw_response": {"provider_body": "must not persist"},
        }
        with self.assertRaises(ValidationError):
            self.gateway.validate_callback_envelope(payload, kinds={"multimodal"})

        payload["raw_response"] = {"retained": False}
        metadata = self.gateway.validate_callback_envelope(
            payload, kinds={"multimodal"},
        )
        self.assertEqual(metadata["diagnostic"], {"retained": False})

    def test_bounded_synchronous_task_returns_normalized_object(self):
        response = Mock(status_code=200, content=b'{"candidates":[]}')
        response.raise_for_status.return_value = None
        response.json.return_value = {"candidates": []}
        with (
            patch.object(type(self.gateway), "_task_contracts", autospec=True,
                         return_value=self.contracts()),
            patch.dict(os.environ, {
                "MB_CONTROL_API_URL": "https://control.internal",
                "MB_CONTROL_BRIDGE_TOKEN": "secret",
            }),
            patch("odoo.addons.mb_ai_bridge.models.gateway.requests.post",
                  return_value=response) as post,
        ):
            result = self.gateway.request(
                company=self.company, task="fixture-request", payload={"value": "safe"},
            )
        self.assertEqual(result, {"candidates": []})
        self.assertNotIn("Idempotency-Key", post.call_args.kwargs["headers"])
