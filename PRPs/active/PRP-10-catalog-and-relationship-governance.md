---
name: prp-10-catalog-and-relationship-governance
status: backlog
review: required
created: 2026-10-08
model: sonnet
phase: 1
ns: NS-02
depends_on: PRP-05, PRP-06, G03 live gate
wave: W5
absorbs: P1.2
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

## Completion note (filled at ship)
- Date:
- Merged commits:
- Deviations from blueprint and why:
- Descoped items:
- G03 live run: date, operator approval, evidence path (or OPEN, in which case this PRP must not have merged):
- Follow-ups:
