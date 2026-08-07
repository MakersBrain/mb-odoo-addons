{
    "name": "Makersbrain Ceramics Firing",
    "summary": "The kiln load as its own record, with the cooling hold that gates unloading.",
    "description": """
A firing is not a work order, and Odoo will not let it be one.

`mrp.workorder.production_id` is `required=True`, so a work order belongs to
exactly one manufacturing order. A kiln is filled because firing is expensive, so
a load routinely holds ware from several orders at once - and a single order
passes through at least two firings, bisque then glaze. Firing and manufacturing
order are many-to-many, and the physical event therefore needs its own record.

`mb.firing` owns it. Each work order points at the firing it happened in, which
gives the many-to-many without a join model: one firing gathers work orders from
many orders, each work order sits in one firing.

**Boards, not pieces.** No adhesive label survives a kiln - bisque runs near
1000 C - so nothing printed can be attached to ware before the last firing.
Identity through the process is borne by the carrier, and Odoo already models
that: `stock.package` with a reusable package type is a ware board, and
`parent_package_id` nests board inside shelf inside load. `stock.quant` already
joins package to lot, so what is on a board needs no model of ours.

**Cooling is a property of the firing.** `cooling_end` is the earliest moment a
load may be unloaded and labelled, which is not the same moment the manufacturing
order is marked done. OCA's `mrp_workorder_blocking_time` models this against a
work order; putting it here instead is both physically right and the reason this
addon needs no AGPL dependency.

**A kiln is one work centre, created with the kiln.** Adding a kiln creates its
`mrp.workcenter` and its `maintenance.equipment` and keeps both named after it,
because an artisan adding a kiln should not have to learn what a work centre is,
and a kiln without one is invisible to planning. One per physical kiln: not one
called "Firing", which would serialise two kilns that fire in parallel, and not
one per firing type, which would let Odoo book the same chamber twice. Bisque
and glaze differ in the routing operation and the controller programme, and
neither of those is a resource.

The work centre goes on `mb_workshop_base.mb_calendar_continuous`, and
`pieces_per_load` becomes its fallback capacity. That second one is what makes
the kiln a batch: Odoo computes a work order as ceil(quantity / capacity)
cycles, so at forty pieces per load a firing of eight and a firing of forty both
cost one firing's time. Odoo's capacity is per product, though, and a real load
mixes ware from several orders - which is exactly the gap `mb.firing` fills. The
work centre answers when the kiln is free; the firing records what was in it.

**A firing's duration comes from its programme, not from a routing.** The
controller schedule decides how long a firing takes - ramps, holds and the drop
are set before anything is loaded, and practice never makes a twelve-hour glaze
programme run in ten. So `mb.kiln.program` carries `firing_hours`, a routing
operation points at a programme, and its duration follows. Cooling counts, on
by default: a kiln cannot take the next load while it is still hot, and a plan
that counts only the heating hours will book two firings into one night.

That is also why the programme moved here from `mb_kiln_bridge` in 19.0.1.2.0.
A programme is a schedule the potter fires to; a workshop with no telemetry has
them just the same and simply types the hours in. Planning cannot depend on
having installed a connector for a kiln you do not own.

Declared, scheduled and measured are kept apart. `firing_hours` is what plans
rest on; `scheduled_hours` is what the programme's own ramps and holds add up
to; `measured_hours` is the median of the firings actually recorded under it.
Adopting either is a button, never a drift - the median rather than the mean,
because one interrupted firing would drag an average somewhere no real firing
has been. The gap between the three is the useful part: it is a kiln losing
power, or a programme nobody has revised.

**A programme has segments, because a controller has segments.** A ramp rate, a
target and a hold, per step - which is what a potter reads and argues with, and
what a duration can be derived from rather than typed. `mb.kiln.program.segment`
holds them, and 19.0.1.3.0 added them so a connector could refresh a programme
from the controller that runs it. What the programme *means* stays the potter's:
bisque or glaze, and how long the load must stand, are questions no controller
can answer, so no refresh touches them.

**A kiln says what it is.** Manufacturer, model, series, chamber volume, maximum
temperature, connected load and zones sit on `mb.kiln`. They are how a chamber
volume stops being a number somebody remembered and starts being the
specification of a known machine. Model, serial and purchase date are mirrored
onto `maintenance.equipment`, which is where Odoo expects an asset's identity to
be and where a service call is raised.

**Curve figures are fields, the curve is an attachment.** A twelve-hour firing
sampled every thirty seconds is about 1,400 points, never read point by point.
Peak temperature and hold time are queried and constrained, so they are fields;
the trace is evidence, so it is an attachment. Peak temperature is not only a
schedule detail - an under-fired glaze is a less mature glaze, and lead release
rises with immaturity.
""",
    "version": "19.0.1.3.0",
    "license": "LGPL-3",
    "category": "Manufacturing/Manufacturing",
    "author": "Makersbrain",
    "depends": [
        # mb.firing gathers work orders, and the lot it produces carries the
        # compliance payload declared there.
        "mb_workshop_base",
        # mrp.workorder, mrp.workcenter and the routing a firing operation sits on.
        "mrp",
        # A kiln is equipment that needs servicing - elements, thermocouples -
        # and maintenance.equipment is where Odoo keeps that. Note that
        # mrp_maintenance, which would bridge equipment to work centre, is
        # Enterprise and absent here, so mb.kiln carries the link itself.
        "maintenance",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/mb_kiln_views.xml",
        "views/mrp_routing_workcenter_views.xml",
        "views/mb_firing_views.xml",
        "views/mb_firing_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
