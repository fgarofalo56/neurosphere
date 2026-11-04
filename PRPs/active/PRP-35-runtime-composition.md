---
name: prp-35-runtime-composition
status: active
started: 2026-11-04
branch: feat/prp-35-runtime-composition
priority: P0
order: 1
review: required
created: 2026-11-04
orchestrator_model: opus
implementer_model: sonnet
model: opus
phase: 6
ns: NS-01, NS-02, NS-06, NS-09
depends_on: []
---

# PRP-35: Runtime composition (ingest config, write registry, search backend, catalog seeding)

## Goal
Make a fresh compose or hosted stack hold data and be able to act on it. The 2026-11-04 deep audit (`PRPs/reports/audit-deep-2026-11-04.md`, root causes 1, 2 and 5) found that "shipped" PRPs are code-complete behind an unconfigured composition root: the ingest edge answers 503 because `NS_INGEST_PRODUCERS_FILE` is never set, the catalog starts empty, catalog search is `_NoSearch`, and the `WriteTargetRegistry` is empty in both the API and the workers (#132), so no model swap, cap change or gateway change can ever execute. This PRP wires those four seams so the reopened PRPs (07, 10, 15, 17, 22, 33, 34) and the pages on top of them have something real to run against. It is for operators standing up a stack and for every downstream PRP that needs data or a write path. It is `review: required` because it activates the write side of an authorization-sensitive system.

Out of scope (separate follow-ups, do not absorb): PRP-06 audit holes (denial recorder, SIEM export, push revocation); real-stack Playwright e2e; live gates (G05, G17, G04, G02, need `NS_LIVE_APPROVED=1`); turning MCP, copilot, scan or lifecycle on by default; multiple APIM gateways in one registry.

## Acceptance criteria
- [ ] Ingest: with the compose dev producers file mounted, `POST` to the ingest edge with the dev producer returns 2xx (not 503 `ingest_not_configured`); with the file unset it still returns 503 and `/readyz` detail shows `composition.ingest.disabled` plus a documented reason.
- [ ] Ingest: the dev producers file holds only `secret_sha256` digests of a documented throwaway dev secret, no plaintext key, and is mounted read-only; Helm mounts an operator-supplied file (Key Vault CSI path or configMap) and the chart documents the value.
- [ ] Seeding: `docker compose up` followed by the documented seed step leaves the catalog non-empty (entities, aliases, edges from the synthetic sandbox) with no host-side script, and is idempotent on re-run.
- [ ] Seeding: the seeder refuses to run unless `NS_ENV=local`; a hosted or Government profile never seeds synthetic data (test asserts the refusal).
- [ ] Search: `NS_SEARCH_PROVIDER` is read by code; `fixture` serves catalog search from an in-memory index built from the catalog, `azure` serves through `AzureAuthorizedSearch`; catalog graph search no longer returns 503 `search_unavailable` when a provider is configured.
- [ ] Search: where Azure AI Search is unavailable for the cloud/region (matrix row `ai_search`, e.g. `usgovtexas`) the provider reports disabled with a reason and never falls through to a cross-cloud endpoint; an indexer keeps the index in step with catalog writes.
- [ ] Search: results are authorization-filtered through the existing scope path (no unfiltered query path added).
- [ ] Write registry: API and workers register Foundry model-swap and APIM gateway-manage connectors from settings, each only when its own flag and target config are present; with none configured the registry is empty and a dry-run reports "no write target" instead of silently passing.
- [ ] Write registry: advisory, Government-refused or write-less connectors are still refused (existing `_check_capable` behaviour unchanged), and one connector per name is documented as a limit.
- [ ] Write registry: a dry-run of `model_deployment_swap` against the in-memory/fake ARM returns a real diff, and the executor path (not catalog metadata editing) is what a later swap would use.
- [ ] `ruff check .`, `ruff format --check .`, `pyright` and the touched pytest suites pass locally; `services/api/openapi.json` drift test passes; `python scripts/validate_planning.py` passes.
- [ ] Live Azure AI Search and live Foundry/APIM writes are reported OPEN (not run); no paid call is made in this PRP.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Catalog seeding source | Sandbox default + real opt-in; connectors only; sandbox everywhere | Sandbox seed by default in compose/dev; hosted/real seeds only from configured connectors |
| 2 | Which write connectors to register | All existing behind flags; Foundry only; pluggable loader, none enabled | All existing (Foundry swap, APIM manage), each behind its own flag, off unless config present; advisory still refused |
| 3 | Search backend | Azure AI Search + in-memory fallback; in-memory/Cosmos only; Azure only | Azure AI Search adapter plus in-memory fallback, chosen by settings; disabled where unsupported |
| 4 | Ingest producers file | Dev file in compose + mounted hosted; operator-only; auto-generated | Non-secret dev producers file in compose; mounted file in hosted; unset stays 503 but surfaced in `/readyz` |
| 5 | Priority/order (assumed by author, not asked) | n/a | P0, order 1: blocks every reopened PRP that needs data or writes. Change with `/prp:prp-prioritize` if you disagree |

## Context manifest (curated codebase intelligence)

### Files that matter
- `services/api/neurosphere_api/main.py:17-25` composition entry: load_settings, create_app, `configure_ingest_from_settings`, `configure_scan_from_settings`, `compose_app`.
- `services/api/neurosphere_api/runtime/builders/__init__.py:356-375` builder order (authz, data, planes, copilot, mcp, gateway, edge).
- `services/api/neurosphere_api/ingest/settings.py:25-35` (`NS_INGEST_`, `producers_file: Path | None`), `ingest/bootstrap.py:44-63` (no-op when unset), `ingest/router.py:42,60-63` (503 `ingest_not_configured`), `ingest/auth.py:36-70` (producers file format: `secret_sha256`, sources map, cloud).
- `services/workers/neurosphere_workers/ingestion/gateway_poll/producers.example.json:5` existing producers example.
- `services/api/neurosphere_api/runtime/builders/planes.py:107-108` (`SUPPORTED_WRITE_CONNECTORS`), `189-196` (`_write_targets` returns empty registry), `118` (PEP 695 `def _backend[T]`).
- `services/workers/neurosphere_workers/runtime/factories.py:411-443` (empty `WriteTargetRegistry()` at 427-431), `203-216` (credential pattern: `lifetime.register(DefaultAzureCredential)`).
- `connectors/sdk-python/neurosphere_connector/write/write_registry.py:16-54` (`_check_capable` refuses non-write, no `write_support`, advisory; keyed by manifest name at 38).
- `packages/core/neurosphere_core/actions/targets.py:27-56` (`ACTION_CONNECTORS`: `model_deployment_swap` to `foundry-model-swap`; `budget_cap_change`, `grant_*`, `mcp_server_*`, `gateway_mode_change` to `apim-gateway`).
- `connectors/reference/foundry-actions/neurosphere_connector_foundry_actions/connector.py:127-150,325-360` (`FoundryModelSwapConnector(account: AccountRef, arm, ...)`, `create_swap_connector` returns advisory on Government or permission shortfall); `endpoints.py:74-95` (`AccountRef`).
- `connectors/reference/apim-gateway/neurosphere_connector_apim_gateway/connector.py:128-175,375-392` (`government_refusal`, factory); `services/workers/neurosphere_workers/actions/apim.py:132-219` (`build_apim_gateway_connector`, `build_http_apim_gateway_connector`, built from a `GatewayRegistration`).
- `services/api/neurosphere_api/actions/dependencies.py:15` (API only calls `dry_run`).
- `packages/core/neurosphere_core/search/protocol.py:53-87` (`SearchRequest`/`SearchResult`, `AuthorizedSearch.search(scope, request)`); `search/azure/client.py:41-68` (`create_search_client`, `AzureAuthorizedSearch`); `search/azure/filters.py:60`; `search/azure/fallback.py:36-90` (`azure_search_capability`, `FallbackAuthorizedSearch`); `search/fixture/index.py:51-124` (`documents_from_catalog`, `FixtureSearchIndex`); `capabilities/data/search.yaml` (`ai_search` rows).
- `services/api/neurosphere_api/runtime/builders/data.py:186-188,211` and `services/workers/neurosphere_workers/recommendations/pipeline.py:127-134`: the two `_NoSearch` sites (`# type: ignore[arg-type]`).
- `infra/bicep/modules/search.bicep` (create-or-reuse, `disableLocalAuth: true`, RBAC only; no endpoint output), `infra/bicep/modules/main.bicep:127-134,190-198`.
- `scripts/sandbox/sbx_seed_stack.py:1-40,1067-1100` (host-only seeder, `seed_entities` via `CatalogRepository.create_entity`, idempotent via `get_entity`), `sandbox/generate.py:77`, `sandbox/catalog.py:69-259`, `Makefile:73-79` (`stack-up`).
- `packages/core/neurosphere_core/catalog/protocol.py:199-310` (`create_entity`, `put_alias`, `put_edge`, `put_override`), `catalog/repo/cosmos.py:157`.
- `docker-compose.yml:118-171` api service, `173-223` workers (read-only sandbox mount at 203-205 is the volume pattern), `221-223` (seed is host-only comment).
- `services/api/Dockerfile.dev:15-25`, `services/workers/Dockerfile.dev:15-27` (copy apim-gateway, azure-monitor; not foundry-actions); `services/api/pyproject.toml:7-20`, `services/workers/pyproject.toml:7-20`, root `pyproject.toml:35-49`.
- `infra/helm/values.yaml:40-55`, `infra/helm/templates/deployment.yaml:44-100` (env loop, volumeMounts 68-80, CSI volume 82-97).
- `services/api/neurosphere_api/health/router.py:53-66`, `health/probes.py:34-40,107`, `runtime/readiness.py:41-60`, `runtime/status.py:55,67-87`, `runtime/builders/edge.py:17-27` (ingest already reports `composition.ingest.disabled` when unset).

### Patterns to match
- Settings classes with env prefix: `ingest/settings.py:25-35`, `deploy/scan/settings.py:9`, `gateway/settings.py:37-41`; opt-in bootstrap that is a no-op when unset: `ingest/bootstrap.py:44-63`.
- Cloud/region gating that returns a disabled reason, never an error or cross-cloud fallback: `search/azure/fallback.py:36-62`, apim `connector.py:128-140`, foundry `connector.py:325-340`.
- Credential injection through the lifetime registry: `factories.py:203-216`.
- Autouse env clearing in test conftests: `services/api/tests/runtime_planes/conftest.py:8-36` (same in `runtime_api`, `runtime_data`, `runtime_routes`, `runtime_gateway_builder`). New `NS_SEARCH_`, `NS_FOUNDRY_`, `NS_APIM_` names must be added to the matching conftests.
- Producers-file test precedent: `services/api/tests/ingest/test_bootstrap.py:46`, `tests/integration/ingestion/support.py:154`.

### Conventions
- `python`, never `python3`; Windows + Git Bash; forward slashes in gate commands; temp files in `./temp/`.
- Pydantic v2 settings, `NS_` prefix, fail-fast on a bad file (`test_bad_producers_file_fails_fast`).
- Run touched test suites together (same-named test dirs with `__init__.py` shadow each other).
- Use `127.0.0.1`, not `localhost`, for emulators.

### Gotchas
- `planes.py` already uses PEP 695 generics (`def _backend[T]`); CodeQL flags them in nested defs. Do not add more in nested functions.
- Existing tests assert the empty registry: `services/api/tests/runtime_planes/test_planes_builder.py:~100-107` and `_ForeignTargets` at `~113-121`. They must be rewritten, not deleted: keep a test that the registry is empty when nothing is configured.
- `write_registry.py:38` keys by manifest name, so one APIM connector only; the worker APIM builders are per-`GatewayRegistration` (read from the Cosmos gateways store), not settings-driven. For this PRP, register one configured gateway via settings and file a follow-up for many.
- Foundry/APIM factories return advisory connectors on Government or permission shortfall; an advisory connector must never reach the registry.
- No `NS_FOUNDRY_*` or `NS_SEARCH_*` settings exist in code. `.env.example:18` mentions `NS_SEARCH_PROVIDER=fixture|azure` that nothing reads (do not read `.env`; `.env.example` only).
- No search indexer exists anywhere (no upload/merge/index calls); item 3 must add one.
- `search.bicep` has no endpoint output and Helm has nothing for search.
- Adding foundry-actions to API/workers needs `pyproject.toml`, `uv.lock` and Dockerfile `COPY` changes; images use `uv --frozen` and need every lock-referenced member copied.
- gitleaks: a producers file with digest-like strings trips `generic-api-key`; fingerprints in `.gitleaksignore` are commit-scoped, add the entry after the commit, no wildcards. `.gitleaks.toml:8-18` has path/regex allowlists. Never put a plaintext key in the file.
- `services/api/openapi.json` is guarded by `services/api/tests/test_openapi_drift.py`; any route or `response_model` change regenerates it. `response_model` renames components.
- `app.state` population (#104) conflicts across docs: `PRPs/shipped/PRP-29-platform-runtime-wiring.md:32` says closed; the deep audit says open. Verify at the start of item 3/4 (`gh issue view 104 --json state`) and record the result.
- Replacing `_NoSearch` changes catalog graph search from 503 `search_unavailable` to live results (`data.py:186-188`); update the tests that pin the 503.
- Local full-suite WinError 10055 socket flakes are TIME_WAIT churn, not a leak.
- Compose project name is fixed and shared across worktrees; sequence compose lanes and use unique `NS_E2E_APP_PORT`/`NS_MOCK_API_PORT` if browser tests run.

### External references
- Azure AI Search authorization/filters and index document upload: https://learn.microsoft.com/azure/search/search-howto-reindex and https://learn.microsoft.com/azure/search/search-security-trimming-for-azure-search (verify via Microsoft Learn MCP in the orchestrator; subagents lack it, paste facts into briefs).
- Azure AI Search availability by cloud/region (Government): https://learn.microsoft.com/azure/search/search-region-availability
- Foundry/Cognitive Services deployments ARM API used by the connector: the pinned API version in `endpoints.py` (do not change it here).

## Implementation blueprint

Parallelization map: items 1, 3 and 4 are independent [P]. Item 2 waits for 1 (both edit `docker-compose.yml`). Item 5 waits for 1-4 (owns the remaining compose env, docs and the smoke test). Shared files and their single owner: `docker-compose.yml` (1 then 2 then 5), `planes.py` and `planes_helpers.py` (4), `data.py` (3), `factories.py` (4), `pyproject.toml`/`uv.lock`/Dockerfiles (4), `openapi.json` (whoever changes a route, expected: none).

### Item 1 — Ingest config  [P]
- Deliverable: a non-secret dev producers file for compose (digests of a documented throwaway dev secret, no plaintext), mounted read-only into the api service with `NS_INGEST_PRODUCERS_FILE` set; Helm value and template mount for an operator-supplied producers file (CSI vault object path or configMap) with docs; `/readyz` reason text for the unset case verified; `.gitleaksignore` entry for the dev file added after commit.
- Owned files (may edit): `docker-compose.yml` (api service env/volumes only), new `infra/dev/ingest-producers.dev.json` (or the repo's existing dev-config dir), `infra/helm/values.yaml`, `infra/helm/templates/deployment.yaml`, `.gitleaksignore`, `services/api/neurosphere_api/ingest/**` (only if a `/readyz` reason needs a code change), `services/api/tests/ingest/**`, `docs/` ingest runbook page.
- Must NOT touch: `planes.py`, `data.py`, `factories.py`, search or connector code, other compose services.
- Depends on: none.
- Acceptance criteria: ingest POST with the dev producer returns 2xx against the composed app in a test (TestClient with the dev file path, plus a compose-level check documented in item 5); unset keeps 503 and `/readyz` shows `composition.ingest.disabled`; the file contains only `secret_sha256` values; `helm template` renders the mount when the value is set and omits it when unset; gitleaks passes with the added fingerprint.
- Pattern references: `ingest/bootstrap.py:44-63`, `ingest/auth.py:36-70`, `producers.example.json:5`, compose workers volume `docker-compose.yml:203-205`, Helm `deployment.yaml:68-97`.

### Item 2 — Catalog seeding  
- Deliverable: a compose-runnable idempotent seeder (one-shot service or `docker compose run` target) that loads the synthetic sandbox catalog (entities, aliases, edges) through `CatalogRepository`, replacing the host-only dependency; it refuses unless `NS_ENV=local`; `make stack-up` and docs use it.
- Owned files (may edit): new seeder module under `scripts/sandbox/` (reuse `seed_entities`, do not fork it), `docker-compose.yml` (new seed service and its depends_on only), `Makefile` (`stack-up` target), `scripts/sandbox/tests/**` or the nearest existing sandbox test dir, `docs/` seeding section.
- Must NOT touch: `sbx_guard` semantics (loopback-only guard stays), catalog repository protocol/Cosmos impl, production seed paths.
- Depends on: item 1 (shared `docker-compose.yml`).
- Acceptance criteria: against the emulator, seed then `list_entities` is non-empty and a second run creates no duplicates; run with `NS_ENV=hosted`/Government profile exits non-zero with a clear message (test); no production data is read; no secret in the compose file.
- Pattern references: `sbx_seed_stack.py:1067-1100`, `catalog/protocol.py:199-310`, `docker-compose.yml:221-223`, `Makefile:73-79`.

### Item 3 — Search backend  [P]
- Deliverable: `NS_SEARCH_PROVIDER` (`fixture` | `azure` | unset) settings class and a search builder; `fixture` builds `FixtureSearchIndex` from the catalog at startup and refreshes it on catalog writes; `azure` builds `AzureAuthorizedSearch` behind `FallbackAuthorizedSearch` so unsupported cloud/region reports disabled with a reason; an indexer that upserts catalog entities into the Azure index (hosted) and keeps the fixture index fresh (local); both `_NoSearch` sites replaced; `search.bicep` outputs the endpoint and the chart/Bicep documents the setting. Authorization filtering stays on the existing scope path.
- Owned files (may edit): `services/api/neurosphere_api/runtime/builders/data.py`, new `services/api/neurosphere_api/runtime/builders/search.py`, `services/api/neurosphere_api/runtime/builders/__init__.py` (register builder only), `services/workers/neurosphere_workers/recommendations/pipeline.py`, new indexer module under `packages/core/neurosphere_core/search/` or the catalog worker, `infra/bicep/modules/search.bicep`, `packages/core/tests/search/**`, `services/api/tests/runtime_data/**` (conftest + new tests), `services/api/tests/runtime_routes/**` only where a test pins 503 `search_unavailable`.
- Must NOT touch: `planes.py`, `factories.py`, compose, Helm, authz/scope logic, the Azure client's auth mode (RBAC/managed identity only, no keys).
- Depends on: none.
- Acceptance criteria: with `NS_SEARCH_PROVIDER=fixture` and a seeded catalog, a catalog search returns matches and an unauthorized scope returns none of the restricted entities (test); with `azure` on an unsupported region the capability is disabled with a reason and no request is made (test using the matrix row); with it unset behaviour is unchanged (503 `search_unavailable`) and documented; the indexer is idempotent and does not log document bodies; no key or connection string appears in code, Bicep output or logs.
- Pattern references: `search/azure/fallback.py:36-90`, `search/fixture/index.py:51-124`, `data.py:186-188,211`, `pipeline.py:127-134`, `runtime_data/conftest.py:25`.

### Item 4 — Write registry (API and workers)  [P]
- Deliverable: settings (`NS_FOUNDRY_` account ref and enable flag; `NS_APIM_` single gateway ref and enable flag) and builders that register `FoundryModelSwapConnector` and the APIM gateway connector into the API and worker `WriteTargetRegistry` only when enabled and configured; credentials via the existing `DefaultAzureCredential` lifetime pattern (no secrets in settings); advisory/refused connectors are skipped with a logged reason; foundry-actions packaged into the API and worker images (pyproject, `uv.lock`, Dockerfile `COPY`). Registered connector names match `ACTION_CONNECTORS`.
- Owned files (may edit): `services/api/neurosphere_api/runtime/builders/planes.py`, `services/api/neurosphere_api/runtime/builders/settings` additions (new `write_targets.py` settings module), `services/workers/neurosphere_workers/runtime/factories.py`, `services/workers/neurosphere_workers/runtime/settings.py`, `services/api/pyproject.toml`, `services/workers/pyproject.toml`, `uv.lock`, `services/api/Dockerfile.dev`, `services/workers/Dockerfile.dev`, `services/api/tests/runtime_planes/**` (incl. `planes_helpers.py`, conftest), `services/workers/tests/action_executor/**` only for new wiring tests.
- Must NOT touch: `write_registry.py` or its refusal rules, connector packages' behaviour, the action executor's permission/approval/audit logic, `data.py`, compose, Helm.
- Depends on: none.
- Acceptance criteria: with nothing configured both registries are empty and an API dry-run returns "no write target" (test replaces the old empty-registry assertion); with the Foundry flag and a fake ARM the registry holds `foundry-model-swap` and a `model_deployment_swap` dry-run returns a real diff; Government profile or missing permission yields the advisory connector and it is NOT registered (test); APIM with a fake `InMemoryApim` registers `apim-gateway`; duplicate names raise or are skipped deterministically (documented single-gateway limit); worker and API images build with `uv sync --frozen`; issue #132 referenced and its state recorded in the completion note.
- Pattern references: `planes.py:189-196`, `factories.py:411-443,203-216`, `foundry connector.py:325-360`, `apim.py:132-219`, `inmemory.py:54`, `test_planes_builder.py:~100-121`.

### Item 5 — Compose wiring, docs and smoke test
- Deliverable: remaining compose env for search and write flags (all off by default except the dev search fixture), a documented operator runbook (ingest producers, seed, search provider, write flags and their consequences), an integration-marked smoke test: compose emulator stack, dev producer ingests, catalog seeded, catalog search returns a hit, write registry reports its configured targets; results reported honestly (the `integration` marker never runs in CI).
- Owned files (may edit): `docker-compose.yml` (env additions only), `.env.example` (document `NS_SEARCH_PROVIDER` and the new names, no values that look like secrets), `docs/` runbook, `tests/integration/runtime_composition/**` (new), `PRPs/backlog/PRP-35-runtime-composition.md` (Execution state and completion note), regenerated `PRPs/INDEX.md` via `scripts/prp_status.py --write`.
- Must NOT touch: items 1-4 source files except to fix an integration defect (then record the deviation).
- Depends on: items 1, 2, 3, 4.
- Acceptance criteria: smoke test passes locally against the emulators (`127.0.0.1`), output shown; test skips cleanly when emulators are down; runbook lists each env var with default and effect; live gates stated OPEN.
- Pattern references: `tests/integration/ingestion/support.py:154`, `docker-compose.yml:118-223`.

## Validation gates
Run from the repo root, forward slashes, through bash. There is no `run-tests.ps1` in this repo; these are the CI commands (`.github/workflows/ci.yml:33-41`) scoped to touched suites. Run the suites together (test package name clash).

```bash
uv sync --frozen --group dev
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q services/api/tests/runtime_planes services/api/tests/runtime_data services/api/tests/runtime_routes services/api/tests/runtime_api services/api/tests/runtime_gateway_builder services/api/tests/ingest services/api/tests/test_openapi_drift.py services/workers/tests/action_executor connectors/reference/foundry-actions/tests connectors/reference/apim-gateway/tests packages/core/tests/search
python scripts/validate_planning.py
```

Feature-specific checks:
- Item 1: `helm template infra/helm --set <producers value>` renders the mount; without the value it does not. `git grep -n "secret_sha256" infra/` shows digests only; gitleaks passes on the branch.
- Item 2: seeder run twice against the emulator, entity count identical; run with `NS_ENV=hosted` exits non-zero.
- Item 5: `docker compose up -d --wait` (emulators only, no paid calls), then `uv run pytest -q -m integration tests/integration/runtime_composition` with the output pasted into the Execution state. Not run in CI, so report it as local evidence.
- Live Azure AI Search and live Foundry/APIM write tests are OPEN: they need `NS_LIVE_APPROVED=1` and an operator-approved environment. Report them as OPEN, do not run them.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (row 5 is an author assumption, flagged for the user)

## Execution state

| Item | Status | Branch / worktree | Model | Evidence | Updated |
|---|---|---|---|---|---|
| 1 | todo | | sonnet | | |
| 2 | todo | | sonnet | | |
| 3 | todo | | sonnet | | |
| 4 | todo | | opus | | |
| 5 | todo | | sonnet | | |

## Completion note (filled at ship)
<date, merged commits, deviations from blueprint + why, descoped items, follow-ups. Record #132 and #104 state. Follow-ups to file: multiple APIM gateways per registry; PRP-06 audit holes; real-stack e2e; live gates.>
