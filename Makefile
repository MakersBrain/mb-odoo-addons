# Development entry points. Every target below works from a clean checkout with
# nothing installed but Docker and GNU make; `make bootstrap` is the first one.

ifneq (,$(wildcard .env))
include .env
export
endif

COMPOSE := docker compose
ODOO    := $(COMPOSE) exec -T odoo odoo
DB_NAME ?= makersbrain
DISPOSABLE_DB ?= mb_scratch

# Every addon in this repository, in dependency order. Odoo resolves the order
# itself, but writing it down means `make install` on an empty database is one
# command and the reader can see the four trees from SPEC.md.
MODULES := mb_workshop_base,mb_label,mb_label_pos,mb_ceramics_firing,mb_kiln_bridge,\
mb_catalogue_sync,mb_depot,mb_payment_sumup,mb_pos_sumup,mb_account_payment_sumup,\
l10n_fr_micro_enterprise

# Which tests run. `--test-enable` alone would also run the tests of every
# dependency Odoo pulls in — all of mail, stock, account and point_of_sale —
# which is thousands of upstream tests taking well over ten minutes and telling
# us nothing about this repository. A `/module` spec restricts the run to tests
# defined in that module, so this is the list above with each name prefixed.
#
# Override to narrow:  make test TAGS=/mb_label
# Down to one class:   make test TAGS=/mb_label:TestLabel
# Or one method:       make test TAGS=/mb_label:TestLabel.test_qr_collision
TAGS ?= /mb_workshop_base,/mb_label,/mb_label_pos,/mb_ceramics_firing,/mb_kiln_bridge,\
/mb_catalogue_sync,/mb_depot,/mb_payment_sumup,/mb_pos_sumup,/mb_account_payment_sumup,\
/l10n_fr_micro_enterprise

.DEFAULT_GOAL := help
.PHONY: help bootstrap up dev mail down clean logs ps shell psql install upgrade configure-ui \
        test check lint format oca reset-poc

help: ## Show available targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-12s %s\n", $$1, $$2}'

bootstrap: ## Prepare a clean checkout: .env, oca/, images, database, addons
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")
	@mkdir -p oca
	$(COMPOSE) pull --quiet
	$(COMPOSE) up -d
	@echo "waiting for Odoo to answer /web/health..."
	@until [ "$$(docker inspect -f '{{.State.Health.Status}}' makersbrain-odoo-web 2>/dev/null)" = healthy ]; do sleep 2; done
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
	$(ODOO) -d $(DB_NAME) -i $(MODULES) --stop-after-init --log-level=warn

upgrade: ## Upgrade MODULES on DB_NAME, running any migration scripts
	$(ODOO) -d $(DB_NAME) -u $(MODULES) --stop-after-init --log-level=warn

configure-ui: ## Apply the streamlined artisan app-switcher layout
	$(ODOO) shell -d $(DB_NAME) --no-http --log-level=warn \
		< scripts/configure_app_visibility.py

test: ## Install MODULES on a fresh disposable database and run their tests
	@$(MAKE) --no-print-directory reset-poc
	$(ODOO) -d $(DISPOSABLE_DB) -i $(MODULES) \
		--test-tags "$(strip $(TAGS))" \
		--stop-after-init --log-level=test

check: lint ## Everything CI runs that needs no container
	python3 tools/check_addons.py

lint: ## Ruff, using the narrow correctness ruleset in pyproject.toml
	@command -v ruff >/dev/null 2>&1 && ruff check . || uvx ruff@latest check .

format: ## Show what ruff would change; does not write
	@command -v ruff >/dev/null 2>&1 && ruff check --diff . || uvx ruff@latest check --diff .

oca: ## Vendor the pinned OCA modules into ./oca
	./tools/vendor-oca.sh

# `dropdb` takes whatever name it is handed, and the name that gets handed to it
# is the one thing here worth being paranoid about: a mistyped DISPOSABLE_DB
# would silently destroy a demonstration database instead of a scratch one. So
# the name is checked against a fixed allowlist and nothing else is droppable
# through this Makefile, whatever the environment says.
reset-poc: ## Drop and recreate DISPOSABLE_DB (allowlisted names only)
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
