from odoo import api, fields, models


class MbKiln(models.Model):
    """A kiln, which is two things Odoo keeps in different places.

    It is equipment that needs servicing - elements, thermocouples, door seals -
    which is `maintenance.equipment`. It is also a work centre that routing
    operations point at and that scheduling reasons about, which is
    `mrp.workcenter`. Odoo bridges the two in `mrp_maintenance`, which is
    Enterprise and therefore absent from this stack, so the link lives here.

    Keeping both is not redundancy. A firing is scheduled against the work
    centre and a thermocouple replacement is planned against the equipment, and
    collapsing them would lose one or the other.

    Both are created for you. An artisan adding a kiln should not have to learn
    what a work centre is first, and a kiln without one is invisible to
    planning - so creating one record creates all three, and the kiln remains
    the name of record for them.

    **One work centre per physical kiln, and only one.** Not one called
    "Firing", because two kilns fire in parallel and a shared work centre would
    serialise them. Not one per firing type either, because bisque and glaze run
    in the same chamber, and two work centres over one kiln let Odoo book both
    at once. What differs between bisque and glaze is the routing operation and
    the controller programme, neither of which is a resource.
    """

    _name = "mb.kiln"
    _description = "Kiln"
    _order = "name"
    _check_company_auto = True

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        comodel_name="res.company", required=True, index=True,
        default=lambda self: self.env.company)

    equipment_id = fields.Many2one(
        comodel_name="maintenance.equipment",
        check_company=True,
        string="Equipment",
        help="Where servicing history and maintenance requests live.",
    )
    workcenter_id = fields.Many2one(
        comodel_name="mrp.workcenter",
        check_company=True,
        string="Work centre",
        help="What routing operations point at, so a firing can be an operation "
             "on a bill of materials.",
    )

    program_ids = fields.One2many(
        comodel_name="mb.kiln.program",
        inverse_name="kiln_id",
        string="Programmes",
        help="The schedules this kiln fires, and how long each one takes. A "
             "kiln that reports nothing still has them - they are simply typed "
             "in rather than imported.",
    )

    manufacturer = fields.Char(
        help="Who made the kiln. Filled from the provider where one reports "
             "it, typed in otherwise.")
    model_number = fields.Char(
        string="Model",
        help="The manufacturer's model, such as 'TE 80 S'. This is what turns "
             "a kiln called 'Leonardo' into something whose specification can "
             "be looked up.")
    series = fields.Char(
        help="The model range, such as 'TE-S'. Useful when a manual or a "
             "spare part is published per range rather than per model.")
    configuration = fields.Selection(
        selection=[
            ("top_loader", "Top loader"),
            ("front_loader", "Front loader"),
            ("other", "Other"),
        ],
        help="How the kiln is loaded. It decides how the shelves stack and "
             "therefore what actually fits in the chamber volume.",
    )
    heating_method = fields.Selection(
        selection=[("electric", "Electric"), ("gas", "Gas"), ("other", "Other")],
    )
    max_temperature = fields.Float(
        string="Maximum temperature",
        help="The highest the kiln is rated for, in degrees Celsius. A "
             "programme asking for more than this is asking for a kiln that "
             "does not exist.")
    chamber_litres = fields.Float(
        string="Chamber volume (L)",
        help="What the chamber holds. Together with the loading configuration "
             "it is the honest upper bound on a load.")
    power_kw = fields.Float(
        string="Power (kW)",
        help="Connected load. It is what a firing's energy cost is estimated "
             "from when the controller does not report consumption itself.")
    zone_count = fields.Integer(
        string="Zones",
        help="Independently controlled heating zones. A single-zone kiln "
             "reports one temperature; a three-zone kiln can be even where a "
             "single-zone one cannot.")
    voltage = fields.Integer(help="Supply voltage the model is built for.")
    phases = fields.Integer(help="Supply phases the model is built for.")
    serial_number = fields.Char(
        help="The manufacturer's serial. Kept on the equipment record too, "
             "which is where Odoo expects to find an asset's serial.")
    purchase_date = fields.Date()

    pieces_per_load = fields.Float(
        string="Pieces per load",
        help="How many pieces fit in one firing. This is what makes the kiln "
             "behave as a batch rather than as per-piece work: Odoo computes a "
             "work order as ceil(quantity / capacity) cycles, so at forty "
             "pieces per load a firing of eight and a firing of forty both take "
             "one firing's time, and forty-one takes two. Left at zero, Odoo "
             "falls back on the quantity the bill of materials produces.",
    )

    provider = fields.Selection(
        selection=[
            ("rohde_mykiln", "ROHDE myKiln"),
            ("none", "No telemetry"),
        ],
        default="none",
        required=True,
        help="Most kilns in most workshops report nothing, and that is a "
             "supported configuration rather than a gap.",
    )
    provider_external_id = fields.Char(
        string="Provider device id",
        copy=False,
        help="The device identifier at the provider. Never written back to them.",
    )

    _provider_device_uniq = models.Constraint(
        "unique (provider, provider_external_id, company_id)",
        "A kiln may only be bound once to a given provider device.",
    )

    @api.model
    def _continuous_calendar(self, company_id):
        """Return the 24/7 calendar owned by the kiln's company."""
        template = self.env.ref(
            "mb_workshop_base.mb_calendar_continuous", raise_if_not_found=False)
        company = self.env["res.company"].browse(company_id).exists()
        if not template or not company:
            return template
        if template.company_id == company:
            return template
        calendar = self.env["resource.calendar"].with_company(company).search([
            ("name", "=", template.name),
            ("company_id", "=", company.id),
        ], limit=1)
        if not calendar:
            calendar = template.with_company(company).copy({
                "company_id": company.id,
            })
        return calendar

    @api.model
    def _prepare_workcenter_values(self, values):
        """The work centre a new kiln gets, on the calendar a kiln needs.

        `mb_calendar_continuous` rather than the workshop's own hours. A firing
        runs fourteen hours and does not stop at closing time; on a nine-to-five
        calendar Odoo spreads one firing across three days and every date
        derived from it is wrong.
        """
        company_id = values.get("company_id") or self.env.company.id
        calendar = self._continuous_calendar(company_id)
        tag = self.env.ref(
            "mb_ceramics_base.mb_workcenter_tag_firing", raise_if_not_found=False)
        workcenter_values = {
            "name": values.get("name"),
            "company_id": company_id,
        }
        if calendar:
            workcenter_values["resource_calendar_id"] = calendar.id
        if tag:
            workcenter_values["tag_ids"] = [fields.Command.link(tag.id)]
        return workcenter_values

    @api.model
    def _prepare_equipment_values(self, values):
        return {
            "name": values.get("name"),
            "company_id": values.get("company_id") or self.env.company.id,
        }

    def _sync_capacity(self):
        """Keep the work centre's fallback capacity at one kiln load.

        A capacity line with no product is what Odoo reaches for when nothing
        more specific matches, which is what a kiln wants: the chamber holds
        what it holds, whatever is in it. Per-product lines added by hand still
        win, and should, once a workshop knows it fits sixty test tiles or
        twelve casseroles.
        """
        unit = self.env.ref("uom.product_uom_unit", raise_if_not_found=False)
        if not unit:
            return
        for kiln in self:
            workcenter = kiln.workcenter_id
            if not workcenter:
                continue
            line = workcenter.capacity_ids.filtered(
                lambda capacity: (
                    not capacity.product_id and capacity.product_uom_id == unit
                )
            )[:1]
            if not kiln.pieces_per_load:
                line.unlink()
            elif line:
                line.capacity = kiln.pieces_per_load
            else:
                self.env["mrp.workcenter.capacity"].create({
                    "workcenter_id": workcenter.id,
                    "product_uom_id": unit.id,
                    "capacity": kiln.pieces_per_load,
                })

    # Fields that describe the hardware rather than the workshop's use of it.
    # A connector owns these; `pieces_per_load`, the name and the work centre
    # are the potter's and are never in this list.
    _SPEC_FIELDS = (
        "manufacturer", "model_number", "series", "configuration",
        "heating_method", "max_temperature", "chamber_litres", "power_kw",
        "zone_count", "voltage", "phases", "serial_number", "purchase_date",
    )

    def _sync_equipment_identity(self):
        """Put the asset facts where Odoo keeps asset facts.

        Model, serial and purchase date belong on `maintenance.equipment`: that
        is the record a service call is raised against, and an engineer asking
        which kiln failed wants the serial on the equipment, not two clicks
        away. They are mirrored rather than moved, because the kiln is the name
        of record and planning never loads the equipment.
        """
        Equipment = self.env["maintenance.equipment"]
        for kiln in self.filtered("equipment_id"):
            values = {}
            model = " ".join(part for part in (kiln.manufacturer,
                                               kiln.model_number) if part)
            if model:
                values["model"] = model
            if kiln.purchase_date:
                values["effective_date"] = kiln.purchase_date
            if kiln.serial_number and kiln.equipment_id.serial_no != kiln.serial_number:
                # `maintenance.equipment.serial_no` is unique across the
                # database. A serial already spoken for is left alone rather
                # than allowed to raise: a duplicate is worth a quiet gap on
                # one record, not a failed sync on every kiln behind it.
                taken = Equipment.with_context(active_test=False).search_count([
                    ("serial_no", "=", kiln.serial_number),
                    ("id", "!=", kiln.equipment_id.id),
                ])
                if not taken:
                    values["serial_no"] = kiln.serial_number
            if values:
                kiln.equipment_id.write(values)

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if not values.get("workcenter_id"):
                values["workcenter_id"] = self.env["mrp.workcenter"].create(
                    self._prepare_workcenter_values(values)).id
            if not values.get("equipment_id"):
                values["equipment_id"] = self.env["maintenance.equipment"].create(
                    self._prepare_equipment_values(values)).id
        kilns = super().create(vals_list)
        kilns.filtered("pieces_per_load")._sync_capacity()
        kilns._sync_equipment_identity()
        return kilns

    def write(self, values):
        """The kiln is the name of record, so renaming it renames both halves.

        Archiving propagates for the same reason: an archived kiln whose work
        centre is still live keeps turning up in planning, offering to schedule
        a firing in a kiln that is no longer there.
        """
        result = super().write(values)
        if values.get("name"):
            self.workcenter_id.name = values["name"]
            self.equipment_id.name = values["name"]
        if "active" in values:
            self.workcenter_id.filtered(
                lambda workcenter: workcenter.active != values["active"]
            ).active = values["active"]
        if "pieces_per_load" in values:
            self._sync_capacity()
        if {"manufacturer", "model_number", "serial_number", "purchase_date"} & set(values):
            self._sync_equipment_identity()
        return result
