from odoo import api, models


class InventoryCaptureLookupProvider(models.AbstractModel):
    _name = "mb.inventory.capture.lookup.provider"
    _description = "Inventory capture product lookup provider"

    @api.model
    def lookup(self, *, barcode=None, query=None, limit=10):
        """Return provider-neutral product candidates without importing records.

        Connector addons extend this hook. Keeping the no-op provider in the
        capture addon prevents a hard dependency on any particular catalogue.
        """
        return []
