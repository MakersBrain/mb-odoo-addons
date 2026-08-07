"""Turning a catalogue package into an Odoo unit of measure, and a catalogue
observation into a price Odoo may put on a purchase order.

Both conversions can fail, and both fail silently if written carelessly - a
VAT-inclusive figure copied into product.supplierinfo.price is wrong by the VAT
rate on every purchase order that follows, and nothing in Odoo will ever say so.
So each returns an explicit reason instead of a best guess.
"""

from odoo import api, models

# Every unit that appears in the loaded catalogue, reduced to millilitres or
# grams. The imperial units are US measure, which is not an assumption: they
# occur only on amaco, speedball and hiclay, all US storefronts. A UK pint is
# 568 ml, so a British source publishing pints would need its own entry here
# rather than falling through to this table.
_TO_BASE = {
    "ml": (1.0, "ml"),
    "l": (1000.0, "ml"),
    "cl": (10.0, "ml"),
    "fl oz": (29.5735, "ml"),
    "pint": (473.176, "ml"),
    "quart": (946.353, "ml"),
    "gallon": (3785.41, "ml"),
    "g": (1.0, "g"),
    "kg": (1000.0, "g"),
    "lb": (453.592, "g"),
    "pound": (453.592, "g"),
    "oz": (28.3495, "g"),
}

# Odoo's own units, by the base this addon reduces to. Verified against the
# running Odoo 19 image: these xmlids exist, and uom.uom there is the reworked
# model with relative_factor/relative_uom_id rather than the old category_id.
_BASE_UOM_XMLID = {
    "ml": "uom.product_uom_milliliter",
    "g": "uom.product_uom_gram",
}


class MbCatalogueUnits(models.AbstractModel):
    _name = "mb.catalogue.units"
    _description = "Catalogue package and price conversions"

    @api.model
    def _package_to_uom(self, quantity, unit):
        """(quantity, unit) -> (quantity_in_base, uom record) or (None, None).

        A package Odoo cannot express is not an error and not a zero: it is a
        product that gets no pack variant, and the supplier's own listing stays
        the only place that says how big the jar is.
        """
        if not quantity or not unit:
            return None, None
        factor, base = _TO_BASE.get(unit.strip().lower(), (None, None))
        if factor is None:
            return None, None
        return quantity * factor, self.env.ref(_BASE_UOM_XMLID[base])

    @api.model
    def _pack_key(self, quantity):
        """Group the packs that are one jar published two ways.

        8 US fl oz is 236.6 ml, and shops round it to 236 or 237; 16 oz becomes
        472 or 473. Keyed on the raw number, one Mayco glaze acquires six pack
        variants where it has four real ones, and an artisan's stock of "473 ml
        Hot Tamale" splits across two of them.

        Two significant figures merges those spellings without merging sizes that
        differ for real - 473 and 500 stay apart. It is not perfect: 59 and 60 ml
        are the same 2 oz jar and this keeps them separate. That case is rarer
        than the one it fixes, and a wrong merge is worse than a wrong split.
        """
        if not quantity:
            return None
        magnitude = 10 ** (len(str(int(abs(quantity)))) - 2)
        return int(round(quantity / magnitude) * magnitude) if magnitude >= 1 else round(quantity)

    @api.model
    def _net_price(self, price, vat_status, vat_rate):
        """(price, reason) - the tax-excluded price, or None and why not.

        product.supplierinfo.price is a net price: Odoo adds tax on top of it.
        Feeding it a VAT-inclusive figure overstates purchase cost and therefore
        understates margin, quietly, forever.

        Neither argument usually comes from the offer. 44% of catalogue offers
        carry no vat_status, and only 1,026 of 132,622 raw records carry a
        vat_rate. Both are properties of the shop and of what this workshop is
        registered for, so both fall back to the vendor mapping - see
        mb.catalogue.supplier. What is never done is inferring either from the
        price, which is how a 20% error becomes permanent and invisible.
        """
        if price is None:
            return None, "no_price"
        if vat_status == "exclusive":
            return price, None
        if vat_status == "inclusive":
            if not vat_rate:
                return None, "inclusive_without_rate"
            # The dump writes a rate either as a percentage (20.0) or a fraction
            # (0.2), depending on what the storefront published.
            rate = vat_rate / 100.0 if vat_rate > 1 else vat_rate
            return price / (1.0 + rate), None
        return None, "unknown_vat_status"
