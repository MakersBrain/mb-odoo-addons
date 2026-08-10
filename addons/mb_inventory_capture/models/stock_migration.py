from odoo import _, fields, models
from odoo.exceptions import UserError


class SupplierLotMigration(models.TransientModel):
    _name = "mb.supplier.lot.migration"
    _description = "Supplier lot tracking cutover analysis"

    product_ids = fields.Many2many(
        "product.product", required=True,
        domain="[('is_storable', '=', True)]",
        help="Products whose future receipts must preserve supplier lots.",
    )
    eligible_product_ids = fields.Many2many(
        "product.product", "mb_supplier_lot_migration_eligible_rel",
        string="Safe to update", readonly=True,
    )
    report = fields.Text(readonly=True)
    analyzed = fields.Boolean(readonly=True)

    def action_analyze(self):
        self.ensure_one()
        lines = []
        eligible = self.env["product.product"]
        for product in self.product_ids.sorted("display_name"):
            if product.tracking == "lot":
                lines.append(_("%(product)s: already lot-tracked", product=product.display_name))
                continue
            if product.tracking == "serial":
                lines.append(_("%(product)s: blocked (serial-tracked)", product=product.display_name))
                continue
            has_stock = bool(self.env["stock.quant"].sudo().search_count([
                ("product_id", "=", product.id),
                ("company_id", "=", self.env.company.id),
                ("quantity", "!=", 0),
            ], limit=1))
            if has_stock:
                lines.append(_(
                    "%(product)s: blocked (on-hand stock must be cut over with an explicit "
                    "inventory adjustment and lot allocation)", product=product.display_name,
                ))
                continue
            eligible |= product
            prior_moves = self.env["stock.move"].sudo().search_count([
                ("product_id", "=", product.id), ("state", "=", "done"),
            ], limit=1)
            suffix = _("; historical moves remain unchanged") if prior_moves else ""
            lines.append(_("%(product)s: safe for future lot tracking%(suffix)s",
                           product=product.display_name, suffix=suffix))
        self.write({
            "eligible_product_ids": [(6, 0, eligible.ids)],
            "report": "\n".join(lines) or _("No products selected."),
            "analyzed": True,
        })
        return self._reopen()

    def action_apply_safe(self):
        self.ensure_one()
        if not self.analyzed:
            raise UserError(_("Analyze the selected products before applying the cutover."))
        if not self.eligible_product_ids:
            raise UserError(_("No products are safe to update."))
        # Re-run immediately before writing so stock received after analysis
        # cannot slip through the cutover.
        selected = self.eligible_product_ids
        self.action_analyze()
        if selected != self.eligible_product_ids:
            raise UserError(_("Stock changed after analysis. Review the refreshed report."))
        self.eligible_product_ids.write({
            "tracking": "lot",
            "mb_supplier_lot_required": True,
        })
        self.report += _("\nUpdated %(count)s product(s).", count=len(selected))
        return self._reopen()

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
