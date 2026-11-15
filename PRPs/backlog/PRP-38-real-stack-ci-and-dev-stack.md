---
name: PRP-38-real-stack-ci-and-dev-stack
status: backlog
priority: P0
order: 21
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-01, NS-05, NS-08
depends_on: []
wave: W12
branch: prp-38-real-stack-ci
allow_parallel: true
issues: [227, 205, 211, 162, 209, 180]
---

# PRP-38: Real stack that starts, seeds cleanly and is tested in CI

## Goal
Make the local real stack and its tests trustworthy, then run them in CI. Today a fresh `make stack-up` never completes (#205), the real-stack seed test fails on fresh emulators (#211), `make replay` quarantines every event as `invalid_wire` (#162), the seeded stack has no gateway and a forecast that answers 409 (#209), and the nine suites in `tests/integration/real_stack` plus the headed-only Playwright route walk never run in CI, so every later PRP in waves W12 to W20 that touches the data path is verified by nothing. This PRP fixes the five defects, adds a compose-gated CI workflow that runs the real-stack pytest suites, and adds a headless real-stack Playwright run that signs in with the in-process dev issuer (never Entra) and walks the main flows. It is for every developer and for the reviewers of the later PRPs. It holds the compose stack during W12: no other W12 PRP may run `docker compose` or `make stack-up`.

Out of scope: worker code changes to make roles idle until in scope (Fix B of #205: `factories.py` belongs to the wave owners); hosted-environment seeding (PRP-58); the admin console specs (PRP-53, PRP-57 add their own real-stack specs later); the mock-API gap of #209 item 1 (PRP-47); the live G17 and operator-only items (PRP-64); making the new job a required check (an operator branch-protection change, listed under Live and open gates).

## Why
- `Makefile:77` runs `docker compose --profile app up -d --wait --build` before `Makefile:79` runs `seed-stack`, which is the step that grants the worker principal its domains. `docker-compose.yml:226` sets `NS_WORKER_EVAL_PILOT_DOMAIN_ID`, and `services/workers/neurosphere_workers/runtime/factories.py:924-931` (`_require_scope`) raises a terminal `RoleConfigError("evaluation_pilot_domain_out_of_scope")`, so the container stays unhealthy and `--wait` aborts (#205).
- `scripts/sandbox/sbx_seed_stack.py:1067-1100` (`seed_entities`) runs after the wait for the workers to land events (`:1288` comment); `tests/integration/real_stack/test_seed.py:180` asserts `skipped_existing == 0` on the first run but the count varies (7 or 10) with timing (#211). The cause is a hypothesis (projection workers write the same entity ids first); it was not reproduced.
- `scripts/sandbox/sbx_cli.py:81-96` (`publish_events`) sends the raw lines of `telemetry.ndjson` through `HubSeam.publish`, whereas `scripts/sandbox/sbx_seed_stack.py:531-562` (`hub_lines`) wraps every document in the `HubMessage` envelope (`packages/core/neurosphere_core/payload/wire.py:30`, `extra="forbid"`, required `wire_version`, `kind`, `event_id`, `cloud`, `customer_id`, `source_id`, `producer_id`, `received_at`, `data`). The worker validates `HubMessage` at `services/workers/neurosphere_workers/ingestion/pipeline.py:135-141`, so every raw line is `invalid_wire`; this matches #162 (all 1653 events quarantined) and explains why `make seed-stack` events land.
- CI never runs the suites: `ci.yml:51` runs `uv run pytest -q`, `pyproject.toml:90` deselects the `integration` marker, and the only compose job is `egress-compose` (`ci.yml:231-247`, `-m integration tests/security/egress`). `frontend/playwright.real-stack.config.ts` is headed and asks a human for an Entra sign-in (`frontend/tests/real-stack/global-setup.ts`); there is one spec, `routes.spec.ts`.
- The suites already compose the API and the `ingestion` and `projections` roles in-process against the emulators with a stand-in issuer (`tests/integration/real_stack/conftest.py:95-140`), so CI needs the emulators only, not the Entra-bound app profile.
- `services/workers/neurosphere_workers/runtime/roles.py:36` keeps `OPT_IN_ROLES = ()`, read at `:79` (#180 item 1).
- `tests/integration/compose/test_app_profile.py:169-172` pins the current (broken) order of `Makefile` steps, so the #205 fix must update that test.

## Acceptance criteria
- [ ] Given a clean checkout, emulators wiped (`docker compose down -v`) and `NS_ENTRA_TENANT_ID` and `NS_ENTRA_CLIENT_ID` exported, when `make stack-up` runs, then it exits 0 and `docker compose --profile app ps` shows api, workers and frontend healthy (#205). The Makefile order is: generate sandbox data, emulators up, sandbox seed, stack-seed grants only, app profile up with `--wait`, full stack seed.
- [ ] `tests/integration/compose/test_app_profile.py` pins the new order and a second test fails if the app profile is started before the grants (#205 regression guard).
- [ ] Given fresh emulators, `uv run pytest -q -m integration tests/integration/real_stack/test_seed.py` passes five runs in a row; `skipped_existing` on the first run is explained and asserted for its real meaning (nothing pre-existing), not a timing-dependent zero (#211). `docs/dev/local-setup.md` states that `test_catalog_discovery` and `test_evaluation_loop` need an empty Event Hubs emulator and how to reset it.
- [ ] `make replay` against an empty hub on the running stack: valid events are accepted and archived, only the manifest's malformed events (5 in the 2026-11-03 report) are quarantined, duplicates and late events are counted as such (#162). A unit test pins that valid lines are wrapped in `HubMessage` and malformed lines stay raw.
- [ ] The seeded stack answers the cost forecast with a value (not 409 `price_version_unresolved`) in at least one seeded domain, and one gateway registration is seeded so `/gateways/detail` has data (#209 items 2 and 3); both are idempotent on re-run.
- [ ] `OPT_IN_ROLES` and the code that reads it are removed, and the test asserting `all == ROLE_NAMES` still passes (#180 item 1).
- [ ] `.github/workflows/real-stack.yml` (new) starts the emulators with `docker compose up -d --wait`, runs `uv run pytest -q -m integration tests/integration/real_stack`, fails loudly (no `|| true`, no `continue-on-error`), dumps `docker compose logs` on failure, and is green on its own PR. It is path-filtered for pull requests and also runs on push to `main` and `workflow_dispatch`.
- [ ] Given the in-process stand-in API and the Vite dev server in the same job, when the headless real-stack Playwright run executes, then it signs in without a human (dev issuer, assumption A3), walks the manifest routes and passes the flow specs for catalog and curation, quality, actions and copilot (each asserting a real API answer, not only that a page rendered). If the sign-in cannot be made reliable, the browser step is descoped, reported OPEN, and the rest still ships.
- [ ] No `.github/workflows/ci.yml`, `factories.py` or Entra id/secret is edited or committed.

PRP exit: all boxes ticked, the new workflow run linked, `verify-gates.ps1` full run green, review pass (`review: required`) approved, PR open with CI green.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | How is #205 fixed | Makefile reorder; make the evaluation role idle until in scope | ASSUMPTION A5 (assigned): reorder the Makefile, not worker code. Refinement found in the code: `seed-stack` also waits for the workers to land events, so grants must be callable alone (a `--grants-only` mode in `sbx_seed_stack.py`), then the full seed runs after the app is up (it is idempotent). Verify that the grant phase needs no worker before relying on it. |
| 2 | Browser sign-in in CI | Real Entra; dev issuer | ASSUMPTION A3 (assigned): the dev issuer (`DevIssuer`, `neurosphere_core/auth/jwt/dev_issuer.py`), never Entra. Needs a stand-in API process (compose `api` validates Entra only) and a pre-seeded MSAL cache in the browser. |
| 3 | Which compose profile runs in CI | Emulators only; full app profile | Emulators only for pytest (the suites are in-process); no app-profile images are built in this job. |
| 4 | New workflow vs editing `ci.yml` | New file; extend `ci.yml` | New `real-stack.yml` (assigned; `ci.yml` is not touched). |
| 5 | Required check | Required now; non-required first | Non-required until it has been green for a week. ASSUMPTION: the operator flips branch protection; this PRP only records the job name. |
| 6 | #162 cause | Generator emits the wrong shape; publisher omits the envelope | ASSUMPTION: the publisher omits the envelope (code read, not reproduced). Item 3 reproduces first; if the cause differs, fix the real one and record it. |
| 7 | CI runner capacity | Accept; shard | The Cosmos emulator is heavy and runner saturation is a known risk (memory note). Verified 2026-11-14 on Microsoft Learn: the vNext emulator image this repo's compose file uses (`mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:vnext-latest`) is documented for GitHub Actions on `ubuntu` runners, as a service container or via `docker run` (https://learn.microsoft.com/azure/cosmos-db/emulator-linux#use-in-continuous-integration-workflow). ASSUMPTION that remains: the emulator plus Event Hubs emulator, Azurite and the app fit one `ubuntu-latest` job; UNVERIFIED until the first run. |

## Context manifest

### Files to read first
- `Makefile` (`:55-84`: `stack-up`, `STACK_WORKER_OID`) and `scripts/sandbox/sandbox.mk` (`seed`, `seed-stack`, `replay`).
- `scripts/sandbox/sbx_seed_stack.py` (`seed_grants`, `seed_prices`/`synthetic_snapshot` `:750-796`, `hub_lines` `:531`, `seed_entities` `:1067`, the main flow `:1230-1330`, argparse `:1586+`).
- `scripts/sandbox/sbx_cli.py` (`publish_events` `:81`, `cmd_replay` `:125`) and `scripts/sandbox/sbx_seam.py` (`HubSeam.publish`).
- `tests/integration/real_stack/conftest.py` (stand-in issuer, `composed_app`) and `test_seed.py`.
- `tests/integration/compose/test_app_profile.py` (`:157-172` Makefile pins).
- `docker-compose.yml` (`:112-290`: api, workers, seed service, `NS_WORKER_EVAL_*`).
- `frontend/playwright.real-stack.config.ts`, `frontend/tests/real-stack/{global-setup,fixtures,routes.spec}.ts`, `frontend/src/auth/{msal,token}.ts` (where tokens are read).
- `services/workers/neurosphere_workers/runtime/roles.py` (`OPT_IN_ROLES`), `.github/workflows/ci.yml` (job conventions, `:231-247`).
- `docs/dev/local-setup.md` ("Real stack", `:121-145`).

### Interfaces consumed
- `DevIssuer`, `JwtValidator`, `CompositionOverrides(authenticator=...)` (PRP-06, shipped); `HubMessage` wire contract (PRP-05/07, shipped); `GatewayStore` and `GatewayRegistration` (`packages/core/neurosphere_core/gateway/store.py:54`, `models.py:138`, PRP-33, shipped).
- `frontend` Vite dev server same-origin proxy for `/api` (`frontend/vite.config.ts:115-125`, active for plain `vite` modes).

### Interfaces provided
- `make stack-up` with the new order and `sbx_seed_stack.py --grants-only`.
- `.github/workflows/real-stack.yml`; job id `real-stack` (name for a later branch-protection change).
- `tests/integration/real_stack/serve_stand_in_api.py` (new): a test-only launcher that serves the composed app with the stand-in validator on `127.0.0.1` (never imported by `main` or compose).
- `NS_REAL_STACK_MODE=ci` for `frontend/playwright.real-stack.config.ts` (headless, `webServer` entries, no human step); `frontend/tests/real-stack/flows/*.spec.ts` (new).

### Patterns to match
- Job shape, `uv sync --frozen --group dev`, timeouts and fail-loud rule: `.github/workflows/ci.yml:231-247` and header `:1-8`.
- Stand-in issuer usage: `tests/integration/real_stack/conftest.py:95-140`.
- Playwright `webServer` pair with unique ports: `frontend/playwright.config.ts:43-56` (`NS_E2E_APP_PORT`, `NS_MOCK_API_PORT`).
- Session replay into pages: `frontend/tests/real-stack/fixtures.ts` (`restoreSession`).
- Makefile pin tests: `tests/unit/sandbox_stack/test_seed_catalog.py:230-237`.

### Gotchas
- The compose project name is shared across worktrees: nothing else runs `docker compose` or `make stack-up` in W12 while this PRP works. Use `127.0.0.1`, never `localhost`, for emulators (`NS_PROBE_COSMOS_URL=http://127.0.0.1:8081/`).
- `integration`-marked suites are deselected by default; the workflow passes `-m integration` explicitly and must also set the repo's `NS_ENV=local` conventions the fixtures expect.
- `test_catalog_discovery` and `test_evaluation_loop` fail when the Event Hubs emulator still holds a backlog; the CI job starts from fresh emulators, local runs need `make dev-reset`.
- Compose reads `NS_ENTRA_TENANT_ID` and `NS_ENTRA_CLIENT_ID` from the environment only; CI must not need them (the pytest path does not build the app profile). Never commit a real tenant or client id.
- MSAL keeps its cache in `sessionStorage`, which Playwright `storageState` does not carry; `fixtures.ts` replays a dumped copy. The CI sign-in must synthesise a cache the frontend accepts (account entry plus a valid unexpired access token minted by the stand-in issuer). Its exact keys are the riskiest unknown; read `@azure/msal-browser` cache key shapes before writing it and keep the token out of logs and artifacts.
- The seed refuses non-loopback hosts (`sbx_guard`); keep every seed step on the host, as today.
- `HubSeam.publish` partitions by line content; keep the partition choice unchanged when wrapping.
- Several tests pin Makefile text (`test_app_profile.py`, `test_seed_catalog.py`): run both after any Makefile edit.
- Playwright needs unique `NS_E2E_APP_PORT` and `NS_MOCK_API_PORT`-style ports per worktree; add a port variable for the stand-in API.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership

```ownership
owns:
  - Makefile
  - scripts/sandbox/**
  - tests/integration/real_stack/**
  - tests/integration/compose/test_app_profile.py
  - tests/unit/sandbox_stack/**
  - frontend/tests/real-stack/**
  - frontend/playwright.real-stack.config.ts
  - .github/workflows/real-stack.yml
  - docs/dev/local-setup.md
  - services/workers/neurosphere_workers/runtime/roles.py
  - services/workers/tests/worker_roles/test_roles.py
tier1:
  - docker-compose.yml
  - Makefile
tier2_appends: []
must_not_touch:
  - services/workers/neurosphere_workers/runtime/factories.py
  - .github/workflows/ci.yml
  - sandbox/**
  - frontend/src/**
  - frontend/tests/mock-api/**
```

## Implementation blueprint

Parallelization: items 1, 3 and 4 touch different scripts but all edit `scripts/sandbox/**`: 1 and 4 both edit `sbx_seed_stack.py`, so only item 3 (`sbx_cli.py`) and item 2 (a test file) are [P] with them. Item 5 needs 1 to 4 done (it runs the suites). Item 6 depends on 5's sign-in helper decision.

### Item 1 - Fresh stack-up order (#205, A5)
- Deliverable: add `--grants-only` to `sbx_seed_stack.py` (generate the world, apply `seed_grants` and nothing that needs workers); reorder `stack-up`: sandbox-generate, `docker compose up -d --wait` (emulators), sandbox seed, `seed-stack --grants-only`, app profile up `--wait --build`, full `seed-stack`, then the compose seed service as today. Update the two Makefile-pin tests and add the "grants before app" test.
- Owned files: `Makefile`, `scripts/sandbox/sbx_seed_stack.py`, `scripts/sandbox/sandbox.mk`, `tests/integration/compose/test_app_profile.py`, `tests/unit/sandbox_stack/**`.
- Must NOT touch: `factories.py`, `docker-compose.yml` env values for the pilot domain.
- Depends on: none.
- Acceptance criteria: first two boxes; a unit test shows `--grants-only` publishes nothing and waits for nothing; the evidence is a real fresh `make stack-up` run (paste the `ps` output); if Docker cannot run it in the session, say "unverified" and leave the box open.
- Tests: `uv run pytest -q tests/unit/sandbox_stack tests/integration/compose/test_app_profile.py`.
- Pattern references: `Makefile:73-82`, `tests/integration/compose/test_app_profile.py:157-172`.

### Item 2 - First-seed skipped_existing and docs (#211)  [P]
- Deliverable: reproduce on wiped emulators with timing logs; identify what counts as existing (candidates: projection-created entities at `sbx_seed_stack.py:1085-1101`, evaluations `:924`, `LANDED` `:1315`); fix the seeder tally to separate "created by projection" from "pre-existing" or change the order, and make `test_seed.py` assert the real meaning; add the empty-hub note to `docs/dev/local-setup.md`.
- Owned files: `scripts/sandbox/sbx_seed_stack.py` (tally only; sequence after item 1's commit), `tests/integration/real_stack/test_seed.py`, `docs/dev/local-setup.md`.
- Must NOT touch: catalog projection code, `CatalogRepository`.
- Depends on: item 1 (same script).
- Acceptance criteria: third box; the cause is stated in the PR with the log that shows it.
- Tests: `NS_PROBE_COSMOS_URL=http://127.0.0.1:8081/ MSYS_NO_PATHCONV=1 uv run pytest -q -m integration tests/integration/real_stack/test_seed.py` five times.
- Pattern references: `tests/integration/real_stack/test_seed.py:150-190`.

### Item 3 - make replay wire envelope (#162)  [P]
- Deliverable: reproduce (`make dev-reset`, `make replay`, count blobs in `ns-quarantine` and `ns-archive`); wrap each parseable telemetry line in `HubMessage` the way `hub_lines` does (same producer id, `observation_kind="gateway"`) and leave unparseable lines raw so the bad-event manifest still holds; share the wrapping helper with `hub_lines` rather than copying it.
- Owned files: `scripts/sandbox/sbx_cli.py`, `scripts/sandbox/sbx_seam.py`, `tests/unit/sandbox_stack/**` (a new file `test_replay_envelope.py`).
- Must NOT touch: `sandbox/bad_events.py` and the generator, `ingestion/pipeline.py`.
- Depends on: none (but if item 1 extracts a helper from `sbx_seed_stack.py`, rebase on it).
- Acceptance criteria: fourth box; counts reported against the manifest.
- Tests: `uv run pytest -q tests/unit/sandbox_stack`.
- Pattern references: `scripts/sandbox/sbx_seed_stack.py:531-562`.

### Item 4 - Seed gaps and OPT_IN_ROLES (#209 items 2-3, #180 item 1)
- Deliverable: on the seeded stack find which model keys the forecast cannot price (`price_version_unresolved`) and extend `synthetic_snapshot` or the seeded cost records so one domain forecasts; seed one `GatewayRegistration` through `GatewayStore` (synthetic, idempotent); delete `OPT_IN_ROLES` and its reader and fix the docs/tests that mention it.
- Owned files: `scripts/sandbox/sbx_seed_stack.py`, `services/workers/neurosphere_workers/runtime/roles.py`, `services/workers/tests/worker_roles/test_roles.py`, `tests/unit/sandbox_stack/**`.
- Must NOT touch: `factories.py`, the price-snapshot store implementation, gateway models.
- Depends on: item 1 (same script).
- Acceptance criteria: fifth and sixth boxes; `grep -rn OPT_IN_ROLES services packages tests scripts` is empty except history files (`docs/validation/lane1-telemetry-cost-deploy.md` is a record; leave it).
- Tests: `uv run pytest -q tests/unit/sandbox_stack services/workers/tests/worker_roles`.
- Pattern references: `sbx_seed_stack.py:750-796`, `gateway/store.py:54`.

### Item 5 - CI workflow for the pytest suites
- Deliverable: `.github/workflows/real-stack.yml` as in the seventh box; `NS_PROBE_COSMOS_URL=http://127.0.0.1:8081/`, health wait, failure log dump, concurrency group, `timeout-minutes` with headroom, least-privilege `permissions: contents: read`; document the job name and the expected runtime in `docs/dev/local-setup.md`.
- Owned files: `.github/workflows/real-stack.yml`, `docs/dev/local-setup.md`, `tests/integration/real_stack/**` (skips that must become failures under `CI`, following the `#100` rule that CI fails rather than skips).
- Must NOT touch: `ci.yml`.
- Depends on: items 1 to 4 merged or in the same branch.
- Acceptance criteria: seventh box with the run URL.
- Tests: the workflow run itself; `actionlint` if available locally, else say it was not run.
- Pattern references: `ci.yml:231-247`, `tests/security/egress/conftest.py` (`skip_or_fail`).

### Item 6 - Headless real-stack Playwright with flow specs (A3)
- Deliverable: `serve_stand_in_api.py` (compose the app with the stand-in validator over the emulators, bind `127.0.0.1`, port from env); `NS_REAL_STACK_MODE=ci` in the Playwright config (headless chromium, `webServer` for the stand-in API and for `vite` with `/api` proxied to it, globalSetup that writes a synthesised MSAL cache instead of waiting for a human); `frontend/tests/real-stack/flows/{catalog-curation,quality,actions,copilot}.spec.ts`, each asserting the API status the page received; add the step to `real-stack.yml` after the pytest step (install Playwright browsers with the repo's pinned version).
- Owned files: `tests/integration/real_stack/serve_stand_in_api.py` (new), `frontend/playwright.real-stack.config.ts`, `frontend/tests/real-stack/**`, `.github/workflows/real-stack.yml`.
- Must NOT touch: `frontend/src/**` (no production auth bypass is added; if the cache cannot be seeded without a code hook, stop and report instead), `main.py`, compose.
- Depends on: item 5.
- Acceptance criteria: eighth box. The stand-in server is never reachable from compose or `main` (a test imports it only from tests). Manual headed mode with real Entra keeps working unchanged (`NS_REAL_STACK_MODE` unset).
- Tests: `pnpm --filter @neurosphere/frontend exec playwright test -c playwright.real-stack.config.ts --list`, then a full local run with `NS_REAL_STACK_MODE=ci` and unique ports.
- Pattern references: `frontend/playwright.config.ts:43-56`, `frontend/tests/real-stack/fixtures.ts`.

### Item 7 - Integration and close-out
- Deliverable: fill the completion note including "Env vars for the operator" (none expected); `CHANGELOG.md` `[Unreleased]` line; regenerate `PRPs/INDEX.md` and the master table; list follow-ups (make the job required; re-run after PRP-53 and PRP-57 for the admin pages; Fix B of #205 if the reorder proves fragile).
- Owned files: the Ownership block plus close-out files named in the reference section 6.
- Depends on: items 1 to 6.
- Acceptance criteria: Validation gates pass; issues #205, #211, #162, #180 and #209 (items 2 and 3) closed by the PR text, #209 item 1 left open for PRP-47.
- Tests: the gates below.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q tests/unit/sandbox_stack tests/integration/compose/test_app_profile.py services/workers/tests/worker_roles
docker compose up -d --wait
NS_PROBE_COSMOS_URL=http://127.0.0.1:8081/ MSYS_NO_PATHCONV=1 uv run pytest -q -m integration tests/integration/real_stack
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
NS_REAL_STACK_MODE=ci pnpm --filter @neurosphere/frontend exec playwright test -c playwright.real-stack.config.ts
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Compose-using commands need the session to hold the stack (this PRP does in W12). Show the output; report any command not run.

## Migration and rollback
No data or schema change. The emulators hold synthetic data only (`make stack-down` and `docker compose down -v` reset them). Roll back by reverting the PR; the new workflow is non-required, so removing it cannot block merges. `--grants-only` is additive.

## Live and open gates
No `NS_LIVE_APPROVED=1` item and no paid call: everything runs on emulators. Operator-only follow-ups: flipping branch protection to require the `real-stack` job (after a week green). Hosted-environment seeding and the hosted smoke are PRP-58 and PRP-63; live runs are PRP-64. If the headless sign-in is descoped, report it OPEN and file an issue.

## NOT building
- Worker-side idling until in scope (Fix B of #205).
- Real Entra sign-in in CI, or any production auth bypass in `frontend/src/**` or the API.
- Admin-console, write-side or hosted specs (later PRPs add their specs to this suite).
- Changes to `ci.yml`, `factories.py`, the sandbox generator, or the mock API.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1, 6 and 7 are assumptions to confirm at plan approval)

## Execution state

| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | verifying | prp-38-real-stack-ci | --grants-only + Makefile reorder + pins; real fresh stack-up UNVERIFIED so far |
| 2 | todo | | |
| 3 | verifying | prp-38-real-stack-ci | shared sbx_wire.py; live replay count against emulator not yet run |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check:
