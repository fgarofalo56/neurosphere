# MCP reference

> Generated file. Do not edit; run `uv run python docs/reference/generate.py`.
> Source commit: `b2ed8aecc9f07859448121b1652261ae170cb183`. Generated: 2026-11-11.
> Sources: `services/api/neurosphere_api/mcp/server/` and the live tool registry.

The NeuroSphere MCP server exposes bounded structured tools and read-only resources over streamable HTTP with OAuth 2.1 resource-server auth. Every call re-derives the caller's `IdentityScope` server-side; scope-shaped arguments (domain, customer, tenant, scope) are refused, never consulted. There is **no confirm, execute or approve tool**: an agent can draft and present a confirmation, a human confirms in the UI or REST API through the same durable action executor. Annotations are client hints, never authorization.

Behaviour against live identity providers and provider backends is covered by live gates; this page documents the registered surface only and does not assert live verification.

## Tools

| Tool | Scope requirement | Read-only | Idempotent |
|---|---|---|---|
| `draft_action` | `action.propose` | no | yes |
| `get_action_status` | `data.read` | yes | yes |
| `get_cost_summary` | `data.read` | yes | yes |
| `list_recommendations` | `data.read` | yes | yes |
| `present_action_confirmation` | `action.propose` | no | no |
| `search_catalog` | `data.read` | yes | yes |
| `validate_action` | `action.propose` | no | no |

The scope requirement is the permission checked on the caller's `IdentityScope` (domain-scoped) before the handler runs.

### `draft_action`

Draft (never confirm or execute) an action intent for a catalog target. Returns the intent id, diff, target version and intent hash. A human confirms in the NeuroSphere UI or REST API; this server has no confirm, execute or approve tool. Results are limited to the caller's server-derived scope; scope, domain and customer arguments are refused.

- Scope requirement: `action.propose`
- Arguments: `action_kind` (`string`, required), `evidence` (array of `EvidenceRef`), `idempotency_key` (`string` or `null`), `proposed_diff` (`ProposedDiff`, required), `target` (`TargetRef`, required), `target_version` (`string`, required)

### `get_action_status`

Current state of an action intent in the caller's readable domains. Results are limited to the caller's server-derived scope; scope, domain and customer arguments are refused.

- Scope requirement: `data.read`
- Arguments: `intent_id` (`string`, required)

### `get_cost_summary`

Cost, latency or error aggregates that NeuroSphere has ingested for the caller's readable domains (coverage depends on the configured connectors). Results are limited to the caller's server-derived scope; scope, domain and customer arguments are refused.

- Scope requirement: `data.read`
- Arguments: `metric` (`string`), `query` (`StructuredQuery`, required)

### `list_recommendations`

List NeuroSphere recommendations in the caller's readable domains. Results are limited to the caller's server-derived scope; scope, domain and customer arguments are refused.

- Scope requirement: `data.read`
- Arguments: `query` (`StructuredQuery`, required)

### `present_action_confirmation`

Bind the confirmation hash and expiry of a validated intent you drafted, for a human to confirm in the NeuroSphere UI or REST API. Results are limited to the caller's server-derived scope; scope, domain and customer arguments are refused.

- Scope requirement: `action.propose`
- Arguments: `intent_id` (`string`, required)

### `search_catalog`

Search NeuroSphere catalog entities (agents, models, deployments and other registered entities) in the caller's readable domains. Results are limited to the caller's server-derived scope; scope, domain and customer arguments are refused.

- Scope requirement: `data.read`
- Arguments: `query` (`StructuredQuery`, required)

### `validate_action`

Run the prerequisite checks and a dry run for an intent you drafted. Results are limited to the caller's server-derived scope; scope, domain and customer arguments are refused.

- Scope requirement: `action.propose`
- Arguments: `intent_id` (`string`, required)

## Resources

| Name | URI | MIME type | Description |
|---|---|---|---|
| `about` | `neurosphere://mcp/about` | `text/markdown` | What this MCP server exposes and what it does not. |
| `recent-recommendations` | `neurosphere://recommendations/recent` | `application/json` | Recent recommendations in the caller's readable domains. |
| `current-scope` | `neurosphere://scope/current` | `application/json` | The caller's server-derived scope (domains and permissions). |

## Related surfaces

- MCP server administration (register servers, sync tools, approve or revoke a tool) is REST under the `mcp-admin` tag in the [API reference](api.md).
- The MCP client connector in `neurosphere_api.mcp.client` consumes external MCP servers; a synced tool is unusable until an administrator approves it.
