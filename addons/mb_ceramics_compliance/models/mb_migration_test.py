from odoo import fields, models


class MbMigrationTest(models.Model):
    """A laboratory's lead and cadmium migration result, held against a glaze lot.

    Against the glaze and not against the ware, because one test result covers
    every article made from that lot of glaze. Recording it per piece would mean
    copying the same figures onto every mug in a firing and having no single
    place to correct them.

    `passed` is recorded rather than computed. The laboratory issues the verdict
    against the limits in force on the test date; deriving it from a limits table
    of ours would put this addon in the position of overruling a lab report the
    first time that table drifted. The class and the figures are kept so the
    verdict stays auditable.
    """

    _name = "mb.migration.test"
    _description = "Lead and cadmium migration test (84/500/EEC)"
    _order = "test_date desc, id desc"
    _check_company_auto = True

    lot_id = fields.Many2one(
        comodel_name="stock.lot",
        string="Glaze lot",
        required=True,
        ondelete="restrict",
        index=True,
        check_company=True,
    )
    product_id = fields.Many2one(related="lot_id.product_id", store=True, string="Material")
    test_date = fields.Date(required=True, default=fields.Date.context_today)
    laboratory = fields.Char()
    migration_limit_class = fields.Selection(
        selection=[
            ("cat1", "Non-fillable, or fillable with internal depth up to 25 mm"),
            ("cat2", "Other fillable articles"),
            ("cat3", "Cooking ware; storage vessels over 3 litres"),
        ],
        required=True,
        help="The article geometry the sample was tested as. The limits differ "
        "by class, so a result is only meaningful alongside it.",
    )
    lead_result = fields.Float(string="Lead migration", digits=(16, 4))
    cadmium_result = fields.Float(string="Cadmium migration", digits=(16, 4))
    passed = fields.Boolean(
        required=True,
        help="The laboratory's verdict, as issued. Not derived from the figures "
        "above, because the limits in force are the lab's to apply.",
    )
    report_ids = fields.Many2many(
        comodel_name="ir.attachment", string="Laboratory report", check_company=True
    )
    note = fields.Text()
    company_id = fields.Many2one(
        comodel_name="res.company", required=True, index=True, default=lambda self: self.env.company
    )
