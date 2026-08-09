import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Setting a group here rather than through res.config.settings is deliberate. A
# settings record carries every setting, so writing one also writes back
# whatever its own defaults resolved to, and
# product/models/res_config_settings.py archives EVERY pricelist when
# group_product_pricelist comes out falsy. Implied groups are the surgical
# equivalent with no side effects.
REQUIRED_FEATURES = [
    "stock.group_stock_multi_locations",     # locations inside the depot at all
    "stock.group_stock_multi_warehouses",    # ...and the Warehouse field that picks one
    "product.group_product_pricelist",       # the commission
    "sale.group_discount_per_so_line",       # shown as a discount, not a lower price
]


class MbDepotCreate(models.TransientModel):
    _name = "mb.depot.create"
    _description = "Create a dépôt-vente"

    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Depositary",
        required=True,
        domain=[("is_company", "=", True)],
    )
    code = fields.Char(
        string="Short name",
        size=5,
        compute="_compute_code",
        store=True,
        readonly=False,
        required=True,
        # Required and stored, so it has to exist before the INSERT rather than
        # after it.
        precompute=True,
        help="Prefixes the depot's transfer references. Five characters, Odoo's "
             "limit, and unique across warehouses.",
    )
    commission = fields.Float(
        string="Commission (%)",
        default=40.0,
        digits="Discount",
        required=True,
    )
    assign_pricelist = fields.Boolean(
        string="Assign the pricelist to the depositary",
        default=True,
    )

    @api.depends("partner_id")
    def _compute_code(self):
        for wizard in self:
            wizard.code = wizard._suggest_code(wizard.partner_id.name or "")

    @api.model
    def _suggest_code(self, name):
        """Five letters from the depositary's name, then digits until it is free.

        Odoo caps stock.warehouse.code at five characters and every transfer
        reference in the depot carries it, so it is worth it being recognisable
        rather than generated.
        """
        letters = re.sub(r"[^A-Za-z0-9]", "", name).upper()[:5]
        if not letters:
            return False
        Warehouse = self.env["stock.warehouse"].with_context(active_test=False)
        candidate, suffix = letters, 0
        while Warehouse.search_count([("code", "=", candidate)]):
            suffix += 1
            candidate = "%s%d" % (letters[:5 - len(str(suffix))], suffix)
        return candidate

    def _enable_features(self):
        group_user = self.env.ref("base.group_user")
        implied = []
        for xmlid in REQUIRED_FEATURES:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                implied.append(fields.Command.link(group.id))
        if implied:
            group_user.sudo().write({"implied_ids": implied})

    def _ensure_warehouse(self):
        """The depot's warehouse, adopting one that is already there.

        One step in and out: a gallery has a shelf, not a receiving bay, and
        multi-step would split one sale into two moves the statement would have
        to learn to ignore.
        """
        Warehouse = self.env["stock.warehouse"]
        warehouse = Warehouse.search([
            ("is_depot", "=", True), ("depot_partner_id", "=", self.partner_id.id),
        ], limit=1)
        if warehouse:
            warehouse.depot_commission = self.commission
            return warehouse
        # partner_id is deliberately left at the company's own address rather
        # than set to the depositary. stock.warehouse._update_partner_data()
        # rewrites its partner's property_stock_customer to the inter-warehouse
        # transit location, on the reasoning that a warehouse's partner is
        # another site of ours. A depositary is not: it is the customer we
        # invoice, and pointing its customer location at transit makes every
        # sale to it fail with "no rule to replenish in Inter-warehouse
        # transit". The depositary is carried by depot_partner_id, which has no
        # such side effect.
        return Warehouse.create({
            "name": self.partner_id.name,
            "code": self.code,
            "company_id": self.env.company.id,
            "reception_steps": "one_step",
            "delivery_steps": "ship_only",
            "is_depot": True,
            "depot_partner_id": self.partner_id.id,
            "depot_commission": self.commission,
        })

    def _ensure_pricelist(self, warehouse):
        """compute_price must be 'percentage': under 'formula' the percentage is
        folded into the unit price and the invoice shows a quietly cheaper piece
        instead of the commission. See _show_discount() in
        sale/models/product_pricelist_item.py.
        """
        name = _("%(partner)s (-%(pct)s%%)",
                 partner=self.partner_id.name, pct=("%g" % self.commission))
        item_values = {
            "applied_on": "3_global",
            "compute_price": "percentage",
            "percent_price": self.commission,
        }
        pricelist = warehouse.depot_pricelist_id
        if pricelist:
            # Re-running with a renegotiated percentage is the reason to run it
            # again at all, so the existing global item is moved rather than
            # left beside a new one that would not deterministically win.
            item = pricelist.item_ids.filtered(
                lambda i: i.applied_on == "3_global")[:1]
            if item:
                item.write(item_values)
            else:
                pricelist.write({"item_ids": [fields.Command.create(item_values)]})
            pricelist.name = name
        else:
            pricelist = self.env["product.pricelist"].create({
                "name": name,
                "currency_id": self.env.company.currency_id.id,
                "company_id": self.env.company.id,
                "item_ids": [fields.Command.create(item_values)],
            })
        return pricelist

    def action_create(self):
        self.ensure_one()
        if self.commission < 0 or self.commission >= 100:
            raise UserError(_("A commission must be between 0 and 100 percent."))

        self._enable_features()

        # Idempotent on purpose: the set of things a depot needs has to agree
        # with itself, and a depot whose commission has been renegotiated is
        # brought up to date by running this again rather than by hand.
        warehouse = self._ensure_warehouse()
        pricelist = self._ensure_pricelist(warehouse)

        if self.assign_pricelist:
            self.partner_id.property_product_pricelist = pricelist

        warehouse.depot_pricelist_id = pricelist

        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.warehouse",
            "res_id": warehouse.id,
            "view_mode": "form",
            "target": "current",
        }
