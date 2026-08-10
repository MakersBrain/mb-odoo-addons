{
    "name": "Makersbrain Kiln Bridge",
    "summary": "Read-only import of kilns and firings from ROHDE myKiln.",
    "description": """
Pulls kilns, live status and completed firings from a provider into the
provider-neutral records owned by `mb_ceramics_firing`.

**Ordinary Odoo shape, chosen deliberately.** POC-PLAN section 10.7 specified
an external sidecar so that no tenant database would ever hold a provider
credential. That was reversed on 6 August 2026: a single workshop does not need
a fan-out poller, and a connection record with an `ir.cron` and a Python client
is the shape an Odoo developer can read and maintain. The cost is real and is
recorded on the model - the myKiln password is a column in this database,
restricted to manufacturing managers. Going multi-tenant reverses the decision
again, and at that point the credential moves out and this addon keeps only the
apply surface.

**Read-only toward the provider.** The client can authenticate, list kilns and
controllers, list firings and fetch samples. There is no method that starts a
firing, sends a programme, or edits provider data. A write-capable connector
needs its own safety review and explicit authorization.

**The programme mapping left in 19.0.1.1.0.** `mb.kiln.program` was defined
here, on the reasoning that a controller programme is a provider's idea. It is
not: it is the schedule a potter fires to, and a workshop with no telemetry has
the same programmes and simply types their hours in. Once a routing operation
took its firing duration from a programme, keeping it here would have made
planning a firing depend on installing a connector for a kiln you do not own.
It now lives in `mb_ceramics_firing`, and this addon matches against it,
records which one a firing ran, and - from 19.0.1.2.0 - fills in its segments.

**Programmes are derived, because there is no library to read.** myKiln has two
endpoints that look like a programme library and neither is one, checked
against the live service on 7 August 2026. `/api/v1/programs/` returns one
nameless, slotless snapshot per firing ever recorded. `/api/v1/library_programs/`
is the real library and is empty, which is also why `library_program_name` is
null on every firing. What every firing *does* report is the controller slot it
ran on and the programme as it ran - so the programme list is built by grouping
firings by slot and taking the most recent. Newest wins, and a firing older
than the one already recorded is ignored, or a backfill walking the archive
would leave every programme showing its oldest profile.

That derivation costs nothing on a routine sync, which already has each
firing's detail in hand. The Refresh programmes button pays for the first run:
one listing call, then one detail call per slot found - three on the live
account rather than seventy-two.

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

The protocol itself was not rediscovered. The client is a port of the tested
TypeScript in `ateliera-app`, whose findings about API v1 - token
authentication, and the join between kilns, controllers and firings - are
carried over rather than guessed at.
""",
    "version": "19.0.1.2.2",
    "license": "LGPL-3",
    "category": "Manufacturing/Manufacturing",
    "author": "Makersbrain",
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
