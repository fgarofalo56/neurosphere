# OpenTelemetry tool, service and MCP attributes (PRP-100)

Status date: 2026-11-23. Every attribute below was read from the cited page on that day while
writing this file. Rule for this document: **no invented attribute names**. The OTLP edge
(`services/api/neurosphere_api/ingest/otlp_mapping.py`) reads only the names listed under
"Read"; anything under "Not read" is deliberately ignored, and any name not on this page is
not coded.

## Sources

| Source | Revision fetched | Notes |
|---|---|---|
| [GenAI execute-tool span](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/execute-tool.md) | `semantic-conventions-genai` `main` at `ae8214a8f3a9` | The GenAI conventions moved out of the core repository; `opentelemetry.io/docs/specs/semconv/gen-ai/*` now only points here. |
| [MCP spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/mcp.md) | same | Client and server spans for MCP. |
| [Service attributes](https://github.com/open-telemetry/semantic-conventions/blob/main/docs/registry/attributes/service.md) | `semantic-conventions` `main` at `aef58d05090b` (latest release `v1.45.0`) | Resource attributes. |
| [Server attributes](https://github.com/open-telemetry/semantic-conventions/blob/main/docs/registry/attributes/server.md) | same | Connection peer attributes. |
| [Peer attributes](https://github.com/open-telemetry/semantic-conventions/blob/main/docs/registry/attributes/peer.md) | same | Deprecated peer naming. |

## Read

| Attribute | Where | Stability | Requirement | Mapped to | Rule |
|---|---|---|---|---|---|
| `gen_ai.tool.name` | span (`gen_ai.execute_tool`, MCP `tools/call`) | Development | Required on execute-tool spans | `tool.tool_name` (max 128) and `tool.external_tool_id` (max 256) | Only on spans mapped to `tool_call`. It is the registered tool name, a low-cardinality identity. |
| `server.service.name` | span (client side) | Development | Recommended | `service.external_service_id` | First choice: the service this span *called*. Prefixed by `server.service.namespace` when present (`<namespace>/<name>`). |
| `server.service.namespace` | span | Development | Recommended | prefix of `service.external_service_id` | Only together with `server.service.name`. |
| `service.peer.name` | span | Deprecated (use `server.service.name`) | n/a | `service.external_service_id` | Fallback for SDKs that still emit it, prefixed by `service.peer.namespace` when present. |
| `service.peer.namespace` | span | Deprecated (use `server.service.namespace`) | n/a | prefix | Only together with `service.peer.name`. |
| `peer.service` | span | Deprecated (use `server.service.name`) | n/a | `service.external_service_id` | Last span-level fallback. |
| `service.name` | resource | Stable | SDKs always set it | `service.external_service_id` | Used only when no span-level called-service attribute is present: the service the span *ran in*. The SDK defaults `unknown_service` and `unknown_service:<exe>` are treated as absent. Prefixed by `service.namespace` when present. |
| `service.namespace` | resource | Stable | optional | prefix | Only together with `service.name`. |
| `server.address` | span, MCP client spans only (a span carrying `mcp.method.name`) | Stable | Recommended if applicable | `mcp_server_ref` | Host name or IP only. Rejected when it holds a scheme, path, query, user info, whitespace or a port. Absent for the stdio transport, so stdio MCP calls carry no server reference. |
| `mcp.method.name` | span | Development | Required on MCP spans | (not stored) | Read only to decide that `server.address` names an MCP server. |

"Rejected" values are dropped with a counted reason; the span is still accepted.

## Not read

| Attribute | Stability | Why it is not read |
|---|---|---|
| `gen_ai.tool.call.id` | Development | Per-call identifier: using it as a tool id would create one series per call. |
| `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result` | Development, Opt-In | Content. Bodies never cross the edge (NS-01). |
| `gen_ai.tool.description` | Development | Free text, not identity. |
| `gen_ai.tool.type` | Development | Not identity; no consumer in this PRP. |
| `service.instance.id` | Stable | Per-instance identity: one series per pod or process. |
| `service.version` | Stable | Not identity for an aggregate series. |
| `server.port`, `client.address`, `client.port` | Stable | Not identity; a port would split one server into several references. |
| `mcp.session.id`, `mcp.resource.uri`, `jsonrpc.request.id` | Development | Per-session or per-request, or a URI that can carry content. |

## Not found

The conventions define no attribute that names an MCP server (only its network address), and no
stable tool identifier separate from `gen_ai.tool.name`. Nothing is coded for either.

Every attribute above except `service.*` resource attributes and `server.address` is at
Development stability and may be renamed; re-check this page when the conventions publish a
GenAI release.
