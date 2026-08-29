# MakersBrain Odoo addons

Odoo 19 Community addons for the MakersBrain workshop platform. The repository
contains 41 installable addons covering workshop operations, ceramics,
consignment, commercial planning, labels, inventory capture, payments, webshop
shipping, French micro-enterprise accounting, and platform integrations.

The [living specification](SPEC.md) describes the current module boundaries and
supported invariants. Each addon's `README.md` or manifest is the operational
source of truth for that addon. Root-level plan files contain only open release,
qualification, or product work.

Human-facing copy uses **MakersBrain**. Repository-owned technical identifiers
use the `mb-` or `mb_` prefix, depending on what the target syntax permits.

## Local development

The local stack requires Docker with Compose and GNU Make. Static checks also
use Python 3, `uv`, and Node.js/npm.

From a clean checkout:

```sh
make bootstrap
```

This creates `.env` from `.env.example`, starts PostgreSQL and Odoo, installs
all addons discovered from `addons/*/__manifest__.py`, applies the development
UI configuration, and serves Odoo at `http://localhost:8169` by default. The
initial development login is `admin` / `admin`.

Common commands:

```sh
make up                 # start the stack
make logs               # follow Odoo logs
make upgrade            # upgrade every repository addon in the development DB
make shell              # open an Odoo shell
make test               # fresh disposable DB; test every repository addon
make test TAGS=/mb_label
make down               # stop containers and keep volumes
```

`make clean` deletes the local database and filestore volumes. `make test`
recreates only an allowlisted disposable database (`mb_scratch` by default).

## Validation

Install the pinned development-only UI package before running the complete
static gate:

```sh
npm ci
make check
make test
git diff --check
```

`make check` runs Ruff, translation validation, the UI-token projection check,
the addon dependency inventory/hash lock, and addon metadata/source checks.
`make test` installs all current manifests on
a fresh disposable database and restricts Odoo's test selection to tests owned
by this repository.

## Translations

English source strings and committed French catalogues are required for every
addon. Validate them with `make i18n-check`. With the development database
running, regenerate every POT and seed its French PO with `make i18n-pot`.
Translation conventions and review commands are documented in
[docs/i18n/README.md](docs/i18n/README.md).

## Repository layout

| Path | Purpose |
| --- | --- |
| `addons/` | Odoo addons, tests, and addon-level documentation |
| `config/` | Local Odoo configuration |
| `contracts/` | Generated private bridge API contract |
| `dependencies/` | Runtime inventory, hash-checked extension lock, and offline wheelhouse |
| `deploy/` | Immutable extension-bundle transport build (not an Odoo runtime image) |
| `docs/` | Cross-addon operational documentation |
| `scripts/` | Repeatable development and operational utilities |
| `tools/` | Static checks, translations, contract generation, and release tooling |
| `docker-compose.yml` | Self-contained local PostgreSQL/Odoo/Mailpit stack |
| `Makefile` | Supported local development and validation entry points |

Third-party OCA sources are reproducibly vendored into the ignored `oca/`
directory with `make oca`; no current addon manifest depends on an OCA addon.

Releases run the exact digest-pinned official Odoo image. MakersBrain code is a
separately signed transport image containing `/payload/addons`, an empty-by-
default `/payload/python`, and a complete digest-bound manifest. The transport
image is copied by the deployment helper and is never used as the Odoo runtime.

The public homepage, privacy policy, and terms are owned by the separate
[`MakersBrain/mb-site`](https://github.com/MakersBrain/mb-site) static site.
This repository intentionally contains no public landing-page implementation.
