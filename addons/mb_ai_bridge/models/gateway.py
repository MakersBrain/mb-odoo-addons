import json
import os
import re
from urllib.parse import urljoin, urlparse

import requests

from odoo import _, api, models
from odoo.exceptions import UserError, ValidationError

MAX_JOB_PAYLOAD_CHARS = 131_072
MAX_OPERATION_KEY_CHARS = 255
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
FORBIDDEN_PAYLOAD_KEYS = {
    "api_key",
    "authorization",
    "credentials",
    "image_base64",
    "key",
    "secret",
    "source_base64",
    "token",
}


def _walk_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key).lower()
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


class AiGateway(models.AbstractModel):
    _name = "mb.ai.gateway"
    _description = "Provider-neutral MakersBrain AI gateway"

    @api.model
    def _task_contracts(self):
        """Return code-owned task definitions keyed by a stable task name.

        A domain addon extends this mapping with ``path`` and optional timeout
        values. Paths are never accepted from a browser or a business record.
        """
        return {}

    @api.model
    def _contract(self, task):
        contract = self._task_contracts().get(task)
        if not isinstance(contract, dict):
            raise ValidationError(_("The requested AI task is not registered."))
        path = contract.get("path")
        if not isinstance(path, str) or not path.startswith("internal/v1/workshops/"):
            raise ValidationError(_("The AI task has an invalid internal route."))
        return contract

    @api.model
    def _validate_payload(self, payload):
        if not isinstance(payload, dict):
            raise ValidationError(_("An AI job payload must be an object."))
        forbidden = FORBIDDEN_PAYLOAD_KEYS.intersection(_walk_keys(payload))
        if forbidden:
            raise ValidationError(
                _("AI job payloads may contain descriptors, never image bytes or credentials.")
            )
        try:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as error:
            raise ValidationError(_("The AI job payload must be valid JSON.")) from error
        if len(encoded) > MAX_JOB_PAYLOAD_CHARS:
            raise ValidationError(_("The AI job payload exceeds the descriptor limit."))

    @api.model
    def submit(self, *, company, task, operation_key, payload):
        company.ensure_one()
        workshop_id = str(company.mb_control_workshop_id or "").lower()
        if not UUID_RE.fullmatch(workshop_id):
            raise UserError(_("This company is not linked to a control-plane workshop."))
        operation_key = str(operation_key or "")
        if (
            not operation_key
            or len(operation_key) > MAX_OPERATION_KEY_CHARS
            or any(character in operation_key for character in "\r\n")
        ):
            raise ValidationError(_("The AI operation key is invalid."))
        self._validate_payload(payload)
        contract = self._contract(task)

        base_url = os.environ.get("MB_CONTROL_API_URL", "").strip().rstrip("/")
        token = os.environ.get("MB_CONTROL_BRIDGE_TOKEN", "")
        parsed_url = urlparse(base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname or not token:
            raise UserError(_("The MakersBrain AI gateway is not configured."))
        relative_path = contract["path"].format(workshop_id=workshop_id)
        endpoint = urljoin(f"{base_url}/", relative_path)
        timeout = (
            float(contract.get("connect_timeout", 3.05)),
            float(contract.get("read_timeout", 10)),
        )
        try:
            response = requests.post(
                endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": operation_key,
                },
                timeout=timeout,
                allow_redirects=False,
            )
            response.raise_for_status()
            result = response.json()
            operation_id = str(result.get("operation_id") or "").lower()
            if response.status_code != 202 or not UUID_RE.fullmatch(operation_id):
                raise ValueError("gateway returned an invalid acceptance response")
            return {"outcome": "accepted", "operation_id": operation_id}
        except requests.Timeout:
            # The endpoint is durable and idempotent, so a timeout can mean that
            # the operation was accepted. The caller may retry the same key.
            return {"outcome": "unknown", "operation_id": False}
        except (requests.RequestException, ValueError) as error:
            raise UserError(_("The AI request could not be queued. Try again.")) from error

    @api.model
    def request(self, *, company, task, payload):
        """Run a bounded synchronous broker task returning normalized JSON."""
        company.ensure_one()
        workshop_id = str(company.mb_control_workshop_id or "").lower()
        if not UUID_RE.fullmatch(workshop_id):
            raise UserError(_("This company is not linked to a control-plane workshop."))
        self._validate_payload(payload)
        contract = self._contract(task)
        if contract.get("mode") != "request":
            raise ValidationError(_("This AI task does not allow synchronous requests."))
        base_url = os.environ.get("MB_CONTROL_API_URL", "").strip().rstrip("/")
        token = os.environ.get("MB_CONTROL_BRIDGE_TOKEN", "")
        parsed_url = urlparse(base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname or not token:
            raise UserError(_("The MakersBrain AI gateway is not configured."))
        endpoint = urljoin(
            f"{base_url}/",
            contract["path"].format(workshop_id=workshop_id),
        )
        timeout = (
            float(contract.get("connect_timeout", 3.05)),
            float(contract.get("read_timeout", 15)),
        )
        try:
            response = requests.post(
                endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
                allow_redirects=False,
            )
            response.raise_for_status()
            if response.status_code != 200 or len(response.content) > MAX_JOB_PAYLOAD_CHARS:
                raise ValueError("gateway returned an invalid synchronous response")
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("gateway returned a non-object response")
            return result
        except requests.Timeout as error:
            raise UserError(_("The AI request timed out; try again.")) from error
        except (requests.RequestException, ValueError) as error:
            raise UserError(_("The AI request failed; try again.")) from error

    @api.model
    def validate_callback_envelope(self, payload, *, kinds):
        """Validate provider-neutral callback metadata shared by domain addons."""
        if not isinstance(payload, dict):
            raise ValidationError(_("The AI callback must be an object."))
        kind = payload.get("kind")
        if kind not in set(kinds):
            raise ValidationError(_("The AI callback kind is not allowed for this task."))
        provider = str(payload.get("provider") or "").strip()
        model = str(payload.get("model") or "").strip()
        if not provider or len(provider) > 128 or not model or len(model) > 128:
            raise ValidationError(_("The AI callback provider and model are invalid."))
        diagnostic = payload.get("raw_response") or {}
        if diagnostic not in ({}, {"retained": False}):
            raise ValidationError(_("Raw AI provider responses must not be retained in Odoo."))
        attempt_id = str(payload.get("attempt_id") or "").lower()
        if not UUID_RE.fullmatch(attempt_id):
            raise ValidationError(_("The AI callback attempt ID is invalid."))
        request_id = str(payload.get("request_id") or "")
        if len(request_id) > 255 or any(character in request_id for character in "\r\n"):
            raise ValidationError(_("The AI callback request ID is invalid."))
        return {
            "kind": kind,
            "provider": provider,
            "model": model,
            "attempt_id": attempt_id,
            "diagnostic": diagnostic,
            "request_id": request_id,
        }
