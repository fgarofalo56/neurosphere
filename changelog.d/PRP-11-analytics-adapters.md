### Added
- PRP-11: the API selects an analytics adapter from `NS_ANALYTICS_BACKEND` (`runtime/builders/analytics.py`), reports it as the optional component `analytics_adapter` and sets `app.state.analytics_adapter`. The product Databricks Statement Execution executor now lives in `neurosphere_core.analytics.databricks.executor`, PR #275.
- PRP-11: Synapse windowed `PERCENTILE_CONT` path for approximate quantiles (#59).

### Changed
- PRP-11: the G01 live script imports the product executor and the shared equivalence workload, bounds setup and teardown with a time budget and uses plain `CREATE SCHEMA` (#60).
- PRP-11: the adapter registry keeps the `capability_unavailable` reason for refused Government regions.

### Fixed
- PRP-11: analytics suite assertions tightened (#61) and adapter nits fixed (#62), including a Fabric migration ledger lock that no longer leaks or reuses recycled executor ids.
