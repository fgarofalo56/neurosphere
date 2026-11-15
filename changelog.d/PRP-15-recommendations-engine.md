### Added
- PRP-15: `NS_WORKER_REC_SOURCE=archive` makes the recommendations worker read telemetry and cost from the redacted archive (`ArchiveSeriesSource`) and agents, owners and duplicate candidates from the live catalog, read-only. `NS_WORKER_REC_LOOKBACK_DAYS` sets the window. The default stays `sandbox`. Truncated or empty archives report unknown coverage and never emit `unused_agent` (PR #281).

### Changed
- PRP-15: held-out recalibration of duplicate precision and pilot latency detection; the two targets are amended to the measured numbers in `docs/evidence/G12/recommendations/README.md`.

### Fixed
- PRP-15: two concurrent `HitlReviewRouter.route` calls for one recommendation now open exactly one review item (deterministic item id, create-only write), and a recommendation id converges on one copy across domain partitions in the Cosmos and in-memory stores (#133). A later `put` into a larger partition than an existing copy is silently discarded.
