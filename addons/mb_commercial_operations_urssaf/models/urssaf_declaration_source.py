from odoo import api, fields, models


class UrssafDeclarationSource(models.Model):
    _inherit = "l10n.fr.micro.urssaf.declaration.source"

    # A recognised turnover event reaches a commercial operation through
    # whichever document produced it -- a POS order or a customer invoice.
    # Resolving that link into a stored column buys two things the previous
    # per-operation scan could not have:
    #
    #   - the operation's evidence becomes an indexed read rather than a
    #     search over every source in the company followed by a Python filter;
    #   - it is a real relation, so the operation can declare an ORM
    #     dependency on it that actually invalidates when a declaration moves.
    mb_commercial_operation_id = fields.Many2one(
        "mb.commercial.operation",
        string="Commercial Operation",
        compute="_compute_mb_commercial_operation_id",
        store=True,
        index=True,
        ondelete="set null",
    )

    @api.depends(
        "company_id",
        "pos_order_id.mb_commercial_operation_id",
        "origin_move_id.mb_commercial_operation_id",
    )
    def _compute_mb_commercial_operation_id(self):
        for source in self:
            operation = (
                source.pos_order_id.mb_commercial_operation_id
                or source.origin_move_id.mb_commercial_operation_id
            )
            # The declaration and the operation must belong to the same
            # company. The scan this replaces enforced that with its domain,
            # and a declaration must not claim another company's turnover.
            source.mb_commercial_operation_id = (
                operation if operation.company_id == source.company_id else False
            )
