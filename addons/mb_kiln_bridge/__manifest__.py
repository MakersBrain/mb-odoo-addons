{
    "name": "MakersBrain Kiln Bridge",
    "summary": "Read-only import of kilns and firings from ROHDE myKiln.",
    "description": """
Pulls kilns, live status and completed firings from a provider into the
provider-neutral records owned by `mb_ceramics_firing`.

**Ordinary Odoo connector.** Each workshop configures a connection record and
scheduled poller. The myKiln password and reusable provider token are stored in
the tenant database, restricted to manufacturing managers, and are never
logged or exported.

**Read-only toward the provider.** The client can authenticate, list kilns and
controllers, list firings and fetch samples. There is no method that starts a
firing, sends a programme, or edits provider data. A write-capable connector
needs its own safety review and explicit authorization.

**Programmes remain provider-neutral.** `mb.kiln.program` belongs to
`mb_ceramics_firing`, so workshops without telemetry can still define firing
schedules. This connector matches imported controller slots to those programmes,
records which one a firing ran, and refreshes provider-owned segments.

**Programmes are derived, because there is no library to read.** myKiln has two
endpoints that look like a programme library and neither is one.
`/api/v1/programs/` returns one
nameless, slotless snapshot per firing ever recorded. `/api/v1/library_programs/`
is the real library and is empty, which is also why `library_program_name` is
null on every firing. What every firing *does* report is the controller slot it
ran on and the programme as it ran - so the programme list is built by grouping
firings by slot and taking the most recent. Newest wins, and a firing older
than the one already recorded is ignored, or a backfill walking the archive
would leave every programme showing its oldest profile.

That derivation costs nothing on a routine sync, which already has each
firing's detail in hand. The Refresh programmes button performs one listing
call, then one detail call per slot found.

**A kiln says what it is.** `/api/v1/kilns/` carries manufacturer, model,
chamber volume, maximum temperature, connected load, zones and serial, and
`/api/v1/kiln_types/` is ROHDE's catalogue of three hundred models, joined on
make and model for the series, the loading configuration and the supply. Volume
and maximum temperature are taken from the kiln and never from the catalogue: a
model is built to more than one specification, and the record the potter
configured describes their machine. The catalogue is fetched only when a kiln
here has never been matched against it.

The specification is written on every sync and the name is not, which is the
same rule from both ends: the provider is the authority on the machine, and the
workshop is the authority on how the workshop uses it.

**Idempotent by identity, not by timestamp.** A kiln is keyed on
(provider, external id, company) and a firing likewise, both already unique in
`mb_ceramics_firing`. Re-running a poll over the same window updates the same
records instead of duplicating them, and the curve attachment is replaced
rather than appended - which is what stops a nightly poll accumulating one
copy of the trace per run.

The client implements the read-only API v1 token authentication and the joins
between kilns, controllers, firings, samples, and kiln types.
""",
    "version": "19.0.1.3.1",
    "license": "AGPL-3",
    "category": "Manufacturing/Manufacturing",
    "author": "MakersBrain",
    "depends": [
        # mb.kiln and mb.firing, which this addon fills but does not define.
        "mb_ceramics_firing",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/mb_kiln_bridge_security.xml",
        "data/ir_cron.xml",
        "views/mb_kiln_connection_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
