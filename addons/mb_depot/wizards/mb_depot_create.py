from odoo import _, fields, models
from odoo.exceptions import UserError

# Setting a group here rather than through res.config.settings is deliberate. A
# settings record carries every setting, so writing one also writes back
# whatever its own defaults resolved to, and
# product/models/res_config_settings.py archives EVERY pricelist when
# group_product_pricelist comes out falsy. Implied groups are the surgical
# equivalent with no side effects.
REQUIRED_FEATURES = [
    "stock.group_stock_multi_locations",   # depot locations at all
    "stock.group_adv_location",            # the route that sources from them
    "product.group_product_pricelist",     # the commission
    "sale.group_discount_per_so_line",     # shown as a discount, not a lower price
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
    commission = fields.Float(
        string="Commission (%)",
        default=40.0,
        digits="Discount",
        required=True,
    )
    warehouse_id = fields.Many2one(
        comodel_name="stock.warehouse",
        string="Sourced from",
        required=True,
        default=lambda self: self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1),
        help="The warehouse whose delivery operation type ships the sales made "
             "from this depot.",
    )
    assign_pricelist = fields.Boolean(
        string="Assign the pricelist to the depositary",
        default=True,
    )

    def _depot_root(self):
        """The parentless view location the depots hang from.

        Not under the warehouse: internal keeps depot stock on our books, but
        being outside WH keeps an ordinary delivery from reserving a piece that
        is physically in a gallery, since those source from WH/Stock and its
        children. Odoo 19 has no "Physical Locations" root any more - WH is
        itself a parentless view location - so the depots get their own.
        """
        root = self.env["stock.location"].search(
            [("name", "=", "Dépôts"), ("location_id", "=", False),
             ("usage", "=", "view")], limit=1)
        if not root:
            root = self.env["stock.location"].create({
                "name": "Dépôts", "usage": "view", "location_id": False,
            })
        return root

    def _enable_features(self):
        group_user = self.env.ref("base.group_user")
        implied = []
        for xmlid in REQUIRED_FEATURES:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                implied.append(fields.Command.link(group.id))
        if implied:
            group_user.sudo().write({"implied_ids": implied})

    def action_create(self):
        self.ensure_one()
        if self.commission < 0 or self.commission >= 100:
            raise UserError(_("A commission must be between 0 and 100 percent."))

        self._enable_features()
        Location = self.env["stock.location"]
        root = self._depot_root()

        existing = Location.search([
            ("depot_partner_id", "=", self.partner_id.id), ("is_depot", "=", True),
        ], limit=1)
        if existing:
            raise UserError(_(
                "%(partner)s already has the depot %(location)s.",
                partner=self.partner_id.display_name,
                location=existing.complete_name,
            ))

        location = Location.create({
            "name": self.partner_id.name,
            "usage": "internal",
            "location_id": root.id,
            "company_id": self.env.company.id,
            "is_depot": True,
            "depot_partner_id": self.partner_id.id,
            "depot_commission": self.commission,
        })

        # One route per depot, selected on the quotation, rather than a
        # warehouse per depot. Same sourcing, none of the picking-type and
        # sequence sprawl a warehouse brings with it.
        route = self.env["stock.route"].create({
            "name": _("Dépôt-vente: %s", self.partner_id.name),
            "sale_selectable": True,
            "product_selectable": False,
            "company_id": self.env.company.id,
            "sequence": 20,
        })
        self.env["stock.rule"].create({
            "name": _("%s → Customer", self.partner_id.name),
            "route_id": route.id,
            "action": "pull",
            "location_src_id": location.id,
            "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            "picking_type_id": self.warehouse_id.out_type_id.id,
            "procure_method": "make_to_stock",
            "warehouse_id": self.warehouse_id.id,
            "company_id": self.env.company.id,
        })

        # compute_price must be 'percentage': under 'formula' the percentage is
        # folded into the unit price and the invoice shows a quietly cheaper
        # piece instead of the commission. See _show_discount() in
        # sale/models/product_pricelist_item.py.
        pricelist = self.env["product.pricelist"].create({
            "name": _("%(partner)s (-%(pct)s%%)",
                      partner=self.partner_id.name,
                      pct=("%g" % self.commission)),
            "currency_id": self.env.company.currency_id.id,
            "company_id": self.env.company.id,
            "item_ids": [fields.Command.create({
                "applied_on": "3_global",
                "compute_price": "percentage",
                "percent_price": self.commission,
            })],
        })
        if self.assign_pricelist:
            self.partner_id.property_product_pricelist = pricelist

        location.write({
            "depot_route_id": route.id,
            "depot_pricelist_id": pricelist.id,
        })

        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.location",
            "res_id": location.id,
            "view_mode": "form",
            "target": "current",
        }
