"""Where a catalogue identity becomes a product in this tenant.

The shape, decided once and relied on everywhere downstream:

    product.template          one manufacturer product   Mayco SC74 Hot Tamale
      product.product         one pack size              473 ml, 118 ml, pint
        product.supplierinfo  one vendor's price for it  Ceradel, 26.88 EUR

The pack belongs on the variant and not on the template because that is what the
catalogue already says: every record carries a parent_external_id grouping the
sizes of one product. Splitting the sizes into separate templates would make
"which pack is cheapest per litre" unanswerable in Odoo, which is most of why an
artisan looks at a supplier price at all.
"""

import logging

from odoo import api, fields, models

from .mb_catalogue_service import IMD_MODULE

_logger = logging.getLogger(__name__)

# The catalogue's material families, mapped onto the taxonomy mb_workshop_base
# owns. Odoo already filters, groups and reports on categ_id everywhere, so a
# family field of our own would be a second taxonomy saying the same thing - and
# the two would disagree the first time anyone touched either.
#
# The categories are not defined here, and that is the point of the dependency:
# a workshop that imports nothing still buys glaze and still owes a migration
# test on the food-contact ware it makes with it, so the taxonomy cannot live
# behind a connector. This addon maps onto it; mb_workshop_base enforces with it.
#
# A family this addon has never heard of lands on the parent category rather than
# nowhere, so it is visible and correctable instead of silently uncategorised.
FAMILY_CATEGORY = {
    "glaze": "mb_ceramics_base.categ_glaze",
    "underglaze": "mb_ceramics_base.categ_underglaze",
    "engobe": "mb_ceramics_base.categ_engobe",
    "clay_body": "mb_ceramics_base.categ_clay_body",
    "stain": "mb_ceramics_base.categ_stain",
    "oxide": "mb_ceramics_base.categ_oxide",
    "raw_material": "mb_ceramics_base.categ_raw_material",
}
FAMILY_FALLBACK = "mb_ceramics_base.categ_ceramic_materials"


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # Provenance only. The ceramics fields - firing range, cone, atmosphere,
    # shrinkage, food-safe - belong to mb_ceramics_material per POC-PLAN section
    # 4, and this addon writes them through the hook at the bottom rather than
    # declaring a second, competing set.
    mb_canonical_id = fields.Char(
        string="Catalogue id", index=True, copy=False, readonly=True,
        help="Identifier of the curated identity in the master catalogue.")
    mb_manufacturer = fields.Char(string="Manufacturer", readonly=True)
    mb_manufacturer_sku = fields.Char(
        string="Manufacturer code", index=True, readonly=True,
        help="The maker's own code (PC-20, SC74). The only key that compares "
             "across suppliers; a shop's article number is never promoted to it.")
    mb_catalogue_synced_at = fields.Datetime(string="Last catalogue sync", readonly=True)

    # -- identity ----------------------------------------------------------

    @api.model
    def _mb_xmlid(self, canonical_id):
        return f"canonical_{canonical_id}".replace("-", "_")

    @api.model
    def _mb_find_by_canonical(self, canonical_id):
        data = self.env["ir.model.data"].search([
            ("module", "=", IMD_MODULE),
            ("name", "=", self._mb_xmlid(canonical_id)),
            ("model", "=", "product.template"),
        ], limit=1)
        if not data:
            return self.browse()
        # A user may have deleted the product; the external id can outlive it.
        return self.browse(data.res_id).exists()

    @api.model
    def _mb_upsert_canonical(self, record):
        """(template, created). Idempotent on the canonical id."""
        canonical_id = record["canonical_product_id"]
        template = self._mb_find_by_canonical(canonical_id)
        values = {
            "mb_canonical_id": canonical_id,
            "mb_manufacturer": record.get("brand"),
            "mb_manufacturer_sku": record.get("manufacturer_sku"),
            "mb_catalogue_synced_at": fields.Datetime.now(),
        }
        # Written when empty rather than on creation only, which is the opposite
        # of the rule for `name` below. An empty category or code is not a choice
        # anybody made, so filling it takes nothing away; a name always exists,
        # so overwriting one always does.
        if not template or not template.categ_id:
            values["categ_id"] = self.env.ref(
                FAMILY_CATEGORY.get(record.get("family"), FAMILY_FALLBACK)).id
        created = not template
        if created:
            values.update({
                # Set once, on creation only. After that the name is the
                # artisan's: they rename a glaze to what they call it on the
                # shelf, and a nightly refresh that renamed it back would be a
                # bug they cannot fix.
                "name": record.get("canonical_name") or record.get("manufacturer_sku"),
                "type": "consu",
                "is_storable": True,
                "purchase_ok": True,
                "sale_ok": False,
            })
            template = self.create(values)
            self.env["ir.model.data"].create({
                "module": IMD_MODULE,
                "name": self._mb_xmlid(canonical_id),
                "model": "product.template",
                "res_id": template.id,
                # The record belongs to the tenant once imported; an addon
                # upgrade must not overwrite what they have since edited.
                "noupdate": True,
            })
        else:
            template.write(values)

        template._mb_apply_ceramics(record)
        template._mb_sync_pack_variants(record.get("offers") or [])
        template._mb_apply_default_code(record.get("manufacturer_sku"))
        return template, created

    def _mb_apply_default_code(self, manufacturer_sku):
        """Put the manufacturer code on the variants, not on the template.

        `product.template.default_code` is a stored field computed from the
        variants: it mirrors the code when a template has exactly one, and is
        False the moment it has two. Writing it on the template therefore looks
        like it works - the value is stored, and it survives right up until
        something recomputes it, at which point every multi-pack product loses
        its code at once and nothing says why.

        So the code goes where Odoo keeps it. A single-pack product still shows
        it on the template, because the compute puts it there.

        The same code on every pack is deliberate: SC74 identifies the glaze, not
        the jar, and Odoo renders the variant as "[SC74] Hot Tamale (473 ml)". The
        per-pack reference that differs is the vendor's, and that already lives on
        product.supplierinfo.product_code.

        Written only where empty, like the category.
        """
        self.ensure_one()
        if not manufacturer_sku:
            return
        variants = self.product_variant_ids.filtered(lambda v: not v.default_code)
        if variants:
            variants.write({"default_code": manufacturer_sku})

    # -- packs -------------------------------------------------------------

    def _mb_pack_label(self, quantity, uom):
        """"473 ml", "1000 g" - what the artisan sees in the variant selector."""
        rounded = int(quantity) if float(quantity).is_integer() else round(quantity, 2)
        return f"{rounded} {uom.name}"

    def _mb_parse_pack_label(self, label):
        """A label this addon wrote, back to (quantity, uom name)."""
        try:
            quantity, unit = label.rsplit(" ", 1)
            return float(quantity), unit
        except ValueError:
            # A label a person typed by hand. Left alone rather than guessed at.
            return None, None

    def _mb_sync_pack_variants(self, offers):
        """Give the template one variant per distinct pack the catalogue knows.

        Only ever adds. A pack that disappears from the catalogue keeps its
        variant, because the artisan may hold stock of it and Odoo cannot
        archive a variant that has stock moves without rewriting history.
        """
        self.ensure_one()
        units = self.env["mb.catalogue.units"]
        attribute = self.env.ref("mb_catalogue_sync.attribute_pack_size")

        # Group first, then label. The label is the most frequently published
        # quantity in its group, so a jar fifteen shops call 473 ml is not
        # renamed to 470 ml by the one shop that calls it 472.
        groups = {}
        for offer in offers:
            quantity, uom = units._package_to_uom(
                offer.get("package_quantity"), offer.get("package_unit"))
            if not quantity:
                continue
            key = (units._pack_key(quantity), uom.id)
            groups.setdefault(key, []).append((quantity, uom))

        labels = {}
        for members in groups.values():
            quantities = [quantity for quantity, _uom in members]
            # Most frequently published; then a whole number, which means a
            # figure a shop actually printed rather than one this addon produced
            # by converting a pint; then the largest.
            #
            # The last two are tie-breaks for determinism, not for correctness -
            # 8 oz is 236.6 ml and 236 and 237 are both roundings of it. What
            # matters is that the label is the same on every run, because an
            # arbitrary winner renames the variant each time a supplier is added.
            common = max(set(quantities),
                         key=lambda value: (quantities.count(value),
                                            float(value).is_integer(),
                                            value))
            labels[self._mb_pack_label(common, members[0][1])] = True
        if not labels:
            return

        value_model = self.env["product.attribute.value"]
        pack_values = value_model.browse()
        for label in sorted(labels):
            value = value_model.search(
                [("attribute_id", "=", attribute.id), ("name", "=", label)], limit=1)
            if not value:
                value = value_model.create({"attribute_id": attribute.id, "name": label})
            pack_values |= value

        line = self.attribute_line_ids.filtered(lambda l: l.attribute_id == attribute)
        if line:
            missing = pack_values - line.value_ids
            if missing:
                line.value_ids = [(4, value.id) for value in missing]
        else:
            self.attribute_line_ids = [(0, 0, {
                "attribute_id": attribute.id,
                "value_ids": [(6, 0, pack_values.ids)],
            })]

    def _mb_variant_for_pack(self, quantity, uom):
        """The product.product carrying that pack, if the template has one.

        Matched on the same grouping key the variants were built with, not on the
        label: the offer that says 472 ml belongs on the variant labelled 473 ml.
        """
        self.ensure_one()
        units = self.env["mb.catalogue.units"]
        wanted = (units._pack_key(quantity), uom.name)
        for variant in self.product_variant_ids:
            for name in variant.product_template_attribute_value_ids.mapped("name"):
                found_quantity, found_unit = self._mb_parse_pack_label(name)
                if found_quantity and (units._pack_key(found_quantity), found_unit) == wanted:
                    return variant
        return self.env["product.product"]

    # -- supplier prices ---------------------------------------------------

    def _mb_sync_supplier_offers(self, offers):
        """(written, refused). One supplierinfo per mapped vendor and pack.

        Three things are deliberately not imported:

        - offers from sources this workshop has not mapped to a vendor. A glaze
          sold by fifteen shops would otherwise put fifteen vendors in front of
          an artisan who buys from one.
        - the distributor's stock level. It is the most volatile field in the
          catalogue and Odoo has nowhere honest to put it: stock in Odoo means
          stock this company owns.
        - any price whose VAT basis is unknown, which is 44% of them today. See
          mb.catalogue.units._net_price.
        """
        self.ensure_one()
        units = self.env["mb.catalogue.units"]
        suppliers = self.env["mb.catalogue.supplier"]._by_source()
        info = self.env["product.supplierinfo"]
        written, refused = 0, {}

        def refuse(reason):
            refused[reason] = refused.get(reason, 0) + 1

        for offer in offers:
            supplier = suppliers.get(offer.get("source_id"))
            if not supplier:
                refuse("source_not_mapped")
                continue

            # What the listing states wins; what the vendor mapping configures
            # fills the silence. Neither is inferred from the price itself.
            price, reason = units._net_price(
                offer.get("price"),
                offer.get("vat_status") or supplier.vat_status,
                offer.get("vat_rate") or supplier.vat_rate,
            )
            if reason:
                refuse(reason)
                continue

            # active_test=False: Odoo ships every currency but activates only the
            # ones a company uses, and a vendor billing in SEK is exactly the case
            # where the currency is not active yet.
            currency = self.env["res.currency"].with_context(active_test=False).search(
                [("name", "=", offer.get("currency"))], limit=1)
            if not currency:
                # Refused rather than converted. The catalogue's EUR figures come
                # from ECB daily reference rates and are indicative, not the rate
                # this artisan will actually be billed at.
                refuse("unknown_currency")
                continue

            quantity, uom = units._package_to_uom(
                offer.get("package_quantity"), offer.get("package_unit"))
            variant = self._mb_variant_for_pack(quantity, uom) if quantity else None

            minimum_quantity = offer.get("min_order_quantity") or 0.0
            values = {
                "partner_id": supplier.partner_id.id,
                "product_tmpl_id": self.id,
                "product_id": variant.id if variant else False,
                "price": price,
                "currency_id": currency.id,
                "min_qty": minimum_quantity,
                "delay": supplier.delay,
                "product_uom_id": uom.id if uom else self.uom_id.id,
                "product_code": offer.get("supplier_reference") or False,
                "product_name": offer.get("supplier_name") or False,
            }
            existing = info.search([
                ("partner_id", "=", supplier.partner_id.id),
                ("product_tmpl_id", "=", self.id),
                ("product_id", "=", variant.id if variant else False),
                ("company_id", "=", self.env.company.id),
                ("min_qty", "=", minimum_quantity),
            ], limit=1)
            if existing:
                existing.write(values)
            else:
                info.create(values)
            written += 1

        return written, refused

    # -- hook --------------------------------------------------------------

    def _mb_apply_ceramics(self, record):
        """Overridden by mb_ceramics_material to write firing range, cone,
        family and the rest. A no-op here so this addon stays installable on its
        own and owns no ceramics field it does not define."""
        return
