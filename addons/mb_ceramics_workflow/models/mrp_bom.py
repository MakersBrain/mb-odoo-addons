from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


RECIPE_STATES = ("approved", "historical", "withdrawn")


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    mb_is_glaze_recipe = fields.Boolean(
        string="Glaze formula",
        help="Express dry ingredients and water as percentages of dry batch weight.",
    )
    mb_recipe_state = fields.Selection(
        [
            ("draft", "Draft"),
            ("approved", "Approved"),
            ("historical", "Historical"),
            ("withdrawn", "Withdrawn"),
        ],
        string="Recipe status",
        default="draft",
        required=True,
        copy=False,
        index=True,
        tracking=True,
    )
    mb_revision = fields.Integer(default=1, required=True, copy=False, readonly=True)
    mb_previous_revision_id = fields.Many2one(
        "mrp.bom", string="Previous revision", copy=False, readonly=True,
        ondelete="restrict", check_company=True,
    )
    mb_successor_revision_ids = fields.One2many(
        "mrp.bom", "mb_previous_revision_id", string="Successor revisions",
        readonly=True,
    )
    mb_approved_at = fields.Datetime(copy=False, readonly=True)
    mb_approved_by_id = fields.Many2one(
        "res.users", copy=False, readonly=True, ondelete="restrict",
    )
    mb_document_count = fields.Integer(compute="_compute_mb_document_count")

    def _compute_mb_document_count(self):
        grouped = self.env["ir.attachment"]._read_group(
            [("res_model", "=", self._name), ("res_id", "in", self.ids)],
            ["res_id"], ["__count"],
        )
        counts = dict(grouped)
        for bom in self:
            bom.mb_document_count = counts.get(bom.id, 0)

    def action_mb_recipe_documents(self):
        action = self.env["ir.actions.actions"]._for_xml_id("base.action_attachment")
        action.update({
            "name": _("Recipe documents"),
            "domain": [("res_model", "=", self._name), ("res_id", "in", self.ids)],
            "context": {
                "default_res_model": self._name,
                "default_res_id": self.id if len(self) == 1 else False,
            },
        })
        return action

    def _mb_assert_recipe_mutable(self):
        if self.env.context.get("mb_recipe_lifecycle_write"):
            return
        locked = self.filtered(
            lambda bom: bom.mb_is_glaze_recipe and bom.mb_recipe_state in RECIPE_STATES
        )
        if locked:
            raise UserError(_(
                "Approved recipe revisions are immutable. Create a new revision "
                "instead of editing: %s",
                ", ".join(locked.mapped("display_name")),
            ))

    def write(self, values):
        internal = self.env.context.get("mb_recipe_lifecycle_write")
        lifecycle_fields = {
            "mb_recipe_state", "mb_revision", "mb_previous_revision_id",
            "mb_approved_at", "mb_approved_by_id",
        }
        if (not internal and lifecycle_fields & set(values)
                and self.filtered("mb_is_glaze_recipe")):
            raise UserError(_("Recipe lifecycle fields can only be changed by their actions."))
        if not internal:
            self._mb_assert_recipe_mutable()
        result = super().write(values)
        if {"product_qty", "product_uom_id", "mb_is_glaze_recipe"} & set(values):
            self.filtered("mb_is_glaze_recipe").bom_line_ids._mb_sync_formula_quantity()
        return result

    def unlink(self):
        self._mb_assert_recipe_mutable()
        return super().unlink()

    def _mb_validate_formula(self):
        for bom in self.filtered("mb_is_glaze_recipe"):
            if not bom.bom_line_ids:
                raise ValidationError(_("A glaze formula needs at least one ingredient."))
            fixed = bom.bom_line_ids.filtered(lambda line: line.mb_quantity_mode == "fixed")
            if fixed:
                raise ValidationError(_(
                    "Every glaze formula ingredient must be a dry or water percentage: %s",
                    ", ".join(fixed.product_id.mapped("display_name")),
                ))
            batch_uom = bom.product_uom_id
            incompatible = bom.bom_line_ids.filtered(
                lambda line, batch_uom=batch_uom:
                not line.product_uom_id._has_common_reference(
                    batch_uom
                )
            )
            if incompatible:
                raise ValidationError(_(
                    "Formula ingredients must use units compatible with the dry "
                    "batch unit: %s",
                    ", ".join(incompatible.product_id.mapped("display_name")),
                ))
            dry_total = sum(bom.bom_line_ids.filtered(
                lambda line: line.mb_quantity_mode == "dry_percent"
            ).mapped("mb_formula_percent"))
            if float_compare(dry_total, 100.0, precision_digits=4):
                raise ValidationError(_(
                    "Dry ingredient percentages must total 100%%; this formula totals %(total).4f%%.",
                    total=dry_total,
                ))

    def action_mb_approve_recipe(self):
        for bom in self:
            if not bom.mb_is_glaze_recipe:
                raise UserError(_("Only glaze formulas use recipe approval."))
            if bom.mb_recipe_state != "draft":
                raise UserError(_("Only a draft recipe can be approved."))
        self._mb_validate_formula()
        for bom in self:
            other = self.search([
                ("id", "!=", bom.id),
                ("product_tmpl_id", "=", bom.product_tmpl_id.id),
                ("product_id", "=", bom.product_id.id or False),
                ("mb_is_glaze_recipe", "=", True),
                ("mb_recipe_state", "=", "approved"),
            ], limit=1)
            if other:
                raise ValidationError(_(
                    "%(product)s already has approved recipe %(recipe)s.",
                    product=bom.product_tmpl_id.display_name,
                    recipe=other.display_name,
                ))
        self.with_context(mb_recipe_lifecycle_write=True).write({
            "mb_recipe_state": "approved",
            "mb_approved_at": fields.Datetime.now(),
            "mb_approved_by_id": self.env.user.id,
            "active": True,
        })
        return True

    def action_mb_new_recipe_revision(self):
        self.ensure_one()
        if not self.mb_is_glaze_recipe or self.mb_recipe_state != "approved":
            raise UserError(_("A new revision can only follow an approved glaze recipe."))
        successor = self.with_context(mb_recipe_lifecycle_write=True).copy({
            "code": _("%(code)s R%(revision)s", code=self.code or self.product_tmpl_id.name,
                      revision=self.mb_revision + 1),
            "active": True,
            "mb_recipe_state": "draft",
            "mb_revision": self.mb_revision + 1,
            "mb_previous_revision_id": self.id,
            "mb_approved_at": False,
            "mb_approved_by_id": False,
        })
        self.with_context(mb_recipe_lifecycle_write=True).write({
            "mb_recipe_state": "historical", "active": False,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Recipe revision"),
            "res_model": "mrp.bom",
            "res_id": successor.id,
            "view_mode": "form",
        }

    def action_mb_withdraw_recipe(self):
        invalid = self.filtered(lambda bom: bom.mb_recipe_state != "approved")
        if invalid:
            raise UserError(_("Only an approved recipe can be withdrawn."))
        self.with_context(mb_recipe_lifecycle_write=True).write({
            "mb_recipe_state": "withdrawn", "active": False,
        })
        return True


class MrpBomLine(models.Model):
    _inherit = "mrp.bom.line"

    mb_quantity_mode = fields.Selection(
        [
            ("fixed", "Fixed quantity"),
            ("dry_percent", "% of dry batch"),
            ("water_percent", "Water % of dry batch"),
        ],
        default="fixed",
        required=True,
    )
    mb_formula_percent = fields.Float(string="Formula %", digits=(16, 4))

    def _mb_sync_formula_quantity(self):
        for line in self.filtered(lambda item: item.bom_id.mb_is_glaze_recipe):
            if line.mb_quantity_mode in ("dry_percent", "water_percent"):
                dry_quantity = line.bom_id.product_uom_id._compute_quantity(
                    line.bom_id.product_qty, line.product_uom_id
                )
                quantity = dry_quantity * line.mb_formula_percent / 100.0
                if float_compare(
                    line.product_qty, quantity,
                    precision_rounding=line.product_uom_id.rounding,
                ):
                    super(MrpBomLine, line.with_context(
                        mb_recipe_formula_sync=True,
                    )).write({"product_qty": quantity})

    @api.model_create_multi
    def create(self, values_list):
        boms = self.env["mrp.bom"].browse([
            values["bom_id"] for values in values_list if values.get("bom_id")
        ])
        boms._mb_assert_recipe_mutable()
        lines = super().create(values_list)
        lines._mb_sync_formula_quantity()
        return lines

    def write(self, values):
        self.mapped("bom_id")._mb_assert_recipe_mutable()
        if (
            "product_qty" in values
            and not self.env.context.get("mb_recipe_formula_sync")
            and any(line.bom_id.mb_is_glaze_recipe
                    and line.mb_quantity_mode != "fixed" for line in self)
        ):
            raise UserError(_("Formula quantities are derived from their percentage."))
        result = super().write(values)
        if {
            "mb_quantity_mode", "mb_formula_percent", "bom_id", "product_uom_id",
        } & set(values):
            self._mb_sync_formula_quantity()
        return result

    def unlink(self):
        self.mapped("bom_id")._mb_assert_recipe_mutable()
        return super().unlink()

    @api.constrains("mb_formula_percent", "mb_quantity_mode")
    def _check_mb_formula_percent(self):
        for line in self:
            if line.mb_quantity_mode != "fixed" and line.mb_formula_percent <= 0:
                raise ValidationError(_("A formula percentage must be greater than zero."))


class MrpRoutingWorkcenter(models.Model):
    _inherit = "mrp.routing.workcenter"

    @api.model_create_multi
    def create(self, values_list):
        self.env["mrp.bom"].browse([
            values["bom_id"] for values in values_list if values.get("bom_id")
        ])._mb_assert_recipe_mutable()
        return super().create(values_list)

    def write(self, values):
        self.mapped("bom_id")._mb_assert_recipe_mutable()
        return super().write(values)

    def unlink(self):
        self.mapped("bom_id")._mb_assert_recipe_mutable()
        return super().unlink()


class MrpBomByproduct(models.Model):
    _inherit = "mrp.bom.byproduct"

    @api.model_create_multi
    def create(self, values_list):
        self.env["mrp.bom"].browse([
            values["bom_id"] for values in values_list if values.get("bom_id")
        ])._mb_assert_recipe_mutable()
        return super().create(values_list)

    def write(self, values):
        self.mapped("bom_id")._mb_assert_recipe_mutable()
        return super().write(values)

    def unlink(self):
        self.mapped("bom_id")._mb_assert_recipe_mutable()
        return super().unlink()
