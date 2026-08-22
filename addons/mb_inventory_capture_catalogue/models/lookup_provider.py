from odoo import _, api, models


class InventoryCaptureCatalogueLookup(models.AbstractModel):
    _inherit = "mb.inventory.capture.lookup.provider"

    @api.model
    def lookup(self, *, barcode=None, query=None, limit=10):
        candidates = list(super().lookup(barcode=barcode, query=query, limit=limit))
        service = self.env["mb.catalogue.service"].search([("active", "=", True)], limit=1)
        if not service:
            return candidates
        payload = (
            service.action_lookup_barcode(barcode, limit=limit)
            if barcode
            else service.action_search(query, limit=limit)
        )
        for record in (payload.get("products") or [])[:limit]:
            canonical_id = str(record.get("canonical_product_id") or "")
            if not canonical_id:
                continue
            template = self.env["product.template"]._mb_find_by_canonical(canonical_id)
            label = " ".join(
                filter(
                    None,
                    [
                        record.get("brand"),
                        record.get("manufacturer_sku"),
                        record.get("canonical_name"),
                    ],
                )
            )
            variants = template.product_variant_ids if template else self.env["product.product"]
            if variants:
                for variant in variants:
                    candidates.append(
                        {
                            "canonical_id": f"catalogue:{canonical_id}",
                            "label": variant.display_name,
                            "product_id": variant.id,
                            "source": "mb_catalogue",
                            "confidence": 1.0 if barcode else 0.85,
                            "grounded": True,
                            "explanation": _(
                                "Verified catalogue identity %(identity)s", identity=canonical_id
                            ),
                        }
                    )
            else:
                candidates.append(
                    {
                        "canonical_id": f"catalogue:{canonical_id}",
                        "label": label,
                        "source": "mb_catalogue",
                        "confidence": 1.0 if barcode else 0.75,
                        "grounded": True,
                        "explanation": _(
                            "Catalogue match; import or map it before applying inventory."
                        ),
                    }
                )
        return candidates
