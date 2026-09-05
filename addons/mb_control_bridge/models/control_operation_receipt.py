from psycopg2.errors import UniqueViolation

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class _ConcurrentOperationReceipt(Exception):
    """Move a unique-index race outside its rolled-back savepoint."""


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

    @api.private
    def for_replay(self, operation_key, command, digest):
        receipt = self.search([("operation_key", "=", operation_key)], limit=1)
        if not receipt:
            return self.browse()
        if receipt.command != command or receipt.payload_digest != digest:
            raise ValidationError(
                _("The operation key was already used with a different command or payload.")
            )
        return receipt

    @api.private
    def record(self, operation_key, command, digest, response):
        return self.create(
            {
                "operation_key": operation_key,
                "command": command,
                "payload_digest": digest,
                "response": response,
            }
        )

    def _execute_once(self, operation_key, command, digest, action):
        """Run a mutation and its success receipt as one retryable unit."""
        try:
            with self.env.cr.savepoint():
                if operation_key:
                    receipt = self.for_replay(operation_key, command, digest)
                    if receipt:
                        return receipt.response
                response = action()
                if operation_key:
                    try:
                        self.record(operation_key, command, digest, response)
                    except UniqueViolation as error:
                        raise _ConcurrentOperationReceipt from error
                return response
        except _ConcurrentOperationReceipt:
            # REPEATABLE READ cannot see the winner after waiting on its unique
            # index entry. Raise a *database-originated* 40001 after the business
            # savepoint has rolled back. Odoo's request layer recognizes its
            # pgcode, retries in a fresh transaction, and then replays the winner.
            self.env.cr.execute(
                """
                    DO $$
                    BEGIN
                        RAISE EXCEPTION USING
                            ERRCODE = '40001',
                            MESSAGE = 'concurrent control-operation receipt';
                    END
                    $$
                """
            )
            raise AssertionError("PostgreSQL did not raise serialization_failure") from None
