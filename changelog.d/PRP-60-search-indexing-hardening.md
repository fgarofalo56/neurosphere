### Added
- Azure AI Search index schema in code (`catalog_index_definition()`), an opt-in `NS_SEARCH_ENSURE_INDEX` startup create-or-update, and write-through indexing of catalog writes from the API and from the `projections` and `foundry_discovery` workers (PRP-60, PR #311).

### Changed
- Azure document keys are URL-safe base64 of the canonical id; the canonical id lives in a filterable `entity_id` field. Indexes built before this change must be recreated.
- Catalog search refresh uses a bounded per-scope single-flight lock instead of one global lock.

### Fixed
- The indexer deletes documents whose entity left every scope's enumeration (ref-counted), and no longer skips the re-upsert when a concurrent scope deletes the same id.
