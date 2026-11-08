---
name: PRP-10-catalog-and-relationship-governance
status: shipped
priority: P1
order: 9
started: 2026-11-07
shipped: 2026-11-08
pr: 192
branch: prp-10-audit-gap-closure
review: required
created: 2026-10-08
model: sonnet
phase: 1
ns: NS-02
depends_on: [PRP-05-api-worker-runtime-and-self-observability, PRP-06-identity-authz-and-audit]
wave: W5
absorbs: P1.2
gates: G03 live gate
orchestrator_model: sonnet
implementer_model: sonnet
---

# PRP-10: Catalog and relationship governance

## Goal
Ship the operational catalog on Cosmos DB NoSQL: a versioned `CatalogRepository` with ETag concurrency and canonical IDs, a bounded `GraphQuery`, an evidence projection worker that creates inferred edges from traces, steward curation with locks, the catalog API, and an authorized AI Search implementation. It is for domain stewards and analysts who need explainable, scope-filtered lineage. It lands in W5 because it needs the API runtime (PRP-05) and authorization (PRP-06). **This PRP cannot merge until the G03 live benchmark has run with operator approval (decision D9).**

> Versioned entities: Person/pseudonymous principal, Agent, AgentVersion, ModelDeployment, GroundingSource/DataAsset, Tool, Service, Domain, Owner, Policy, Recommendation and RunReference. Stable cloud/customer/source-qualified IDs resolve collisions and agent aliases.

> Relations include INVOKES, DELEGATES_TO, USES_MODEL, READS, WRITES, GROUNDED_BY, OWNED_BY, DEPENDS_ON and SUPERSEDES. Every edge has provenance, evidence IDs, confidence, first/last observation, validity interval and asserted/inferred/curated status. Store raw telemetry outside the graph.

> Infer relationships using traces, observed access and optional embeddings. Domain-authorized stewards can accept, reject, override and lock edges with reason and expiry. Preserve observed facts separately from declared and curated relationships; an override cannot erase security evidence. Re-inference must respect locks; conflicts route to review.

> Search/CRUD/import/export, optimistic concurrency, lifecycle deprecation, ownership recertification, stale-agent reconciliation and scope-filtered lineage. Purview and Unity Catalog are optional connector integrations; do not assume universal write-back, labeling or OpenLineage support.

## Acceptance criteria
- [ ] Item 1: Given two concurrent edits with the same ETag, When both write, Then the second returns `stale_version`; an alias resolves to exactly one canonical ID of the form `cloud:customer:source:type:id`.
- [ ] Item 2: Traversal beyond the depth or fan-out budget returns a partial result with a `truncated` flag, never an unbounded walk.
- [ ] Item 3: A sandbox trace produces INVOKES and USES_MODEL edges, each carrying provenance, evidence IDs, confidence, observation window and `inferred` status.
- [ ] Item 4: A locked edge is unchanged after re-inference while the new observation is retained; a conflicting inference lands in the review queue; an override cannot delete security evidence.
- [ ] Item 5: Export is filtered by the caller's `IdentityScope`; p95 <= 500 ms on indexed scoped queries over the sandbox dataset (planning target, measured).
- [ ] Item 6: A document from another domain is never returned by `AuthorizedSearch` for a scoped caller; the fixture fallback behaves identically for the same query and scope.
- [ ] Item 7: `docs/evidence/G03/live-<date>.md` exists with measured p95 for the three workloads on a real Cosmos account, produced by `scripts/gates/g03_live.py` under `NS_LIVE_APPROVED=1`.
- [ ] PRP exit: items 1-6 green under `verify-gates -Mode full`; item 7 evidence filed. Without item 7 the PRP does not merge.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required; opus | sonnet, review required (D6) |
| 2 | Merge precondition | merge on emulator evidence; require live G03 | Live G03 run is required before merge (D9). Emulator evidence from PRP-02 exits Phase 0 only as "bounded feasibility". Items 1-6 may be implemented and reviewed before the live run, but the PR is not merged until item 7 evidence is in the PR |
| 3 | Who runs the live benchmark | agent; operator | Operator approves and sets `NS_LIVE_APPROVED=1`; the implementer prepares the command and files the result. It targets the Commercial subscription (D7), may incur cost, and is never run by CI |
| 4 | Graph store | Neo4j; Cosmos NoSQL adjacency; Gremlin | Cosmos NoSQL documents and adjacency behind `CatalogRepository`/`GraphQuery` (PRP.md section 2; ADR-0005 from PRP-02). Not an arbitrary graph query engine. No Apache AGE assumption |
| 5 | Partition key | single id; domain only; hierarchical | Domain plus shard (hierarchical partition keys, up to 3 levels, Python SDK 4.6 or later, new containers only); the live benchmark confirms or revises the shard count |
| 6 | Projection source | emulator change feed; outbox | Outbox consumer with per-sink checkpoints (PRP-07 writes the outbox). Not the "all versions and deletes" change-feed mode (preview API, constraints) |
| 7 | Where raw telemetry lives | graph; outside | Outside the graph. Edges hold evidence IDs that point to ledger or archive records |
| 8 | Lock semantics | block inference; affect presented lineage only | Locks affect presented lineage, not observations. Inference still records observations; the presented edge follows the lock until expiry. Every lock needs reason and expiry |
| 9 | Search backend | AI Search only; AI Search plus fixture | AI Search implementation of `AuthorizedSearch` with a server-side scope filter, plus the PRP-03 fixture as fallback. Vector availability in Government is unverified, so no Government claim |
| 10 | Optional integrations | build Purview/Unity now; defer | Deferred. Purview and Unity Catalog are optional connectors; no write-back assumed |
| 11 | Emulator limits | rely on emulator for perf | Emulator has no RU accounting and no range/composite/spatial indexes; p95 numbers from it are bounded feasibility only (G12). Only the live run supports performance statements |
| 12 | Dependency on PRP-06 | wait; protocol | Depends on PRP-06 for scope derivation and policy middleware; routes use `require(permission)` from `neurosphere_api.authz` |
| 13 | G03 harness provisioning under Entra (delta, 2026-10-17) | fix via az CLI; fix via mgmt SDK; stop | The PRP-02 harness created databases/containers through the data-plane SDK, which Entra tokens cannot do (403 substatus 5300, learn.microsoft.com/azure/cosmos-db/troubleshoot-forbidden). Operator signed off on a delta: item 7 may edit `scripts/gates/g03_live.py` and `tests/load/graph_benchmark/` so the live path provisions the fresh database and containers through the control plane (`az cosmosdb sql ...`, no shell, no keys) and benchmarks over the data plane with Entra; the emulator path is unchanged. Target: throwaway serverless account in Limitlessdata - DMLZ, new RG deleted after the run |

## Context manifest

### Files that matter
- `PRP.md` - sections 1-3 (Cosmos NoSQL adjacency, outbox, canonical IDs, locks).
- `docs/PRD.md` - NS-02 text.
- `docs/ARCHITECTURE.md` - catalog and projection diagrams.
- `docs/RESEARCH-AND-GATES.md` - G03 and G12 rows; Cosmos hierarchical partition keys and change-feed modes (observed 2026-04-27 and 2026-06-17 per the register); Gremlin limits.
- `docs/adr/0002-stack-pins.md` - azure-cosmos 4.17, azure-search-documents 12.0.
- `docs/DECISIONS-LOG.md` - D6, D7, D8, D9, D11.
- `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.env.example`, `.claude/hooks/config.ps1`, `scripts/validate_planning.py`.
- Created by PRP-01: `packages/contracts/schemas/catalog/` (entities, relations, ID grammar), `.../scope/`, `.../query/`.
- Created by PRP-02: `docs/adr/0005-catalog-store.md`, `tests/load/graph_benchmark/`, `docs/evidence/G03/`, `scripts/gates/g03_live.py`.
- Created by PRP-03: `packages/core/neurosphere_core/search/fixture/`, `sandbox/` generator.
- Created by PRP-05: `neurosphere_core.errors`, `.../scope/`, `.../paging/`, `.../clients/`, router registry.
- Created by PRP-06: `neurosphere_core.auth.scope`, `neurosphere_api.authz`, `neurosphere_core.audit`.
- Created by PRP-07: outbox collection and checkpoints under `services/workers/neurosphere_workers/projections/outbox/`.

### Patterns to match
- Pydantic v2 `extra="forbid"` models generated from `packages/contracts`; do not hand-edit generated files.
- Repository and graph as protocols in `neurosphere_core.catalog`; Cosmos implementations behind them; fixture in-memory implementations for unit tests.
- FastAPI router per module: `services/api/neurosphere_api/catalog/router.py`, `.../catalog/curation/router.py`.
- Every query takes `IdentityScope` and a structured, allowlisted filter object; no query text from callers or models.
- Tests beside packages; `pytest.mark.integration` (compose emulators), `pytest.mark.live` (real Cosmos); load tests under `tests/load/`.

### Conventions
- ruff line 100, py312, S rules on; pyright standard; conventional commits; owned-file discipline.
- Evidence under `docs/evidence/G03/`; `scripts/gates/g03_live.py` refuses without `NS_LIVE_APPROVED=1`.
- Forward slashes only in commands.

### Gotchas
- Event Hubs has no DLQ: quarantine is an explicit container + replay CLI; checkpoints advance only after durable accept or quarantine. Metadata geo-DR copies neither payloads nor RBAC.
- `IdentityScope` is derived server-side; caller- or model-supplied `domain_id`/`customer_id` is ignored. Same scope object on REST, search, cache keys, exports, WebSocket, copilot tools, MCP.
- No LLM-generated SQL/Cypher/KQL/JS. Charts are a Vega-Lite subset (no `expr`, signals, external `url` data) rendered with `vega-interpreter` in a sandboxed iframe.
- Government is gated, not banned: disabled-with-reason from the capability matrix; separate endpoints (`login.microsoftonline.us`, `*.documents.azure.us`, `*.servicebus.usgovcloudapi.net`, `*.search.azure.us`). Never route Government data to Commercial.
- Fail closed: policy store outage returns 503. Privileged roles are scoped; no bypass.
- One action executor for button/chat/REST/MCP; same intent hash; permission and target version rechecked at execution; read-only connectors are advisory; no catalog-only pretend swaps.
- Costs: null/unknown never 0; estimated vs invoiced always distinct; projections cite price version. Provider billing freshness is not sub-10s.
- Catalog: raw events outside the graph; locks affect presented lineage not observations; traversals budgeted; ETag mismatch returns `stale_version`. Outbox is the projection baseline, not emulator change feed.
- Emulators: Event Hubs emulator lacks Entra, so producer identity is enforced at the ingest edge; Cosmos vNext emulator has no RU accounting, no sprocs/triggers/UDF, no range/composite/spatial indexes, so G03 emulator evidence is "bounded feasibility" only.
- `scripts/gates/*` refuse without `NS_LIVE_APPROVED=1`; missing live evidence is an open gate, never a skipped green test. No paid model calls in CI.
- No FedRAMP/ATO/parity claims. Availability, GA and authorization are separate matrix columns.
- Secrets via vault references; dev issuer only when `NS_ENV=local`; never read `.env`. Pseudonymize people; prompt/response bodies off by default; redact before archive and before any external transmission (judges, connectors).
- Hidden navigation is not authorization; the API must deny.
- Versions: Python 3.12, Node 24, TypeScript 6.0.x (not 7), Helm 4, MkDocs Material 9.7 (EOL 2026-11-05, evaluate Zensical), sigma 4 + graphology (never @cosmograph, CC-BY-NC), MCP SDK 2.x (spec 2026-07-28). See docs/adr/0002-stack-pins.md.
- CI contains no `|| true`; `scripts/validate_planning.py` fails if it does. Python is `python`, not `python3`.
- PRP-specific: this PRP does not merge without G03 live evidence (D9). A green emulator suite is not a substitute and must not be reported as one.
- PRP-specific: stored procedures, triggers, UDFs and composite or spatial indexes do not exist in the Cosmos vNext emulator; do not design the repository around them (and the platform does not use sprocs).
- PRP-specific: hierarchical partition keys apply to new containers only; changing the key later is a migration (PRP-13 tooling), so pin the key design in an ADR note before writing data.
- PRP-specific: inferred edge confidence is a model output, not a fact; never surface it without provenance and evidence IDs. An edge missing either is rejected by schema.
- PRP-specific: an override may change the presented relationship but must not delete the evidence that contradicts it; security-relevant evidence is retained and visible to Auditors.
- PRP-specific: AI Search semantic ranker and agentic retrieval are in US Gov Arizona and Virginia, not Texas; vector search availability in Government is unverified. Gate any Government option through the matrix.

### External references
- Cosmos DB hierarchical partition keys: https://learn.microsoft.com/azure/cosmos-db/hierarchical-partition-keys (observed 2026-04-27).
- Cosmos DB change feed modes: https://learn.microsoft.com/azure/cosmos-db/change-feed-modes (observed 2026-06-17).
- Cosmos DB vNext Linux emulator limits: https://learn.microsoft.com/azure/cosmos-db/emulator-linux (GA June 2026).
- Gremlin limits and partitioning (why NoSQL adjacency): https://learn.microsoft.com/azure/cosmos-db/gremlin/limits and https://learn.microsoft.com/azure/cosmos-db/gremlin/partitioning (retrieved 2026-10-06).
- Azure AI Search regional support: https://learn.microsoft.com/azure/search/search-region-support (observed 2026-10-01).
- azure-cosmos 4.17 and azure-search-documents 12.0: docs/adr/0002-stack-pins.md (observed 2026-10-08).

## Implementation blueprint

### Item 1 - catalog-repository  [P]
- Deliverable: `CatalogRepository` on Cosmos with versioned documents, ETag optimistic concurrency, domain/shard partition key, canonical ID resolver and alias table, plus an in-memory fixture implementation.
- Owned files (may edit): `packages/core/neurosphere_core/catalog/repo/`.
- Must NOT touch: `packages/core/neurosphere_core/catalog/graph/`, `services/api/neurosphere_api/catalog/`, `services/workers/neurosphere_workers/projections/`, `packages/contracts/`, root `pyproject.toml`, `docker-compose.yml`.
- Depends on: none.
- Acceptance criteria:
  - Concurrent edit with a stale ETag returns `stale_version` (integration test on the Cosmos emulator).
  - Alias lookup resolves to one canonical ID; ID grammar rejects malformed IDs using the PRP-01 corpus.
  - Every query requires an `IdentityScope`; a call without one fails at type level and at runtime.
- Pattern references: Pydantic forbid-extra; clients factory; errors taxonomy.
- Tests to write: `packages/core/tests/catalog/test_repo.py`, `tests/integration/catalog/test_repo_cosmos.py`.

### Item 2 - graph-query
- Deliverable: `GraphQuery` with get, search, neighbors and bounded impact paths with depth and fan-out budgets.
- Owned files (may edit): `packages/core/neurosphere_core/catalog/graph/`.
- Must NOT touch: `packages/core/neurosphere_core/catalog/repo/`, `services/api/neurosphere_api/catalog/`, `packages/core/neurosphere_core/search/`.
- Depends on: Item 1.
- Acceptance criteria:
  - Traversal beyond budget returns partial plus `truncated=true`.
  - Presented lineage applies locks and curated overrides; raw observations remain queryable by Auditor scope only.
  - Results exclude any node outside the caller's scope, including as path intermediates.
- Pattern references: structured allowlisted query models from PRP-01.
- Tests to write: `packages/core/tests/catalog/test_graph_budgets.py`, `packages/core/tests/catalog/test_graph_scope.py`.

### Item 3 - evidence-projection-worker
- Deliverable: outbox consumer that creates inferred edges from trace observations with evidence IDs, honoring per-sink checkpoints.
- Owned files (may edit): `services/workers/neurosphere_workers/projections/catalog/`.
- Must NOT touch: `services/workers/neurosphere_workers/projections/outbox/` (PRP-07), `packages/core/neurosphere_core/catalog/repo/`, `services/workers/neurosphere_workers/runtime/`.
- Depends on: Item 1.
- Acceptance criteria:
  - A sandbox trace with delegation produces INVOKES and USES_MODEL edges with provenance and evidence IDs.
  - Replaying the same outbox batch produces no duplicate edges (idempotency test).
  - Worker checkpoint advances only after durable write.
- Pattern references: worker runtime base from PRP-05; checkpoint interface.
- Tests to write: `services/workers/tests/projections/test_catalog_projection.py`.

### Item 4 - curation-and-locks  [P]
- Deliverable: curation routes and domain logic for accept, reject, override and lock with reason and expiry; re-inference respects locks; conflicts go to a review queue interface (consumed by PRP-17).
- Owned files (may edit): `services/api/neurosphere_api/catalog/curation/`.
- Must NOT touch: `services/api/neurosphere_api/catalog/` outside `curation/` (item 5), `packages/core/neurosphere_core/catalog/`, `services/workers/`.
- Depends on: none.
- Acceptance criteria:
  - Locked edge unchanged after re-inference; the new observation is stored.
  - Lock without reason or expiry is rejected with `invalid_schema`; expired lock stops applying.
  - Override cannot remove security evidence (test); every curation action writes an audit record.
- Pattern references: `require(permission)` from `neurosphere_api.authz`; ETag `stale_version`.
- Tests to write: `services/api/tests/catalog/test_curation.py`.

### Item 5 - catalog-api
- Deliverable: CRUD, search, import and export routes; lifecycle deprecation; ownership recertification; stale-agent reconcile.
- Owned files (may edit): `services/api/neurosphere_api/catalog/` (excluding `curation/`).
- Must NOT touch: `services/api/neurosphere_api/catalog/curation/`, `packages/core/neurosphere_core/catalog/`, `packages/core/neurosphere_core/search/`.
- Depends on: Items 1, 2.
- Acceptance criteria:
  - Export filtered by scope; a cross-domain entity never appears (negative test).
  - p95 <= 500 ms on indexed scoped queries over the sandbox dataset; the measurement is recorded as a result of the test, not asserted from the target.
  - Missing ETag on update returns `invalid_schema`; mismatch returns `stale_version`.
- Pattern references: router per module; pagination models from PRP-05.
- Tests to write: `services/api/tests/catalog/test_catalog_api.py`, `tests/load/catalog_latency/test_catalog_p95.py`.

### Item 6 - authorized-search  [P]
- Deliverable: Azure AI Search implementation of `AuthorizedSearch` with a server-side scope filter and fallback to the PRP-03 fixture.
- Owned files (may edit): `packages/core/neurosphere_core/search/azure/`.
- Must NOT touch: `packages/core/neurosphere_core/search/fixture/` (PRP-03), `packages/core/neurosphere_core/catalog/`.
- Depends on: none.
- Acceptance criteria:
  - A cross-domain document is never returned (test with filter-injection attempts, including a caller-supplied `domain_id`).
  - Same query and scope returns identical IDs from fixture and Azure implementations on the sandbox set within the documented ranking tolerance.
  - Search cache keys include a hash of the scope.
- Pattern references: `AuthorizedSearch` protocol; `search/fixture/` behavior.
- Tests to write: `packages/core/tests/search/test_azure_search_scope.py`.

### Item 7 - g03-live-benchmark-gate
- Deliverable: run `scripts/gates/g03_live.py` (created by PRP-02) against the Commercial subscription with operator approval and file the evidence; update the G03 row.
- Owned files (may edit): `docs/evidence/G03/live-<date>.md`, `docs/RESEARCH-AND-GATES.md` (G03 row only).
- Must NOT touch: `scripts/gates/g03_live.py`, `tests/load/graph_benchmark/`, any other row of `docs/RESEARCH-AND-GATES.md`.
- Depends on: Items 1, 2.
- Acceptance criteria:
  - Evidence file contains measured p95 for the three workloads (skew, degree, cross-domain) on a real account, the date, the account SKU class and request-unit settings used.
  - Evidence lists deltas from the emulator run (G12).
  - Operator approval is recorded (who, when) in the evidence file; no credential values appear.
- Pattern references: PRP-02 evidence format.
- Tests to write: none (evidence artifact); `tests/unit/gates/test_g03_live_refuses.py` already owned by PRP-02.

### Round 2: audit gap closure (items 8-13, added 2026-11-07)
Reopened by the 2026-11-04 audit (section at the end). Rechecked 2026-11-07 against main 2b97e06: catalog search is composed by PRP-35 item 3 (`NS_SEARCH_PROVIDER`, compose sets `fixture`) but no hosted config sets it; compose seeds the sandbox (PRP-35 item 2) but a real stack's catalog stays empty because the projection worker only calls `put_edge` and `put_edge` does not require endpoint entities, so trace edges dangle and scope filtering hides them; #55 is mostly closed by PRP-29/35 (`ArchiveTraceEventSource`, `EnvClaimsSource`, composition root); the #53 "denied `require()` unaudited" bullet is closed by PRP-06 D1-D5 (`authz/dependencies.py` denied-attempt audit). User decisions 2026-11-07: all items 8-13; live runs stay OPEN (emulator only); item 12 is the API-level compose test only.

### Item 8 - trace-entity-discovery  [P] (review: required)
- Deliverable: the catalog projection creates, if absent, the Agent / AgentVersion / ModelDeployment / Tool entities a trace references (canonical IDs from `mapping.py`, domain from the event, inside the worker's derived scope), before writing the edges that point at them; never updates or overwrites an existing (declared/curated) entity; idempotent on replay. Out-of-scope candidates are recorded to a quarantine record with a `skipped_out_of_scope` counter instead of only being dropped (#55); the per-customer outbox assumption is documented in the module docstring (#55).
- Owned files (may edit): `services/workers/neurosphere_workers/projections/catalog/`, `services/workers/tests/projections/`.
- Must NOT touch: `packages/core/neurosphere_core/catalog/` (items 9, 10), `packages/contracts/`, `services/workers/neurosphere_workers/runtime/` (report if wiring is needed).
- Depends on: none.
- Acceptance criteria: a sandbox trace into an empty repository yields the agent and model-deployment entities and the INVOKES/USES_MODEL edges between them, all visible through `RepositoryGraphQuery.neighbors` for an in-scope caller; a replay creates no duplicates and no update to a pre-existing entity; an out-of-scope candidate produces a quarantine record and counter, and the checkpoint still advances only after durable write or quarantine.
- Tests to write: `services/workers/tests/projections/test_catalog_entity_discovery.py`.

### Item 9 - lock-observation-review-semantics  [P] (#54)
- Deliverable: presented lineage refreshes from the newest observation after a lock expires; `ReviewItem` id includes a generation/evidence component so a later conflict after resolution is enqueued; an expired lock's `set_confidence` does not carry into a replacement lock; observation id includes confidence; merging an older observation after a newer one does not regress confidence or `last_observed` (ordered by observation time, not arrival); a protocol + memory + Cosmos method lists edges by domain.
- Owned files (may edit): `packages/core/neurosphere_core/catalog/rules.py`, `review_queue.py`, `review_queue_cosmos.py`, `protocol.py`, `repo/` (domain edge listing and observation id only), `packages/core/tests/catalog/`.
- Must NOT touch: `packages/core/neurosphere_core/catalog/graph/`, `services/`, `packages/contracts/`.
- Depends on: none.
- Acceptance criteria: one regression test per #54 bullet (stale-agent paging moves to item 10).
- Tests to write: `packages/core/tests/catalog/test_semantics_round2.py`.

### Item 10 - authz-and-existence-hardening  (review: required; #53 + core/api parts of #56)
- Deliverable: curation `EdgeOverride.actor` / `lock.actor` stamped server-side from the scope principal (mismatch rejected); duplicate-ID and alias-clash errors identical whether the ID is taken in the caller's domain or another; `put_override` uniqueness checked unscoped; fan-out truncation computed after the endpoint scope filter; raw-view root probe uses an explicit repo method, not the unknown-edge fallback; create checks scope (403) before contract validation (422); stale-agent reconcile pages all edges (or relies on enforced newest-first ordering); `RateLimitedError` uses the response retry-after; time budget checked before root/raw/override fetches; stale-agent plan digest keyed (HMAC with the existing pseudonym/plan key source); `services/api/tests/{audit,catalog}` collect when run alone; Person-needs-domain stated in contract docs.
- Owned files (may edit): `packages/core/neurosphere_core/catalog/repo/`, `packages/core/neurosphere_core/catalog/graph/`, `services/api/neurosphere_api/catalog/` (incl. `curation/`), `packages/core/tests/catalog/`, `services/api/tests/catalog/`, `services/api/tests/audit/` (collection fix only).
- Must NOT touch: `packages/core/neurosphere_core/catalog/rules.py` / review queue (item 9), `services/api/neurosphere_api/routers.py`, `openapi.json` (orchestrator regenerates), `packages/contracts/`.
- Depends on: Item 9 (shares `repo/`).
- Acceptance criteria: one negative/regression test per bullet; cross-domain duplicate-ID response byte-identical to the in-domain one apart from the requested ID.
- Tests to write: `packages/core/tests/catalog/test_hardening_round2.py`, `services/api/tests/catalog/test_catalog_api_hardening.py`.

### Item 11 - search-hardening-and-hosted-wiring  [P] (search parts of #56, #55 Gov guard)
- Deliverable: `search/azure/filters.py` cache key wraps `scope_cache_key`; test that `scope_hash_of(scope) == scope.scope_hash` for a derived scope; a TimeoutError raised inside the Azure SDK is not reported as `partial_reason="timeout_ms"`; in a Government cloud with Azure Search disabled/unconfigured the search builder reports degraded (readiness reason) instead of silently answering from an empty fixture; hosted config sets `NS_SEARCH_PROVIDER` (and `NS_SEARCH_SERVICE`/`NS_SEARCH_REGION` when a search service is deployed) in `infra/demo/main.bicep`, `infra/appservice/main.bicep` where the API env is defined, and the Helm chart.
- Owned files (may edit): `packages/core/neurosphere_core/search/azure/`, `packages/core/tests/search/`, `services/api/neurosphere_api/runtime/builders/search.py`, its tests, `infra/demo/main.bicep`, `infra/appservice/main.bicep`, `infra/helm/templates/deployment.yaml`, `infra/helm/values*.yaml`, and their existing infra tests.
- Must NOT touch: `packages/core/neurosphere_core/search/fixture/`, `services/api/neurosphere_api/runtime/builders/data.py`, `packages/core/neurosphere_core/catalog/`.
- Depends on: none.
- Acceptance criteria: one test per bullet; `az bicep build` (or the repo's bicep test) clean on edited templates; `helm template` renders the env vars.

### Item 12 - catalog-compose-verification
- Deliverable: a compose-backed integration test (`pytest.mark.integration`) that posts a sandbox trace through the ingest edge, lets the catalog projection run, and asserts over HTTP that the discovered entities, the edges and a search hit appear for an in-scope caller and not for an out-of-scope one. Browser real-stack specs are out of scope (re-plan step 4 PRP).
- Owned files (may edit): `tests/integration/catalog/`.
- Must NOT touch: product code; report gaps instead.
- Depends on: Items 8, 11.
- Acceptance criteria: passes locally against `docker compose up -d --wait` (emulators, 127.0.0.1); output recorded as evidence; never runs in CI (integration marker).

### Item 13 - export-p95-on-cosmos
- Deliverable: `tests/load/catalog_latency` gains a Cosmos emulator backend (labelled bounded feasibility, G12) and a live mode that refuses without `NS_LIVE_APPROVED=1`; results written to `temp/` and summarised in `docs/evidence/G03/catalog-export-emulator-<date>.md`. The live run stays OPEN this round.
- Owned files (may edit): `tests/load/catalog_latency/`, `docs/evidence/G03/catalog-export-emulator-*.md`.
- Must NOT touch: `scripts/gates/g03_live.py`, `tests/load/graph_benchmark/`, product code.
- Depends on: Item 10.
- Acceptance criteria: emulator run produces p50/p95 for scoped export/list/get with the "not a live claim" label; live mode refusal test; no latency assertion.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
docker compose up -d --wait
python -m pytest -m integration tests/integration/catalog
python -m pytest packages/core/tests/catalog packages/core/tests/search services/api/tests/catalog services/workers/tests/projections
python -m pytest tests/load/catalog_latency
NS_LIVE_APPROVED=1 python scripts/gates/g03_live.py    # operator-approved, requires NS_LIVE_APPROVED=1; must run before merge (D9)
```

## Live and open gates
- G03 (graph partition/traversal benchmark): item 7 supplies the live Commercial run. Merge is blocked until `docs/evidence/G03/live-<date>.md` exists. After it lands, G03 is NARROWED for Commercial; Government Cosmos behavior remains unverified.
- G12 (emulator parity): record deltas between emulator and live p95, index behavior and RU accounting.
- G01 is touched only through the Search regional notes above; no evidence closes it here.
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Purview or Unity Catalog connectors; OpenLineage write-back.
- Neo4j adapter; any Gremlin or Apache AGE dependency.
- The review queue UI and HITL workflow (PRP-17); this PRP only emits conflicts to a queue interface.
- Map rendering and viewport API (PRP-18); recommendations (PRP-15).
- Embedding-based relationship inference (optional in NS-02; only trace-based inference is in scope).
- Schema or ID changes to PRP-01 contracts; request those through PRP-01.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Execution state

PR #52 (CI green 2026-10-17); item 7 live G03 evidence filed 2026-10-17, so the D9 merge hold is lifted; follow-ups #53-#56. Plan approved 2026-10-17. Item 0 was added at plan approval to close a blueprint gap: items 2, 3 and 4 share the catalog protocols, the lock/override rules and the review-queue interface, and router registration lives in a shared file no item owned. Waves: 0 → (1, 4, 6) → (2, 3) → 5. Item 7 deferred by the operator; the PR is held until its evidence lands (D9).

| Item | Status | Branch | Model | Evidence | Updated |
|------|--------|--------|-------|----------|---------|
| 0 | merged | worktree-agent-afa6790ef3378ec5e | sonnet | 1357ad9; ruff/format/pyright clean; 46 passed (re-run on branch); Snyk Code 0; review APPROVE (5 non-blocking: post-lock-expiry stale confidence/validity, resolved ReviewItem id swallows later conflicts, expired lock set_confidence carries into new lock, observation id ignores confidence, no domain-level edge list); merge 0b38c7d, catalog+search 116 passed + pyright clean post-merge | 2026-10-17 |
| 1 | merged | worktree-agent-a1f3031a9fb234dbc | sonnet | 249f381; ruff/format/pyright clean; unit 75 passed, integration (Cosmos emulator, bounded feasibility only) 23 passed (re-run on branch); Snyk Code 0; review APPROVE (non-blocking: cross-domain duplicate-ID existence signal (unify error type/message), put_override id uniqueness only in-scope, check-then-insert race, fixed RateLimited retry-after); merge d6fd3f9; post-merge collision core/api tests/catalog packages fixed by orchestrator; full default suite 4271 passed | 2026-10-17 |
| 2 | merged | worktree-agent-a424258055dc3415c | sonnet | d6c3403; ruff/format/pyright clean; core 828 passed (re-run on branch); Snyk Code 0; review CHANGES REQUIRED (1 blocker: visited_nodes/visited_edges count out-of-scope nodes/edges, query.py:206-207,301); rework 4c30a74: counts over in-scope presented results + regression test; 829 passed (re-run); Haiku confirm CONFIRMED; non-blocking: fan-out overflow counts hidden edges before scope filter, raw-view root probe relies on engine unknown-edge fallback, time budget not checked before root/override fetch; merge 0aef02e, core+api 1184 passed post-merge | 2026-10-17 |
| 3 | merged | worktree-agent-ac3ff2a3afce222c6 | sonnet | f4cf20e; ruff/format/pyright clean; workers 178 passed (re-run on branch); Snyk Code 0. Gaps reported: no trace-event readback by doc_id exists (TraceEventSource protocol + in-memory only), worker ClaimsSource (managed identity) not wired; review APPROVE (non-blocking: out-of-scope candidates dropped with no quarantine/alert, foreign-customer entry wedges sink (per-customer outbox assumption undocumented), replay arrival-order confidence regression); merge 066ff14, workers+core 1007 passed + pyright clean post-merge | 2026-10-17 |
| 4 | merged | worktree-agent-ac756305fd619d259 | sonnet | 0e272ba; ruff/format/pyright clean; catalog+authz 193 passed (re-run on branch); Snyk Code 0 (run by orchestrator); review APPROVE (non-blocking: caller-supplied EdgeOverride.actor/lock.actor not stamped from scope principal, require() 403s unaudited (repo-wide), no-op inference unaudited by design); merge 16e3d3d; orchestrator wired /catalog/curation in routers.py + regenerated openapi.json; services/api 355 passed + pyright/ruff clean post-merge | 2026-10-17 |
| 5 | merged | worktree-agent-a50db6271c68287de | sonnet | ca03b8e; ruff/format/pyright clean; services/api 390 passed, load 1 passed (re-run on branch); Snyk Code 0 (run by orchestrator); p95 in-memory sandbox (200 agents, 8 domains; bounded feasibility, not live): get 0.31 ms, list 0.93, search 2.07, neighbors d3 120.9, impact d3 16.0; review APPROVE (non-blocking: stale-agent _last_observed reads first edge page only, unkeyed plan digest, 422-before-403 ordering on create); merge d3c0b51; orchestrator wired /catalog in routers.py + regenerated openapi.json; full default suite 4338 passed | 2026-10-17 |
| 6 | merged | worktree-agent-a187807cc8b320819 | sonnet | 844b3ac; ruff/format/pyright clean; 71 passed (re-run on branch); Snyk Code 0; review APPROVE (4 non-blocking: Gov silent-empty fixture fallback needs composition-root guard, cache_key not on scope_cache_key layout, scope_hash agreement test, SDK TimeoutError read as partial); merge e62bcfd, search 71 passed + pyright clean post-merge | 2026-10-17 |
| 7 | merged | worktree-agent-a4dbe5c8fb2d6deca | sonnet | harness delta 457904d (control-plane provisioning via az; offline 80 passed, emulator smoke 1 passed, Snyk 0; review APPROVE, merge e47672a); evidence writer fix (live disclaimer + Live account section; 82 passed, Snyk 0, Haiku APPROVE); live run 2026-10-17 operator-approved (Frank Garofalo), serverless Entra-only account in Limitlessdata - DMLZ centralus via private endpoint + P2S VPN: all 9 cells correct, mean 39-58 RU/traversal, p95 1.58-2.13 s incl. WAN RTT; evidence docs/evidence/G03/live-2026-10-17.{md,json}; RG deleted, DNS records gone. First attempt blocked by landing-zone policy (public access forced off) | 2026-10-17 |
| 8 | merged | worktree-agent-ac283b3eafd2c1099 | sonnet | c083aaf; re-run on branch: ruff/format/pyright clean, workers projections + core catalog 125 passed; Snyk Code 0; review APPROVE (non-blocking: in-memory quarantine default, durable sink NOT wired in runtime; same-ID entity in an out-of-scope domain stalls the sink checkpoint (fail-closed, no leak); silent None for unknown type; no test for a non-InvalidSchema create failure); merge 1a84a7e, post-merge 363 passed. Deviations: no AgentVersion (no version field), entities draft + attributes.discovered_from=telemetry, provider/platform unknown | 2026-11-08 |
| 9 | merged | worktree-agent-a513a04adbbc7e68f | sonnet | f3f3f68; re-run on branch: ruff/format/pyright clean, 365 passed; Snyk Code 0; merge b4e3d0c, post-merge (8+9) 370 passed. Deviations: present_edge latest_observation had no caller (handed to item 10); observation and review-item ids change for stored data (still readable; a replayed old observation records once more; no migration); no Cosmos-emulator test for list_edges_by_domain or the open-duplicate query; open-duplicate check is check-then-insert | 2026-11-08 |
| 10 | merged | worktree-agent-ae4e2412e4d7b760d | sonnet | 915e4b7; re-run on branch: ruff/format/pyright clean; api catalog alone 83 passed, api audit alone 35 passed, combined + load 427 passed; Snyk Code 0; review APPROVE (non-blocking: fan-out page-not-exhausted reports max_edges for nodes with >500 total edges incl. hidden ones (coarse signal); graph imports auditor_domains from repo engine, not the protocol; keyed plan digest still owed); merge d5cd121; post-merge (8-12) 577 passed, pyright clean, openapi.json + docs reference regenerated with no drift. Behaviour changes: create with missing/out-of-scope domain 403 (was 422); lock actor mismatch 403 actor_mismatch; cross-domain alias-ID clash now refused with the same message as in-domain. Deviation: plan digest stays unkeyed (no reachable key source) | 2026-11-08 |
| 11 | merged | worktree-agent-a6e95b17c56f1dfab | sonnet | 47c287e; re-run on branch: ruff/format/pyright clean, search + runtime_data + infra 189 passed; az bicep build demo+appservice exit 0 and helm template renders NS_SEARCH_PROVIDER (agent-run); Snyk Code 0; merge 57c9be1, post-merge (8+9+11) 559 passed. Deviations: cache_key mirrors the scope_cache_key layout (core cannot import api; parity test pins it); Government provider=azure misconfig fails the whole catalog component on /readyz; Bicep/Helm default fixture (demo deploys no AI Search) | 2026-11-08 |
| 12 | merged | worktree-agent-a1c6d8bc9a9497a65 | sonnet | b5e6c8b; tests/integration/real_stack/test_catalog_discovery.py (integration marker, compose emulators, API + ingestion/projections roles in-process like test_seed.py, real ingest edge + Event Hubs); re-run on branch by orchestrator: ruff clean, 1 passed (entities 9.6 s, edges +0.2 s, search immediate with NS_SEARCH_REFRESH_SECONDS=5), tests/integration/catalog 23 passed; merge c55d235. Asserts 2 agents, 2 tools, 2 model deployments, 5 inferred edges with event:/trace: evidence, search hit, out-of-scope caller sees nothing. Deviations: out-of-scope direct GET is 403 (generic, same as absent entity; PRP-06 behaviour) not 404; PresentedEdge exposes no provenance method field (follow-up). Never runs in CI (integration marker) | 2026-11-08 |
| 13 | merged | worktree-agent-a6cfae434e56879e4 | sonnet | fdf5da1; re-run on branch: ruff/format clean, default selection 4 passed 2 deselected; emulator run re-run by orchestrator 1 passed (445 s): get p95 48.8 ms, scoped list 54.6, scoped export 51.2, fixture search 337.0, neighbors d3 5087.9 (budget-bound), impact d3 2018.6; evidence docs/evidence/G03/catalog-export-emulator-2026-11-08.md; merge e7a399a; final: ruff . + pyright clean, touched suites 633 passed, full collection 10159 collected no errors, gitleaks 12 commits no leaks, validate_planning PASS. Live export p95 OPEN (not run) | 2026-11-08 |

Round 2 (audit gap closure, items 8-13): plan approved 2026-11-07, integration branch `prp-10-audit-gap-closure` from main 2b97e06. Waves: (8, 9, 11) → 10 → (12, 13). Live runs stay OPEN this round (user decision); item 12 is the API compose test only (browser real-stack specs go to the re-plan step 4 PRP).

## Completion note (filled at ship)
- Date: 2026-10-17
- Merged commits: PR #52 (merge b67b8ab). Item merges: 0b38c7d (0), d6fd3f9 (1), 0aef02e (2, incl. rework 4c30a74), 066ff14 (3), 16e3d3d (4), d3c0b51 (5), e62bcfd (6), e47672a (7 harness delta); G03 evidence 6ac7ae6. Orchestrator commits: 03b876f (azure-search-documents 12.0, relock), 70f6598 and 074b2f5 (router registration, openapi.json), 86bcbdf (test-package collision fix).
- Deviations from blueprint and why:
  - Item 0 (shared catalog core) added at plan approval: items 2, 3 and 4 needed the same protocols, lock/override rules and review-queue interface, which no item owned.
  - Router registration in `services/api/neurosphere_api/routers.py` and `openapi.json` regeneration done by the orchestrator at merge time (shared files).
  - `services/api/tests/catalog/` has no `__init__.py`: with one, it collided with `packages/core/tests/catalog` as a top-level `catalog` test package.
  - Item 3 ships `TraceEventSource` and `ClaimsSource` as protocols with in-memory implementations only: no trace-event readback by `doc_id` and no worker managed-identity wiring exist yet (#55).
  - Item 7 (clarification 13): the PRP-02 G03 harness could not run under Entra (data-plane tokens cannot create databases/containers, 403/5300); with operator sign-off it now provisions through the control plane via `az`, and the evidence writer gained a live disclaimer and account section.
  - Item 7 target: Limitlessdata - DMLZ, where the landing-zone Modify policy forces Cosmos public network access off; the run used a private endpoint in the hub VNet and the operator workstation over the Entra P2S VPN, so the live latency includes WAN round trip.
- Descoped items: none. (Embedding inference, Purview/Unity connectors, review-queue UI and map rendering were out of scope per "NOT building".)
- G03 live run: 2026-10-17, operator approval Frank Garofalo (in session), `docs/evidence/G03/live-2026-10-17.md` and `.json`. All 9 cells correct; mean 39-58 RU per traversal; p95 1.58-2.13 s incl. WAN RTT. G03 NARROWED (Commercial); in-region latency, 429, index tuning and Government remain open.
- Follow-ups: #53 (authorization/existence-signal hardening), #54 (lock/observation/review-queue semantics), #55 (production wiring), #56 (search/budget/test nits), #57 (G03 in-region run, ADR-0005 key decision, matrix rows, enterprise networking guide, harness hardening).

## Audit gap closure 2026-11-08 (items 8-13)

Shipped 2026-11-08 via PR #192 (squash merge 0eb3604; CI green: 32 pass, 2 skipped (main-only)). Item merges on the integration branch: 1a84a7e (8), b4e3d0c (9), d5cd121 (10), 57c9be1 (11), c55d235 (12), e7a399a (13); CI fix-forward 619a79a (first CI run had 5 failures outside the touched suites: the hosted-demo param test regex never matched `=` so every Bicep param looked required, the D9 parameter list lacked the two search params, and two review-queue store tests predated the open-duplicate dedup; tests fixed, product code unchanged). Branch `prp-10-audit-gap-closure`. Closed: a real stack's catalog now fills from telemetry, because the projection worker creates-if-absent the agent, model-deployment and tool entities a trace references before writing the inferred edges (item 8, reviewed APPROVE); proved on the compose emulators through the real ingest edge and Event Hubs: 2 agents, 2 tools, 2 model deployments and 5 inferred edges with `event:`/`trace:` evidence appear in about 10 s, are searchable, and are invisible to another domain (item 12). #54 lock, observation and review-queue semantics (item 9; lineage refresh after lock expiry wired by item 10). #53 and the core/api parts of #56: actor stamping, non-disclosing duplicate-ID errors, unscoped `put_override` uniqueness, fan-out truncation after the scope filter, explicit auditor check for the raw view, 403 before 422 on create, paged stale-agent reconcile, retry-after, time budgets, standalone test collection (item 10, reviewed APPROVE). Search parts of #56 and the #55 Government guard; hosted Bicep and Helm now set `NS_SEARCH_PROVIDER` (default `fixture`; `azure` with service and region when one is deployed) (item 11). Scoped export p95 measured on the Cosmos vNext emulator, bounded feasibility only (item 13, `docs/evidence/G03/catalog-export-emulator-2026-11-08.md`): get 49.9 ms, scoped list 55.1, scoped export 54.2, fixture search 334.4, neighbors depth 3 5075.6 (budget-bound), impact depth 3 2009.1.

**Behaviour changes:** catalog create with a missing or out-of-scope `domain_id` returns 403 (was 422); a curation lock whose actor differs from the caller returns 403 `actor_mismatch`; a cross-domain alias-ID clash is now refused with the same message as an in-domain one; with `NS_SEARCH_PROVIDER=azure` in Government and search unavailable, `/readyz` fails the catalog component (no silent fixture). Observation and review-item ids now differ for the same input (stored documents stay readable; replaying an old observation records it once more; no migration).

**Still OPEN:** live export p95 and in-region G03 (#57; user decision 2026-11-07, needs the operator on the P2S VPN); G12 RU accounting and index deltas; browser real-stack catalog/curation specs (re-plan step 4 PRP); item 12's compose test carries the `integration` marker and never runs in CI.

**Follow-ups (not done this round):** durable `CandidateQuarantine` sink in the worker runtime (in-memory today); same-ID entity in an out-of-scope domain stalls the projection checkpoint (fail-closed, no leak); keyed stale-agent plan digest (no reachable key source); `PresentedEdge` exposes no provenance method; graph traversal does sequential per-edge entity reads (neighbors depth 3 is budget-bound on the emulator; batch or bound-concurrent reads); fan-out reports `max_edges` for nodes with more than 500 total edges, hidden ones included; graph imports `auditor_domains` from the repo engine rather than the protocol; Cosmos-emulator tests for `list_edges_by_domain` and the review queue's open-duplicate query; open-duplicate check is check-then-insert. Filed as #193 (projection quarantine sink and collision), #194 (graph read performance, fan-out signal, auditor_domains layering) and #195 (plan digest, provenance, emulator coverage, open-duplicate race, id change, cache_key duplication); #53-#56 closed as superseded. #57 (live G03 + live export p95) stays open.

## Audit 2026-11-04

Reopened after a deep audit (static read by a read-only agent; no tests were run). Gaps, with evidence:

- Catalog search is not composed: `runtime/builders/data.py:211` uses `_NoSearch` (raises `search_unavailable`, `data.py:187-190`); the `search/azure` package has no non-test caller under `services/`. Explorer search hits 503.
- The catalog starts empty: the projection worker (`projections/catalog/handler.py:181-221`) only calls `put_edge`; entities exist only via `POST /catalog/entities` or import.
- Frontend catalog e2e (`catalog.spec.ts`, `curation.spec.ts`) runs against the mock API only; the only real-stack catalog route is `/catalog/publication`.
- Export p95 (500 ms target) measured on the in-memory repository only (`test_catalog_p95.py:43,58`); live G03 figure (1.58-2.13 s) is graph traversal. Follow-ups #53/#54 on lock/conflict semantics open.
