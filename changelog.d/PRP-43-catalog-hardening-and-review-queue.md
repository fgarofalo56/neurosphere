### Added
- PRP-43: relationship review queue. `GET /api/v1/catalog/curation/review-queue` and `POST /api/v1/catalog/curation/review-queue/{item_id}/resolve` (needs `catalog.curate` on the item's domain, audited), and a `/catalog/review-queue` page under Governance. Projection candidates that are out of scope or collide with an entity id in another domain now go to a durable `catalog_quarantine` Cosmos container instead of memory; `NS_WORKER_CATALOG_QUARANTINE_WARN` (default 100) sets the one-time warning threshold. `PresentedEdge.provenance` is exposed on curation and map responses. See `docs/runbooks/catalog-review-queue.md` (PR #292).

### Changed
- Graph traversal resolves endpoints with bounded concurrency (16) and reports `max_edges` only from in-scope edges; the entity write routes refuse a declared `Content-Length` over 64 KiB; `ChangeConfirmDialog` gains a `controls` slot and `reasonMode`.
