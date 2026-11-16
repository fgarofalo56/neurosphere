---
name: PRP-51-composition-and-api-hygiene
status: backlog
priority: P2
order: 48
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-08, NS-09
depends_on: []
wave: W19
branch: prp-51-composition-hygiene
allow_parallel: true
issues: [254, 130, 131, 133, 132]
---

# PRP-51: Composition and API hygiene

## Goal
Finish the hardening that the PRP-29 reviews queued against the API and worker composition roots and the deprecated path aliases, now that every other composition owner has merged. Concretely: the deprecated-alias headers become standards-correct (RFC 9745 `Deprecation: @<epoch>`) and appear on error responses too, with parity and `root_path` tests and the nginx limitation documented; the alias removal is prepared and date-gated rather than done early; test-only `CompositionOverrides` are refused outside `NS_ENV=local`; the copilot and CORS startup refusals share one dedicated error type; `cosmos_account` is validated; the 60 s container verify stops delaying process start; `/readyz` detail gets an explicit exposure switch; and the remaining #132 and #133 bullets are verified against the code and either fixed or recorded. It is for operators running the hosted API and for maintainers of the composition roots. It runs last (W19) because it owns the composition bodies that PRP-11, 21, 39, 40, 41, 42, 44, 45, 54 and 60 all edit earlier.

Out of scope: removing the aliases before their announced `Sunset` of 2027-04-30 (see Clarifications 1); hosted managed-identity validation of worker tokens (#131 worker identity bullet: needs a hosted-identity design, follow-up issue, PRP-58 is the nearest owner); the recommendation `HitlReviewRouter` race and duplicate ids across partitions (PRP-15); deploy `consented_by` (PRP-59); `ChartFrame` postMessage target (PRP-47); archive reader sizing on a real storage account (operator, PRP-64); the `/readyz` probe defaults per profile (#143, PRP-58); the denial recorder (#131 first bullet, already shipped and verified in `runtime/builders/authz.py`).

## Why
- `DEPRECATION_HEADER` is the literal `"true"` (`services/api/neurosphere_api/deprecation.py:44`) and the headers come from a route dependency, so 401/403/422/503 answers on alias paths carry none (`deprecation.py:9-12`); there is no parity test of the copied `APIRoute` kwargs (`deprecated_alias`, `deprecation.py:93-120`) and the `root_path` branch (`:68-74`) has no test (#130).
- `CompositionOverrides` can replace the authenticator and scope source, and `compose_app` accepts it with no check of `settings.env` (`runtime/overrides.py:24-60`, `runtime/compose.py:163-186`); it is unreachable from `main.create` only by convention (#131).
- `CopilotCredentialConfigError` derives from `BaseException` (`runtime/builders/copilot.py:89`) while the CORS refusal raises `InvalidSchemaError` (`runtime/cors.py:45-55`): two startup refusals, two mechanisms (#131).
- `StoreSettings.cosmos_account` is a free string in both API and worker settings (`runtime/settings.py:86`, worker `runtime/settings.py:81`); `_container_step` runs inside the lifespan with a 60 s timeout (`runtime/compose.py:58,108-130,143-160`), so a Cosmos outage delays process start (#131).
- `/readyz` returns component names and reason codes to unauthenticated callers (`runtime/readiness.py:3-20`, `health/router.py:25-60`); hosted exposure was never decided (#131).
- `sbx_grant_operator.py` accepts `--cloud government` (`scripts/sandbox/sbx_grant_operator.py:321`) although the seed is Commercial-only and the hosted path hard-codes `cloud="commercial"` (`:279,289`); `PolicyReviewerDirectory` has no pointer to the HITL authorizer gate (`runtime/builders/planes.py:149-155`); the recommendation store is published only on `app.state` (`runtime/builders/data.py:308-314`) (#131).
- #132 and #133 contain bullets that later PRPs or code have already settled; leaving them unreconciled keeps the issues open for work that is done.

## Acceptance criteria
- [ ] Alias responses carry `Deprecation: @<epoch seconds of the deprecation date>`, `Sunset`, and `Link: <successor>; rel="successor-version"`; the same three headers are present on a 401, 403, 422 and 503 answer on an alias path, and absent on non-alias paths (#130 items 2 and 3).
- [ ] A parity test compares every `APIRoute` constructor attribute that `deprecated_alias` copies against the live signature of the installed FastAPI, failing with the attribute name when one is dropped or newly added (#130 item 5).
- [ ] A test of the header dependency under a nested `root_path` (`/edge/api`) asserts the `Link` successor path is correct (#130 item 6).
- [ ] `docs/runbooks/api-path-aliases.md` states that the nginx edge proxies only `/api/`, `/readyz` and `/healthz`, so `/catalog`, `/catalog/curation`, `/audit`, `/v1/ingest`, `/v1/deploy/scan`, `/v1/deploy/plan` and `/mcp` are reachable only on the API port, and lists the removal checklist (#130 item 4).
- [ ] An expiry test fails with the removal checklist once the current date is on or after `SUNSET_AT`, and passes before; alias removal itself is not performed (#130 item 1, Clarifications 1).
- [ ] Given `compose_app(app, settings, overrides=...)` with `settings.env != "local"`, then composition refuses with `StartupRefusedError` naming only the override field names; with `env == "local"` it behaves as today (#131 `CompositionOverrides` guard).
- [ ] `StartupRefusedError` (new, `runtime/errors.py`) is the base of the copilot credential refusal and a new `CorsConfigError`; `_run_builders` re-raises it instead of converting it to `build_error`, so callers handle one type; the existing refusal messages and reason codes are unchanged (#131 startup-refusal bullet).
- [ ] `NS_STORE_COSMOS_ACCOUNT` is validated in API and worker settings against `^[a-z0-9][a-z0-9-]{1,42}[a-z0-9]$` (Cosmos account naming); a value that looks like a URL or a key is refused at settings load without echoing it (#131 `cosmos_account`).
- [ ] The container verify no longer runs inside the lifespan startup path: the app accepts `/healthz` immediately, `cosmos_containers` is `pending` and blocks `/readyz` (503, reason `composition.cosmos_containers.pending`) until the background step finishes, then `ok` or `failed`; a 60 s hung verify never delays startup (#131 container verify).
- [ ] `NS_READYZ_DETAIL=full|summary` (default `full`, today's behaviour); `summary` returns `status` and the aggregate `composition` entry only; the system-status API of PRP-45 is unaffected (#131 `/readyz` detail, Clarifications 3).
- [ ] `sbx_grant_operator.py --cloud government` is refused with a one-line message that the stack seed is Commercial-only (#131).
- [ ] `PolicyReviewerDirectory` documents the HITL authorizer gate; the recommendation store is also published as `RECOMMENDATION_STORE` (`SharedKey`) and `app.state.recommendation_store` stays for request-time dependencies (#131).
- [ ] A reconciliation table in the completion note lists each bullet of #132 and #133 as fixed (with test or commit), done by another PRP, accepted, or filed as a follow-up issue, verified against the code on the merge commit (#132, #133).
- [ ] PRP exit: targeted suites, `ruff`, `pyright`, `services/api/tests/test_openapi_drift.py`, `verify-gates.ps1 -Mode full` pass.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Alias removal timing | Remove now; remove after Sunset; remove behind a setting | ASSUMPTION: do not remove before `Sunset` 2027-04-30; clients were promised the window (PRP-29 Clarification 9). This PRP ships the removal checklist and an expiry test that turns red on that date; the deletion (drop `register_with_alias` alias half, `routers.py`, tests, `openapi.json`) is a one-item follow-up then. If the owner wants earlier removal, that is a decision to take before execution |
| 2 | Where the alias headers middleware is installed | `app.py`; `runtime/compose.py`; route dependency only | `compose_app` (a composition body this PRP owns in W19); `app.py` stays untouched. If a test shows the order against `CORSMiddleware` matters, install it inside `install_cors`'s caller and record the deviation |
| 3 | `/readyz` hosted exposure | Always full; always summary; setting | Setting with default `full` so existing probes, the hosted smoke and PRP-45 keep working; hosted profiles choose in PRP-58 |
| 4 | Startup refusal base | Keep `BaseException`; shared `Exception` subclass re-raised by the builder loop | Shared `StartupRefusedError(Exception)`; the builder loop re-raises it explicitly so a credential in configuration is still a hard refusal, not a degraded component |
| 5 | Container verify off the lifespan path | Background task; shorter timeout; leave | Background task with a `pending` step state that blocks readiness; behaviour for orchestrators is unchanged (not ready until verified) but liveness no longer waits |
| 6 | Worker identity (managed-identity token validation) | Include; follow-up | Follow-up issue; needs a hosted design, not a hygiene change |
| 7 | #133 recommendation and evaluation id races | Include; verify only | Verify only: PRP-15 fixes the recommendation router and ids; the evaluation store already looks the id up across partitions (`evaluation/cosmos_store.py:269-318`); the residual race window is recorded as accepted |

## Context manifest

### Files to read first
- `services/api/neurosphere_api/deprecation.py` and `services/api/tests/path_aliases/{alias_support,test_deprecation_headers,test_aliases}.py`.
- `services/api/neurosphere_api/runtime/compose.py` - `compose_app`, `_run_builders`, `_container_step`, `_wrap_lifespan`.
- `services/api/neurosphere_api/runtime/{overrides,cors,status,readiness,settings}.py`.
- `services/api/neurosphere_api/runtime/builders/copilot.py:20-120` - the credential refusal.
- `services/api/neurosphere_api/health/router.py` and `health/probes.py` (read only for `probes.py`).
- `services/api/neurosphere_api/main.py` - where startup refusals surface.
- `services/workers/neurosphere_workers/runtime/settings.py:70-90`.
- `scripts/sandbox/sbx_grant_operator.py:260-330`.
- `frontend/nginx/templates/default.conf.template` - the proxied prefixes.

### Interfaces consumed
- PRP-48 (W15): `authz/deployment_scope.py`, `read_audit.py`, `ROLE_GATED_PATHS`, route-file edits including `scripts/sandbox/sbx_grant_operator.py`; keep them.
- PRP-45 (W16): the composed readiness registry feeds its system-status API; this PRP must keep `ComponentRegistry` semantics (`ok`, `failed`, `disabled`, `not_built`) and only adds `pending` for a startup step.
- PRP-58 (W18): per-profile `NS_PROBE_*` settings and the choice of `NS_READYZ_DETAIL` per hosted profile.
- PRP-44, 45, 54, 60 builder modules and the `BuilderSpec` registry in `runtime/builders/__init__.py`: this PRP edits their bodies only where listed.

### Interfaces provided
- `neurosphere_api.runtime.errors.StartupRefusedError`, `CorsConfigError`.
- `RECOMMENDATION_STORE: SharedKey[RecommendationStore]` in `runtime/builders/__init__.py`.
- Setting `NS_READYZ_DETAIL` (`full` default, `summary`).
- Registry step state `pending` for `cosmos_containers` (status JSON of PRP-45 gains one value).
- `neurosphere_api.deprecation.install_alias_headers(app)` and the RFC 9745 header constant.

### Patterns to match
- Typed shared keys and `ctx.publish`: `runtime/builders/__init__.py:161-173`, `data.py:221-224`.
- Component states and reason-code regex: `runtime/status.py:1-30`.
- Settings validation that does not echo input: `runtime/cors.py:60-75`.
- Alias test support: `services/api/tests/path_aliases/alias_support.py`.

### Gotchas
- The `cosmos_containers` step currently starts `ok` and only blocks after a failure (`status.py:57-96`); introducing `pending` must make `/readyz` 503 from the first request, not after. Test the readiness body at app start, before the background task completes.
- `main.create` is not edited: it already lets a refusal propagate out of `compose_app`; check `services/api/tests/runtime_api/test_cors.py` and `runtime_planes/test_copilot_builder.py:212-228` which assert the old exception types and update them in the same item.
- `ComponentRegistry.reported`/`not_built` loops run after a builder raises; the re-raise must come before them.
- The `Link` header must stay percent-encoded (`_PATH_SAFE`); do not build it from the raw request path in the new middleware.
- Alias error responses are produced by exception handlers outside the route stack, so a dependency cannot add headers there; use ASGI middleware keyed on the alias prefixes, which `register_with_alias` records.
- `openapi.json` changes: alias operations unchanged, `/readyz` schema unchanged (the `summary` mode returns a subset of the same model); regenerate anyway and run the drift test.
- `sbx_grant_operator.py` is also edited by PRP-48 (W15); rebase on it.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/runtime/compose.py
  - services/api/neurosphere_api/runtime/overrides.py
  - services/api/neurosphere_api/runtime/cors.py
  - services/api/neurosphere_api/runtime/errors.py
  - services/api/neurosphere_api/runtime/readiness.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/neurosphere_api/runtime/settings.py
  - services/api/neurosphere_api/runtime/builders/copilot.py
  - services/api/neurosphere_api/runtime/builders/data.py
  - services/api/neurosphere_api/runtime/builders/planes.py
  - services/api/neurosphere_api/deprecation.py
  - services/api/neurosphere_api/health/router.py
  - services/api/neurosphere_api/health/__init__.py
  - services/workers/neurosphere_workers/runtime/settings.py
  - scripts/sandbox/sbx_grant_operator.py
  - tests/unit/sandbox_stack/test_grant_operator_cloud.py
  - services/api/tests/path_aliases/**
  - services/api/tests/runtime_api/test_startup_refusal.py
  - services/api/tests/runtime_api/test_overrides_guard.py
  - services/api/tests/runtime_api/test_container_step_background.py
  - services/api/tests/runtime_api/test_cors.py
  - services/api/tests/runtime_planes/test_copilot_builder.py
  - services/api/tests/health/test_readyz_detail.py
  - services/workers/tests/runtime/test_settings_cosmos_account.py
  - docs/runbooks/api-path-aliases.md
tier1:
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/routers.py
tier2_appends:
  - services/api/tests/runtime_routes/manifest_calls.py
  - mkdocs.yml
must_not_touch:
  - services/api/neurosphere_api/health/probes.py
  - services/api/neurosphere_api/app.py
  - services/api/neurosphere_api/main.py
  - services/api/neurosphere_api/authz/**
  - packages/contracts/**
  - infra/**
  - services/workers/neurosphere_workers/runtime/factories.py
  - services/api/neurosphere_api/recommendations/**
```

## Implementation blueprint
Parallelization map: Items 1, 2, 3 all edit `runtime/compose.py` and are sequential (1 then 2 then 3). Item 4 touches builders and a script and is independent [P]. Item 5 reconciles issues and closes out. `routers.py` is edited only if Item 1's middleware install needs a registry hook; otherwise untouched.

### Item 1 - Alias headers, parity and root_path tests, runbook
- Deliverable: RFC 9745 `Deprecation` value derived from a `DEPRECATED_AT` constant; ASGI middleware `install_alias_headers(app)` adding the three headers to every response whose path starts with a registered alias prefix, error responses included; `register_with_alias` records the alias prefixes; the compose install; parity test over `APIRoute` attributes; nested `root_path` test; expiry test; runbook with the nginx note and the removal checklist.
- Owned files: `deprecation.py`, `runtime/compose.py` (one install line), `services/api/tests/path_aliases/**`, `docs/runbooks/api-path-aliases.md`, `mkdocs.yml` (nav line).
- Must NOT touch: `app.py`, any router module, `routers.py` beyond a registry attribute if unavoidable.
- Depends on: none.
- Acceptance criteria: criteria 1 to 5; `test_deprecation_headers.py` assertions of `"true"` are updated to the new form.
- Tests: `uv run pytest -q services/api/tests/path_aliases services/api/tests/test_openapi_drift.py`.
- Pattern references: `deprecation.py:63-82`, `alias_support.py`.

### Item 2 - Startup refusals and overrides guard
- Deliverable: `runtime/errors.py` with `StartupRefusedError` and `CorsConfigError`; copilot refusal re-based; `_run_builders` re-raises `StartupRefusedError`; `compose_app` refuses `overrides` when `settings.env != "local"` listing field names only.
- Owned files: `runtime/errors.py` (new), `runtime/compose.py`, `runtime/cors.py`, `runtime/overrides.py` (docstring, no field change), `runtime/builders/copilot.py` (class base and docs), `services/api/tests/runtime_api/{test_startup_refusal,test_overrides_guard,test_cors}.py`, `services/api/tests/runtime_planes/test_copilot_builder.py`.
- Must NOT touch: other builder bodies, `main.py`.
- Depends on: Item 1 (shared `compose.py`).
- Acceptance criteria: criteria 6 and 7; the credential-shaped `NS_COPILOT_*` refusal still aborts startup and never echoes a value.
- Tests: `uv run pytest -q services/api/tests/runtime_api services/api/tests/runtime_planes`.
- Pattern references: `copilot.py:89-110`, `compose.py:78-96`.

### Item 3 - Settings validation, background container verify, readyz detail
- Deliverable: `cosmos_account` validators in API and worker settings; `_container_step` runs as a background task started in the lifespan with a `pending` step state; `NS_READYZ_DETAIL` read by the readiness probes and health router.
- Owned files: `runtime/{settings,status,readiness,compose}.py`, `health/router.py`, `health/__init__.py`, `services/workers/neurosphere_workers/runtime/settings.py`, tests `runtime_api/test_container_step_background.py`, `health/test_readyz_detail.py`, `services/workers/tests/runtime/test_settings_cosmos_account.py`.
- Must NOT touch: `health/probes.py`.
- Depends on: Item 2.
- Acceptance criteria: criteria 8 to 10; with a fake client whose verify hangs, `/healthz` answers 200 and `/readyz` 503 `composition.cosmos_containers.pending` within a second of start; after the fake completes `/readyz` is 200.
- Tests: `uv run pytest -q services/api/tests/runtime_api services/api/tests/health services/api/tests/runtime_routes services/workers/tests/runtime`.
- Pattern references: `compose.py:99-160`, `status.py:57-96`.

### Item 4 - Small composition and script fixes  [P]
- Deliverable: `--cloud government` refused in `sbx_grant_operator.py` (choices narrowed with a message); `PolicyReviewerDirectory` docstring pointer; `RECOMMENDATION_STORE` `SharedKey` declared in `builders/__init__.py` and published from `_recommendations`.
- Owned files: `scripts/sandbox/sbx_grant_operator.py`, `tests/unit/sandbox_stack/test_grant_operator_cloud.py`, `runtime/builders/planes.py` (docstring), `runtime/builders/data.py` (`_recommendations`), `runtime/builders/__init__.py` (one `SharedKey` line, Tier 1 for this wave).
- Must NOT touch: any other builder, PRP-48's changes in the script.
- Depends on: none.
- Acceptance criteria: criterion 11 and 12; `tests/unit/sandbox_stack/test_grant_operator.py` unchanged and green.
- Tests: `uv run pytest -q tests/unit/sandbox_stack services/api/tests/runtime_planes services/api/tests/runtime_data`.
- Pattern references: `builders/__init__.py:161-173`.

### Item 5 - Reconcile #132 and #133, integration and close-out
- Deliverable: for each bullet of #132 and #133 grep and run the cited code on the merge base and fill the reconciliation table (write connectors: PRP-35 and PRP-54; lifecycle: PRP-23; Commercial copilot rows: verified in `foundry.yaml` and PRP-16 round 2; copilot degraded readiness; sampling coverage mapping; Commercial LLM judge; curation `lock.actor` fixed in `catalog/curation/service.py`; recommendation router race and duplicate ids: PRP-15; `consented_by`: PRP-59; `ChartFrame`: PRP-47; catalog search: replaced by `NS_SEARCH_PROVIDER` in PRP-35; archive reader sizing: operator); file follow-up issues for anything still open; regenerate `services/api/openapi.json` and `docs/reference/**`; `python scripts/prp_status.py --write`; CHANGELOG entry.
- Owned files: this PRP file; generated Tier 3 files.
- Depends on: Items 1 to 4.
- Acceptance criteria: criterion 13 and reference section 6; a comment on #130, #131, #132, #133 states what was closed and what stays open.

## Validation gates
```bash
uv sync --frozen --group dev
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q services/api/tests/path_aliases services/api/tests/runtime_api services/api/tests/runtime_planes services/api/tests/runtime_data services/api/tests/runtime_routes services/api/tests/health services/api/tests/test_openapi_drift.py services/workers/tests/runtime tests/unit/sandbox_stack tests/docs/test_reference_coverage.py
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
The `test_readyz_emulator.py` suite is `integration`-marked and skipped in the CI python job; run it locally against the emulators (`127.0.0.1`) when Item 3 lands and paste the output.

## Migration and rollback
No data migration. New environment variable `NS_READYZ_DETAIL` (default `full`, no change in behaviour). The `pending` state is visible to PRP-45's status API as a new value; deploy API and consumers together. Rollback: revert the PR; the background container step returns to the lifespan path, the alias headers return to dependency-only. Stricter `cosmos_account` validation could refuse a previously accepted odd value at boot: the refusal names the field only, and reverting restores acceptance.

## Live and open gates
Nothing here needs `NS_LIVE_APPROVED=1`. OPEN and handed on: worker managed-identity token validation (follow-up issue), per-profile `NS_READYZ_DETAIL` and probe defaults (PRP-58), archive reader sizing (PRP-64 operator check), alias deletion after 2027-04-30.

## NOT building
Alias deletion before the Sunset date; worker identity validation; `/readyz` authentication; new probes; recommendation or evaluation id race fixes (PRP-15); `consented_by` stamping (PRP-59); frontend changes.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided or labelled ASSUMPTION

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-51-composition-hygiene | commit on branch |
| 2 | todo | | after 1 |
| 3 | todo | | after 2 |
| 4 | todo | | |
| 5 | todo | | |

## Completion note (filled at ship)
- Date, PR, merge commit:
- Deviations from the blueprint:
- Descoped items (worker identity, alias deletion):
- OPEN gates:
- Env vars for the operator (`NS_READYZ_DETAIL`):
- #132 and #133 reconciliation table:
- Follow-up issue numbers:
- Issue state (#130, #131, #132, #133):
