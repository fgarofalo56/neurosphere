### Added
- A curated, deterministic demo world for local development and CI (PRP-71): 32 named agents
  in four business domains with descriptions, tags, capabilities, owners and versions, plus
  services, tools, model deployments, an MCP server and data assets with classification,
  sensitivity categories and EU or US residency, connected by ownership, access, dependency
  and delegation edges. Generator profile `--profile demo-world`; ids and names are listed in
  `sandbox/demo/README.md`.
- Demo telemetry with tool, service and MCP-server identity on spans, delegation traces, four
  agents that exist only in telemetry, and one scripted incident (a failing service that
  degrades exactly its downstream agents), described by `incident-manifest.json`.
- `make demo-up`, `make demo-down` and `make demo-check`: the local real stack with the demo
  world and `infra/dev/demo-profile.env`, which turns on the producer store, the MCP server,
  the deployment scan, lifecycle in dry-run and archive-sourced recommendations against local
  backends, and a check that fails on an unexplained empty page.
- Stored feature settings are seeded for the demo profile through the same validation and
  audit as the settings route.

### Changed
- `docker-compose.yml` forwards the demo profile's settings when they are exported and lets
  the evaluation pilot domain be overridden. Defaults are unchanged, so `make stack-up` and a
  plain `docker compose up` behave as before.
- In the demo world only, the seed grants the signed-in operator each persona role over the
  demo domains so one sign-in opens the role-gated pages.
- Not part of the demo profile: the copilot stays off until PRP-78 ships the recorded mode,
  write-target apply stays advisory locally (the management host cannot be pointed at a
  loopback fake), and the demo world is never loaded into a hosted environment.

### Fixed
- The scripted demo incident now shows in the dashboards: a failed call to the outage service
  abandons the model call that was waiting on it, which is the span kind the aggregates count.
  Before, every domain showed an hourly error rate of zero.
- The recommendations worker role no longer restarts on every tick when an archived cost
  record carries an unreported token count.
- `make demo-up` no longer leaves the workers unhealthy a few minutes after it finishes: the
  closing catalog seed container seeds the same profile as the rest of the stack.
- The seed publish waits and retries when the Event Hubs emulator throttles it, and
  `make demo-check --wait-seconds` waits for a domain whose error series is still draining.
