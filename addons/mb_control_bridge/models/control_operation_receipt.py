from odoo import _, fields, models
from odoo.exceptions import ValidationError


class ControlOperationReceipt(models.Model):
    _name = "mb.control.operation.receipt"
    _description = "Applied control-plane operation"
    _order = "create_date desc, id desc"

    operation_key = fields.Char(required=True, readonly=True, index=True)
    command = fields.Char(required=True, readonly=True, index=True)
    payload_digest = fields.Char(required=True, readonly=True)
    response = fields.Json(required=True, readonly=True)

    _operation_key_unique = models.Constraint(
        "UNIQUE(operation_key)",
        "A control-plane operation key can be applied only once.",
    )

    def for_replay(self, operation_key, command, digest):
        receipt = self.search([("operation_key", "=", operation_key)], limit=1)
        if not receipt:
            return self.browse()
        if receipt.command != command or receipt.payload_digest != digest:
            raise ValidationError(_(
                "The operation key was already used with a different command or payload."
            ))
        return receipt

    def record(self, operation_key, command, digest, response):
        return self.create({
            "operation_key": operation_key,
            "command": command,
            "payload_digest": digest,
            "response": response,
        })
