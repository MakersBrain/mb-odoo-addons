"""The catalogue service this tenant reads, and the import it performs.

Import is on demand and per product. The catalogue holds ~47,000 supplier
listings over 76 shops; an artisan uses a few dozen materials. Pulling the
catalogue into a tenant would be both useless to them and a copy of the
strongest asset in the product sitting in a database we hand to a customer.
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

# ir.model.data module for everything this addon imports. A reserved name, not a
# real module: it keeps imported records out of the way of an addon upgrade
# while still giving every one of them a stable external id.
IMD_MODULE = "__mb_catalogue__"


class MbCatalogueService(models.Model):
    _name = "mb.catalogue.service"
    _description = "Master catalogue service"

    name = fields.Char(required=True, default="Makersbrain catalogue")
    base_url = fields.Char(
        string="Base URL", required=True,
        help="Root URL of the catalogue read API.")
    # TODO(control-plane): per POC-PLAN section 5.1 a tenant should hold a
    # reference to a credential, not the credential. This field is the stand-in
    # until mb_connected_account exists.
    api_key = fields.Char(string="API key", groups="base.group_system")
    active = fields.Boolean(default=True)
    last_import_at = fields.Datetime(string="Last import", readonly=True)
    last_import_summary = fields.Text(string="Last import summary", readonly=True)

    _base_url_unique = models.Constraint(
        "unique(base_url)",
        "That catalogue service is already configured.",
    )

    # -- search ------------------------------------------------------------

    def action_search(self, query, limit=25):
        """Search the master catalogue. Returns payloads, imports nothing.

        This is what the artisan-facing picker calls: they search "PC-20" or
        "hot tamale", see what the catalogue knows, and choose. Nothing enters
        the tenant's product list until they do.
        """
        self.ensure_one()
        return self.env["mb.catalogue.client"]._get(
            self, "/v1/canonical-products", {"q": query, "limit": limit}
        )

    def action_lookup_barcode(self, barcode, limit=10):
        """Exact normalized barcode lookup; imports nothing."""
        self.ensure_one()
        return self.env["mb.catalogue.client"]._get(
            self, "/v1/canonical-products", {"barcode": barcode, "limit": limit}
        )

    # -- import ------------------------------------------------------------

    def action_import(self, canonical_ids):
        """Import canonical products by id, and refresh the offers of the
        suppliers this workshop buys from.

        Idempotent: importing the same id twice updates one product.template and
        creates no second one. That property comes from ir.model.data, not from
        matching on name - two Mayco glazes can share a name, and a matcher that
        merged them would be undiscoverable afterwards.
        """
        self.ensure_one()
        if not canonical_ids:
            return {"imported": 0, "updated": 0, "offers": 0, "refused": {}}

        payload = self.env["mb.catalogue.client"]._get(
            self, "/v1/canonical-products", {"ids": ",".join(canonical_ids)}
        )
        products = payload.get("products") or []
        if not products:
            raise UserError(_("The catalogue returned nothing for those products."))

        summary = {"imported": 0, "updated": 0, "offers": 0, "refused": {}}
        for record in products:
            template, created = self.env["product.template"]._mb_upsert_canonical(record)
            summary["imported" if created else "updated"] += 1
            offers, refused = template._mb_sync_supplier_offers(record.get("offers") or [])
            summary["offers"] += offers
            for reason, count in refused.items():
                summary["refused"][reason] = summary["refused"].get(reason, 0) + count

        self.write({
            "last_import_at": fields.Datetime.now(),
            "last_import_summary": self._format_summary(summary),
        })
        return summary

    @api.model
    def _format_summary(self, summary):
        lines = [
            _("%(created)s created, %(updated)s updated, %(offers)s supplier prices.",
              created=summary["imported"], updated=summary["updated"],
              offers=summary["offers"]),
        ]
        # Refusals are reported, never hidden. An import that silently dropped
        # half the offers looks exactly like a supplier that has no prices.
        for reason, count in sorted(summary["refused"].items()):
            lines.append(_("Refused %(reason)s: %(count)s", reason=reason, count=count))
        return "\n".join(lines)
