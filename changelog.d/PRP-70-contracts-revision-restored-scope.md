### Added
- Contracts for the restored original scope (PRP-70), all additive inside `v1`: capability
  tags, capabilities and environment on catalog entities, `semver` on agent versions, and
  sensitivity categories and a residency geography on grounding sources.
- `EntityRevision` and `EntityRevisionDiff` contracts for version history and diff.
- Agent-match request, response and feedback contracts for the task-to-agent recommender.
- `map/v1` contract area with node facets and a topology-change marker.
- Framework ids `soc2_tsc`, `iso_27001_annex_a`, `gdpr`, `nist_800_53_r5`, `eu_ai_act` and
  `iso_42001` as mapping targets on compliance controls.
- Optional tool, service and MCP-server identity on the telemetry event (`schema_version`
  1.1.0).
- Structured-query filters on tag, capability, sensitivity category, residency region,
  residency geography and `contains_personal_data`.

### Changed
- The additive-only contract baseline was refreshed and its exception list is empty.
