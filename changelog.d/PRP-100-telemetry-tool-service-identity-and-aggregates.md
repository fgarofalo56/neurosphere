### Added
- Tool, service and MCP server identity on OTLP spans (PRP-100). The OTLP edge reads
  `gen_ai.tool.name` on tool spans, the called service (`server.service.name`, then the
  deprecated `service.peer.name` and `peer.service`, then the resource `service.name`) and, on MCP
  client spans, `server.address`, into the telemetry `tool`, `service` and `mcp_server_ref` fields.
  Values are length-capped and validated; an invalid value is dropped and counted in the 202
  body's `dropped_fields` (attribute and reason only, never the value), and the span is still
  accepted. Events that carry this identity are stamped `schema_version` 1.1.0. Attribute names,
  sources and stability are recorded in `docs/connectors/verification/otel-genai-tool-service.md`.
- Per-tool and per-service aggregate series. The aggregates worker rolls up calls, errors,
  unknown outcomes and p50/p95 latency for each tool (`tool_call` spans) and each service (any
  span that names one) under the subject kinds `tool` and `service`, readable through the
  existing `SubjectMetricsReader` with the same health thresholds as agents. Canonical tool and
  service ids are derived from the event scope and the external id; an id outside the canonical
  alphabet gets no series.

### Changed
- Agent, model and domain latency and error series still count `model_call` spans only; the
  realtime map delta still shows agent and model nodes only until the map gains tool and service
  node kinds (PRP-74, PRP-77).
