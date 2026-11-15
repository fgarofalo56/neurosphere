---
name: PRP-21-scale-federation-finops-and-dr
status: backlog
priority: P1
order: 26
review: required
created: 2026-10-08
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 4
ns: NS-07, NS-08
depends_on: []
wave: W13
branch: prp-21-round2-admission-federation
allow_parallel: true
absorbs: P4.3 + P4.4, G07
issues: [232, 105, 106, 107]
---

# PRP-21: Scale, federation, FinOps and DR (round 2)

## Goal
Wire the shipped per-domain admission limiter into the running API so a noisy domain is throttled in a real deployment, harden federation (one bad cell no longer denies the whole summary, operators can register peer cells, the cell endpoint host is allowlisted), clear the small PRP-21 follow-ups (locust ADR row, FinOps interval band, DR package imports, load scenario coverage), and re-run the pilot profile against the composed API with admission on. It is for SRE and FinOps operators and domain owners, and it runs in W13 because it is the wave owner of the API composition files (`authz/dependencies.py`, `runtime/builders/data.py`), `docker-compose.yml` and `infra/helm/**`. **Every number stays a measured result against a provisional planning target, never a guarantee.**

Out of scope: the sized load runs, failover, geo-replication, production restore, AI Search rebuild and invoiced-cost evidence (#108, operator only, PRP-64); the ingest edge's own per-producer limiter stays as it is (PRP-46 owns ingest follow-ups); admin UI for quotas (PRP-44/PRP-57); the APIM rate limit in Bicep (PRP-52).

## Why
- The limiter is not wired: no file under `services/` imports `neurosphere_core.admission` (grep over `services/` returns nothing); #105 stays open.
- The shipped middleware cannot work as written. `packages/core/neurosphere_core/admission/middleware.py:41-45` reads `scope["state"]["identity_scope"]`, but nothing in `neurosphere_api` ever sets `identity_scope` (zero matches). The `IdentityScope` is derived inside the FastAPI dependency `current_derivation` / `current_scope` (`services/api/neurosphere_api/authz/dependencies.py:92-123`) and checked in `require` (`:165-210`). ASGI middleware registered with `add_middleware` (`app.py:110-113`) runs before routing and before any dependency, so it sees no scope and would answer every request 401. Admission therefore has to be a dependency step (or an auth-first middleware that duplicates token validation, which is rejected).
- Federation composes one in-process cell only: `runtime/builders/data.py:262-285` builds `CellRef(... endpoint="https://local-cell.invalid/")` and an `InProcessCellClient`; `HttpCellClient` (`federation/client.py:80`) is used only in tests; `FederationSettings` (`data.py:147-155`) has no peer setting.
- #106 findings are all still true in code: a cell answering for another cell/cloud/boundary raises `CapabilityUnavailableError` that aborts the merge (`federation/service.py:132-156`); the window comes from `summaries[0]` (`:172-178`); all-denied returns an empty 200 `complete=false`; `cache.put` rebuilds the entry dict on every write (`federation/cache.py:62-67`) and `MAX_TTL_SECONDS` is a hard 300 (`:21`).
- #107: `docs/adr/0002-stack-pins.md` has no locust row; `finops/service.py:51` uses `Z_95 = 1.96`; `[tool.pyright]` (`pyproject.toml:79-85`) has no `extraPaths`, so `tests/integration/dr/*` carry pyright ignores; `tests/load/profiles/compose_pilot.py:6` still says the composed API has no ingest producers although `docker-compose.yml` now sets `NS_INGEST_PRODUCERS_FILE`.

## Acceptance criteria
- [ ] Given `NS_ADMISSION_ENABLED=true` and a quota policy file, When one domain exceeds its quota through any route that uses `require(...)`, Then it receives 429 `rate_limited` with `Retry-After` and another domain's requests still succeed (API-level test, two domains, fake clock).
- [ ] Given admission is off (default) or the policy file is absent, Then behaviour is unchanged when off; when on with no file the conservative default applies and a warning is logged, never unlimited (#105 bullet 4).
- [ ] The admission key comes only from the server-derived scope plus a route domain that `permits` already validated; a caller-supplied domain never selects a bucket (test); a denied-permission request is not charged to the target domain.
- [ ] Compose mounts a dev quota file and sets the settings; Helm has a documented value and mount for an operator-supplied file; `helm template` renders the mount only when set.
- [ ] A peer cell registered through `NS_FEDERATION_PEERS_FILE` is reached through `HttpCellClient` (MockTransport test); a peer whose host is not in its boundary allowlist, or whose scheme is not https, fails registry load at startup; a Government peer in a Commercial serving cloud (or the reverse) is refused at load.
- [ ] One peer answering for a different cell, cloud, boundary or customer yields that cell `unavailable` and the other cells still merge; no row from the mismatched response appears in the result (test).
- [ ] Merged window is min start / max end across answering cells; when every cell answers `denied` the route returns 403, not an empty 200; `cache.put` evicts without rebuilding the dict; the cache TTL ceiling is a setting.
- [ ] FinOps forecast bands use a t-quantile for small samples (documented table, no new dependency) and the committed evidence is regenerated; `unknown` stays `unknown`, never 0.
- [ ] ADR-0002 has a locust row (2.47.0, MIT, outside `uv.lock`, isolated subprocess); `[tool.pyright] extraPaths` includes `infra/dr` and the DR test pyright ignores are gone; `/otlp/metrics` is exercised by a load scenario.
- [ ] The pilot profile runs against the composed API with admission on and the result (including noisy-neighbor behaviour under the skew scenario) is written to `docs/evidence/G07/pilot/`, labelled "compose, bounded feasibility"; thresholds that fail are reported as failed.
- [ ] PRP exit: touched suites pass, `verify-gates.ps1 -Mode full` green, G07 row text updated to say what was measured and what stays OPEN (#108).

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Admission mechanism | ASGI middleware; auth-first middleware; FastAPI dependency | Dependency step inside `require()`. ASGI middleware cannot see the scope (Why bullet 2), and an auth-first middleware would validate tokens twice |
| 2 | Charge point | Before permission check; after | After the permission check passes, with the validated target domain as the route domain, so a denied caller cannot drain another domain's bucket |
| 3 | Coverage | Every route; routes with `require()`; ingest too | Routes that use `require()`. The ingest edge authenticates producers separately and keeps its own per-producer limiter (`ingest/limits.py:75`, 429 `rate_limited`); health and public paths are not charged |
| 4 | Default state | On; off | ASSUMPTION: `NS_ADMISSION_ENABLED` defaults to false; compose and Helm examples turn it on. Absent policy with enabled true uses the conservative default (10 req/s, burst 20) with a warning, per round-1 clarification 6 |
| 5 | Where state lives | `AuthzState`; `app.state.admission` | `app.state.admission`, read in `require_permission`; `authz/state.py` is PRP-48's file and is not edited |
| 6 | Peer cell config | Inline env; file | `NS_FEDERATION_PEERS_FILE` (JSON: cells plus per-boundary `allowed_hosts`). No credentials in the file: the caller's bearer is forwarded as today (A7 principle) |
| 7 | Ingest latency target (#107) | Invent a number; keep the placeholder | ASSUMPTION: no new target is invented. The 2 s p95 threshold stays labelled provisional in `tests/load/profiles/definitions.py` with a pointer to the open owner decision; the owner sets the real figure |
| 8 | Pilot re-run | Live sized; compose | Compose, composed API, admission on; no live gate. Sized profiles stay OPEN (#108, PRP-64) |
| 9 | Model and review | sonnet/none; sonnet/required | sonnet, review required: admission touches the authz dependency every route uses |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/admission/{middleware.py,limiter.py,config.py}` - limiter, `derive_limiter_key`, `load_quota_policy`.
- `services/api/neurosphere_api/authz/dependencies.py` - `require`, `current_scope` (the Tier-1 edit).
- `services/api/neurosphere_api/runtime/builders/__init__.py` - `default_builders`, `BuilderSpec`; `runtime/builders/edge.py` as a small builder example.
- `services/api/neurosphere_api/runtime/builders/data.py:147-155,251-290` - `FederationSettings`, `_federation`.
- `services/api/neurosphere_api/federation/{service,client,cache,router}.py` - merge, clients, cache.
- `services/workers/neurosphere_workers/federation/models.py` - `CellRef`, `CellRegistry` (endpoint validation lives here).
- `services/api/neurosphere_api/finops/service.py` - band at `Z_95` (line 51).
- `tests/load/profiles/{definitions,compose_pilot,scenarios}.py` and `docs/evidence/G07/load/README.md`.
- `docker-compose.yml:118-175` (api service env and volumes) and `infra/helm/values.yaml:40-55`, `infra/helm/templates/deployment.yaml:44-100`.
- `docs/runbooks/ingest.md` - runbook style to copy for the new admission page.

### Interfaces consumed
- `IdentityScope`, `permits`, `Permission` (PRP-06, shipped); `RateLimitedError` taxonomy (PRP-05).
- `AggregateReader` and `AUTHENTICATOR`, `SCOPE_SOURCE` shared keys (PRP-14, PRP-06 builders).
- Ingest producers file wiring in compose (PRP-35) so the composed API accepts pilot traffic.

### Interfaces provided
- Settings: `NS_ADMISSION_ENABLED`, `NS_ADMISSION_POLICY_FILE`, `NS_FEDERATION_PEERS_FILE`, `NS_FEDERATION_CACHE_MAX_TTL_SECONDS`.
- `app.state.admission` (a `TokenBucketLimiter` or absent); builder module `runtime/builders/admission.py` (new). PRP-44 can later feed the policy from the admin store through the same limiter constructor.
- Evidence directory `docs/evidence/G07/pilot/` for PRP-64's comparison.

### Patterns to match
- Opt-in settings and a no-op when unset: `ingest/bootstrap.py:44-63`; builder shape `runtime/builders/edge.py:17-29`.
- Fail-fast on a bad settings file: `data.py:251-258` (`ComponentUnavailableError`).
- Mounted read-only dev file in compose: `docker-compose.yml:163,171` (`ingest-producers.dev.json`); Helm mount: `deployment.yaml:68-97`.
- Federation scope tests: `services/api/tests/federation_api/test_federation_scope.py`.

### Gotchas
- Real test directories are `services/api/tests/{federation_api,finops_api}`, `services/workers/tests/federation_worker` and `packages/core/tests/admission`; the round-1 gate line named directories that do not exist. A new `services/api/tests/admission_api/` must stay uniquely named.
- `require()` is used by every protected route; the route-inventory tests (`services/api/tests/authz/test_route_inventory.py`) must keep passing with no new route. No `openapi.json` change is expected (a 429 response is not declared per route).
- The limiter holds a `threading.Lock` (`limiter.py:96-118`); the dependency calls `admit` synchronously, which is fine, but never `await` inside the lock.
- The compose project is shared across worktrees: this PRP holds the compose stack in W13; item 4 is the only item that runs `docker compose`.
- ASSUMPTION conflict check: PRP-39 (also W13) must not edit `authz/dependencies.py`; it is this PRP's file in W13.
- Locust must stay out of `uv.lock` and run as an isolated subprocess (gevent monkeypatching).

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership

```ownership
owns:
  - packages/core/neurosphere_core/admission/**
  - packages/core/tests/admission/**
  - services/api/neurosphere_api/federation/**
  - services/workers/neurosphere_workers/federation/**
  - services/api/neurosphere_api/finops/**
  - services/api/neurosphere_api/runtime/builders/admission.py
  - services/api/tests/admission_api/**
  - services/api/tests/federation_api/**
  - services/api/tests/finops_api/**
  - services/workers/tests/federation_worker/**
  - tests/load/profiles/**
  - tests/integration/dr/**
  - infra/dr/**
  - infra/dev/admission-quotas.dev.json
  - docs/runbooks/admission-and-federation.md
  - docs/evidence/G07/pilot/**
  - docs/evidence/G07/finops/**
tier1:
  - services/api/neurosphere_api/authz/dependencies.py
  - services/api/neurosphere_api/app.py
  - services/api/neurosphere_api/runtime/builders/data.py
  - docker-compose.yml
  - infra/helm/**
  - docs/adr/0002-stack-pins.md
  - pyproject.toml
tier2_appends:
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/settings.py
  - services/api/tests/authz/test_route_inventory.py
must_not_touch:
  - services/api/neurosphere_api/authz/state.py
  - services/api/neurosphere_api/ingest/**
  - packages/contracts/**
  - uv.lock
```

## Implementation blueprint

Items 1, 2 and 3 are independent [P] (disjoint files; `pyproject.toml` is edited only by item 3, `docker-compose.yml` only by item 1, `data.py` only by item 2). Item 4 waits for 1 and 3. Item 5 closes out.

### Item 1 - Admission wiring through the authz dependency  [P]
- Deliverable: `AdmissionSettings` (`NS_ADMISSION_ENABLED`, `NS_ADMISSION_POLICY_FILE`) and new builder `runtime/builders/admission.py` that loads `load_quota_policy`, builds a `TokenBucketLimiter` and sets `app.state.admission` only when enabled; `require_permission` in `authz/dependencies.py` charges the limiter after the permission check passes, using `derive_limiter_key(scope, target.domain_id)`, and raises the limiter's `RateLimitedError`; the unused ASGI factory stays in core but its docstring states it requires an upstream scope setter and is not used by the API; compose mounts `infra/dev/admission-quotas.dev.json` and sets the settings; Helm value `admission.policyFile` (and ConfigMap alternative) mirroring the ingest mount; runbook page.
- Owned files: `packages/core/neurosphere_core/admission/**`, `services/api/neurosphere_api/runtime/builders/admission.py`, `services/api/neurosphere_api/authz/dependencies.py`, `services/api/tests/admission_api/**`, `packages/core/tests/admission/**`, `infra/dev/admission-quotas.dev.json`, `docker-compose.yml` (api env and volumes only), `infra/helm/**` (values and the api deployment mount only), `docs/runbooks/admission-and-federation.md`, Tier-2 append in `builders/__init__.py` (`default_builders`) and `runtime/settings.py`.
- Must NOT touch: `authz/state.py`, `ingest/**`, `routers.py`, other compose services.
- Depends on: none.
- Acceptance criteria: the first four criteria above; a test asserts no `identity_scope` state is required; existing authz and route-inventory tests unchanged.
- Tests: `services/api/tests/admission_api/test_admission_dependency.py` (new), `services/api/tests/admission_api/test_admission_builder.py` (new), `packages/core/tests/admission/test_noisy_neighbor.py`, `services/api/tests/authz/test_route_inventory.py`; `helm template` check in the gates.
- Pattern references: `authz/dependencies.py:165-210`, `limiter.py:57-118`, `edge.py:17-29`, `ingest/bootstrap.py:44-63`.

### Item 2 - Federation hardening and peer cells  [P]
- Deliverable: `FederationSettings` gains `peers_file` and `cache_max_ttl_seconds`; `_federation` loads peers, builds one `HttpCellClient` over a shared `httpx.AsyncClient` (no redirects, closed on shutdown) and registers each peer; `CellRegistry` loading validates per-boundary `allowed_hosts`, https only and serving-cloud equality; `Federator` marks a mismatched response `unavailable`, takes min/max window, returns 403 when every cell is `denied`; `SummaryCache.put` evicts lazily; TTL ceiling configurable.
- Owned files: `services/api/neurosphere_api/federation/**`, `services/workers/neurosphere_workers/federation/**`, `services/api/neurosphere_api/runtime/builders/data.py` (the `_federation` function and `FederationSettings` only), `services/api/tests/federation_api/**`, `services/workers/tests/federation_worker/**`, `docs/runbooks/admission-and-federation.md` (federation section; coordinate with item 1 by appending a section, not editing its text).
- Must NOT touch: other builders in `data.py`, `authz/**`, contracts.
- Depends on: none.
- Acceptance criteria: the federation criteria above; the scope-leak tests still pass (no out-of-scope row, no cross-cloud contribution).
- Tests: `services/api/tests/federation_api/test_federation_scope.py`, `services/api/tests/federation_api/test_peers_http.py` (new), `services/api/tests/federation_api/test_federation_resilience.py` (new), `services/workers/tests/federation_worker/test_cell_summary.py`.
- Pattern references: `federation/service.py:120-180`, `federation/client.py:80-125`, `data.py:262-285`.

### Item 3 - Minor follow-ups (#107)  [P]
- Deliverable: ADR-0002 locust row; t-quantile table in `finops/service.py` replacing `Z_95` for small samples (documented, deterministic) and regenerated `docs/evidence/G07/finops/` via the existing evidence entry point (`finops/__main__.py`); `[tool.pyright] extraPaths = ["infra/dr"]` and removal of the DR pyright ignores (`tests/integration/dr/test_restore_compose.py:11-12`, `test_target_refusal.py:5`); `/otlp/metrics` scenario in `tests/load/profiles/scenarios.py`; corrected rationale text in `compose_pilot.py`; provisional wording on the ingest p95 threshold.
- Owned files: `docs/adr/0002-stack-pins.md`, `pyproject.toml` (`[tool.pyright]` only), `services/api/neurosphere_api/finops/**`, `services/api/tests/finops_api/**`, `tests/load/profiles/**`, `tests/integration/dr/**`, `infra/dr/**`, `docs/evidence/G07/finops/**`.
- Must NOT touch: `uv.lock`, `[project]` or dependency tables in `pyproject.toml`, `federation/**`.
- Depends on: none.
- Acceptance criteria: the FinOps, ADR, pyright and `/otlp/metrics` criteria; repo-wide `uv run pyright` stays clean (it covers `infra/dr` only through `extraPaths`).
- Tests: `services/api/tests/finops_api/test_forecast.py`, `services/api/tests/finops_api/test_finops_unknown_not_zero.py`, `services/api/tests/finops_api/test_t_quantile.py` (new), `tests/load/profiles/test_profiles_definition.py`.
- Pattern references: `finops/service.py:1-60`, `tests/load/profiles/scenarios.py`.

### Item 4 - Pilot re-run on the composed API
- Deliverable: `compose_pilot` targets the compose `api` service (profile `app`) with admission enabled and the dev ingest producers; run the pilot and the skew scenario; write evidence JSON and a README (environment, method, admitted/throttled counts per domain) to `docs/evidence/G07/pilot/`; failed thresholds are reported as failed.
- Owned files: `tests/load/profiles/compose_pilot.py`, `tests/load/profiles/test_pilot_compose.py`, `docs/evidence/G07/pilot/**`.
- Must NOT touch: product code, `docker-compose.yml` (item 1 owns it), `docs/evidence/G07/load/**` (round-1 evidence stays).
- Depends on: items 1 and 3.
- Acceptance criteria: the pilot criterion above; run once, output pasted into the Execution state; only this item uses the compose stack.
- Tests: `tests/load/profiles/test_pilot_compose.py` (integration marker, skips cleanly with the stack down).
- Pattern references: `docs/evidence/G07/load/README.md`.

### Item 5 - Integration and close-out
- Deliverable: Tier-2 inventories if a route changed (none expected), update the G07 row in `docs/RESEARCH-AND-GATES.md` (the one row) in the close-out commit, regenerate Tier 3 files, tick round-1 boxes confirmed in code, completion note with "Env vars for the operator" (the four new settings), `python scripts/prp_status.py --write`, CHANGELOG entry.
- Owned files: this PRP file; `docs/RESEARCH-AND-GATES.md` (G07 row only).
- Must NOT touch: items 1-4 source except an integration defect (record it).
- Depends on: items 1-4.
- Acceptance criteria: completion note filled; #105 and #106 closed by the PR if fully fixed, #107 closed or its residue listed; #108 left open.

## Validation gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/admission services/api/tests/admission_api services/api/tests/federation_api services/api/tests/finops_api services/workers/tests/federation_worker services/api/tests/authz tests/load/profiles services/api/tests/test_openapi_drift.py
helm template infra/helm --set admission.policyFile=/etc/neurosphere/admission/quotas.json
docker compose --profile app up -d --wait
uv run pytest -q -m integration tests/load/profiles/test_pilot_compose.py tests/integration/dr
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
python scripts/validate_planning.py
```

## Migration and rollback
No data migration. New settings default to off or unset, so existing deployments behave as before. Rollback: set `NS_ADMISSION_ENABLED=false` (and drop the peers file) to disable at runtime, or revert the PRP branch. The `require()` change is a no-op when `app.state.admission` is absent.

## Live and open gates
- #108 (enterprise/stress profiles, failover, geo-replication, production restore, AI Search rebuild, invoiced cost) needs `NS_LIVE_APPROVED=1` and an operator; handed to PRP-64. G07 stays OPEN.
- Compose pilot numbers are bounded feasibility (emulators), not a sizing result.
- No paid call is made by this PRP.

## NOT building
- Sized or stress load runs, DR on real services, invoiced FinOps evidence (PRP-64).
- Admission for the ingest edge, UI for quotas, quota storage in the admin store (PRP-44, PRP-57).
- A new ingest latency target number (owner decision pending, Clarification 7).
- A new auth-first middleware.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (rows 4 and 7 are labelled assumptions)

## Execution state

| Item | Status | Branch/worktree | Notes |
|------|--------|-----------------|-------|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |

## Completion note (filled at ship)
- Date, PR, merge commit:
- Deviations from the blueprint and why:
- Descoped items:
- OPEN gates (#108 items, G07):
- Env vars for the operator (`NS_ADMISSION_ENABLED`, `NS_ADMISSION_POLICY_FILE`, `NS_FEDERATION_PEERS_FILE`, `NS_FEDERATION_CACHE_MAX_TTL_SECONDS`):
- Follow-up issue numbers:
- Product check (can an operator set quotas and add a cell without editing code?):

## History
- Round 1 (PR #103, merged 2026-10-22, merge `6b43d63`) shipped the load profiles, the admission library, federation summaries, the FinOps forecast, the DR drill and the router wiring (items 1-6). The pilot failed its 1k events/s target on compose and was recorded as bounded feasibility.
- The 2026-11-04 audit reopened it: admission not composed, federation single cell, FinOps on a sandbox ledger, DR synthetic.
- The 2026-11-14 re-audit (lane-c) found the PRP-11 dependency not real (no import of `neurosphere_core.analytics` in admission, federation, finops, load or DR), the FinOps "sandbox ledger" half stale (the route reads `CosmosLedgerStore`), the UI-missing gap stale, and a design blocker: ASGI middleware cannot see the scope. That is why admission is a dependency step here.
- This rewrite removed the round-1 blueprint, wiring-delta and audit sections, dropped `depends_on`, fixed the gate paths to `federation_api`, `finops_api` and `federation_worker`, and split operator-only #108 out to PRP-64.
- The original text is in git history (`git log --follow PRPs/backlog/PRP-21-scale-federation-finops-and-dr.md`).
