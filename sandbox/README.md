# NeuroSphere sandbox generator

Deterministic, seeded, offline generator of synthetic AI-governance data (PRP-03 item 3).
Everything is synthetic: pseudonymous principals only (no names, emails, SSNs, addresses or
phone numbers), no production data, no network. Records are built from the generated
`neurosphere_contracts` models. The package does not import from `services/*`.

```
python -m sandbox.generate --seed 1 --profile tiny --cloud commercial --out temp/sandbox
```

| Flag | Meaning |
|---|---|
| `--seed N` | Required. Same seed + epoch => byte-identical files. |
| `--profile tiny\|pilot\|custom\|demo-world` | `tiny`: 24 agents, 4 days (smoke). `pilot`: 1000 agents, 20 domains, 7 days (about 100k telemetry events, 14 s). `custom`: starts at 200 agents, override with `--agents --domains --days --traces-per-agent-day`. `demo-world`: the curated demo estate (below); only `--days` is an accepted override. |
| `--cloud commercial\|government` | Required. One cloud per output directory; labelled sets are never mixed. Government output is still synthetic and local. |
| `--epoch` | Window start, RFC 3339 UTC (default `2026-10-01T00:00:00Z`). No wall clock is read. |
| `--out DIR` | Default `temp/sandbox` (gitignored). Re-running overwrites every fixed-name file. |
| `--duplicate-rate --out-of-order-rate --malformed-rate --missing-optional-rate` | Bad-event fractions of the telemetry stream (defaults 1%, 1%, 0.5%, 2%; mutually exclusive per event). |

Generation streams: catalog files are written entity by entity and traces are produced one
hour at a time, so memory does not grow with event volume. The 100k-agent enterprise profile
is a PRP-21 target; `--profile custom --agents 100000` works in the same streaming mode.

## The `demo-world` profile (PRP-71)

```
python -m sandbox.generate --seed 1 --profile demo-world --cloud commercial --out temp/demo-world
```

A hand-curated, named estate (32 agents in 4 domains, 7 services, 16 tools, 4 models, 15 data
assets, 12 `delegates_to` hand-offs; ids and names in `sandbox/demo/README.md`) with telemetry and
one scripted incident, built by `sandbox/demo/` through the same writers. The layout is the table
below plus:

| File | Content |
|---|---|
| `services.ndjson` | Service entities (`catalog/v1/service`); `mcp_servers.ndjson` carries the MCP server entity |
| `incident-manifest.json` | The scripted outage: `service_id`, `service_name`, `downstream_agent_ids`, `unrelated_agent_ids`, `undeclared_agent_ids`, `window` (the last hour of the seeded window, `epoch + days`), `baseline_window`, `effects`, `expected_health_transitions` |

`run-manifest.json` gains `demo_world` (`undeclared_agents`: the four telemetry-only agents, which
have no catalog entity; `outage_service_id`; `downstream_agent_ids`; `delegations`) and
`incident_manifest_file`. No bad events are injected (the incident is the only fault), so
`bad-event-manifest.*` are written with zero counts and `anomaly-manifest.json` has no entries; the
`--*-rate`, `--agents`, `--domains` and `--traces-per-agent-day` flags are refused. Same seed and
epoch give byte-identical files; `tiny`, `pilot` and `custom` are unchanged (the profile is a
dispatch at the top of `generate`).

The seed (`scripts/sandbox/sbx_seed_stack.py --profile demo-world`, local and CI only; the hosted
seed refuses it) loads the curated entities and every edge through the repository before it
publishes telemetry, so the projection never replaces the curated metadata with a telemetry
draft; the four telemetry-only agents are left for the projection to discover. It shifts the epoch
on a 5-minute grid so the incident window ends 30 to 35 minutes before the run (anchored on the
window end), and reports the rebased `incident` manifest next to the counts. Its summary adds
`services`, `tools`, `mcp_server_entities` and `edges` to the usual categories (`entities` stays
the total).

## Output layout (consumed by the seed-and-replay CLI)

All files are NDJSON (one canonical JSON object per line, sorted keys, ASCII, LF endings)
unless noted.

| File | Content | Contract |
|---|---|---|
| `domains.ndjson` | Domains | `catalog/v1/domain` |
| `owners.ndjson` | Owners (team, group, service principal, person-kind pointing at a Person) | `catalog/v1/owner` |
| `persons.ndjson` | Pseudonymous principals (`psn_` + 32 hex, blake2b of the seed) | `catalog/v1/person` |
| `model_deployments.ndjson` | Model deployments (shared, with a price reference) | `catalog/v1/model_deployment` |
| `grounding_sources.ndjson` | Grounding sources | `catalog/v1/grounding_source` |
| `tools.ndjson` | Tools | `catalog/v1/tool` |
| `agents.ndjson` | Agents and sub-agents (`agent_kind: sub_agent`) | `catalog/v1/agent` |
| `agent_versions.ndjson` | AgentVersions | `catalog/v1/agent_version` |
| `relations.ndjson` | Mixed relation documents; the `relation_type` field selects the schema: `owned_by`, `uses_model`, `invokes`, `grounded_by`, `delegates_to`. `status: asserted` = declared, `status: inferred` = derived from traces (cites `trace:<trace_id>` evidence) | `catalog/v1/<relation_type>` |
| `telemetry.ndjson` | Delegation traces as `TelemetryEvent` spans, including the bad events. Line order is arrival order, not event-time order | `telemetry/v1/telemetry-event` |
| `cost.ndjson` | `CostRecord` observations | `cost/v1/cost-record` |
| `anomaly-manifest.json` | Injected anomalies (JSON) | below |
| `bad-event-manifest.json` | Bad-event summary and expected counts (JSON) | below |
| `bad-event-manifest.ndjson` | One entry per bad telemetry line | below |
| `run-manifest.json` | Seed, profile, cloud, epoch, per-file record counts (JSON) | below |

Load order for entities: domains, owners/persons, models/sources/tools, agents, versions,
relations. IDs follow `cloud:customer:source:type:id`, customer `synthco`, catalog source
`sandbox` (for example `commercial:synthco:sandbox:agent:a-000042`). Telemetry
`environment` is always `sandbox`. All documents are JSON-Schema-valid except the lines the
bad-event manifest marks `malformed`.

### Telemetry and cost semantics

- Spans per trace: `request` -> `agent_run` -> `retrieval`, `model_call`, `retry`, `tool_call`,
  `delegation` (-> child `agent_run`), `error`, `cancellation`. Tool and source references
  are carried in `data_source_refs` (tools have no dedicated TelemetryEvent field).
- Cost: every model call yields a `gateway` and an `application` estimated record and, for a
  fraction of calls, a `billing` invoiced record, all sharing one `dedupe_key`
  (`synthco/<model_call event_id>`) for de-duplication tests. Money is a decimal string.
  Prices come from the synthetic sheet `sandbox-prices-2026-10`. Bad-event injection applies
  to telemetry only; cost records are always clean.

### `anomaly-manifest.json`

```json
{
  "manifest_version": "1.0", "kind": "sandbox-anomaly-manifest",
  "seed": 1, "profile": "pilot", "cloud": "commercial", "epoch": "2026-10-01T00:00:00Z",
  "anomalies": [{
    "anomaly_id": "anom-cost_spike-001",
    "type": "cost_spike | latency_regression | unused_agent | duplicate_agent_candidates",
    "affected_ids": ["<canonical agent id>", "..."],
    "window": {"start": "<RFC 3339>", "end": "<RFC 3339, exclusive>"},
    "label": "ground_truth | candidate",
    "details": {}
  }]
}
```

`duplicate_agent_candidates` are always `label: candidate` with `details.auto_merge: false`;
they are overlap-based (shared grounding sources and the same model deployment), meant for
consolidation review, never ground-truth merges. `unused_agent` is an active agent with zero
telemetry for the whole window. `cost_spike` multiplies tokens (12x) and volume (3x) inside
the window; `latency_regression` multiplies durations (3x) from the window start to the end.

### `bad-event-manifest.json` / `.ndjson`

`bad-event-manifest.json` holds `rates`, `counts` per kind, and `expected`
(`total_lines`, `duplicate_lines`, `malformed_lines`, `valid_distinct_events`).
`bad-event-manifest.ndjson` has one entry per defective line of `telemetry.ndjson`
(`line` is 1-based):

| `kind` | Extra fields | What the line is |
|---|---|---|
| `duplicate` | `event_id`, `duplicate_of_line` | Byte-identical re-delivery of an earlier line |
| `out_of_order` | `event_id`, `event_time`, `delay_seconds` | Valid event delivered `delay_seconds` after its time |
| `malformed` | `event_id`, `mutation` | Schema-violating: `missing_required_field`, `invalid_trace_id`, `negative_duration`, `non_utc_timestamp`, `unknown_field`, `wrong_type`. `event_id` is the original id (may be absent from the line) |
| `missing_optional` | `event_id`, `dropped_fields` | Still schema-valid, optional fields omitted |

PRP-07 quarantine tests should expect exactly `counts.malformed` rejected lines and
`valid_distinct_events` distinct accepted `event_id`s.

## Tests

```
uv run pytest sandbox/tests -q
```

`test_determinism` (hashes), `test_schema_validity` (Pydantic and JSON Schema),
`test_anomaly_manifest` (pilot, plus measurable effects), `test_no_legacy_terms` (deny-list),
`test_bad_event_mix`. All offline; the pilot data set is generated once per session.
