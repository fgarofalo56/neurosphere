# ADR-0005: Catalog store, Cosmos DB NoSQL adjacency

- Status: provisional (pending live gate G03; the partition key decision is PROVISIONAL)
- Date: 2026-10-11
- Deciders: Frank Garofalo
- Relates to: gates G01 and G03 (`docs/RESEARCH-AND-GATES.md`), PRP.md section 2

## Context

The versioned catalog and curated relationships need an operational store with bounded graph-shaped reads (get, search, neighbors, bounded impact paths) behind `CatalogRepository` and `GraphQuery`. PRP.md section 2 names Cosmos DB NoSQL documents with adjacency as the default. Alternatives considered: Cosmos DB for Apache Gremlin, and Neo4j.

Evidence available today is documentation-derived matrix rows and one emulator run. The emulator run is bounded feasibility only (PRP-02 clarification 1).

## Decision

1. **Default engine: Cosmos DB NoSQL adjacency.** Nodes and edges are documents. Traversals are executed by application code through bounded structured calls limited by the `Budget` contract (depth, fan-out, node, edge and time limits). Cosmos is not treated as a native arbitrary graph query engine.
2. **Neo4j is an optional deep-graph adapter**, enabled per deployment only when license, private deployment, residency, availability and benchmarks allow. It is **not** an automatic Government fallback: if the Cosmos path is disabled for a Government profile, nothing silently routes to Neo4j, and nothing bridges Government data to Commercial.
3. **Gremlin is out** unless the live benchmark or a changed limits page changes the answer. No Gremlin evidence was gathered; this is a scope decision, not a measured result.
4. **Partition key shape: PROVISIONAL.** The benchmark parametrized three variants: flat `/domain`, hierarchical `/tenant` + `/domain`, and hierarchical `/tenant` + `/domain` + `/shard`. The working design preference is the hierarchical `/tenant` + `/domain` + `/shard` shape, because it keeps tenant isolation in the key path and lets a hot domain spread across shards. This is a design preference only; the emulator latencies do not separate the variants in a way that justifies a final choice. **Closing evidence is the live run**: `scripts/gates/g03_live.py` writing `docs/evidence/G03/live-<date>.md`, operator-approved and gated by `NS_LIVE_APPROVED=1`, required before PRP-10 merges. Until then PRP-10 must keep the key shape behind one configuration point.
5. **Hierarchical partition key constraints**: up to 3 levels, new containers only (no in-place conversion of an existing container), and the Python SDK must be `azure-cosmos` >= 4.6. The benchmark ran on SDK 4.17.1.
6. **The transactional outbox is the projection baseline**, not the emulator change feed. Change feed all-versions-and-deletes mode is preview in Commercial and unverified in Government, so no design depends on it.

## Evidence relied on

Emulator evidence (label: emulator, bounded feasibility):

- `docs/evidence/G03/emulator-2026-10-11.md`
- `docs/evidence/G03/emulator-2026-10-11.json`

What those files support: bounded traversals stayed within the depth, fan-out, node, edge and time budgets and matched the reference traversal on all three workloads (skewed, high_degree, cross_domain) and all three partition variants. Local emulator p95 ranged from roughly 0.65 s to 2.06 s; the high_degree workload reached the 2000 ms timeout budget in every iteration, so it demonstrates budget enforcement, not acceptable latency.

What they do **not** support. The following are **unmeasured**, and nothing in this ADR claims otherwise: request unit (RU) cost, index policy and index behaviour, throttling (HTTP 429), and cross-partition fan-out cost. The vNext emulator has no RU accounting, does not reproduce range or composite indexes, does not throttle, and has no per-partition cost model. Emulator latency gives no cost, SLA, throughput or performance guarantee.

Matrix rows (`packages/core/neurosphere_core/capabilities/data/cosmos.yaml`):

| Row id | Availability / GA | Consequence |
|---|---|---|
| `cosmos_db.hierarchical_partition_keys.commercial.global.any` | unverified / unverified | Hierarchical keys are disabled by `validate_profile` until the row is verified |
| `cosmos_db.hierarchical_partition_keys.government.global.any` | unverified / unverified | Disabled for Government; a flat-key fallback design is needed there |
| `cosmos_db.change_feed_all_versions_and_deletes.commercial.global.any` | preview / preview | Preview; not a baseline (decision 6) |
| `cosmos_db.change_feed_all_versions_and_deletes.government.global.any` | unverified / unverified | Disabled for Government |
| `cosmos_db.base.government.any.any` | available / unverified | Cosmos is selectable in Government; GA unverified is a warning, not authorization |
| `cosmos_db.base.commercial.global.any` | unverified / unverified | Commercial base availability not yet captured; refresh the row |

This exposes a tension: the provisional hierarchical key is currently disabled by the matrix in both clouds, so PRP-10 needs either a verified row or the flat `/domain` variant as the fallback. The flat variant was benchmarked and matched the reference traversal like the others.

## Consequences

- PRP-10 builds `CatalogRepository` and `GraphQuery` on Cosmos NoSQL adjacency with every traversal bounded by `Budget`.
- Gate G03 remains OPEN for live evidence (RU, indexing, 429 behaviour, cross-partition cost). This ADR is revisited when `live-<date>.md` exists.
- A Neo4j adapter, if ever added, is a separate PRP with its own license, residency and benchmark evidence.
- No statement here claims FedRAMP authorization, ATO or Commercial/Government parity. GA is not authorization.

## References

- `PRPs/active/PRP-02-capability-matrix-and-feasibility-benchmark.md` (item 4, clarifications 13 and 14)
- `PRP.md` section 2, `docs/ARCHITECTURE.md`
- `docs/evidence/G03/emulator-2026-10-11.md`, `docs/evidence/G03/emulator-2026-10-11.json`
- https://learn.microsoft.com/azure/cosmos-db/hierarchical-partition-keys
