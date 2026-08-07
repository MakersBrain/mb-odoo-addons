"""Take ownership of the material categories, which used to live in `mb_catalogue_sync`.

The taxonomy moved because it is not the catalogue's. A workshop that never
imports anything still buys glaze and still owes a lead-and-cadmium migration
test on the food-contact ware it makes with it, and `_mb_check_food_contact`
reads `categ_glaze`, `categ_underglaze` and `categ_engobe` to decide which
consumed lots need a passing test. Leaving them in the importer put a compliance
gate behind an optional connector.

Without this script the move is a drop and recreate rather than a move. Every
`ir.model.data` row for these eight categories still says `mb_catalogue_sync`,
so on upgrade `mb_workshop_base` would create eight *new* categories under its
own module and the old ones would linger beside them - twice as many entries in
every category selector, and any product already filed under an old one still
pointing at a record that `mb_catalogue_sync`'s eventual uninstall will delete.
Reassigning the rows first means Odoo's loader finds the existing xmlid and
updates the record in place.

This runs pre-migrate on `mb_workshop_base`, which `mb_catalogue_sync` now
depends on and which therefore loads first. By the time the importer is updated,
none of these rows are its responsibility any more.

One-shot: after it has run, the source rows are gone and a second run matches
nothing.
"""

import logging

MOVED_CATEGORIES = (
    "categ_ceramic_materials",
    "categ_glaze",
    "categ_underglaze",
    "categ_engobe",
    "categ_clay_body",
    "categ_stain",
    "categ_oxide",
    "categ_raw_material",
)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # `ir_model_data` is unique on (module, name), so a row that this addon
    # somehow already owns would make the UPDATE raise and abort the upgrade.
    # That should not happen - the source rows are deleted below in the same
    # transaction, so a re-run finds nothing - but an upgrade is the wrong place
    # to discover an assumption was wrong, and a category is cheap to leave
    # alone and loud about.
    cr.execute(
        """
        UPDATE ir_model_data AS source
           SET module = 'mb_workshop_base'
         WHERE source.module = 'mb_catalogue_sync'
           AND source.model = 'product.category'
           AND source.name IN %s
           AND NOT EXISTS (
                 SELECT 1 FROM ir_model_data AS target
                  WHERE target.module = 'mb_workshop_base'
                    AND target.model = 'product.category'
                    AND target.name = source.name
               )
     RETURNING name
        """,
        (MOVED_CATEGORIES,),
    )
    moved = [row[0] for row in cr.fetchall()]

    cr.execute(
        """
        SELECT name FROM ir_model_data
         WHERE module = 'mb_catalogue_sync'
           AND model = 'product.category'
           AND name IN %s
        """,
        (MOVED_CATEGORIES,),
    )
    conflicted = [row[0] for row in cr.fetchall()]

    if moved:
        _logger.info(
            "mb_workshop_base: took ownership of %s material categories from "
            "mb_catalogue_sync: %s", len(moved), ", ".join(sorted(moved)))
    if conflicted:
        # Left in place deliberately rather than deleted: the row still points
        # at a real category which may still be on products, and repointing
        # those is not something to do silently inside an upgrade.
        _logger.warning(
            "mb_workshop_base already owned these material categories, so %s "
            "kept mb_catalogue_sync's copies: %s. Both sets now exist; merge "
            "them by hand before uninstalling mb_catalogue_sync, which would "
            "delete its copies and any product filed under one.",
            len(conflicted), ", ".join(sorted(conflicted)))
