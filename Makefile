# NeuroSphere developer targets. Gate commands of record live in
# .claude/hooks/config.ps1; these are convenience wrappers for humans.

.DEFAULT_GOAL := help
.PHONY: help setup hooks lint typecheck test gates validate dev-up dev-down dev-logs docs clean

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
	docker compose down -v

dev-logs: ## Tail emulator logs
	docker compose logs -f

docs: ## Build the docs site (available after PRP-25)
	uv run mkdocs build --strict

clean: ## Remove local build artefacts
	rm -rf .pytest_cache .ruff_cache .venv node_modules frontend/dist temp/*
