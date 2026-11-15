---
name: PRP-43-catalog-hardening-and-review-queue
status: backlog
priority: P1
order: 31
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-02, NS-04
depends_on: [PRP-37-contracts-revision-admin-cost-and-permissions]
wave: W14
branch: prp-43-catalog-hardening
allow_parallel: true
issues: [237, 193, 194, 195, 207, 208, 210]
---

# PRP-43: Catalog hardening and the relationship review queue

## Goal
Close the PRP-10 follow-ups that leave the catalog quietly lossy or unreviewable, and give stewards the missing review surface. Out-of-scope or colliding projection candidates stop being dropped from memory or wedging the catalog checkpoint and go to a durable quarantine; graph traversal stops reading one entity per edge; presented edges expose their provenance method; the review queue's open-duplicate check becomes race-safe and emulator-tested; the shared `ChangeConfirmDialog` gets a control slot; the entity write adapters get their four review notes closed; and conflicts the projection enqueues to `catalog_review_queue` finally reach a reviewer through a list route, a resolve route and a page. It is for stewards (who today cannot see a relationship conflict at all) and for operators who need skipped candidates to survive a worker restart. It is `review: required` because it touches a write path that enqueues into governed data and adds a resolve action.

Out of scope: `CostRecord` and structured-query contract changes and the contract-level provenance guarantee (PRP-37, already merged); the bulk "edges among ids" graph call (PRP-18, extended here, never rewritten); the keyed stale-agent plan digest and the search `cache_key` helper move (`neurosphere_core/search/**` belongs to PRP-60); the `catalog/router.py` and `ui_adapters/catalog.py` authorization edits of PRP-48; admin console pages (PRP-53, PRP-57); live Cosmos latency re-measure on a real account (#57, PRP-64); enriching discovered entities from connectors (#193 last bullet, needs connector metadata that does not exist yet).

## Why
- `build_projections` constructs `CatalogProjection` without a `quarantine` argument (`services/workers/neurosphere_workers/runtime/factories.py:437-442`), so the handler falls back to `InMemoryCandidateQuarantine` (`projections/catalog/handler.py:153`) and every out-of-scope candidate is lost on restart (#193).
- An entity id that exists outside the worker scope makes `create_entity` raise `InvalidSchemaError`, `get_entity` stays `None`, and `_ensure_entities` re-raises (`handler.py:256-262`), so the catalog checkpoint stops advancing (#193). `build_entity` returning `None` is skipped silently at `handler.py:253`.
- `RepositoryGraphQuery._in_scope` awaits one `get_entity` per unseen endpoint (`catalog/graph/query.py:282-292`); the emulator evidence puts neighbors at depth 3 over its 5 s budget. `_expand` flags `max_edges` from an unfiltered cursor (`query.py:334-336`) and the module imports `auditor_domains` from `repo/engine.py` (`query.py:62`) (#194).
- `PresentedEdge` (`catalog/protocol.py:347-376`) has no provenance although every stored relation carries it (`CatalogEdge.provenance`, `protocol.py:190` for observations and the relation contracts); `rules.present_edge` (`rules.py:198`) never copies it (#195).
- `CosmosReviewQueue.enqueue` is check-then-insert (`catalog/review_queue_cosmos.py:122-133`); `tests/integration/catalog/test_repo_cosmos.py` has no `list_edges_by_domain` or review-queue case (#195).
- `ChangeConfirmDialog` has `reasonNote` but no control slot and still requires free text (`frontend/src/features/governed-change/ChangeConfirmDialog.tsx:34-78,131`); the reason-code picker sits outside it at `features/catalog/CatalogEntityPage.tsx:245-415` (#207).
- Nothing lists or resolves `catalog_review_queue`: the only consumer is the `get_review_queue` dependency (`catalog/curation/dependencies.py:60`), and `CurationService` only enqueues (`curation/service.py:356-366`) (#210).

## Acceptance criteria
- [ ] Given an out-of-scope candidate, when the projection handles it, then a `CandidateQuarantineRecord` is written to a durable `catalog_quarantine` Cosmos container (idempotent by candidate edge id) and survives a worker restart; a store failure fails the entry and holds the checkpoint (#193 bullet 1).
- [ ] Given an entity id that exists in a domain outside the worker scope, when a candidate references it, then the candidate is quarantined with reason `entity_id_collision`, `stats.skipped_collision` increments, and the checkpoint advances; given any other create failure (for example `ForbiddenError`) the exception propagates and the checkpoint holds (#193 bullets 2 and 4).
- [ ] `build_entity` returning `None` is an explicit counted outcome (`stats.entities_undiscoverable`) with a debug log of the entity type only, not a silent `continue` (#193 bullet 3).
- [ ] When `skipped_out_of_scope + skipped_collision` crosses `NS_WORKER_CATALOG_QUARANTINE_WARN` (default 100 per process lifetime) the worker logs one WARNING with counts only, never ids (#193 alert threshold).
- [ ] Given a 3-depth neighbors query over an emulator-sized fixture, when endpoints are resolved, then reads run with bounded concurrency (16) and a repeated endpoint is read once; the fake-repository test asserts at most one `get_entity` call per distinct id and a lower wall time than the sequential baseline (#194 bullet 1).
- [ ] Given a node with more than 500 edges of which fewer than `fan_out` are in scope, then `max_edges` is not reported; given more than `fan_out` in-scope edges it is (#194 bullet 2).
- [ ] `graph/query.py` no longer imports from `repo/engine.py`; `auditor_domains` lives in a neutral module and `engine.py` re-exports it (#194 bullet 3).
- [ ] `PresentedEdge.provenance` is populated by `present_edge` from the stored edge, and the curation and map responses carry it; `frontend/src/features/curation/types.ts` shows the method on the edge page (#195 provenance bullet).
- [ ] Two concurrent `enqueue` calls for the same open conflict leave exactly one open item on the Cosmos emulator; after `resolve`, a later conflict enqueues under its own id (#195 open-duplicate race).
- [ ] `tests/integration/catalog/` covers `list_edges_by_domain` and the review-queue open-duplicate query on the emulator (#195 coverage bullet).
- [ ] The id-backfill decision is recorded (see Clarifications 4) in the completion note and `docs/` catalog reference (#195 id bullet).
- [ ] `ChangeConfirmDialog` accepts an optional `controls` slot and a `reasonMode: "text" | "code"`; in code mode the free-text reason is hidden, submit is enabled when the slot reports valid, and `CatalogEntityPage` moves its reason-code picker into the dialog (#207).
- [ ] A PUT that targets domain X's own Domain entity needs `catalog.curate` on X (test); creating a `grant` catalog entity changes no principal's computed permissions (test over scope derivation); a body whose declared `Content-Length` exceeds 64 KiB is refused before parsing with `request_too_large`; non-user principals are accepted exactly as the PRP-10 create route (pinned by test) (#208).
- [ ] `GET /api/v1/catalog/curation/review-queue` lists open items in the caller's scope; `POST /api/v1/catalog/curation/review-queue/{item_id}/resolve` resolves one with `catalog.curate` on the item's domain, stamps `resolved_by` server-side, writes an audit record, and answers an out-of-scope or missing item with the same 404 (#210 API).
- [ ] `/catalog/review-queue` renders the open items with age, edge link and a resolve control (kept curation or accepted inference), handles empty, 403 and 503 states, passes the axe a11y spec, and appears in Governance navigation (#210 UI).
- [ ] PRP exit: targeted suites, repo-wide `ruff`, `pyright`, frontend lint/typecheck/test and `verify-gates.ps1 -Mode full` pass; the live Cosmos re-measure is reported OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where does the durable quarantine live | New `catalog_quarantine` container; reuse `catalog_review_queue`; reuse `admin_config` | New container partitioned `/customer_id`,`/domain_id` (same shape as the review queue). Reusing the review queue would mix operator-facing items with machine records |
| 2 | What does resolving a review item do | Mark only; mark and write an override | ASSUMPTION: resolve only records `kept_curation` or `accepted_inference` on the item (existing `ReviewQueue.resolve`). `accepted_inference` does not edit the edge; the page links to the edge page where the steward uses the existing decision control, so one audited decision path stays the only way to change curation |
| 3 | Review item SLA and merge into `/review` | Merge into HITL `/review`; separate queue | Separate queue (HITL items need approval roles and timers; this is a steward conflict list). ASSUMPTION: no SLA enforcement; the page shows item age and sorts oldest first |
| 4 | Backfill of observation and review-item ids that now include confidence and generation | One-off backfill; none | ASSUMPTION: no backfill. No real data exists yet; a pre-change observation replayed once is recorded one extra time and `merge_observation` is idempotent by evidence, so the effect is one duplicate observation row. Revisit before the first real ingestion (PRP-64) |
| 5 | Keyed stale-agent plan digest (#195 bullet 1) | Wire `PSEUDONYMIZER` into `CatalogService`; leave | Leave unkeyed; the live set is re-derived so it is safe. Recorded as accepted in the completion note |
| 6 | Graph read cost fix | New batched `get_entities` protocol method; bounded concurrency | Bounded concurrency with a per-walk cache. A new protocol method would break every `CatalogRepository` fake; revisit if the emulator re-measure still misses budget |
| 7 | Non-user principals on entity write routes (#208 item 4) | Refuse on both routes; keep and pin | Keep and pin with a test; tightening needs `catalog/router.py`, which PRP-48 owns in W15. Filed as a follow-up note |
| 8 | Raw body cap (#208 item 3) | New middleware; per-route dependency | ASSUMPTION: a per-route dependency on the two entity write routes rejects an oversized declared `Content-Length`; chunked bodies stay bounded by the global 1 MiB `RequestSizeLimitMiddleware` plus the existing post-parse 64 KiB check |

## Context manifest

### Files to read first
- `services/workers/neurosphere_workers/projections/catalog/handler.py` - `CatalogProjection`, `_apply`, `_ensure_entities`, `ProjectionStats`.
- `services/workers/neurosphere_workers/projections/catalog/quarantine.py` - record model, protocol, in-memory sink.
- `services/workers/neurosphere_workers/runtime/factories.py:430-445` - `build_projections` (the `[serial-after: PRP-42]` edit).
- `packages/core/neurosphere_core/catalog/graph/query.py` - `_walk`, `_in_scope`, `_expand` (PRP-18 adds `edges_among` here one wave earlier).
- `packages/core/neurosphere_core/catalog/protocol.py:347-376` and `rules.py:150-215` - `PresentedEdge` and `present_edge`.
- `packages/core/neurosphere_core/catalog/review_queue.py` and `review_queue_cosmos.py` - queue protocol and Cosmos implementation.
- `services/api/neurosphere_api/catalog/curation/{router,dependencies,service}.py` - routes, scope-first dependencies, audit.
- `services/api/neurosphere_api/ui_adapters/{entities,models}.py` - entity write adapters and `_check_entity_body`.
- `frontend/src/features/governed-change/ChangeConfirmDialog.tsx` and `features/catalog/CatalogEntityPage.tsx:245-420`.
- `frontend/src/features/curation/{EdgePage.tsx,paths.ts,routes.tsx,types.ts}` and `frontend/tests/mock-api/features/curation.ts`.

### Interfaces consumed
- `EdgesAmongQuery` and `RepositoryGraphQuery.edges_among` in `catalog/graph/` (PRP-18): extended only, never edited.
- Relation contracts already require `provenance` (`catalog/v1/common.schema.json#/$defs/provenance`, asserted by PRP-37); this PRP only populates the core `PresentedEdge` field.
- `Permission.CATALOG_CURATE`, `require`, `AuthzTarget` (`neurosphere_api.authz`); PRP-48 (W15) later adds `audited_read` and `require_deployment_admin` and edits `catalog/router.py`; this PRP does not touch that file.
- Cosmos stores registry `packages/core/neurosphere_core/stores/containers.py` (Tier 1; PRP-37 owned it in W12).

### Interfaces provided
- `neurosphere_core.catalog.PresentedEdge.provenance` (`common.Provenance`); openapi and `frontend/src/features/curation/types.ts` change with it.
- Routes `GET /api/v1/catalog/curation/review-queue` and `POST /api/v1/catalog/curation/review-queue/{item_id}/resolve` (plus the deprecated `/catalog/curation/...` alias that `register_with_alias` adds); response models `ReviewQueuePage` and `ReviewResolution` request body.
- Container `catalog_quarantine`; `CosmosCandidateQuarantine` in `projections/catalog/quarantine_cosmos.py`; worker setting `NS_WORKER_CATALOG_QUARANTINE_WARN`.
- `neurosphere_core.catalog.auditor` (new) exporting `auditor_domains`.
- Frontend: `ChangeConfirmDialog` props `controls`, `reasonMode`; route `catalog/review-queue`, `reviewQueueNavItems()`.

### Patterns to match
- Cosmos store with hierarchical key and mapped errors: `catalog/review_queue_cosmos.py:60-130`.
- Scope-first route authorization: `catalog/curation/dependencies.py:85-135` (`edge_access`).
- Audited mutation: `catalog/curation/service.py:140-230` (`decide`).
- Per-route request guard returning `request_too_large`: `middleware/size_limit.py:15-45`.
- Frontend page with scope-gated list and states: `features/catalog/RecertificationsPage.tsx`, route registration `features/catalog/routes.tsx:20-45`.

### Gotchas
- `create_entity` raises a bare `InvalidSchemaError(_TAKEN["entity"])` for both a scoped and an out-of-scope duplicate (`repo/engine.py:243-249`), so the worker cannot tell collision from a real schema failure. Item 1 gives both raises a stable `reason="entity_id_taken"`; keep the message unchanged for existing tests.
- The quarantine container needs Tier-1 store files (`stores/containers.py`, `infra/compose/cosmos-containers.json`, `infra/demo/modules/cosmos-data.bicep`, `infra/bicep/modules/cosmos.bicep`); this PRP is the W14 owner of those four files (granted 2026-11-14; no other W14 PRP adds a container). Item 2 still follows PRP-37, which lands in W12.
- `build_projections` is a worker composition body; PRP-42 owns `factories.py` in W14, so the wiring in Item 2 is `[serial-after: PRP-42]`.
- Review-queue ids already include the conflict generation (`rules.review_item_id`); the open-duplicate marker must not change them.
- `PresentedEdge` is a `response_model`: adding a field renames nothing but changes `openapi.json` (Tier 3, regenerate last) and frontend `types.ts`; `map/service.py:76` derives its own provenance from status and is PRP-18/49 territory, do not edit it.
- New route paths go through `register_with_alias`; PRP-51 removes aliases later, so use no alias-specific code.
- Same-named test directories shadow each other: new directories below have unique names.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/catalog/**
  - packages/core/tests/catalog/test_graph_perf_round3.py
  - packages/core/tests/catalog/test_presented_edge_provenance.py
  - packages/core/tests/catalog/test_review_queue_marker.py
  - services/workers/neurosphere_workers/projections/catalog/**
  - services/workers/tests/projections/test_catalog_quarantine_collision.py
  - services/workers/tests/projections/test_catalog_quarantine_cosmos.py
  - services/api/neurosphere_api/catalog/**
  - services/api/neurosphere_api/ui_adapters/entities.py
  - services/api/tests/catalog_review_queue_api/**
  - services/api/tests/ui_adapters_api/test_entity_write_hardening.py
  - frontend/src/features/governed-change/**
  - frontend/src/features/curation/**
  - frontend/src/features/catalog/CatalogEntityPage.tsx
  - frontend/tests/mock-api/features/curation.ts
  - frontend/tests/e2e/curation/review-queue.spec.ts
  - tests/integration/catalog/**
tier1:
  - packages/core/neurosphere_core/stores/containers.py
  - infra/compose/cosmos-containers.json
  - infra/demo/modules/cosmos-data.bicep
  - infra/bicep/modules/cosmos.bicep
tier2_appends:
  - services/workers/neurosphere_workers/runtime/settings.py
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/route-manifest.json
  - frontend/src/app/workspaceNav.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/runtime_routes/manifest_calls.py
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/search/**
  - services/api/neurosphere_api/catalog/router.py
  - services/api/neurosphere_api/ui_adapters/catalog.py
  - services/api/neurosphere_api/map/**
  - services/api/neurosphere_api/runtime/builders/data.py
```

## Implementation blueprint
Parallelization map: Items 1, 3, 5 are independent [P]. Item 2 waits for 1 and carries two serial-after edits. Item 4 and Item 6 both touch `review_queue_cosmos.py` consumers: 6 waits for 4. Item 7 waits for 6. Item 8 is last. Shared files: `catalog/protocol.py` (4 only), `review_queue_cosmos.py` (4 only), `curation/router.py` (6 only), `frontend/src/features/curation/**` (7 only).

### Item 1 - Quarantine behaviour and Cosmos sink  [P]
- Deliverable: `entity_id_taken` reason on both `create_entity` raises; `_ensure_entities` quarantines a collision (`REASON_ENTITY_COLLISION`) and still propagates any other failure; counted outcomes for undiscoverable types; `CosmosCandidateQuarantine` (new) implementing `CandidateQuarantine` on container `catalog_quarantine`; threshold warning from the handler.
- Owned files: `catalog/repo/engine.py`, `projections/catalog/{handler,quarantine,quarantine_cosmos,discovery}.py`, `services/workers/tests/projections/test_catalog_quarantine_collision.py`, `.../test_catalog_quarantine_cosmos.py`.
- Must NOT touch: `factories.py`, `stores/containers.py`.
- Depends on: none.
- Acceptance criteria: criteria 1 to 4; a `ForbiddenError` from `create_entity` propagates and the checkpoint is not advanced (fake outbox reader asserts); replay of the same quarantined candidate leaves one record.
- Tests: the two new files above plus `uv run pytest -q services/workers/tests/projections packages/core/tests/catalog`.
- Pattern references: `quarantine.py:30-60`, `review_queue_cosmos.py:60-130`.

### Item 2 - Wire the durable quarantine  [serial-after: PRP-37] [serial-after: PRP-42]
- Deliverable: container spec `catalog_quarantine` in the four store files and regenerated `cosmos-containers.json`; `build_projections` passes `CosmosCandidateQuarantine`; worker setting `NS_WORKER_CATALOG_QUARANTINE_WARN` appended to worker settings (Tier 2).
- Owned files: `stores/containers.py`, `infra/compose/cosmos-containers.json`, `infra/demo/modules/cosmos-data.bicep`, `infra/bicep/modules/cosmos.bicep`, `factories.py` (`build_projections` body only), `services/workers/neurosphere_workers/runtime/settings.py` (append), `tests/integration/catalog/test_quarantine_cosmos.py` (emulator, `integration` marker).
- Must NOT touch: any other builder in `factories.py`, any existing container spec.
- Depends on: Item 1; PRP-37 merged (stores); PRP-42 merged (`factories.py`).
- Acceptance criteria: containers drift test (`packages/core/tests/stores_registry`) passes with the new entry; `az bicep build` of both modules succeeds; with the emulator, a restarted projection still holds the quarantined records.
- Tests: `uv run pytest -q packages/core/tests/stores_registry services/workers/tests/runtime`, then `uv run pytest -q -m integration tests/integration/catalog` with the emulator at `127.0.0.1` (not run in CI; report as local evidence).
- Pattern references: `containers.py:168-173` (`catalog_review_queue`), `factories.py:437-442`.

### Item 3 - Graph traversal read cost and fan-out signal  [P]
- Deliverable: bounded-concurrency endpoint resolution in `_in_scope`/`_expand` (semaphore 16, per-walk cache already present), scope-filtered fan-out signal (page on until `fan_out + 1` in-scope edges or exhaustion, within budget), `auditor_domains` moved to `catalog/auditor.py` (new) and re-exported by `repo/engine.py`.
- Owned files: `catalog/graph/query.py` (only `_in_scope`, `_expand` and the import; the PRP-18 `edges_among` code stays untouched), `catalog/auditor.py` (new), `catalog/repo/engine.py` (re-export line), `packages/core/tests/catalog/test_graph_perf_round3.py`.
- Must NOT touch: `catalog/graph/latest.py`, the `edges_among` implementation or its tests.
- Depends on: none (PRP-18 merged first in W13; rebase on it).
- Acceptance criteria: criteria 5 to 7; existing `test_graph_scope.py` and `test_graph_budgets.py` stay green unmodified; an optional emulator benchmark under `tests/integration/catalog/` is marked `integration` and its numbers go in the completion note (#57 live re-measure stays OPEN).
- Tests: `uv run pytest -q packages/core/tests/catalog`.
- Pattern references: `query.py:282-292`, `packages/core/tests/catalog/graph_helpers.py`.

### Item 4 - Presented-edge provenance and review-queue hardening
- Deliverable: `PresentedEdge.provenance` added and populated in `present_edge`; Cosmos review queue writes a deterministic open-marker document (same partition, `kind="open_marker"`, id from edge, reason and governing decision) before the item, treats a conflict on it as "already open", and removes it on `resolve`; `list_open` excludes markers; in-memory twin behaves the same; emulator tests for `list_edges_by_domain` and the open-duplicate race.
- Owned files: `catalog/protocol.py` (field only), `catalog/rules.py` (`present_edge`), `catalog/review_queue.py`, `catalog/review_queue_cosmos.py`, `packages/core/tests/catalog/test_presented_edge_provenance.py`, `packages/core/tests/catalog/test_review_queue_marker.py`, `tests/integration/catalog/test_repo_cosmos.py`, `tests/integration/catalog/test_review_queue_cosmos.py` (new).
- Must NOT touch: `packages/contracts/**`, `catalog/repo/engine.py` beyond Item 1/3 lines.
- Depends on: none.
- Acceptance criteria: criteria 8 to 11; an item stored before this change (no marker) is still listed, resolved and deduplicated by the old query path.
- Tests: `uv run pytest -q packages/core/tests/catalog packages/core/tests/review_queue_cosmos`; emulator: `uv run pytest -q -m integration tests/integration/catalog`.
- Pattern references: `review_queue_cosmos.py:122-153`, `rules.py:198-215`.

### Item 5 - Entity write adapter follow-ups  [P]
- Deliverable: the four #208 outcomes: pinned tests for Domain self-edit and grant-entity inertness, a per-route `Content-Length` dependency on the two write routes, a pinned non-user principal test.
- Owned files: `services/api/neurosphere_api/ui_adapters/entities.py`, `services/api/tests/ui_adapters_api/test_entity_write_hardening.py`.
- Must NOT touch: `ui_adapters/models.py`, `catalog/router.py`, `middleware/**`.
- Depends on: none.
- Acceptance criteria: criterion 13; existing `test_entity_write_adapters.py` unchanged and green.
- Tests: `uv run pytest -q services/api/tests/ui_adapters_api services/api/tests/catalog`.
- Pattern references: `ui_adapters/entities.py:90-140`, `test_entity_write_adapters.py:184-200`.

### Item 6 - Review-queue routes
- Deliverable: list and resolve routes on the curation router with a `ReviewQueueGuard` dependency (scope-first, 404 for missing or out-of-scope), response models `ReviewQueuePage` and `ReviewResolveBody`, audit through `CurationService` (new `resolve_review_item` method), Tier-2 inventory lines.
- Owned files: `curation/{router,service,dependencies}.py`, `services/api/neurosphere_api/catalog/curation/__init__.py` if exports change, `services/api/tests/catalog_review_queue_api/**` (new).
- Must NOT touch: `catalog/router.py`, `ui_adapters/curation.py`.
- Depends on: Item 4.
- Acceptance criteria: criterion 14; viewer without `catalog.curate` gets 403; resolving twice is idempotent (second call 200 with the stored item); audit record carries the item id and resolution, no evidence payload.
- Tests: `uv run pytest -q services/api/tests/catalog_review_queue_api services/api/tests/catalog services/api/tests/authz`.
- Pattern references: `curation/router.py:75-110`, `curation/service.py:140-230`.

### Item 7 - Frontend: dialog slot and review-queue page
- Deliverable: `ChangeConfirmDialog` `controls` slot and `reasonMode`; `CatalogEntityPage` uses it; `ReviewQueuePage` with age, edge link, resolve dialog; `paths.ts` additions; `reviewQueueNavItems()` wired through the Governance group; mock handlers; e2e and a11y route sample.
- Owned files: `frontend/src/features/governed-change/**`, `frontend/src/features/curation/{ReviewQueuePage,paths,routes,strings,types,data,index}.ts*`, `frontend/src/features/curation/reviewQueue.test.tsx` (new), `frontend/src/features/catalog/CatalogEntityPage.tsx`, `frontend/tests/mock-api/features/curation.ts`, `frontend/tests/e2e/curation/review-queue.spec.ts` (new).
- Must NOT touch: `frontend/src/app/Shell.tsx`, `frontend/tests/mock-api/server.ts`.
- Depends on: Item 6 (route shapes).
- Acceptance criteria: criteria 12, 8 (UI part) and 15; existing `ChangeConfirmDialog.test.tsx` and `catalog-write.test.tsx` pass with only the intended assertion changes.
- Tests: `pnpm --filter @neurosphere/frontend test -- governed-change curation catalog`, `pnpm --filter @neurosphere/frontend test:e2e -- curation`, `lint`, `typecheck`, `format`.
- Pattern references: `features/catalog/RecertificationsPage.tsx`, `features/catalog/routes.tsx`.

### Item 8 - Integration and close-out
- Deliverable: Tier-2 appends (routes registry lines, route manifest, nav, a11y samples, route inventories); regenerate `services/api/openapi.json`, `docs/reference/**`, `python packages/contracts/scripts/generate.py --check`, `python scripts/prp_status.py --write`; docs section for the review queue and quarantine under `docs/`; completion note.
- Owned files: the Tier-2 files in the ownership block, `docs/runbooks/catalog-review-queue.md` (new), this PRP file.
- Depends on: Items 1 to 7.
- Acceptance criteria: reference section 6 satisfied; cross-test grep (`review_queue`, `PresentedEdge`, `CandidateQuarantine`) over `tests/` and `services/*/tests` run before push.

## Validation gates
```bash
uv sync --frozen --group dev
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/catalog packages/core/tests/review_queue_cosmos packages/core/tests/stores_registry services/workers/tests/projections services/workers/tests/runtime services/api/tests/catalog_review_queue_api services/api/tests/catalog services/api/tests/ui_adapters_api services/api/tests/authz services/api/tests/test_openapi_drift.py
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend test:e2e -- curation
docker compose up -d --wait
uv run pytest -q -m integration tests/integration/catalog
python packages/contracts/scripts/generate.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
The `integration` suite is skipped by the CI python job; report its output as local evidence.

## Migration and rollback
New container `catalog_quarantine` (created by the emulator bootstrap locally and by the two Bicep modules on the next deploy). Existing review-queue documents stay valid (markers are additive). The `PresentedEdge` field is additive in responses. Rollback: revert the PR; leave the empty container; the worker falls back to the in-memory sink when `catalog_quarantine` cannot be reached only if Item 2 is reverted. The review-queue routes can be disabled by reverting Item 6; no data is deleted anywhere.

## Live and open gates
Live Cosmos latency re-measure of graph traversal is OPEN (#57, handed to PRP-64). The emulator benchmark is local evidence only. Nothing here needs `NS_LIVE_APPROVED=1`.

## NOT building
Keyed stale-agent digest; moving the search `cache_key` helper (PRP-60); connector enrichment of discovered entities; a batched `get_entities` protocol method; SLA timers or escalation for review items; merging review items into HITL `/review`; refusing non-user principals on entity routes (needs `catalog/router.py`, PRP-48); admin console pages.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided or labelled ASSUMPTION

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | verifying | prp-43-catalog-hardening | quarantine collision + Cosmos sink + threshold warning done, tests green |
| 2 | in-progress | prp-43-catalog-hardening | container spec, regenerated cosmos-containers.json (Bicep reads it), worker setting `CatalogProjectionSettings.quarantine_warn`, emulator test written (not run). OPEN: `build_projections` wiring is [serial-after: PRP-42] (not in PRPs/shipped) |
| 3 | verifying | prp-43-catalog-hardening | bounded concurrency 16, scope-filtered fan-out, `catalog/auditor.py`; rebased on PRP-18 main |
| 4 | verifying | prp-43-catalog-hardening | provenance on PresentedEdge, Cosmos open marker, emulator tests written (not run: no compose) |
| 5 | verifying | prp-43-catalog-hardening | per-route pre-parse Content-Length guard via route class, pinned tests |
| 6 | verifying | prp-43-catalog-hardening | list + resolve routes, `ReviewQueueGuard` (`review_queue_guard`), audit, tests |
| 7 | verifying | prp-43-catalog-hardening | dialog `controls`/`reasonMode`, ReviewQueuePage, nav, mock, vitest, e2e + a11y green |
| 8 | in-progress | prp-43-catalog-hardening | runbook + mkdocs nav + Tier-2 lines done; Tier-3 regeneration, factories wiring and close-out left for the merge step |

## Completion note (filled at ship)
- Date, PR, merge commit:
- Deviations from the blueprint:
- Descoped items:
- OPEN gates (live Cosmos re-measure, #57):
- Env vars for the operator (`NS_WORKER_CATALOG_QUARANTINE_WARN`):
- Follow-up issue numbers (non-user principal refusal, connector enrichment):
- Issue state (#193, #194, #195, #207, #208, #210):
