from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class MbProductionLoss(models.Model):
    _name = "mb.production.loss"
    _description = "Ceramics production loss"
    _order = "date desc, id desc"
    _check_company_auto = True

    production_id = fields.Many2one(
        "mrp.production", required=True, ondelete="restrict", index=True,
        domain=[("mb_workflow_kind", "in", ("bisque", "glazing", "finishing"))],
        check_company=True)
    product_id = fields.Many2one(related="production_id.product_id", store=True)
    quantity = fields.Float(required=True, digits="Product Unit")
    operation_id = fields.Many2one(
        "mrp.workorder", string="Operation", ondelete="restrict",
        check_company=True)
    reason = fields.Text(required=True)
    date = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    user_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, readonly=True)
    board_id = fields.Many2one(
        "stock.package", ondelete="restrict", check_company=True)
    firing_id = fields.Many2one(
        "mb.firing", ondelete="restrict", check_company=True)
    company_id = fields.Many2one(
        related="production_id.company_id", store=True, required=True, index=True,
        precompute=True)

    _positive_quantity = models.Constraint(
        "CHECK(quantity > 0)", "A process-loss quantity must be positive.")

    @api.constrains("operation_id", "production_id", "firing_id")
    def _check_links(self):
        for loss in self:
            if loss.operation_id and loss.operation_id.production_id != loss.production_id:
                raise ValidationError("The loss operation must belong to its manufacturing order.")
            if loss.firing_id and loss.operation_id.mb_firing_id != loss.firing_id:
                raise ValidationError("The loss firing must be the operation's firing.")

    def write(self, values):
        if not self.env.context.get("mb_allow_loss_correction"):
            raise UserError("Production loss is immutable; create a correcting entry instead.")
        return super().write(values)

    def unlink(self):
        raise UserError("Production loss is immutable and cannot be deleted.")
