"""Search the master catalogue and import what the artisan actually uses.

This is the whole point of the addon being on-demand. The catalogue holds tens of
thousands of supplier listings; a workshop uses a few dozen materials. Bulk
import would put a manufacturer's entire range in front of someone who bought
four glazes, and every one of those products would then need managing forever.

So: type what is on the jar, see what the catalogue knows, tick the ones you
have, import those.
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


class MbCatalogueImport(models.TransientModel):
    _name = "mb.catalogue.import"
    _description = "Import materials from the master catalogue"

    service_id = fields.Many2one(
        "mb.catalogue.service", string="Catalogue", required=True,
        default=lambda self: self.env["mb.catalogue.service"].search([], limit=1))
    query = fields.Char(
        string="Search",
        help="A manufacturer code or a product name: PC-20, SC74, hot tamale. "
             "Punctuation in a code does not matter.")
    manufacturer = fields.Char(help="Restrict to one manufacturer id, e.g. mayco.")
    line_ids = fields.One2many("mb.catalogue.import.line", "wizard_id")
    result_count = fields.Integer(compute="_compute_result_count")

    @api.depends("line_ids")
    def _compute_result_count(self):
        for wizard in self:
            wizard.result_count = len(wizard.line_ids)

    def action_search(self):
        """Fill the list from the catalogue. Imports nothing."""
        self.ensure_one()
        if not self.service_id:
            raise UserError(_("No catalogue service is configured."))

        params = {"limit": 80}
        if self.query:
            params["q"] = self.query
        if self.manufacturer:
            params["manufacturer"] = self.manufacturer

        payload = self.env["mb.catalogue.client"]._get(
            self.service_id, "/v1/canonical-products", params)
        products = payload.get("products") or []

        # Which of these the workshop already has, so the list says so rather
        # than silently importing something twice and looking like it worked.
        template = self.env["product.template"]
        existing = {
            product.mb_canonical_id: product
            for product in template.search(
                [("mb_canonical_id", "in", [p["canonical_product_id"] for p in products])])
        }

        self.line_ids.unlink()
        self.line_ids = [(0, 0, {
            "canonical_id": product["canonical_product_id"],
            "brand": product.get("brand"),
            "manufacturer_sku": product.get("manufacturer_sku"),
            "name": product.get("canonical_name"),
            "family": product.get("family"),
            "firing_range": product.get("firing_range"),
            "source_count": product.get("source_count") or 0,
            "unit_price_low": product.get("min_price_per_litre")
                              or product.get("min_price_per_kg") or 0.0,
            "unit_price_high": product.get("max_price_per_litre")
                               or product.get("max_price_per_kg") or 0.0,
            "unit_price_per": "l" if product.get("min_price_per_litre") else "kg",
            "product_tmpl_id": existing.get(product["canonical_product_id"], template).id,
        }) for product in products]

        return self._reopen()

    def action_import(self):
        """Import the ticked lines, then show what was created."""
        self.ensure_one()
        chosen = self.line_ids.filtered("selected")
        if not chosen:
            raise UserError(_("Tick at least one material to import."))

        summary = self.service_id.action_import(chosen.mapped("canonical_id"))
        templates = self.env["product.template"].search(
            [("mb_canonical_id", "in", chosen.mapped("canonical_id"))])

        message = _("%(created)s created, %(updated)s updated, "
                    "%(offers)s supplier prices.",
                    created=summary["imported"], updated=summary["updated"],
                    offers=summary["offers"])
        if summary["refused"]:
            # Said out loud. An import that quietly dropped every price looks
            # exactly like a supplier that has none.
            message += "\n" + "\n".join(
                _("Refused %(reason)s: %(count)s", reason=reason, count=count)
                for reason, count in sorted(summary["refused"].items()))
        _logger.info("catalogue import: %s", message.replace("\n", " | "))

        return {
            "type": "ir.actions.act_window",
            "name": _("Imported materials"),
            "res_model": "product.template",
            "view_mode": "list,form",
            "domain": [("id", "in", templates.ids)],
            "context": {"create": False},
        }

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_select_all(self):
        self.ensure_one()
        self.line_ids.filtered(lambda line: not line.product_tmpl_id).selected = True
        return self._reopen()


class MbCatalogueImportLine(models.TransientModel):
    _name = "mb.catalogue.import.line"
    _description = "One catalogue search result"
    _order = "source_count desc, brand, manufacturer_sku"

    wizard_id = fields.Many2one("mb.catalogue.import", required=True, ondelete="cascade")
    selected = fields.Boolean(string="Import")
    canonical_id = fields.Char(required=True)
    brand = fields.Char(string="Manufacturer", readonly=True)
    manufacturer_sku = fields.Char(string="Code", readonly=True)
    name = fields.Char(readonly=True)
    family = fields.Char(readonly=True)
    firing_range = fields.Char(string="Firing", readonly=True)
    # How many shops carry it: the strongest signal that a code is the one meant,
    # and the reason the list is ordered by it.
    source_count = fields.Integer(string="Suppliers", readonly=True)
    unit_price_low = fields.Float(string="From", readonly=True, digits=(12, 2))
    unit_price_high = fields.Float(string="To", readonly=True, digits=(12, 2))
    unit_price_per = fields.Selection(
        [("l", "per litre"), ("kg", "per kg")], readonly=True)
    # Set when the workshop already has it, which is why the row is not tickable.
    product_tmpl_id = fields.Many2one(
        "product.template", string="Already imported", readonly=True)
