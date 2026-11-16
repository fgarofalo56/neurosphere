### Added
- PRP-46: the `nscostcenter` CloudEvent extension now survives ingest. `HubMessage.cost_center`, `Observation.cost_center`, `LedgerEntry.cost_center` and `LedgerFilters.cost_center` carry it to the ledger (sanitised, never rejects an event, a record's own `tags.cost_center` wins). Entries stored before the change still load.
- PRP-46: `GatewayRegistration.poll_attribution` reports attributed, exact, subscription-only and unattributed rows and a failed metrics query per poll; the gateway detail API returns it.
- PRP-46: ingest reason `observation_source_mismatch` (per-item); counters for dropped non-billing invoiced records (`ns.outbox.cost_dropped`).

### Changed
- PRP-46: `POST .../mcp-servers/{id}/publication-record` now requires `catalog.curate` (was `action.propose`), matching the grant route.
- PRP-46: the APIM create step sends `If-None-Match: *` and refuses with `resource_appeared` when the resource appeared between plan and apply; grant publication records refuse a replayed older intent (`stale_intent`, 409).

### Fixed
- PRP-46: ARM ids with a `.`/`..`/trailing-dot resource group are refused; a failed gateway failure-record logs the exception type and never raises; a 403 on optional inventory lists degrades to empty with `unreadable`; the duplicates counter is created once per pipeline.
