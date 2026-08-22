"""The catalogue sources this workshop actually buys from."""

from odoo import api, fields, models


class MbCatalogueSupplier(models.Model):
    """A catalogue source this workshop actually buys from.

    Only these produce product.supplierinfo. Without the mapping, importing a
    glaze sold by fifteen shops would put fifteen vendors and fifteen prices in
    front of an artisan who buys from one.
    """

    _name = "mb.catalogue.supplier"
    _description = "Catalogue source mapped to a vendor"

    source_id = fields.Char(
        required=True,
        string="Catalogue source",
        help="The source id in the catalogue, e.g. 'ceradel' or 'les-cousins'.",
    )
    partner_id = fields.Many2one(
        "res.partner", required=True, string="Vendor", domain=[("is_company", "=", True)]
    )
    active = fields.Boolean(default=True)
    # A supplier's own currency, when it differs from the company's. The catalogue
    # publishes prices in EUR, PLN, SEK, USD and GBP; Odoo needs to be told which
    # one this vendor bills in rather than converting behind the artisan's back.
    currency_id = fields.Many2one("res.currency")
    delay = fields.Integer(string="Delivery lead time", default=0)

    # The VAT basis of this vendor's published prices, and the rate to undo.
    #
    # These are here rather than read off the offer because the data cannot
    # supply them: 44% of catalogue offers carry no vat_status, and only 1,026 of
    # 132,622 raw records carry a vat_rate at all. A storefront's VAT basis is a
    # property of the shop, and the rate is a property of the shop's country and
    # of what this workshop is registered for - both facts a person knows and a
    # crawler does not.
    #
    # An offer that states its own basis still wins over these. They are the
    # fallback, not an override.
    vat_status = fields.Selection(
        [("inclusive", "Prices include VAT"), ("exclusive", "Prices exclude VAT")],
        string="Published prices",
        help="What this vendor's listed prices mean, when the listing does not say.",
    )
    vat_rate = fields.Float(
        string="VAT rate (%)",
        help="Used to convert this vendor's VAT-inclusive prices to the net price "
        "Odoo stores. Leave empty to refuse inclusive prices rather than guess.",
    )

    _source_unique = models.Constraint(
        "unique(source_id)",
        "That catalogue source is already mapped.",
    )

    @api.model
    def _by_source(self):
        return {supplier.source_id: supplier for supplier in self.search([])}
