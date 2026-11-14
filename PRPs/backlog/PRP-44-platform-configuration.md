---
name: PRP-44-platform-configuration
status: backlog
priority: P0
order: 32
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-01, NS-04, NS-08
depends_on: [PRP-37-contracts-revision-admin-cost-and-permissions, PRP-39-identity-admin-api-and-revocation]
wave: W15
branch: prp-44-platform-config
allow_parallel: true
issues: [238, 209]
---

# PRP-44: Platform configuration (domains, budgets, price sheets, review policy)

## Goal
Give an admin an audited API for the four platform objects the product has no home for today: a domain registry (create, list, retire), budgets with alert thresholds per domain, versioned price sheet uploads, and a stored human-review policy. Price sheets go into the existing append-only `price_snapshots` store and are consumed by the ingestion cost ledger, so cost estimation no longer depends on a seeder or an env-named JSON file; the stored review policy replaces the argument-less `ReviewPolicyRegistry()` in the API and the workers. Each object is an `admin_config` document (PRP-37) guarded by `If-Match` and an audit record. It is for the operator who needs real cost estimates and real SLA and expiry rules on a hosted stack, and for the console pages in PRP-53 and PRP-57. It runs in W15 on PRP-37 and PRP-39, and owns `runtime/builders/data.py`, `runtime/planes.py` and the worker `factories.py` bodies for the wave.

Out of scope: budget alert delivery (email, webhook) and anything that evaluates a budget against spend (nothing consumes budgets in this PRP; ASSUMPTION); scraping or fetching provider price lists (the admin uploads a sheet); sandbox seed data and the seeded price coverage in the dev stack (PRP-38 owns `scripts/sandbox/**`, #209 items 2 and 3); the forecast route and FinOps (PRP-21, `services/api/neurosphere_api/finops/**`); system-wide feature settings (PRP-45); the console pages (PRP-53, PRP-57); write targets (PRP-54); `main.py` and `routers.py` structure beyond one hook line.

## Why
- No domain object exists: "domain" is a string in policy documents and every record; there is no `Domain` model in core (lane-d step 1, "Domains"), so a typo in an assignment silently creates a dangling scope.
- No product budget model: `grep '^class .*Budget'` finds only analytics, evaluation and tool budgets; the Azure budget is Bicep only (`infra/demo/modules/budget.bicep`; lane-d step 1, "Budgets and alerts").
- Prices are written only by the sandbox seeder (`scripts/sandbox/sbx_seed_stack.py:791`, `seed_prices`); the ledger reads a file named by `NS_LEDGER_PRICE_TABLE_FILE` when ingestion starts (`services/workers/neurosphere_workers/ingestion/wiring.py:86-92,183-186`), so on a real stack every estimate is `price_unresolved`, the forecast answers 409 `price_version_unresolved` (`services/api/neurosphere_api/finops/service.py:265-269`), and #209 item 2 shows the seeded sheet prices only `synthetic-model`.
- A snapshot with only an input or only an output price for a model is silently left out of the ledger price version (`packages/core/neurosphere_core/pricing/models.py` `to_price_version`), so an uploaded sheet can look complete and price nothing.
- Review policy is hard-coded defaults: `ReviewPolicyRegistry()` at `runtime/builders/data.py:377`, `runtime/builders/planes.py:241` and `services/workers/neurosphere_workers/runtime/factories.py:514`; SLA, escalation and expiry (`hitl/policy.py:37-60`) cannot be changed without a code change (lane-d step 1, "HITL SLA / escalation / expiry").

## Acceptance criteria
- [ ] Given customer-level `config.manage`, When an admin creates, lists and retires a domain through `/api/v1/admin/platform/domains`, Then the id must be canonical for the deployment cloud and customer, a duplicate is 409, the reserved `customer-control` domain is created with `is_control_domain=true` and can never be retired, every write is audited, and a retired domain keeps its record.
- [ ] Given at least one registered domain, When PRP-39's identity routes assign a role, membership or grant naming an unregistered domain, Then they return 422 `domain_not_registered`; given no registered domain at all, they behave as before (so an existing deployment keeps working until it registers domains).
- [ ] Budgets: a budget for a registered domain with `period`, a decimal-string `amount`, `currency`, and `thresholds_percent` (strictly increasing, 1 to 200) is stored and listed; an unknown domain, a float amount or a duplicate threshold is 422; nothing is evaluated or sent.
- [ ] Price sheets: `POST /api/v1/admin/platform/price-sheets` converts a `PriceSheetUpload` to a `PriceSnapshot` with a computed content hash and appends it to `price_snapshots`; the same `snapshot_id` with a different hash is 409 (`SnapshotConflictError`), the same hash is an idempotent 200; a sheet that does not apply to the deployment cloud is 422; `synthetic: true` is refused outside `NS_ENV=local`; an `azure_retail_prices` sheet for Government is refused by the existing model rule.
- [ ] Each upload returns a coverage report: models priced (input and output present), models incomplete (only one side, which `to_price_version` would drop), and rows without a token meter; incomplete models are a warning, not a rejection.
- [ ] Given a stored sheet, When the ingestion worker starts, Then its ledger price table contains the snapshot's `PriceVersion` (id = `snapshot_id`) merged with any file table (equal ids with identical content collapse to one; equal ids with different content refuse startup with `price_version_conflict`), and an estimated observation then cites a stored price version (the forecast precondition at `finops/service.py:219-269`).
- [ ] Review policy: `PUT /api/v1/admin/platform/review-policy` validates a `ReviewPolicyDocument` into `ReviewPolicy` objects (positive durations, `sla` at least 60 s, `expiry` at most 90 days, `max_escalations` 0 to 10, known `approver_permission`), refuses any change that sets `self_approval_forbidden=false` or an approver other than `action.approve` for `maker_checker`, bumps `policy_version`, and returns a before and after diff; missing `If-Match` is `invalid_schema`, stale is `stale_version`.
- [ ] Given a stored review policy, When the API or the worker roles `actions`, `hitl_timers` and `evaluation` start, Then `HitlService` and the action plane resolve their policies from it (stored over defaults, applied at startup, no hot reload, A1); with no stored policy `ReviewPolicyRegistry` behaviour is identical to today (`packages/core/tests/hitl` and `services/api/tests/hitl_api` pass unchanged).
- [ ] Callers without customer-level `config.manage` get 403 and a denial record on every route; every route is in the route inventories; no price value or policy body appears in a log line; `openapi.json` regenerated.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, `validate_planning.py` pass; PR open with CI green.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where the four objects live | New containers; `admin_config` kinds | `admin_config` kinds `domain`, `budget`, `price_sheet` (metadata and coverage), `review_policy` (PRP-37); price rows themselves go to the existing `price_snapshots` container (partition `/snapshot_id`, append-only) |
| 2 | Price sheet versioning | Mutable sheet; append-only snapshots | Append-only snapshots (`packages/core/neurosphere_core/pricing/store.py`): a changed list is a new `snapshot_id`; no update or delete route |
| 3 | Permission | Per-domain `config.manage`; customer-level | Customer-level `config.manage` through `require_customer_control(Permission.CONFIG_MANAGE)` (`actions/customer_control.py:91`) for every route; ASSUMPTION: budgets could be domain-scoped later |
| 4 | When changes apply | Hot reload; restart | A1: applied at startup (review policy, price table); the API reports `restart_required` only through PRP-45's settings view, not here |
| 5 | Domain registry enforcement | Always; only once non-empty | ASSUMPTION: enforced only when the registry holds at least one domain, so existing deployments keep working; the reserved control domain is registered first by the create route when absent |
| 6 | Budget alerts | Deliver; store only | ASSUMPTION (lane-d unit D): store only; the validation doc says only that budgets are "not configurable" |
| 7 | Price coverage (#209 item 2) | Catalog-wide coverage; per-sheet report | ASSUMPTION: the per-sheet report above. A catalog-wide "which models have no price" view needs the catalog repository and is a follow-up; the seeded dev sheet is PRP-38 |
| 8 | Review policy safety | Free edit; guarded | Guarded: the maker-checker invariant (no self approval, `action.approve`) can never be loosened through this API; other kinds may change durations and approver permission among known permissions |
| 9 | Synthetic sheets | Allowed everywhere; local only | ASSUMPTION: `synthetic: true` only under `NS_ENV=local`, so a hosted ledger never prices from invented numbers |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/pricing/{models,store,cosmos_store}.py` - `PriceSnapshot`, `compute_content_hash`, `to_price_version`, append-only `put`, sync Cosmos store (run in a thread).
- `packages/core/neurosphere_core/hitl/policy.py:30-110` - `ReviewPolicy`, `default_policies`, `ReviewPolicyRegistry`.
- `packages/core/neurosphere_core/ledger/prices.py:96-130` - `PriceTable` (duplicate ids raise).
- `services/workers/neurosphere_workers/ingestion/wiring.py:86-92,143-195` - `load_price_table`, `build_pipeline_deps`.
- `services/workers/neurosphere_workers/runtime/factories.py:346-380,391-420,509-516,540-560,688-692,1084` - `_sync_cosmos`, `_price_snapshots`, `build_ingestion`, `_hitl_service` and its three callers.
- `services/api/neurosphere_api/runtime/builders/data.py:353-390`, `planes.py:225-250` - the two `ReviewPolicyRegistry()` sites.
- `services/api/neurosphere_api/actions/customer_control.py:91-110`, `mcp/admin/router.py:96-198`.
- `services/api/neurosphere_api/finops/service.py:219-285` - why prices must reach the ledger.
- `PRPs/backlog/PRP-37-*.md`, `PRP-39-*.md`, `PRP-45-*.md` - "Interfaces provided".

### Interfaces consumed
- PRP-37: `DomainDefinition`, `Budget`, `PriceSheetUpload`, `ReviewPolicyDocument` (`neurosphere_contracts.admin.v1`; `PriceSheetUpload` maps to `PriceSnapshot` minus `content_hash`, `ReviewPolicyDocument` maps to `ReviewPolicyRegistry` inputs, per PRP-37 Item 2); `neurosphere_core.admin` `AdminConfigRepository`, `CosmosAdminConfigRepository`, `InMemoryAdminConfigRepository`, `ADMIN_KIND_MODELS`, `admin_config_chain_id`; `customer_control_domain_id`; container `admin_config`.
- PRP-39: `neurosphere_api.admin` package root; identity routes under `admin/identity/` (one call site is edited here after PRP-39 has merged, item 6).
- PRP-45 (W16, later): reads this PRP's documents for the checklist; no code dependency.
- Shipped: `PriceSnapshotStore`, `CosmosPriceSnapshotStore`, `InMemoryPriceSnapshotStore`, `HitlService`, `ReviewPolicyRegistry`, `require_customer_control`, `AUDIT_REPOSITORY`, `HITL_SERVICE`.

### Interfaces provided
- Routes under `/api/v1/admin/platform`: `domains` (`POST`, `GET`, `GET /{domain_id}`, `POST /{domain_id}/retire`), `budgets` (`POST`, `GET`, `GET /{budget_id}`, `PUT /{budget_id}`, `DELETE /{budget_id}`), `price-sheets` (`POST`, `GET`, `GET /{snapshot_id}`, `GET /{snapshot_id}/coverage`), `review-policy` (`GET`, `PUT`).
- Core `neurosphere_core.admin.platform`: `DomainRegistry` (`is_registered`, `has_any`), `PlatformAdmin` services, `price_sheet_to_snapshot`, `coverage_report`, `LoadableReviewPolicyRegistry` (subclass of `ReviewPolicyRegistry` with `load_from(repository)` called once at startup), `merge_price_tables(snapshots, file_table)`.
- Shared keys `DOMAIN_REGISTRY` and `REVIEW_POLICIES` (new lines in `runtime/builders/__init__.py`); component `admin_platform` (optional) in `runtime/status.py`; `app.state.admin_platform`.
- Worker package `neurosphere_workers.admin_platform` (new): `ledger_price_table(cfg)`, `load_review_policies(cfg, cosmos)`.
- Audit operations `domain.create`, `domain.retire`, `budget.put`, `budget.delete`, `price_sheet.upload`, `review_policy.replace`.

### Patterns to match
- ETag and audited admin writes: `mcp/admin/router.py:96-198`, `packages/core/neurosphere_core/mcp/cosmos_store.py:86-140`.
- Off-loop use of the sync price store: `factories.py:363-380` (`asyncio.to_thread`).
- Append-only conflict rule: `pricing/store.py` module docstring (idempotent equal hash, conflict on different hash).
- Shared key publish and consume: `runtime/builders/data.py` publishes `HITL_SERVICE`, `planes.py` reads it.

### Gotchas
- `PriceTable` raises on duplicate `price_version_id`; a file table and a snapshot with the same id must be compared by content and refused if they differ (`price_version_conflict`), not silently merged.
- The price store is sync (`azure.cosmos`), the API composition uses the async client. Build a separate sync client for prices from the same settings (local: `NS_COSMOS_ENDPOINT` plus key, the pattern at `factories.py:346-362`), always call it through `asyncio.to_thread`, and close it with the composition lifetime.
- Builders do no network I/O: load stored review policy and domains in `ctx.on_startup` hooks, not in `build`. Until the hook runs the registry holds defaults; the hook must run before the app serves (the lifespan runs startup hooks first).
- `ReviewPolicyRegistry` is immutable by design. `LoadableReviewPolicyRegistry` replaces its dictionaries exactly once, guarded by a lock-free "loaded" flag, and refuses a second load.
- Review policy and price documents carry no secrets, but price rows are commercially sensitive: never log a price or a policy body; log `snapshot_id` and counts only.
- `data.py` was Tier-1 for PRP-40 in W14 and `planes.py` is shared with PRP-54 in W17: rebase first and keep edits to the two `ReviewPolicyRegistry()` sites plus the builder wiring.
- Test directories need unique names (`admin_platform_api`, `admin_platform_worker`); existing `services/api/tests/hitl_api` and `packages/core/tests/hitl` must stay green.
- `scripts/sandbox/**` is PRP-38's; do not extend the seeder here.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - services/api/neurosphere_api/admin/platform/**
  - services/api/neurosphere_api/runtime/builders/admin_platform.py
  - packages/core/neurosphere_core/admin/platform/**
  - packages/core/tests/admin_platform/**
  - services/workers/neurosphere_workers/admin_platform/**
  - services/workers/neurosphere_workers/ingestion/wiring.py
  - services/api/tests/admin_platform_api/**
  - services/workers/tests/admin_platform_worker/**
  - tests/security/authz/test_admin_platform*.py
  - docs/runbooks/platform-config.md
tier1:
  - services/api/neurosphere_api/runtime/builders/data.py
  - services/api/neurosphere_api/runtime/builders/planes.py
  - services/workers/neurosphere_workers/runtime/factories.py
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - mkdocs.yml
must_not_touch:
  - services/api/neurosphere_api/admin/__init__.py
  - services/api/neurosphere_api/admin/sources/**
  - services/api/neurosphere_api/admin/system/**
  - services/api/neurosphere_api/authz/**
  - services/api/neurosphere_api/finops/**
  - scripts/sandbox/**
  - packages/contracts/**
  - packages/core/neurosphere_core/pricing/**
  - packages/core/neurosphere_core/hitl/**
  - infra/**
  - frontend/**
```

## Implementation blueprint

Parallelization: item 1 first. Items 2 and 3 [P] after it (separate router files). Item 4 after 2 and 3; item 5 [P] with 4 after item 1 (separate trees; both touch `factories.py` or `data.py` only in their own bodies, so run 5 after 4 if one session). Item 6 after 4; item 7 last.

### Item 1 - Platform administration in core
- Deliverable: `neurosphere_core/admin/platform/` with `DomainRegistry` and domain admin (canonical id check, reserved control domain, no retire of the control domain), budget admin (domain must exist, threshold rules, decimal amounts), `price_sheet_to_snapshot` and `coverage_report`, review-policy conversion and the safety rules, `LoadableReviewPolicyRegistry`, and `merge_price_tables`.
- Owned files: `packages/core/neurosphere_core/admin/platform/**`, `packages/core/tests/admin_platform/**`.
- Must NOT touch: `neurosphere_core/pricing/**`, `hitl/**`, PRP-37 modules in `neurosphere_core/admin/*.py`.
- Depends on: PRP-37 merged.
- Acceptance criteria: criteria 1 (rules), 3, 4 (conversion and conflict), 5, 7 and the loadable registry (second `load_from` raises; no stored policy equals `default_policies()`); a `PriceSheetUpload` example round-trips through `PriceSnapshot` with a matching hash; `merge_price_tables` refuses equal ids with different content.
- Tests: `packages/core/tests/admin_platform/test_domains.py`, `test_budgets.py`, `test_price_sheet.py`, `test_review_policy.py`, `test_merge_price_tables.py`.
- Pattern references: `pricing/models.py:232`, `pricing/store.py`, `hitl/policy.py:60-110`.

### Item 2 - Domain and budget routes  [P]
- Deliverable: `admin/platform/{domains,budgets}.py` routers and models with `If-Match`, audit through `run_audited_mutation` on `admin_config_chain_id`, `register(registry)` hook.
- Owned files: `services/api/neurosphere_api/admin/platform/{__init__,domains,budgets,models}.py`, `services/api/tests/admin_platform_api/test_domains.py`, `test_budgets.py`.
- Must NOT touch: `admin/__init__.py`, price or review-policy routers.
- Depends on: item 1.
- Acceptance criteria: criteria 1 and 3 over the in-memory repository, including the 403 matrix for a non-customer-level admin.
- Tests: `services/api/tests/admin_platform_api`.
- Pattern references: `mcp/admin/router.py:96-198`.

### Item 3 - Price sheet and review policy routes  [P]
- Deliverable: `admin/platform/{price_sheets,review_policy}.py` routers; price upload appends to the snapshot store through `asyncio.to_thread` and writes the `price_sheet` metadata document; coverage endpoint; review policy `GET` and `PUT` with diff.
- Owned files: `services/api/neurosphere_api/admin/platform/{price_sheets,review_policy}.py`, `services/api/tests/admin_platform_api/test_price_sheets.py`, `test_review_policy.py`.
- Must NOT touch: items 2 files, `finops/**`.
- Depends on: item 1.
- Acceptance criteria: criteria 4, 5 and 7; upload is idempotent on equal hash; no price value in logs (caplog assertion).
- Tests: `services/api/tests/admin_platform_api`.
- Pattern references: `pricing/store.py` conflict rule, `factories.py:363-380`.

### Item 4 - API composition (data.py, planes.py, builder)
- Deliverable: new `runtime/builders/admin_platform.py` (Tier-2 append in `default_builders`) building the admin services, the sync price store and the `DOMAIN_REGISTRY` and `REVIEW_POLICIES` shared keys, reporting `admin_platform`; `data.py` and `planes.py` use the shared `LoadableReviewPolicyRegistry` at the two `ReviewPolicyRegistry()` sites; startup hooks load stored policy and domains once.
- Owned files: `services/api/neurosphere_api/runtime/builders/admin_platform.py`, Tier-1 `data.py` and `planes.py` (the two sites and the wiring only), `services/api/tests/admin_platform_api/test_builder.py`.
- Must NOT touch: `compose.py`, `main.py`, `edge.py`, `copilot.py`.
- Depends on: items 2 and 3.
- Acceptance criteria: criteria 8 (API half) and "behaviour identical with no stored policy"; Cosmos unavailable reports `admin_platform` disabled with a reason and the app serves with defaults; re-run `services/api/tests/{runtime_api,runtime_data,runtime_planes,runtime_routes,hitl_api,actions_api}`.
- Tests: `services/api/tests/admin_platform_api/test_builder.py`, plus the re-runs.
- Pattern references: `runtime/builders/data.py:353-390`, `planes.py:225-250`, `runtime/builders/gateway.py`.

### Item 5 - Worker pickup: ledger prices and review policy  [P]
- Deliverable: `neurosphere_workers/admin_platform/` (`ledger_price_table`, `load_review_policies`); `build_pipeline_deps` accepts an optional `price_table`; `build_ingestion` passes the merged table (snapshots plus file); `_hitl_service` takes a `LoadableReviewPolicyRegistry` loaded by its three callers (`build_actions`, `build_hitl_timers`, `build_evaluation`).
- Owned files: `services/workers/neurosphere_workers/admin_platform/**`, `ingestion/wiring.py` (the `price_table` parameter only), Tier-1 `factories.py` (`build_ingestion`, `_hitl_service` and its three call sites only), `services/workers/tests/admin_platform_worker/**`.
- Must NOT touch: `build_gateway_poll`, `build_foundry_discovery`, `build_billing_export` (PRP-42), `build_lifecycle`, `build_recommendations`, `BUILDERS`.
- Depends on: item 1.
- Acceptance criteria: criteria 6 and 8 (worker half); with no snapshots and no policy the ledger and HITL behave exactly as before (`services/workers/tests/{ingestion,action_executor,hitl_timers,evaluation_worker,worker_roles}` unchanged); a Cosmos read failure falls back to the file table and defaults with one structured log line and a reason code.
- Tests: `services/workers/tests/admin_platform_worker/test_ledger_prices.py`, `test_review_policy_load.py`; re-run the suites named above and `tests/integration/ingestion`.
- Pattern references: `factories.py:363-380,391-420`, `ingestion/wiring.py:86-92`.

### Item 6 - Identity domain check and authorization suite  [serial-after: PRP-39]
- Deliverable: a single call site in the identity routes that rejects an unregistered domain through the `DOMAIN_REGISTRY` when the registry is non-empty (422 `domain_not_registered`); ABAC negative cases for every platform route; a leak test that greps logs and audit payloads for price values and policy bodies.
- Owned files: the one call site in `services/api/neurosphere_api/admin/identity/service.py` (edit only after PRP-39 has merged and the branch is rebased), `tests/security/authz/test_admin_platform.py`, `tests/security/authz/test_admin_platform_secrecy.py`, `services/api/tests/admin_platform_api/test_identity_domain_check.py`.
- Must NOT touch: any other identity file.
- Depends on: items 2 and 4; PRP-39 merged.
- Acceptance criteria: criterion 2; every platform route has a deny case per dimension (no role, viewer, auditor, ordinary-domain admin, expired control admin, other customer, other cloud); PRP-39's `services/api/tests/admin_identity_api` and `tests/security/authz/test_admin_identity*.py` still pass.
- Tests: the three files above plus the PRP-39 suites.
- Same-wave notes: PRP-48 owns the rest of `tests/security/authz/**` in W15; this PRP adds only the two `test_admin_platform*.py` files there. PRP-48 provides `is_reserved_chain_name`; domain create must refuse reserved chain names by calling it, as a `[serial-after: PRP-48]` step (merge after PRP-48, rebase, then add the call and its test).
- Pattern references: `tests/security/authz/test_api_paths.py`.

### Item 7 - Integration and close-out
- Deliverable: `routers.py` hook and inventories, `docs/runbooks/platform-config.md` and `mkdocs.yml` nav, rebase and Tier-3 regeneration (`openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`), CHANGELOG entry, completion note with the product check (can an admin load a price sheet and see an estimate priced, without a file?) and a follow-up issue for catalog-wide price coverage.
- Owned files: Tier-2 lines, the runbook, this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1-6.
- Acceptance criteria: validation gates pass; CI green; #209 item 2 commented with what shipped (sheet upload and ledger pickup) and what stays with PRP-38 (the dev seed).

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/admin_platform packages/core/tests/hitl packages/core/tests/ledger services/api/tests/admin_platform_api services/api/tests/admin_identity_api services/api/tests/hitl_api services/api/tests/actions_api services/api/tests/finops_api services/api/tests/runtime_api services/api/tests/runtime_data services/api/tests/runtime_planes services/api/tests/runtime_routes services/workers/tests/admin_platform_worker services/workers/tests/ingestion services/workers/tests/action_executor services/workers/tests/hitl_timers services/workers/tests/evaluation_worker services/workers/tests/worker_roles tests/security/authz tests/integration/ingestion services/api/tests/test_openapi_drift.py tests/docs/test_reference_coverage.py tests/docs/test_nav_allowlist.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No migration: all four objects are new documents, and `price_snapshots` already exists and is append-only. With nothing stored, ingestion, HITL and identity behave exactly as before. Rollback: revert the PR; stored documents are inert, and uploaded snapshots remain (they cannot be deleted by design, a wrong sheet is superseded by a new `snapshot_id` with a later effective date). Review policy can be reset by `PUT` of the defaults.

## Live and open gates
None run. Proof is in-memory twins, the Cosmos emulator for the snapshot store (marked `integration`, local only) and fakes. A real provider price sheet upload on a hosted stack and its effect on a live forecast are operator checks for PRP-58 and PRP-64; Government price sheets stay customer-supplied and unverified (G01 and G04 are OPEN).

## NOT building
Budget evaluation, alerts or notifications; fetching or scraping prices; a price sheet editor; deleting a snapshot; per-domain price overrides; catalog-wide price coverage; the dev-stack seed fix; the forecast changes; hot reload; the console pages.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 3, 5, 6, 7 and 9 are ASSUMPTIONS for plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
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
- Product check (can an operator use it without editing files):
