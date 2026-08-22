from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.l10n_fr_micro_urssaf.models.internal import internal_context


class UrssafDeclarationSource(models.Model):
    _inherit = "l10n.fr.micro.urssaf.declaration.source"

    # This is a legal-evidence snapshot, not a computed mirror of the source
    # documents. Draft evidence follows its POS order/invoice through write(),
    # while filing freezes the value with the rest of the declaration source.
    mb_commercial_operation_id = fields.Many2one(
        "mb.commercial.operation",
        string="Commercial Operation",
        readonly=True,
        copy=False,
        index=True,
        ondelete="restrict",
    )

    @api.model
    def _mb_resolve_commercial_operation(self, pos_order, origin_move, company):
        pos_operation = pos_order.mb_commercial_operation_id
        invoice_operation = origin_move.mb_commercial_operation_id
        if pos_operation and invoice_operation and pos_operation != invoice_operation:
            raise ValidationError(
                _(
                    "URSSAF receipt evidence cannot link POS order %(order)s "
                    "(%(pos_operation)s) and invoice %(invoice)s "
                    "(%(invoice_operation)s) because they belong to different "
                    "commercial operations.",
                    order=pos_order.display_name,
                    pos_operation=pos_operation.display_name,
                    invoice=origin_move.display_name,
                    invoice_operation=invoice_operation.display_name,
                )
            )
        operation = pos_operation or invoice_operation
        return operation if operation.company_id == company else self.env["mb.commercial.operation"]

    def _mb_operation_from_values(self, values):
        self.ensure_one()
        pos_order = (
            self.env["pos.order"].browse(values.get("pos_order_id"))
            if "pos_order_id" in values
            else self.pos_order_id
        )
        origin_move = (
            self.env["account.move"].browse(values.get("origin_move_id"))
            if "origin_move_id" in values
            else self.origin_move_id
        )
        declaration = (
            self.env["l10n.fr.micro.urssaf.declaration"].browse(values.get("declaration_id"))
            if "declaration_id" in values
            else self.declaration_id
        )
        return self._mb_resolve_commercial_operation(
            pos_order,
            origin_move,
            declaration.company_id,
        )

    @api.model_create_multi
    def create(self, values_list):
        prepared = []
        for original_values in values_list:
            values = dict(original_values)
            pos_order = self.env["pos.order"].browse(values.get("pos_order_id"))
            origin_move = self.env["account.move"].browse(values.get("origin_move_id"))
            declaration = self.env["l10n.fr.micro.urssaf.declaration"].browse(
                values.get("declaration_id")
            )
            operation = self._mb_resolve_commercial_operation(
                pos_order,
                origin_move,
                declaration.company_id,
            )
            values["mb_commercial_operation_id"] = operation.id or False
            prepared.append(values)
        return super().create(prepared)

    def write(self, values):
        attribution_fields = {
            "declaration_id",
            "pos_order_id",
            "origin_move_id",
            "mb_commercial_operation_id",
        }
        if not attribution_fields.intersection(values):
            return super().write(values)

        # A multi-record write may span declarations or source documents and
        # therefore cannot safely share one snapshot value.
        result = True
        for source in self:
            source_values = dict(values)
            operation = source._mb_operation_from_values(source_values)
            source_values["mb_commercial_operation_id"] = operation.id or False
            result = super(UrssafDeclarationSource, source).write(source_values) and result
        return result

    def _mb_validate_and_sync_commercial_operation(self):
        """Validate and refresh draft snapshots through the evidence write()."""
        # Filed rows are snapshots. Resolving their live document links here
        # would make unrelated later edits capable of invalidating frozen
        # evidence, even though the snapshot itself must not change.
        for source in self.filtered(lambda record: record.declaration_state == "draft"):
            operation = source._mb_operation_from_values({})
            if source.mb_commercial_operation_id != operation:
                source.with_context(**internal_context()).write(
                    {"mb_commercial_operation_id": operation.id or False}
                )


class PosOrder(models.Model):
    _inherit = "pos.order"

    def write(self, values):
        result = super().write(values)
        if "mb_commercial_operation_id" in values:
            sources = (
                self.env["l10n.fr.micro.urssaf.declaration.source"]
                .sudo()
                .search([("pos_order_id", "in", self.ids)])
            )
            sources._mb_validate_and_sync_commercial_operation()
        return result


class AccountMove(models.Model):
    _inherit = "account.move"

    def write(self, values):
        result = super().write(values)
        if "mb_commercial_operation_id" in values:
            sources = (
                self.env["l10n.fr.micro.urssaf.declaration.source"]
                .sudo()
                .search([("origin_move_id", "in", self.ids)])
            )
            sources._mb_validate_and_sync_commercial_operation()
        return result
