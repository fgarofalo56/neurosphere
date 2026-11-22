### Added
- Telemetry agent identity resolution (PRP-137): OTLP spans that carry only an external agent id
  now count for the catalog agent that sent them. The workers resolve the id at read time through
  `external_id` alias documents, so the archive is not rewritten. An id with no alias gets a
  deterministic derived id and a draft agent marked `discovered_from = "telemetry"`; the event is
  never dropped.
- `PUT` and `GET /api/v1/agent-identity/domains/{domain}/aliases` to declare, repoint and look up
  an alias (`catalog.curate` to write, `data.read` to read, audited, with a `reresolve_needed`
  hint and the exact job arguments).
- Operator job `python -m neurosphere_workers.agent_identity reresolve` that re-applies an alias to
  archived events in the aggregates window, idempotently, and prints a JSON report.
- Domain attribution for OTLP events at read time, with the operator setting
  `NS_AGENT_IDENTITY_DISCOVERY_DOMAIN`; settings `NS_AGENT_IDENTITY_POSITIVE_TTL_SECONDS`,
  `NS_AGENT_IDENTITY_NEGATIVE_TTL_SECONDS` and `NS_AGENT_IDENTITY_RESCAN_MAX_EVENTS`.
- The Foundry discovery poller writes an alias for each discovered agent that has an external id.
- Runbook `docs/runbooks/agent-identity-resolution.md`.
