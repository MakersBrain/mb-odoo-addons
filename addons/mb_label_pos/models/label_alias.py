import unicodedata
from urllib.parse import unquote

from odoo import api, fields, models

from odoo.addons.mb_label.models.label_template import normalize_qr, normalize_qr_url_prefix


def parse_prefixed_identity(value, prefixes):
    value = unicodedata.normalize("NFKC", value or "").strip()
    for raw_prefix in prefixes:
        prefix = normalize_qr_url_prefix(raw_prefix)
        marker = "%s#" % prefix
        if not prefix or not value.startswith(marker):
            continue
        encoded = value[len(marker):]
        parts = encoded.split("/")
        if len(parts) not in (1, 2) or not all(parts):
            return {"matched": True, "error": "invalid"}
        try:
            decoded = [unicodedata.normalize("NFKC", unquote(part)).strip() for part in parts]
        except (UnicodeDecodeError, ValueError):
            return {"matched": True, "error": "invalid"}
        if not all(decoded):
            return {"matched": True, "error": "invalid"}
        return {
            "matched": True,
            "sku": decoded[0],
            "lot_name": decoded[1] if len(decoded) == 2 else False,
        }
    return {"matched": False}


class MbLabelQrAlias(models.Model):
    _name = "mb.label.qr.alias"
    _inherit = ["mb.label.qr.alias", "pos.load.mixin"]

    pos_available_quantity = fields.Float(compute="_compute_pos_available_quantity")

    def _compute_pos_available_quantity(self):
        for alias in self:
            alias.pos_available_quantity = 0.0

    @api.model
    def _pos_available_quantity(self, product, lot, config):
        if not product.is_storable:
            return None
        location = config.picking_type_id.default_location_src_id
        if not location:
            return 0.0
        return self.env["stock.quant"]._get_available_quantity(
            product, location, lot_id=lot or None, strict=False)

    @api.model
    def _load_pos_data_domain(self, data, config):
        template_domain = self.env["product.template"]._load_pos_data_domain(data, config)
        available_templates = self.env["product.template"].search(template_domain)
        return [
            ("company_id", "=", config.company_id.id),
            ("product_id.product_tmpl_id", "in", available_templates.ids),
        ]

    @api.model
    def _load_pos_data_fields(self, config):
        return [
            "id", "value", "active", "product_id", "lot_name", "qr_url_prefix",
            "pos_available_quantity",
        ]

    @api.model
    def _load_pos_data_search_read(self, data, config):
        return super(MbLabelQrAlias, self.with_context(active_test=False))._load_pos_data_search_read(
            data, config)

    @api.model
    def _load_pos_data_read(self, records, config):
        rows = super()._load_pos_data_read(records, config)
        aliases = self.with_context(active_test=False).browse([row["id"] for row in rows])
        storable_aliases = aliases.filtered("product_id.is_storable")
        product_ids = storable_aliases.product_id.ids
        available_by_product = dict.fromkeys(product_ids, 0.0)
        available_by_lot = {}
        location = config.picking_type_id.default_location_src_id
        if product_ids and location:
            # Match stock.quant._get_available_quantity(), which is sudoed.
            # The source location and products are already bounded by the POS
            # config and its product projection.
            grouped_quants = self.env["stock.quant"].sudo()._read_group(
                [
                    ("location_id", "child_of", location.id),
                    ("product_id", "in", product_ids),
                ],
                ["product_id", "lot_id"],
                ["quantity:sum", "reserved_quantity:sum"],
            )
            tracked_products = storable_aliases.product_id.filtered(
                lambda product: product.tracking != "none"
            )
            tracked_product_ids = set(tracked_products.ids)
            for product, lot, quantity, reserved_quantity in grouped_quants:
                available = quantity - reserved_quantity
                if product.id in tracked_product_ids:
                    # Match stock.quant._get_available_quantity(): negative
                    # tracked buckets do not consume another lot's stock.
                    available = max(available, 0.0)
                available_by_product[product.id] += available
                available_by_lot[(product.id, lot.id or False)] = available

        by_id = {}
        for alias in aliases:
            if not alias.product_id.is_storable:
                by_id[alias.id] = None
            elif not location:
                by_id[alias.id] = 0.0
            elif alias.lot_id:
                # A non-strict lot lookup includes untracked stock, exactly as
                # stock.quant._get_available_quantity() does.
                by_id[alias.id] = max(
                    available_by_lot.get((alias.product_id.id, alias.lot_id.id), 0.0)
                    + available_by_lot.get((alias.product_id.id, False), 0.0),
                    0.0,
                )
            else:
                by_id[alias.id] = max(available_by_product[alias.product_id.id], 0.0)
        for row in rows:
            row["pos_available_quantity"] = by_id[row["id"]]
        return rows

    @api.model
    def pos_resolve(self, value, config_id):
        config = self.env["pos.config"].browse(config_id).exists()
        if not config:
            return {"status": "invalid_config"}
        value = normalize_qr(value)
        exact = self.with_context(active_test=False).search([
            ("company_id", "=", config.company_id.id),
            ("value", "=", value),
        ], limit=2)
        if len(exact) > 1:
            return {"status": "ambiguous"}
        if exact:
            if not exact.active:
                return {"status": "retired"}
            if not exact.product_id.product_tmpl_id.available_in_pos or not exact.product_id.sale_ok:
                return {"status": "not_available"}
            available = self._pos_available_quantity(
                exact.product_id, exact.lot_id, config)
            if available is not None and available <= 0:
                return {"status": "out_of_stock"}
            return {
                "status": "resolved",
                "source": "alias",
                "product_id": exact.product_id.id,
                "lot_name": exact.lot_name or False,
                "tracking": exact.product_id.tracking,
                "available_quantity": available,
            }

        foreign = self.sudo().with_context(active_test=False).search([
            ("company_id", "!=", config.company_id.id),
            ("value", "=", value),
        ], limit=1)
        if foreign:
            return {"status": "wrong_company"}

        prefixes = config.mb_label_qr_prefixes or []
        identity = parse_prefixed_identity(value, prefixes)
        if not identity["matched"]:
            return {"status": "no_match"}
        if identity.get("error"):
            return {"status": "invalid"}

        template_domain = self.env["product.template"]._load_pos_data_domain({}, config)
        templates = self.env["product.template"].search(template_domain)
        products = self.env["product.product"].search([
            ("product_tmpl_id", "in", templates.ids),
            ("default_code", "=", identity["sku"]),
        ], limit=2)
        if not products:
            return {"status": "unknown_product"}
        if len(products) > 1:
            return {"status": "ambiguous"}

        lot_name = identity.get("lot_name")
        if lot_name:
            lots = self.env["stock.lot"].search([
                ("product_id", "=", products.id),
                ("name", "=", lot_name),
                ("company_id", "in", [False, config.company_id.id]),
            ], limit=2)
            if not lots:
                return {"status": "unknown_lot"}
            if len(lots) > 1:
                return {"status": "ambiguous"}
        else:
            lots = self.env["stock.lot"]
        available = self._pos_available_quantity(products, lots, config)
        if available is not None and available <= 0:
            return {"status": "out_of_stock"}
        return {
            "status": "resolved",
            "source": "compatibility",
            "product_id": products.id,
            "lot_name": lot_name or False,
            "tracking": products.tracking,
            "available_quantity": available,
        }
