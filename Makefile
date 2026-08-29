# Development entry points. Every target below works from a clean checkout with
# nothing installed but Docker and GNU make; `make bootstrap` is the first one.

ifneq (,$(wildcard .env))
include .env
export
endif

COMPOSE := docker compose
ODOO    := $(COMPOSE) exec -T odoo odoo
DB_NAME ?= mb_odoo
DISPOSABLE_DB ?= mb_scratch

# Pinned on purpose. `ruff format` is a gate, not a suggestion, so an unpinned
# `@latest` that reflows one expression differently from CI turns a green branch
# red for a reason nobody can reproduce locally. Bump both here and in
# .github/workflows/ci.yml in the same commit.
RUFF_VERSION := 0.16.4
MYPY_VERSION := 2.3.1
RUFF := uvx ruff@$(RUFF_VERSION)
MYPY := uvx mypy@$(MYPY_VERSION)

# Discover every addon from its manifest so local and CI coverage cannot drift
# when a module is added. Odoo resolves dependency order itself.
ADDON_MANIFESTS := $(wildcard addons/*/__manifest__.py)
ADDONS := $(sort $(notdir $(patsubst %/,%,$(dir $(ADDON_MANIFESTS)))))
empty :=
space := $(empty) $(empty)
comma := ,
MODULES_ARG := $(subst $(space),$(comma),$(ADDONS))

# Which tests run. `--test-enable` alone would also run the tests of every
# dependency Odoo pulls in — all of mail, stock, account and point_of_sale —
# which is thousands of upstream tests taking well over ten minutes and telling
# us nothing about this repository. A `/module` spec restricts the run to tests
# defined in that module, so this is the list above with each name prefixed.
#
# Override to narrow:  make test TAGS=/mb_label
# Down to one class:   make test TAGS=/mb_label:TestLabel
# Or one method:       make test TAGS=/mb_label:TestLabel.test_qr_collision
TAGS ?= $(addprefix /,$(ADDONS))
TAGS_ARG := $(subst $(space),$(comma),$(TAGS))

.DEFAULT_GOAL := help
.PHONY: help bootstrap up dev mail down clean logs ps shell psql install upgrade configure-ui \
        test check lint format format-check typecheck oca reset-test-db brand-check \
        dependency-check bridge-contract-check po-parse-check

help: ## Show available targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-12s %s\n", $$1, $$2}'

bootstrap: ## Prepare a clean checkout: .env, oca/, images, database, addons
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")
	@mkdir -p oca
	$(COMPOSE) pull --quiet
	$(COMPOSE) up -d
	@echo "waiting for Odoo to answer /web/health..."
	@until [ "$$(docker inspect -f '{{.State.Health.Status}}' mb-odoo-web 2>/dev/null)" = healthy ]; do sleep 2; done
	@$(MAKE) --no-print-directory install
	@$(MAKE) --no-print-directory configure-ui
	@echo
	@echo "Odoo is on http://localhost:$${ODOO_PORT:-8169}, database $(DB_NAME)."
	@echo "Log in as admin/admin, then: make logs"

up: ## Start the stack in the background
	$(COMPOSE) up -d
	@echo "Odoo starting on http://localhost:$${ODOO_PORT:-8169}"

dev: ## Run Odoo in the foreground with the developer tools enabled
	$(COMPOSE) run --rm --service-ports odoo odoo \
		-d $(DB_NAME) --dev=reload,qweb,xml --log-level=debug

mail: ## Start the stack plus Mailpit (SMTP sink; UI on MAILPIT_UI_PORT)
	$(COMPOSE) --profile tools up -d
	@echo "Mailpit UI on http://localhost:$${MAILPIT_UI_PORT:-8125}"

down: ## Stop the stack, keep the data volumes
	$(COMPOSE) --profile tools down

clean: ## Stop the stack and delete every database and the filestore
	$(COMPOSE) --profile tools down -v

logs: ## Follow Odoo logs
	$(COMPOSE) logs -f odoo

ps: ## Show container status
	$(COMPOSE) ps

shell: ## Open an Odoo shell on DB_NAME (env, self are bound)
	$(COMPOSE) exec odoo odoo shell -d $(DB_NAME) --log-level=warn

psql: ## Open psql against DB_NAME
	$(COMPOSE) exec db psql -U $${DB_USER:-odoo} -d $(DB_NAME)

install: ## Install MODULES on DB_NAME, creating the database if needed
	@$(COMPOSE) exec -T db psql -U $${DB_USER:-odoo} -d postgres -tAc \
		"select 1 from pg_database where datname='$(DB_NAME)'" | grep -q 1 || \
		$(ODOO) db init $(DB_NAME)
	$(ODOO) -d $(DB_NAME) -i $(MODULES_ARG) --stop-after-init \
		--http-port=0 --gevent-port=0 --log-level=warn

upgrade: ## Upgrade MODULES on DB_NAME
	$(ODOO) -d $(DB_NAME) -u $(MODULES_ARG) --stop-after-init \
		--http-port=0 --gevent-port=0 --log-level=warn

configure-ui: ## Apply the streamlined artisan app-switcher layout
	$(ODOO) shell -d $(DB_NAME) --no-http --log-level=warn \
		< scripts/configure_app_visibility.py

test: ## Install MODULES on a fresh disposable database and run their tests
	@$(MAKE) --no-print-directory reset-test-db
	$(ODOO) -d $(DISPOSABLE_DB) -i $(MODULES_ARG) \
		--test-tags "$(TAGS_ARG)" \
		--stop-after-init --http-port=0 --gevent-port=0 --log-level=test

check: lint format-check typecheck i18n-check po-parse-check brand-check dependency-check \
       bridge-contract-check ## Everything CI runs that needs no container
	python3 tools/check_addons.py

bridge-contract-check: ## Fail if the committed control-bridge contract has drifted
	python3 tools/bridge_contract.py --check

po-parse-check: ## Independently parse translation catalogues and validate headers
	uv run --no-project --with polib python tools/check_po_parse.py

dependency-check: ## Validate declared imports and the hash-checked empty lock
	python3 tools/dependency_policy.py

# The design system is `@makersbrain/ui`, pinned by this repository's
# development-only package.json. Odoo consumes its generated SCSS projection;
# this gate verifies the checked-in copy byte-for-byte. Run `npm ci` first.
brand-check: ## Fail if the Odoo token projection has fallen behind mb-ui
	python3 tools/check_brand_scss.py

# polib comes through uv rather than a checked-in requirements file: nothing
# here is a Python package, so there is no install step to hang a dependency on.
i18n-check: ## Translation catalogues and source marking (no container needed)
	uv run --no-project --with polib python tools/check_i18n.py --all --summary

i18n-pot: ## Re-export every POT from DB_NAME; the catalogue-freshness gate
	./tools/i18n.sh pot $(DB_NAME) $(shell ls addons)
	uv run --no-project --with polib python tools/i18n_seed_po.py $(shell ls addons)

lint: ## Ruff, using the correctness ruleset in pyproject.toml
	$(RUFF) check .

format: ## Apply the formatter and import order in place
	$(RUFF) check --select I --fix .
	$(RUFF) format .

format-check: ## Fail if anything is unformatted or the imports are unsorted
	$(RUFF) format --check .
	$(RUFF) check --select I .

# `tools/` is real Python and is enforced. `addons/` is advisory: `odoo` ships no
# stubs and is not importable outside the container, so every ORM symbol is
# `Any` and a green run there proves very little. It is still worth running --
# the typed pure-Python modules (carrier providers, shop-import fetchers) are
# genuinely checked -- but it must not gate a merge on a false negative.
typecheck: ## mypy: blocking on tools/, advisory on addons/
	$(MYPY) tools
	@echo "--- addons/ (advisory; does not fail the build) ---"
	@$(MYPY) addons || true

oca: ## Vendor the pinned OCA modules into ./oca
	./tools/vendor-oca.sh

# `dropdb` takes whatever name it is handed, and the name that gets handed to it
# is the one thing here worth being paranoid about: a mistyped DISPOSABLE_DB
# would silently destroy a demonstration database instead of a scratch one. So
# the name is checked against a fixed allowlist and nothing else is droppable
# through this Makefile, whatever the environment says.
reset-test-db: ## Drop and recreate DISPOSABLE_DB (allowlisted names only)
	@case "$(DISPOSABLE_DB)" in \
	  mb_scratch|mb_ci|mb_test) ;; \
	  *) echo "refusing to drop '$(DISPOSABLE_DB)': not in the allowlist" \
	          "(mb_scratch, mb_ci, mb_test)." >&2; \
	     echo "Databases outside it are dropped by hand, on purpose." >&2; \
	     exit 1 ;; \
	esac
	@# Terminate first. A backend left over from an interrupted run holds the
	@# database open, the drop fails, and `make test` then reinstalls onto a
	@# database that already has the modules — where `-i` is a no-op and the
	@# at_install tests silently do not run. A green suite that tested nothing
	@# is worse than a red one.
	@$(COMPOSE) exec -T db psql -U $${DB_USER:-odoo} -d postgres -c \
		"select pg_terminate_backend(pid) from pg_stat_activity \
		 where datname = '$(DISPOSABLE_DB)'" >/dev/null 2>&1 || true
	@$(ODOO) db drop $(DISPOSABLE_DB) 2>/dev/null || true
	$(ODOO) db init $(DISPOSABLE_DB) --force
	@echo "$(DISPOSABLE_DB) is empty"
