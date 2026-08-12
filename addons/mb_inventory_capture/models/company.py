from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    mb_inventory_ai_enabled = fields.Boolean(
        string="Allow inventory image AI fallback",
        default=False,
        help=(
            "Permit unresolved inventory-label crops to use the configured multimodal "
            "primary/secondary route. Barcode, GS1, catalogue and deterministic OCR remain active."
        ),
    )
    mb_inventory_vision_primary = fields.Selection(
        [("gemini", "Google Gemini"), ("azure", "Azure multimodal"),
         ("openai", "OpenAI"), ("claude", "Anthropic Claude")],
        string="Inventory vision primary",
        help="Provider name only. Credentials remain in the extraction broker.",
    )
    mb_inventory_vision_secondary = fields.Selection(
        [("gemini", "Google Gemini"), ("azure", "Azure multimodal"),
         ("openai", "OpenAI"), ("claude", "Anthropic Claude")],
        string="Inventory vision fallback",
        help="Optional distinct fallback used only for retryable provider failures.",
    )

    @api.constrains(
        "mb_inventory_ai_enabled", "mb_inventory_vision_primary",
        "mb_inventory_vision_secondary",
    )
    def _check_inventory_vision_order(self):
        for company in self:
            if company.mb_inventory_ai_enabled and not company.mb_inventory_vision_primary:
                raise ValidationError(_(
                    "Choose an inventory vision provider before enabling AI fallback."
                ))
            if company.mb_inventory_vision_secondary and not company.mb_inventory_vision_primary:
                raise ValidationError(_("Choose a primary inventory vision provider first."))
            if company.mb_inventory_vision_secondary == company.mb_inventory_vision_primary \
                    and company.mb_inventory_vision_secondary:
                raise ValidationError(_("The primary and fallback providers must be different."))
