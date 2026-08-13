"""Hand the ceramics half of this addon to `mb_ceramics_base` and `mb_ceramics_compliance`.

Everything ceramic left `mb_workshop_base` in 19.0.2.0.0 - the material and ware
taxonomy, the seeded work centres, `mb_clay_body_id`, and all of 84/500/EEC.
What stayed is what a leatherworker would install unchanged. The reasoning is in
CRAFT-PLATFORM-PLAN.md section 2; this script is what makes the move a move
rather than a drop and recreate.

**The successors are force-installed first.** A database that had the old module
had all of it, and the artisan did not opt out of food-contact compliance - it
was split away from them. Handing rows to a module nobody installs would leave
`mb_food_contact` and every migration test owned by nothing, which is the same
data loss this script exists to prevent, reached by a longer route. So both new
modules are flipped to `to install` before anything moves, and Odoo's loader
picks them up in this same run. A database installing `mb_workshop_base` for the
first time never runs this script and still chooses freely.

Four transfers, in the order they matter:

1. **The menus are renamed in place.** `menu_mb_ceramics_production` and its two
   siblings were ceramic names in a module that no longer holds anything
   ceramic. Renaming the `ir_model_data` row rather than letting the new IDs be
   created keeps the artisan's own re-sequencing, their access group edits and
   every child menu that already points at them. `menu_mb_workshop_root` is
   untouched: `scripts/configure_app_visibility.py` names it.

2. **The categories and work centres go to `mb_ceramics_base`.** Without this
   the loader would find no `mb_ceramics_base.categ_glaze`, create a second
   Glazes category beside the first, and leave every product already filed under
   the old one pointing at a record this addon's next cleanup deletes.

3. **The migration test model, views and rules go to `mb_ceramics_compliance`.**
   Same failure, with a laboratory result attached to it.

4. **The field rows go with their fields.** This is the one that is not
   cosmetic. `ir.model.data` rows named `field_product_template__mb_food_contact`
   and friends still say `mb_workshop_base` after the Python has moved, and
   Odoo's module cleanup would then drop the columns - taking the stored
   `mb_label_food_warning` and `mb_migration_passed` values with them. It has to
   happen pre-migrate, before the loader reconciles this module's field list.

Per SPEC.md a version bump is free while no tenant database exists, but a record
that moves between modules needs a script regardless. This is that case.

The precedent for the SQL shape is `19.0.1.2.0/pre-migrate.py`, which moved the
material categories in from `mb_catalogue_sync`. `ir_model_data` is unique on
(module, name), so every UPDATE guards against a target row that somehow already
exists. A duplicate that points to the same record is collapsed to the successor
ID. A duplicate that points elsewhere aborts the upgrade: allowing cleanup to
choose between physical records would be data loss disguised as a warning.

One-shot in both directions. After it has run the source rows are gone, so a
second run matches nothing.
"""

import logging

_logger = logging.getLogger(__name__)

# (old name, new name) inside mb_workshop_base. The root is deliberately absent.
RENAMED_MENUS = (
    ("menu_mb_ceramics_production", "menu_mb_workshop_production"),
    ("menu_mb_ceramics_stock_quality", "menu_mb_workshop_stock_quality"),
    ("menu_mb_ceramics_configuration", "menu_mb_workshop_configuration"),
)

MATERIAL_CATEGORIES = (
    "categ_ceramic_materials",
    "categ_glaze",
    "categ_underglaze",
    "categ_engobe",
    "categ_clay_body",
    "categ_stain",
    "categ_oxide",
    "categ_raw_material",
)

FINISHED_CATEGORIES = (
    "categ_finished_ceramics",
    "categ_tableware",
    "categ_drinkware",
    "categ_vases",
    "categ_planters",
    "categ_decorative",
    "categ_tiles",
    "categ_jewellery",
)

WORKCENTRE_RECORDS = (
    "mb_workcenter_tag_forming",
    "mb_workcenter_tag_surface",
    "mb_workcenter_tag_firing",
    "mb_workcenter_tag_waiting",
    "mb_workcenter_throwing",
    "mb_workcenter_handbuilding",
    "mb_workcenter_trimming",
    "mb_workcenter_assembly",
    "mb_workcenter_drying",
    "mb_workcenter_capacity_drying",
    "mb_workcenter_glazing",
    "mb_workcenter_capacity_glazing",
    "mb_workcenter_decorating",
)

COMPLIANCE_RECORDS = (
    "mb_migration_test_view_list",
    "mb_migration_test_view_form",
    "mb_migration_test_action",
    "mb_migration_test_company_rule",
    "access_mb_migration_test_user",
    "access_mb_migration_test_manager",
    "menu_mb_migration_test",
    "model_mb_migration_test",
    "view_production_lot_form_mb_workshop",
)

# `ir.model.data` names for the moved fields, which is how Odoo tracks which
# module owns a column. The names are Odoo's own convention:
# field_<model with dots as underscores>__<field>.
CERAMICS_BASE_FIELDS = (
    "field_product_template__mb_clay_body_id",
)

COMPLIANCE_FIELDS = (
    "field_product_template__mb_food_contact",
    "field_product_template__mb_migration_limit_class",
    "field_product_template__mb_tableware_form",
    "field_product_template__mb_label_food_warning",
    "field_stock_lot__mb_food_contact",
    "field_stock_lot__mb_glaze_lot_ids",
    "field_stock_lot__mb_migration_passed",
    "field_stock_lot__mb_migration_test_ids",
)


def _rename(cr, old, new):
    cr.execute(
        """
        UPDATE ir_model_data AS source
           SET name = %s
         WHERE source.module = 'mb_workshop_base'
           AND source.name = %s
           AND NOT EXISTS (
                 SELECT 1 FROM ir_model_data AS target
                  WHERE target.module = 'mb_workshop_base'
                    AND target.name = %s
               )
        """,
        (new, old, new),
    )
    renamed = cr.rowcount
    if renamed:
        return renamed

    cr.execute(
        """
        SELECT source.id, source.model, source.res_id, target.model, target.res_id
          FROM ir_model_data AS source
          JOIN ir_model_data AS target
            ON target.module = source.module
           AND target.name = %s
         WHERE source.module = 'mb_workshop_base'
           AND source.name = %s
        """,
        (new, old),
    )
    duplicate = cr.fetchone()
    if not duplicate:
        return 0
    source_id, source_model, source_res_id, target_model, target_res_id = duplicate
    if (source_model, source_res_id) != (target_model, target_res_id):
        raise RuntimeError(
            "mb_workshop_base cannot rename "
            f"{old} to {new}: both XML IDs exist and point to different "
            "records. Merge those records before retrying the upgrade."
        )
    cr.execute("DELETE FROM ir_model_data WHERE id = %s", (source_id,))
    _logger.info(
        "mb_workshop_base: removed redundant XML ID %s; %s owns the same record",
        old, new,
    )
    return 0


def _hand_over(cr, names, module):
    """Reassign rows to `module`, whatever model they describe.

    Matched on name alone rather than on (model, name) because the set spans
    product categories, work centres, capacity lines, views, actions, menus,
    access rules and field definitions, and the names are unambiguous within
    this module.
    """
    if not names:
        return []
    cr.execute(
        """
        UPDATE ir_model_data AS source
           SET module = %s
         WHERE source.module = 'mb_workshop_base'
           AND source.name IN %s
           AND NOT EXISTS (
                 SELECT 1 FROM ir_model_data AS target
                  WHERE target.module = %s
                    AND target.name = source.name
               )
     RETURNING name
        """,
        (module, tuple(names), module),
    )
    return [row[0] for row in cr.fetchall()]


def _resolve_conflicts(cr, names, module):
    """Collapse identical duplicate IDs and reject divergent records."""
    cr.execute(
        """
        SELECT source.id, source.name, source.model, source.res_id,
               target.model, target.res_id
          FROM ir_model_data AS source
          JOIN ir_model_data AS target
            ON target.module = %s
           AND target.name = source.name
         WHERE source.module = 'mb_workshop_base'
           AND source.name IN %s
        """,
        (module, tuple(names)),
    )
    duplicates = cr.fetchall()
    identical_ids = [
        source_id
        for source_id, _name, source_model, source_res_id, target_model, target_res_id
        in duplicates
        if (source_model, source_res_id) == (target_model, target_res_id)
    ]
    divergent = [
        name
        for _source_id, name, source_model, source_res_id, target_model, target_res_id
        in duplicates
        if (source_model, source_res_id) != (target_model, target_res_id)
    ]
    if divergent:
        raise RuntimeError(
            "mb_workshop_base cannot hand records to "
            f"{module}: the successor XML IDs already point to different "
            f"records: {', '.join(sorted(divergent))}. Merge those records "
            "before retrying the upgrade."
        )
    if identical_ids:
        cr.execute(
            "DELETE FROM ir_model_data WHERE id IN %s",
            (tuple(identical_ids),),
        )
        _logger.info(
            "mb_workshop_base: removed %s redundant XML IDs already owned by %s",
            len(identical_ids), module,
        )


def _force_install(cr, modules):
    """Mark the successors for installation in this same upgrade run.

    `to install` rather than `installed`: the loader still does the real work -
    tables, data files, access rules - and this only puts the modules on its
    list. A module already installed or already queued is left alone.
    """
    cr.execute(
        """
        UPDATE ir_module_module
           SET state = 'to install'
         WHERE name IN %s
           AND state = 'uninstalled'
     RETURNING name
        """,
        (tuple(modules),),
    )
    return [row[0] for row in cr.fetchall()]


def migrate(cr, version):
    forced = _force_install(cr, ("mb_ceramics_base", "mb_ceramics_compliance"))
    if forced:
        _logger.info(
            "mb_workshop_base: this database had the ceramics half, so %s will "
            "be installed in this run: %s", len(forced), ", ".join(sorted(forced)))

    renamed = [new for old, new in RENAMED_MENUS if _rename(cr, old, new)]
    if renamed:
        _logger.info(
            "mb_workshop_base: renamed %s menus to craft-neutral IDs: %s",
            len(renamed), ", ".join(renamed))

    to_ceramics_base = MATERIAL_CATEGORIES + FINISHED_CATEGORIES \
        + WORKCENTRE_RECORDS + CERAMICS_BASE_FIELDS
    to_compliance = COMPLIANCE_RECORDS + COMPLIANCE_FIELDS

    for names, module in (
        (to_ceramics_base, "mb_ceramics_base"),
        (to_compliance, "mb_ceramics_compliance"),
    ):
        moved = _hand_over(cr, names, module)
        if moved:
            _logger.info(
                "mb_workshop_base: handed %s records to %s: %s",
                len(moved), module, ", ".join(sorted(moved)))
        _resolve_conflicts(cr, names, module)
