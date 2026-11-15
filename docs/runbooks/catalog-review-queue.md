# Catalog review queue and candidate quarantine

PRP-43. Two operator surfaces for the relationship catalog: the steward review queue (conflicts
between new inference and a steward decision) and the worker's durable candidate quarantine
(edges the catalog projection refused to write).

## Review queue (stewards)

When re-inference contradicts a steward lock or a curated reject, the catalog keeps the curated
state, still stores the observation, and enqueues a review item in `catalog_review_queue`.

| Surface | Path | Permission |
|---|---|---|
| List open items | `GET /api/v1/catalog/curation/review-queue` | `catalog.curate` (items in domains the caller may curate, oldest first) |
| Resolve one item | `POST /api/v1/catalog/curation/review-queue/{item_id}/resolve` body `{"resolution": "kept_curation" \| "accepted_inference"}` | `catalog.curate` on the item's domain |
| Page | `/catalog/review-queue` (Governance navigation) | same, enforced by the API |

Behaviour worth knowing:

- `resolved_by` and `resolved_at` are stamped by the server; the body carries only the outcome.
- A missing item, an item outside the caller's scope and an item in a domain the caller can read
  but not curate all answer the same 404.
- Resolving twice is idempotent: the second call returns the stored item and writes no new audit
  record.
- Resolving only records the outcome. `accepted_inference` does not edit the edge; open the edge
  page and use the audited decision control, so there is one path that changes curation.
- The audit record is on the domain chain, operation `catalog.review_resolve`; its `detail` holds
  `resolution=<outcome>:item=<item id>` and it never carries the conflicting evidence.
- No SLA or escalation: the page shows item age and sorts oldest first. Items are separate from the
  HITL `/review` queue on purpose (HITL items need approval roles and timers).

### Open-conflict marker

The Cosmos queue writes a deterministic marker document (`id` starts `open-`, `status` is
`marker`) in the item's partition before the item, so two concurrent enqueues of the same
conflict leave exactly one open item. The marker is removed when the item is resolved. A marker
whose item never landed (a crash between the two writes) is taken over after 60 seconds. Items
stored before markers existed are still listed, resolved and de-duplicated by the older query.
Markers are never listed and cannot be read or resolved as items.

### Id backfill decision

Observation ids and review-item ids now include confidence and the conflict generation. No
backfill is done: no real data exists yet. A pre-change observation replayed once is recorded one
extra time (`merge_observation` is idempotent by evidence), so the effect is one duplicate
observation row. Revisit before the first real ingestion (PRP-64).

## Candidate quarantine (operators)

The catalog projection writes a `CandidateQuarantineRecord` (identifiers only, no span content)
for every candidate it will not write:

| Reason | Meaning |
|---|---|
| `out_of_scope` | the candidate's cloud, customer or domain is outside the worker scope |
| `entity_id_collision` | an endpoint id exists in a domain outside the worker scope, so the entity cannot be created or read |

Both are counted (`skipped_out_of_scope`, `skipped_collision`) and the checkpoint advances. Any
other failure (for example `ForbiddenError` from the repository, or a quarantine store outage)
propagates and holds the checkpoint. `build_entity` returning `None` is counted as
`entities_undiscoverable`.

Records live in the `catalog_quarantine` Cosmos container (partition `/customer_id`,
`/domain_id`; document id = candidate edge id, so a replay overwrites). The container is created
by the emulator bootstrap locally and by the Bicep modules on the next deploy, from
`infra/compose/cosmos-containers.json`.

### Alert threshold

`NS_WORKER_CATALOG_QUARANTINE_WARN` (default 100): once `skipped_out_of_scope + skipped_collision`
reaches it within one process lifetime the worker logs one WARNING with counts only, never ids.
Raise it for a deployment that legitimately carries many foreign-domain events.

### Wiring status

`build_projections` in the worker factories passes `CosmosCandidateQuarantine` and the threshold
to `CatalogProjection` once PRP-42 has merged (that file is single-owner in W14). Until then the
worker still uses the in-memory sink.

## Open gates

- Live Cosmos latency re-measure of graph traversal (#57) is OPEN and handed to PRP-64. The
  emulator tests under `tests/integration/catalog/` are local evidence only.
