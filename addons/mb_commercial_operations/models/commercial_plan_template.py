from odoo import fields, models


class MbCommercialPlanTemplate(models.Model):
    _name = "mb.commercial.plan.template"
    _description = "Commercial Planning Template"
    _order = "name"
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    operation_type = fields.Selection(
        selection=lambda self: (
            self.env["mb.commercial.operation"]._fields["operation_type"].selection
        ),
        required=True,
        default="market",
    )
    calculation_mode = fields.Selection(
        [("product_mix", "Product Mix"), ("average_basket", "Average Basket")],
        required=True,
        default="product_mix",
    )
    default_duration_hours = fields.Float(default=7.0)
    default_setup_hours = fields.Float(string="Default Setup / Loading Hours")
    default_service_hours = fields.Float(string="Default Service / Public Hours", default=6.0)
    default_teardown_hours = fields.Float(string="Default Teardown / Unloading Hours")
    default_labour_hourly_cost = fields.Monetary()
    default_travel_hourly_cost = fields.Monetary()
    default_fuel_consumption_l_per_100km = fields.Float(default=7.0)
    default_fuel_price_eur_per_l = fields.Monetary(default=1.80)
    warning_age_days = fields.Integer(default=90)
    currency_id = fields.Many2one(related="company_id.currency_id")
    cost_line_ids = fields.One2many("mb.commercial.plan.template.cost", "template_id")
    product_line_ids = fields.One2many("mb.commercial.plan.template.product", "template_id")


class MbCommercialPlanTemplateCost(models.Model):
    _name = "mb.commercial.plan.template.cost"
    _description = "Commercial Planning Template Cost"
    _order = "sequence, id"
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    template_id = fields.Many2one(
        "mb.commercial.plan.template", required=True, ondelete="cascade", index=True
    )
    company_id = fields.Many2one(related="template_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    name = fields.Char(required=True)
    category = fields.Selection(
        selection=lambda self: self.env["mb.commercial.cost.line"]._fields["category"].selection,
        required=True,
        default="other",
    )
    calculation = fields.Selection(
        selection=lambda self: self.env["mb.commercial.cost.line"]._fields["calculation"].selection,
        required=True,
        default="fixed",
    )
    quantity = fields.Float(default=1.0)
    rate = fields.Monetary()
    percentage = fields.Float(digits=(16, 4))


class MbCommercialPlanTemplateProduct(models.Model):
    _name = "mb.commercial.plan.template.product"
    _description = "Commercial Planning Template Product"
    _order = "sequence, id"
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    template_id = fields.Many2one(
        "mb.commercial.plan.template", required=True, ondelete="cascade", index=True
    )
    company_id = fields.Many2one(related="template_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    product_id = fields.Many2one("product.product", required=True, check_company=True)
    expected_sold_qty = fields.Float(default=1.0)
    desired_opening_qty = fields.Float(default=1.0)
    safety_qty = fields.Float()
    sale_price_excluded_tax = fields.Monetary()
    product_unit_cost = fields.Monetary()
