# neurosphere — developer targets
# Most targets are scaffolding: the Claude Code build session (see CLAUDE.md /
# PRP.md) implements the services these call. Targets are defined up front so the
# demo flow and CI are stable as the implementation lands.

COMPOSE ?= docker compose
PY ?= python

.DEFAULT_GOAL := help
.PHONY: help up down seed demo test lint diagram pricing logs clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Start the core stack (postgres, dab, identity, gateway, catalog, mcp)
	$(COMPOSE) --profile core up -d
	./scripts/wait-for-healthy.sh

down: ## Stop and remove the stack
	$(COMPOSE) down -v

seed: ## Generate + load the synthetic data into the system of record
	$(COMPOSE) run --rm seeder

demo: up seed ## Full end-to-end demo: up -> seed -> query through the gateway -> print the answer
	./scripts/demo.sh

test: ## Run the test suite (zero-move / auth / discovery / behavior / no-fabric)
	$(PY) -m pytest -q

lint: ## Ruff format-check + lint
	ruff format --check .
	ruff check .

diagram: ## Render docs/architecture.png
	$(PY) scripts/gen-architecture-diagram.py

pricing: ## Print live, dated cloud infrastructure prices
	$(PY) tools/azure_pricing.py

logs: ## Tail all service logs
	$(COMPOSE) logs -f

clean: ## Remove generated runtime artifacts
	rm -rf data/out output
