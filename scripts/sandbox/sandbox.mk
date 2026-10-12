# Sandbox seed/replay targets (PRP-03 item 4). Included from the Makefile; dev-* targets live there.
# Needs the emulators up (`make dev-up`). Settings come from NS_SANDBOX_* env vars, see sbx_guard.py.

SANDBOX_SEED    ?= 1
SANDBOX_PROFILE ?= tiny
SANDBOX_CLOUD   ?= commercial
SANDBOX_DIR     ?= temp/sandbox
SANDBOX_CLI     := uv run python scripts/sandbox/sbx_cli.py

.PHONY: sandbox-generate seed replay seed-reset

sandbox-generate:
	uv run python -m sandbox.generate --seed $(SANDBOX_SEED) --profile $(SANDBOX_PROFILE) --cloud $(SANDBOX_CLOUD) --out $(SANDBOX_DIR)

seed: sandbox-generate ## Generate tiny sandbox data, load Cosmos and the telemetry hub (idempotent)
	$(SANDBOX_CLI) seed --data-dir $(SANDBOX_DIR)

replay: sandbox-generate ## Push sandbox telemetry incl. bad events to the hub (skips if already present)
	$(SANDBOX_CLI) replay --data-dir $(SANDBOX_DIR) $(REPLAY_ARGS)

seed-reset: ## Drop sandbox Cosmos databases and restart the Event Hubs emulator (empty hub)
	$(SANDBOX_CLI) reset
	docker compose restart eventhubs
	docker compose up -d --wait
