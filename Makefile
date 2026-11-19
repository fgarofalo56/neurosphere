# NeuroSphere developer targets. Gate commands of record live in
# .claude/hooks/config.ps1; these are convenience wrappers for humans.

.DEFAULT_GOAL := help
.PHONY: help setup hooks lint typecheck test gates validate dev-up dev-down dev-reset dev-logs dev-ps docs clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: hooks ## Install toolchains and git hooks
	uv sync
	pnpm install

hooks: ## Point git at the version-controlled secret guards
	bash scripts/install-git-hooks.sh

lint: ## Ruff lint + format check, pnpm lint
	uv run ruff check .
	uv run ruff format --check .
	pnpm lint

typecheck: ## Pyright + tsc
	uv run pyright
	pnpm typecheck

test: ## Unit tests (python + node)
	uv run pytest -q
	pnpm test

gates: ## The kit's full gate run (what "done" means)
	powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full

validate: ## Planning-document alignment check (not a product test)
	uv run python scripts/validate_planning.py

prp-status: ## Regenerate the PRP status table in the master index from PRPs/ directories
	uv run python scripts/prp_status.py --write

dev-up: ## Start local Azure emulators (no paid calls)
	docker compose up -d --wait

dev-down: ## Stop emulators and drop volumes
	docker compose --profile test down -v --remove-orphans

dev-reset: ## Tear down and bring the emulators back up empty and healthy
	docker compose --profile test down -v --remove-orphans
	docker compose up -d --wait

dev-logs: ## Tail emulator logs
	docker compose logs -f

dev-ps: ## Show emulator status and health
	docker compose --profile test ps

-include scripts/sandbox/sandbox.mk

docs: ## Build the docs site (available after PRP-25)
	uv run mkdocs build --strict

clean: ## Remove local build artefacts
	rm -rf .pytest_cache .ruff_cache .venv node_modules frontend/dist temp/*

# Real stack (PRP-29 item 11): api + workers + frontend on the compose emulators, then the host
# seed. Order (PRP-38 item 1, #205): the worker principal needs its domain grants BEFORE the app
# profile starts, or the evaluation role stays unhealthy and `up --wait` aborts, so the grants-only
# seed runs first and the full seed after the app is up (it is idempotent).
# Needs NS_ENTRA_TENANT_ID / NS_ENTRA_CLIENT_ID exported (never committed; see
# docs/dev/local-setup.md "Real stack"). The seed runs from the host against 127.0.0.1 because
# sbx_guard accepts loopback hosts only; it must use the same tenant and worker object id as the
# compose workers, so both get STACK_WORKER_OID (its default equals docker-compose.yml's; a test
# pins it).
STACK_WORKER_OID ?= 7d2e3f40-5b6c-4d7e-9f80-a1b2c3d4e5f6
# Optional env file sourced into the shell of the two `docker compose` app/seed lines (empty for
# a plain stack-up). `make demo-up` sets it to the PRP-71 demo profile.
STACK_ENV_FILE ?=
STACK_ENV_LOAD = $(if $(STACK_ENV_FILE),set -a && . $(STACK_ENV_FILE) && set +a && ,)

.PHONY: stack-up stack-down demo-up demo-down demo-check

stack-up: ## Real stack: compose app profile (api, workers, frontend :8080) + sandbox seed + stack seed
	@test -n "$$NS_ENTRA_TENANT_ID" || { echo "stack-up: export NS_ENTRA_TENANT_ID first (docs/dev/local-setup.md, Real stack)" >&2; exit 1; }
	@test -n "$$NS_ENTRA_CLIENT_ID" || { echo "stack-up: export NS_ENTRA_CLIENT_ID first (docs/dev/local-setup.md, Real stack)" >&2; exit 1; }
	$(MAKE) sandbox-generate
	docker compose up -d --wait
	NS_SANDBOX_COSMOS_ENDPOINT=http://127.0.0.1:8081 NS_SANDBOX_EVENTHUBS_CONNECTION_STRING="$$(python -c "print('Endpoint=sb://127.0.0.1;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=' + 'SAS_KEY' + '_VALUE;UseDevelopmentEmulator=true;')")" $(SANDBOX_CLI) seed --data-dir $(SANDBOX_DIR) --no-events
	NS_ENV=local NS_AUTH_TENANT_ID="$$NS_ENTRA_TENANT_ID" NS_WORKER_OBJECT_ID="$(STACK_WORKER_OID)" NS_COSMOS_ENDPOINT=http://127.0.0.1:8081 $(MAKE) seed-stack SEED_ARGS=--grants-only
	$(STACK_ENV_LOAD)NS_SANDBOX_DIR="$(if $(or $(filter /% ./% ../%,$(SANDBOX_DIR)),$(findstring :,$(SANDBOX_DIR))),$(SANDBOX_DIR),./$(SANDBOX_DIR))" NS_WORKER_OBJECT_ID="$(STACK_WORKER_OID)" docker compose --profile app up -d --wait --build
	NS_ENV=local NS_AUTH_TENANT_ID="$$NS_ENTRA_TENANT_ID" NS_WORKER_OBJECT_ID="$(STACK_WORKER_OID)" NS_COSMOS_ENDPOINT=http://127.0.0.1:8081 $(MAKE) seed-stack
	$(STACK_ENV_LOAD)NS_WORKER_OBJECT_ID="$(STACK_WORKER_OID)" docker compose --profile seed run --rm --build seed

stack-down: ## Stop the real stack and the emulators (run dev-up to bring the emulators back)
	docker compose --profile app down --remove-orphans

# Demo profile (PRP-71 item 4): the exact stack-up ordering (grants-only seed, app profile, full
# seed) with the demo-world seed profile and infra/dev/demo-profile.env applied. Same Entra
# exports as stack-up.
demo-up: ## Demo profile: stack-up with SEED_PROFILE=demo-world and infra/dev/demo-profile.env
	$(MAKE) stack-up SEED_PROFILE=demo-world STACK_ENV_FILE=infra/dev/demo-profile.env

demo-down: ## Stop the demo stack (same as stack-down)
	$(MAKE) stack-down

demo-check: ## Demo check: every page's backing API returns data or a documented empty
	uv run python scripts/sandbox/sbx_demo_check.py
