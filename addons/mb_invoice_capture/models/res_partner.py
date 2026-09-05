from odoo import api, fields, models


def normalized_identifier(value):
    return "".join(character for character in (value or "").upper() if character.isalnum())


def normalized_name(value):
    return " ".join((value or "").casefold().split())


class ResPartner(models.Model):
    _inherit = "res.partner"

    mb_invoice_vat_key = fields.Char(
        compute="_compute_mb_invoice_supplier_keys",
        store=True,
        index="btree_not_null",
        readonly=True,
        copy=False,
    )
    mb_invoice_registry_key = fields.Char(
        compute="_compute_mb_invoice_supplier_keys",
        store=True,
        index="btree_not_null",
        readonly=True,
        copy=False,
    )
    mb_invoice_siren_key = fields.Char(
        compute="_compute_mb_invoice_supplier_keys",
        store=True,
        index="btree_not_null",
        readonly=True,
        copy=False,
    )
    mb_invoice_name_key = fields.Char(
        compute="_compute_mb_invoice_supplier_keys",
        store=True,
        index="trigram",
        readonly=True,
        copy=False,
    )

    @api.depends("vat", "company_registry", "name")
    def _compute_mb_invoice_supplier_keys(self):
        for partner in self:
            registry_key = normalized_identifier(partner.company_registry)
            partner.mb_invoice_vat_key = normalized_identifier(partner.vat) or False
            partner.mb_invoice_registry_key = registry_key or False
            partner.mb_invoice_siren_key = registry_key[:9] if len(registry_key) >= 9 else False
            partner.mb_invoice_name_key = normalized_name(partner.name) or False
