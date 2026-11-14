---
name: PRP-60-search-indexing-hardening
status: backlog
priority: P2
order: 47
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-02
depends_on: []
wave: W18
branch: prp-60-search-indexing-hardening
allow_parallel: true
---

# PRP-60: Search indexing hardening

## Goal
Make the catalog search index correct and current when it is backed by Azure AI Search, and stop one slow caller from stalling every other caller's search. PRP-35 shipped the search provider and a catalog indexer, but its completion note lists four defects with no issue: Azure document keys contain colons (the index key rejects them), the index has no `text` field, catalog writes made by the workers never reach the index, the indexer never deletes or moves documents, and one global lock serialises every scope's refresh. This PRP fixes those, adds an index schema definition with an explicit opt-in to create it, and hands the two composition edits it cannot make itself to serial items. It is for operators running `NS_SEARCH_PROVIDER=azure` and for every user of catalog search. It is `review: required` because it sits on the authorization-filtered search path.

Out of scope: any live Azure AI Search run (OPEN, handed to PRP-64); the Bicep search module and Helm values (PRP-52, PRP-58); changing how results are authorized (the scope filter and the repository re-fetch stay exactly as they are); a vector or semantic ranking mode; the admin settings page for search (PRP-45).

## Why
- Azure AI Search document keys may contain only letters, digits, underscore, dash and equals, but canonical ids are `cloud:customer:source:type:local` (`packages/core/neurosphere_core/search/fixture/index.py:51-86`, `documents_from_catalog` splits on `:`), and `AzureIndexSink.upsert` (`search/indexer.py:104-116`) uploads `SearchDocument.model_dump()` with `id` set to that value; the Azure query path then reads `doc["id"]` back as the canonical id (`search/azure/client.py:108`) and filters grants with `search.in(id, ...)` (`search/azure/filters.py:99-100`).
- The index is never defined in code: the only index references are the `NS_SEARCH_INDEX` default `neurosphere-catalog` in `services/api/neurosphere_api/runtime/builders/search.py` and the "created by IaC/operator" note; `_SELECT` (`client.py:34`) does not request `text`, and nothing guarantees the index has a `text` field that `merge_or_upload_documents` can fill.
- Nothing calls `SearchRuntime.invalidate()` outside tests (`services/api/tests/runtime_data/test_search_builder.py:136-145`); freshness is only the lazy per-scope refresh (`builders/search.py` `IndexedGraphQuery._sync`, default 30 s). Worker projections write the catalog from another process (`services/workers/neurosphere_workers/projections/catalog/`) and cannot reach the API's in-process index at all.
- `CatalogIndexer` only upserts: `index_entities` and `refresh` (`indexer.py:150-196`) never remove a document whose entity left the enumeration, and `IndexSink` (`indexer.py:62-65`) has no delete.
- `IndexedGraphQuery._sync` holds one `asyncio.Lock` (`builders/search.py` `self._lock`) across `indexer.refresh(scope)`, so a slow refresh for one scope blocks every other scope's search.
- ASSIGNMENTS named `services/api/neurosphere_api/search/**` and `services/workers/neurosphere_workers/search/**`; neither directory exists. The real code is `packages/core/neurosphere_core/search/**` and `services/api/neurosphere_api/runtime/builders/search.py` (the two `_NoSearch` fallbacks are in `runtime/builders/data.py:190-217` and `services/workers/tests/projections/test_catalog_entity_discovery.py:26`).

## Acceptance criteria
- [ ] Given a canonical id with colons, When it is indexed to Azure, Then the document key is an encoded form that contains only characters Azure allows (URL-safe base64 of the canonical id, no padding), the canonical id is stored in a separate retrievable, filterable `entity_id` field, and decoding the key returns the canonical id (round-trip property test).
- [ ] The Azure query path selects and returns `entity_id` as the hit id, grants are filtered on `entity_id`, and `_doc_in_scope` checks `entity_id`; the fixture path is unchanged; existing scope-filter tests pass unmodified in behaviour.
- [ ] An index definition (`catalog_index_definition()`) declares the key field, `entity_id`, `entity`, `cloud`, `customer_id`, `domain_id` as filterable strings and `text` as a searchable string; a test asserts every field `SearchDocument` serialises exists in the definition (drift guard).
- [ ] `NS_SEARCH_ENSURE_INDEX` (default false) makes the builder create-or-update the index through an injected index client when true and the Azure provider is enabled; with it false nothing is created; unsupported cloud or region still makes no request (existing test extended).
- [ ] Given an entity that disappears from a scope's enumeration, When that scope refreshes, Then its document is deleted from the sinks, and a document still enumerated by another scope's last refresh is not deleted by a stale scope (ref-counted removal test); a delete failure raises `DependencyTransientError` and the document stays remembered for retry.
- [ ] Given two scopes, When scope A's refresh is slow, Then scope B's search is not delayed (test with a gated sink); concurrent searches for the same scope share one refresh (single-flight); the per-scope lock table is bounded.
- [ ] Given a catalog write through the wrapped repository (create, update, deprecate), Then the changed entity is upserted or removed in the sink without a full re-enumeration, and a sink failure does not fail the catalog write (logged by exception type only).
- [ ] No document body, id or entity text is logged (extend `test_document_bodies_are_never_logged`); no key or connection string path is introduced.
- [ ] The two serial wiring items are present and either done after their predecessor merged or reported as `[serial-after]` open; a note in the completion records which.
- [ ] PRP exit: touched suites pass, `verify-gates.ps1 -Mode full` green, one review pass approved, live Azure checks reported OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Key encoding | Replace `:` with `_`; hash; URL-safe base64 | URL-safe base64 without padding: reversible, collision-free, and `id` is not a user-visible value. Replacement with `_` can collide with legal local ids |
| 2 | Canonical id field | Reuse `id`; new field | New `entity_id` field. Filters on grants move to it; `id` becomes an opaque key |
| 3 | Who creates the index | Operator only; builder always; builder opt-in | Builder opt-in via `NS_SEARCH_ENSURE_INDEX=true`; it needs index-write RBAC (Search Service Contributor), which the data-plane identity may not hold, so default is false and the schema is also usable by an operator script |
| 4 | Cross-process invalidation | Shared change marker; write-through sink in the writer | Write-through: a repository wrapper upserts the changed entity into the configured sink. With `fixture` the in-process index lives only in the API, so worker writes become visible at the lazy refresh (default 30 s, `NS_SEARCH_REFRESH_SECONDS`) and the PRP documents that bound; with `azure` the worker wrapper writes to Azure directly |
| 5 | Delete semantics | Delete on absence; delete on deprecate | ASSUMPTION: a document is deleted when its entity is no longer returned by the scoped enumeration; deprecated entities are handled by whatever `list_entities` returns by default (not changed here). If the owner wants deprecated entities hidden from search, that is a one-line filter and a follow-up |
| 6 | Stale-hit safety | Trust the index; re-fetch | Unchanged: every hit is re-fetched through the repository with the caller's scope (`RepositoryGraphQuery.search`), so a stale index entry never discloses a record the caller cannot read |
| 7 | API composition edit | Edit `data.py` here; serial item | Serial item `[serial-after: PRP-44]` (PRP-44 holds `runtime/builders/data.py` in W15); this PRP only exports the one function to call |
| 8 | Worker composition edit | Edit `factories.py` here; serial item | Serial item `[serial-after: PRP-55]` (PRP-55 holds worker `factories.py` bodies in W18) |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/search/indexer.py` - `IndexSink`, `FixtureSearchStore`, `AzureIndexSink`, `CatalogIndexer` (the whole file).
- `packages/core/neurosphere_core/search/azure/client.py` and `filters.py` - `_SELECT`, `_doc_in_scope`, `FIELD_*`, `build_filter`.
- `packages/core/neurosphere_core/search/fixture/index.py:38-90` - `SearchDocument`, `documents_from_catalog`.
- `services/api/neurosphere_api/runtime/builders/search.py` - `SearchSettings`, `IndexedGraphQuery`, `build_catalog_graph`, `SearchRuntime`.
- `services/api/neurosphere_api/runtime/builders/data.py:190-225` - `_NoSearch` and where `build_catalog_graph` is called.
- `packages/core/tests/search/{test_indexer.py,test_azure_search_scope.py,search_helpers.py}` and `services/api/tests/runtime_data/test_search_builder.py`.
- `packages/core/neurosphere_core/catalog/protocol.py:198-245` - `CatalogRepository` write methods the wrapper decorates (read only).
- `PRPs/shipped/PRP-35-runtime-composition.md` - item 3 and the follow-ups list.
- `services/workers/neurosphere_workers/runtime/factories.py` - where workers build the catalog repository (read only, for the serial item).

### Interfaces consumed
- `CatalogRepository` and `EntityFilter` (PRP-10); `AuthorizedSearch` and `SearchRequest` (PRP-05/PRP-10); `azure_search_capability` and `FallbackAuthorizedSearch` (PRP-35); `azure.search.documents.aio.SearchClient` and `azure.search.documents.indexes.aio.SearchIndexClient` (already in `azure-search-documents>=12,<13`, `packages/core/pyproject.toml:12`; no new dependency).

### Interfaces provided
- `neurosphere_core.search.azure.schema`: `encode_document_key`, `decode_document_key`, `catalog_index_definition`, `ensure_index`.
- `IndexSink.delete(ids)`; `CatalogIndexer.remove(ids)`; `neurosphere_core.search.write_hook.IndexingCatalogRepository`.
- `runtime/builders/search.py`: `wrap_catalog_for_search(ctx, repository)` returning `(repository, graph)`; `NS_SEARCH_ENSURE_INDEX`.
- PRP-45 can later write the settings from the admin store; PRP-64 runs the live index check.

### Patterns to match
- Capability-gated, no request when unsupported: `search/azure/fallback.py:36-90`; test `test_search_builder.py:160-200`.
- Idempotent upsert with a remembered digest only after sink success: `indexer.py:165-175`.
- Counts-only logging: `indexer.py:196`.
- Decorating a repository through the protocol: look at `catalog/repo/engine.py` write methods for the exact signatures the wrapper forwards.
- Fake Azure backend for tests: `packages/core/tests/search/search_helpers.py`.

### Gotchas
- Scope enumeration only: the indexer can enumerate only what the calling scope may read, so deletion by absence is per scope. A document leaves the index only when no scope's last enumeration still contains it; a wrongly deleted document reappears at the next refresh, and the repository re-fetch (Clarification 6) means a stale or missing entry never widens access.
- The existing tests pass `SearchDocument` with colon ids to `AzureIndexSink` and assert on the payload (`test_indexer.py:121`); update the assertions, do not weaken them.
- `search.in(entity_id, '...|...', '|')` ids contain colons and slashes; keep the existing `_ID_RE` validation and delimiter.
- PEP 695 generics in nested functions fail CodeQL; keep generics at module level.
- The worker's catalog write path is PRP-43's code (`projections/catalog/**`); the wrapper is applied where the repository is built, not inside the handler.
- A Government deployment with Azure search unavailable must not fall back to an in-process index for the worker wrapper: no sink, no wrapper (existing guard in `build_catalog_graph` raises for Government).

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership

```ownership
owns:
  - packages/core/neurosphere_core/search/**
  - packages/core/tests/search/**
  - services/api/tests/search_runtime/**
  - services/api/tests/runtime_data/test_search_builder.py
  - docs/runbooks/runtime-composition.md
tier1:
  - services/api/neurosphere_api/runtime/builders/search.py
tier2_appends:
  - services/api/neurosphere_api/runtime/settings.py
must_not_touch:
  - packages/core/neurosphere_core/catalog/**
  - services/workers/neurosphere_workers/projections/**
  - services/api/neurosphere_api/runtime/builders/data.py
  - services/workers/neurosphere_workers/runtime/factories.py
  - infra/bicep/modules/search.bicep
  - packages/contracts/**
  - pyproject.toml
  - uv.lock
```

## Implementation blueprint

Items 1 and 3 are independent [P] (disjoint files). Item 2 waits for 1 (both edit `indexer.py`). Item 4 waits for 2. Items 5 and 6 are serial-after items. Item 7 closes out.

### Item 1 - Azure document key, `entity_id` and `text`  [P]
- Deliverable: new `search/azure/schema.py` with `encode_document_key`/`decode_document_key` (URL-safe base64, no padding, reject non-canonical input), `catalog_index_definition()` (key `id`, filterable `entity_id`, `entity`, `cloud`, `customer_id`, `domain_id`, searchable `text`) and `ensure_index(index_client, definition)` (create-or-update through an injected `SearchIndexClient`-shaped protocol); `AzureIndexSink` maps each `SearchDocument` to the Azure document (`id` key, `entity_id` canonical, the other fields, `text`); `client.py` selects and returns `entity_id`, `filters.py` and `_doc_in_scope` use `entity_id` (add `FIELD_ENTITY_ID`).
- Owned files: `packages/core/neurosphere_core/search/azure/**`, `packages/core/neurosphere_core/search/indexer.py` (`AzureIndexSink` only), `packages/core/tests/search/**`.
- Must NOT touch: `search/fixture/**`, `search/protocol.py`, catalog code.
- Depends on: none.
- Acceptance criteria: key round-trip, field mapping, drift guard against `SearchDocument` fields, scope tests still green, no network in tests.
- Tests: `packages/core/tests/search/test_azure_key_encoding.py` (new), `packages/core/tests/search/test_index_definition.py` (new), `packages/core/tests/search/test_azure_search_scope.py`, `packages/core/tests/search/test_indexer.py`.
- Pattern references: `search/azure/client.py:75-135`, `filters.py:63-110`.

### Item 2 - Indexer deletes
- Deliverable: `IndexSink.delete(ids)` implemented by `FixtureSearchStore` (rebuild only if something was removed), `AzureIndexSink` (`delete_documents` with encoded keys, failure raises `DependencyTransientError` reason `search_index_delete_failed`) and `CompositeIndexSink`; `CatalogIndexer` tracks, per scope, the ids last enumerated and removes ids that left the scope's enumeration only when no other scope's last enumeration still holds them; `CatalogIndexer.remove(ids)` for explicit removal; the remembered digest for a removed id is dropped only after the sink accepted the delete.
- Owned files: `packages/core/neurosphere_core/search/indexer.py`, `packages/core/tests/search/**`.
- Must NOT touch: `search/azure/**` key logic (item 1), catalog code.
- Depends on: item 1.
- Acceptance criteria: the deletion, ref-count and retry criteria; counts-only logging.
- Tests: `packages/core/tests/search/test_indexer_deletes.py` (new), `packages/core/tests/search/test_indexer.py`.
- Pattern references: `indexer.py:150-200`.

### Item 3 - Per-scope refresh locks and index bootstrap  [P]
- Deliverable: `IndexedGraphQuery._sync` uses a bounded map of per-scope `asyncio.Lock`s (single-flight per scope, eviction with the freshness table, never a global lock); `SearchSettings.ensure_index` (`NS_SEARCH_ENSURE_INDEX`) and, when true and Azure is enabled, a one-time `ensure_index` call at build through an overridable `search_index_client` backend (override name for tests); new function `wrap_catalog_for_search(ctx, repository)` returning the (possibly wrapped) repository and the graph, so the later wiring edit is one call; module docstring updated.
- Owned files: `services/api/neurosphere_api/runtime/builders/search.py`, `services/api/tests/runtime_data/test_search_builder.py`, `services/api/tests/search_runtime/**`.
- Must NOT touch: `runtime/builders/data.py`, `builders/__init__.py` ordering, `search/**` logic.
- Depends on: none (the repository wrapper it returns is added in item 4; until then it returns the repository unchanged).
- Acceptance criteria: the concurrency criterion, ensure-index opt-in and no-request-when-unsupported criteria; `Government` guard unchanged.
- Tests: `services/api/tests/search_runtime/test_scope_locks.py` (new), `services/api/tests/search_runtime/test_ensure_index.py` (new), `services/api/tests/runtime_data/test_search_builder.py`.
- Pattern references: `builders/search.py` `IndexedGraphQuery._sync`, `test_search_builder.py:160-200`.

### Item 4 - Write-through repository wrapper
- Deliverable: `neurosphere_core/search/write_hook.py` with `IndexingCatalogRepository(inner, indexer)` forwarding every `CatalogRepository` method and, after a successful `create_entity`, `update_entity` or `deprecate_entity`, calling `indexer.index_entities` (or `remove` for removal) for just that entity; sink errors are swallowed after logging the exception type so a search outage never fails a catalog write; `wrap_catalog_for_search` (item 3) applies it when a provider is configured and calls `SearchRuntime.invalidate()` after writes.
- Owned files: `packages/core/neurosphere_core/search/write_hook.py` (new), `packages/core/tests/search/**`, `services/api/neurosphere_api/runtime/builders/search.py`.
- Must NOT touch: `catalog/**`, `projections/**`.
- Depends on: items 2 and 3.
- Acceptance criteria: the write-through criterion; the wrapper still satisfies `CatalogRepository` (`isinstance` on the runtime-checkable protocol); no behavioural change when no provider is configured.
- Tests: `packages/core/tests/search/test_write_hook.py` (new), `services/api/tests/search_runtime/test_wrap_catalog.py` (new).
- Pattern references: `catalog/protocol.py:198-245`, `indexer.py:150-175`.

### Item 5 - API composition wiring  [serial-after: PRP-44]
- Deliverable: in `runtime/builders/data.py` `_catalog`, replace the separate `build_catalog_graph` call with `wrap_catalog_for_search` so `app.state.catalog_repository` is the wrapped repository (one-line edit; the `_NoSearch` fallback stays for the unset provider).
- Owned files: `services/api/neurosphere_api/runtime/builders/data.py` (the `_catalog` function only), `services/api/tests/runtime_data/test_data_builder.py`.
- Must NOT touch: other builder bodies.
- Depends on: item 4 and PRP-44 merged and this branch rebased.
- Acceptance criteria: an API catalog write is searchable without waiting for the refresh interval (builder test); with no provider the repository is not wrapped.
- Tests: `services/api/tests/runtime_data/test_data_builder.py`, `services/api/tests/runtime_data/test_search_builder.py`.
- Pattern references: `data.py:206-225`.

### Item 6 - Worker composition wiring  [serial-after: PRP-55]
- Deliverable: where `factories.py` builds the worker catalog repository, wrap it with `IndexingCatalogRepository` over an Azure `IndexSink` built from the same `NS_SEARCH_*` settings, only when provider is `azure`, the capability row is supported and a service is configured; otherwise no wrapper.
- Owned files: `services/workers/neurosphere_workers/runtime/factories.py` (the catalog repository construction only), `services/workers/tests/runtime_factories/**` if present or a new `services/workers/tests/search_wiring/`.
- Must NOT touch: other builder bodies, `projections/**`.
- Depends on: item 4 and PRP-55 merged and this branch rebased.
- Acceptance criteria: with `NS_SEARCH_PROVIDER=azure` and a fake backend a projection write produces an index upsert; with `fixture` or unset nothing is wrapped.
- Tests: `services/workers/tests/search_wiring/test_worker_wrap.py` (new).
- Pattern references: `factories.py` credential pattern `lifetime.register(DefaultAzureCredential)`, `builders/search.py` `_azure_backend`.

### Item 7 - Integration and close-out
- Deliverable: regenerate Tier 3 files if any route or model changed (none expected), update the runbook `docs/runbooks/runtime-composition.md` search section with `NS_SEARCH_ENSURE_INDEX`, the key encoding, the freshness bounds and the live-gate note (the runbook edit is allowed here as a documentation-only close-out change; list it in the completion note), completion note with "Env vars for the operator", `python scripts/prp_status.py --write`, CHANGELOG entry, follow-up issue for hiding deprecated entities if the owner wants it.
- Owned files: this PRP file; `docs/runbooks/runtime-composition.md` (search section only).
- Must NOT touch: items 1-6 source except an integration defect (record it).
- Depends on: items 1-4 (5 and 6 when their predecessors have merged; otherwise recorded OPEN).
- Acceptance criteria: completion note filled; OPEN items named.

## Validation gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/search services/api/tests/search_runtime services/api/tests/runtime_data services/api/tests/runtime_routes services/workers/tests/projections services/api/tests/test_openapi_drift.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
python scripts/validate_planning.py
```

Items 5 and 6 add `services/workers/tests/search_wiring` to the pytest line when they run.

## Migration and rollback
- Migration: an existing Azure index built with the old schema (key `id` = canonical id, no `entity_id`, maybe no `text`) is not compatible. The index must be recreated with `catalog_index_definition()` (operator script or `NS_SEARCH_ENSURE_INDEX=true` on an empty index) and re-populated by the indexer; nothing hosted exists yet that uses the old schema (live Azure search was never run). Fixture-provider deployments need no migration.
- Rollback: revert the PRP branch; set `NS_SEARCH_PROVIDER=fixture` to stop using Azure at runtime. Items 5 and 6 are single-call edits and revert independently.

## Live and open gates
- Live Azure AI Search (index create, upsert, delete, query with the new key and `entity_id` filter) needs `NS_LIVE_APPROVED=1` and an operator-approved environment; reported OPEN and handed to PRP-64 with PRP-58's hosted wiring. Offline fake-backend tests are the only evidence here.
- No paid call is made.

## NOT building
- Bicep or Helm changes for search (PRP-52, PRP-58); semantic or vector search; a search admin page (PRP-45).
- Changes to authorization filtering or to what a scope may enumerate.
- Cross-process push invalidation for the fixture provider (bounded by the refresh interval).
- Hiding deprecated entities from search (follow-up if wanted).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (row 5 is a labelled assumption)

## Execution state

| Item | Status | Branch/worktree | Notes |
|------|--------|-----------------|-------|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | serial-after PRP-44 |
| 6 | todo | | serial-after PRP-55 |
| 7 | todo | | |

## Completion note (filled at ship)
- Date, PR, merge commit:
- Deviations from the blueprint and why:
- Descoped items:
- OPEN gates (live Azure AI Search, items 5 and 6 if their predecessors had not merged):
- Env vars for the operator (`NS_SEARCH_ENSURE_INDEX`):
- Follow-up issue numbers:
- Product check (can an operator stand up the Azure index and see a new entity searchable without editing files?):
