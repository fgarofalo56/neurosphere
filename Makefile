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
# seed. Needs NS_ENTRA_TENANT_ID / NS_ENTRA_CLIENT_ID exported (never committed; see
# docs/dev/local-setup.md "Real stack"). The seed runs from the host against 127.0.0.1 because
# sbx_guard accepts loopback hosts only; it must use the same tenant and worker object id as the
# compose workers, so both get STACK_WORKER_OID (its default equals docker-compose.yml's; a test
# pins it).
STACK_WORKER_OID ?= 7d2e3f40-5b6c-4d7e-9f80-a1b2c3d4e5f6

.PHONY: stack-up stack-down

stack-up: ## Real stack: compose app profile (api, workers, frontend :8080) + host seed
	@test -n "$$NS_ENTRA_TENANT_ID" || { echo "stack-up: export NS_ENTRA_TENANT_ID first (docs/dev/local-setup.md, Real stack)" >&2; exit 1; }
	@test -n "$$NS_ENTRA_CLIENT_ID" || { echo "stack-up: export NS_ENTRA_CLIENT_ID first (docs/dev/local-setup.md, Real stack)" >&2; exit 1; }
	NS_WORKER_OBJECT_ID="$(STACK_WORKER_OID)" docker compose --profile app up -d --wait --build
	NS_ENV=local NS_AUTH_TENANT_ID="$$NS_ENTRA_TENANT_ID" NS_WORKER_OBJECT_ID="$(STACK_WORKER_OID)" NS_COSMOS_ENDPOINT=http://127.0.0.1:8081 $(MAKE) seed-stack

stack-down: ## Stop the real stack and the emulators (run dev-up to bring the emulators back)
	docker compose --profile app down --remove-orphans
