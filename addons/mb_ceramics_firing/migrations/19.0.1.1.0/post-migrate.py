"""Give kilns created before 19.0.1.1.0 the work centre they now come with.

Until this version a kiln could exist with neither half filled in, because both
had to be created and linked by hand and nothing said so. A kiln without a work
centre is invisible to planning: no operation can point at it, so no firing can
be scheduled. Backfilling is therefore not tidying - it is what makes the
existing records usable at all.

Kilns that already carry a work centre or a piece of equipment are left exactly
as they are, including ones pointing at records a workshop set up itself.
"""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    kilns = env["mb.kiln"].with_context(active_test=False).search([
        "|",
        ("workcenter_id", "=", False),
        ("equipment_id", "=", False),
    ])
    for kiln in kilns:
        values = {"name": kiln.name, "company_id": kiln.company_id.id}
        if not kiln.workcenter_id:
            kiln.workcenter_id = env["mrp.workcenter"].create(
                kiln._prepare_workcenter_values(values))
            # An archived kiln whose work centre is live keeps turning up in
            # planning, offering a kiln that is no longer there.
            kiln.workcenter_id.active = kiln.active
        if not kiln.equipment_id:
            kiln.equipment_id = env["maintenance.equipment"].create(
                kiln._prepare_equipment_values(values))
    kilns._sync_capacity()
