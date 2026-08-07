"""Take ownership of `mb.kiln.program`, which used to live in `mb_kiln_bridge`.

The model moved because a firing duration hangs off it, and a workshop with no
telemetry needs firing durations just as much as one with a myKiln account -
see the model's own docstring for the argument.

Moving a model between modules is not a code-only change. Every `ir.model.data`
row for the model, its fields, its selections, its constraint and its access
rules still says `mb_kiln_bridge`, and when that module is updated and no longer
declares them, Odoo's end-of-load cleanup deletes exactly the rows it can no
longer account for - taking the model, and with a populated table the data, with
them. Reassigning the module first is what makes the move a move rather than a
drop and recreate.

This runs pre-migrate on `mb_ceramics_firing`, which is a dependency of
`mb_kiln_bridge` and therefore loads first. By the time the bridge is updated,
none of these rows are its responsibility any more.
"""

MOVED_PREFIXES = (
    "model_mb_kiln_program",
    "field_mb_kiln_program__",
    "selection__mb_kiln_program__",
    "constraint_mb_kiln_program_",
    "access_mb_kiln_program_",
)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE ir_model_data
           SET module = 'mb_ceramics_firing'
         WHERE module = 'mb_kiln_bridge'
           AND (%s)
        """ % " OR ".join(["name LIKE %s"] * len(MOVED_PREFIXES)),
        ["%s%%" % prefix for prefix in MOVED_PREFIXES],
    )
