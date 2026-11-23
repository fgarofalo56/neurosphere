# API reference

> Generated file. Do not edit; run `uv run python docs/reference/generate.py`.
> Source commit: `f77c05974a2ed28e3914b30eeb70f746562414b7`. Generated: 2026-11-22.
> Sources: `services/api/openapi.json`, `packages/contracts/schemas/errors/v1/error-codes.json`.

NeuroSphere API version 0.1.0, OpenAPI 3.1.0. 221 operations on 186 paths.

## Status and verification

This page documents the committed API contract. It is not evidence that a live deployment, provider or region behaves as described. Operations whose summary or description says preview or unverified carry a **Preview/unverified** marker, and operations the contract marks deprecated carry **Deprecated**. Capability rows that are unverified in the capability matrix stay unverified here. Availability, feature maturity and authorization are separate gates; nothing here claims an authorization or compliance status.

## Error taxonomy

Errors are RFC 9457 problem details (`ProblemDetails`, `application/problem+json`) with one of the codes below. The table is the committed taxonomy; a `reason` is mandatory where noted.

| Code | HTTP | Retryable | Reason | Retry-After | Meaning |
|---|---|---|---|---|---|
| `unauthorized` | 401 | no | optional | forbidden | No valid authenticated identity (missing, expired or wrong-audience credential). Re-authenticate; never retried automatically. |
| `forbidden` | 403 | no | optional | forbidden | Authenticated, but the server-derived IdentityScope does not permit the query, tool, export, push or action. Fail closed; no privileged bypass. |
| `capability_unavailable` | 409 | no | required | forbidden | The request is schema-valid but conflicts with the deployment's current capability state (cloud, region, SKU, GA or authorization scope per the capability matrix). 409 rather than 422 so that 422 always means 'fix the payload'. A machine-readable reason is mandatory so the UI can show the option disabled with its reason. Never satisfied by routing Government data to Commercial. |
| `stale_version` | 409 | no | optional | forbidden | Target version or ETag no longer matches (optimistic concurrency). The caller must re-read and re-confirm; an action is never blindly retried against a changed target. |
| `rate_limited` | 429 | yes | optional | required | A rate limit or bounded budget was exceeded. Retry after retry_after_seconds. |
| `invalid_schema` | 422 | no | optional | forbidden | The request body failed contract validation. The optional errors array carries JSON Pointers to the offending members. |
| `dependency_transient` | 503 | yes | optional | optional | A downstream dependency failed transiently. 503 by default (including fail-closed policy-store outage); 502 when an upstream returned an invalid response. Retry with backoff. |
| `not_found` | 404 | no | optional | forbidden | No route matches, or the named resource does not exist in the caller's scope. Added in 1.1.0 (PRP-37). A resource outside the caller's IdentityScope is reported as not_found or forbidden per route policy, never with details of the other tenant or domain. |
| `method_not_allowed` | 405 | no | optional | forbidden | The route exists but does not accept this HTTP method. Added in 1.1.0 (PRP-37). |
| `payload_too_large` | 413 | no | optional | forbidden | The request body exceeds the route's size limit. Shrink the payload; never retried automatically. Added in 1.1.0 (PRP-37). |
| `internal_error` | 500 | no | optional | forbidden | An unexpected server fault. The body carries only the correlation_id; no stack trace, exception text, query or secret. Not retried automatically. Added in 1.1.0 (PRP-37). |

Framework-level validation failures on some routes surface as the OpenAPI `HTTPValidationError` (HTTP 422) shape listed per operation below.

## Endpoint index

| Tag | Method | Path | Summary |
|---|---|---|---|
| actions | GET | `/api/v1/actions/domains/{domain}/intents` | List Intents |
| actions | POST | `/api/v1/actions/domains/{domain}/intents` | Draft Intent |
| actions | GET | `/api/v1/actions/domains/{domain}/intents/{intent_id}` | Get Intent |
| actions | POST | `/api/v1/actions/domains/{domain}/intents/{intent_id}/confirm` | Confirm Intent |
| actions | POST | `/api/v1/actions/domains/{domain}/intents/{intent_id}/confirmation` | Present Confirmation |
| actions | POST | `/api/v1/actions/domains/{domain}/intents/{intent_id}/decisions` | Decide Intent |
| actions | POST | `/api/v1/actions/domains/{domain}/intents/{intent_id}/validate` | Validate Intent |
| actions | GET | `/api/v1/actions/emergency-disable` | Read Emergency Disable |
| actions | PUT | `/api/v1/actions/emergency-disable` | Set Emergency Disable |
| admin-connectors | GET | `/api/v1/admin/sources/connectors` | List Connectors |
| admin-connectors | POST | `/api/v1/admin/sources/connectors` | Create Connector |
| admin-connectors | GET | `/api/v1/admin/sources/connectors/{config_id}` | Get Connector |
| admin-connectors | PUT | `/api/v1/admin/sources/connectors/{config_id}` | Replace Connector |
| admin-connectors | DELETE | `/api/v1/admin/sources/connectors/{config_id}` | Retire Connector |
| admin-connectors | POST | `/api/v1/admin/sources/connectors/{config_id}/disable` | Disable Connector |
| admin-connectors | POST | `/api/v1/admin/sources/connectors/{config_id}/enable` | Enable Connector |
| admin-identity | GET | `/api/v1/admin/identity/principals` | List Principals |
| admin-identity | GET | `/api/v1/admin/identity/principals/{principal_id}` | Get Principal |
| admin-identity | PUT | `/api/v1/admin/identity/principals/{principal_id}/domain-memberships/{domain_id}` | Put Domain Membership |
| admin-identity | DELETE | `/api/v1/admin/identity/principals/{principal_id}/domain-memberships/{domain_id}` | Delete Domain Membership |
| admin-identity | PUT | `/api/v1/admin/identity/principals/{principal_id}/grants/{grant_id}` | Put Grant |
| admin-identity | DELETE | `/api/v1/admin/identity/principals/{principal_id}/grants/{grant_id}` | Delete Grant |
| admin-identity | GET | `/api/v1/admin/identity/principals/{principal_id}/revocation` | Get Revocation |
| admin-identity | POST | `/api/v1/admin/identity/principals/{principal_id}/revocation` | Revoke Principal |
| admin-identity | DELETE | `/api/v1/admin/identity/principals/{principal_id}/revocation` | Lift Revocation |
| admin-identity | PUT | `/api/v1/admin/identity/principals/{principal_id}/role-assignments/{assignment_id}` | Put Role Assignment |
| admin-identity | DELETE | `/api/v1/admin/identity/principals/{principal_id}/role-assignments/{assignment_id}` | Delete Role Assignment |
| admin-identity | GET | `/api/v1/admin/identity/role-mapping` | Get Role Mapping |
| admin-platform-budgets | GET | `/api/v1/admin/platform/budgets` | List Budgets |
| admin-platform-budgets | POST | `/api/v1/admin/platform/budgets` | Create Budget |
| admin-platform-budgets | GET | `/api/v1/admin/platform/budgets/{budget_id}` | Get Budget |
| admin-platform-budgets | PUT | `/api/v1/admin/platform/budgets/{budget_id}` | Replace Budget |
| admin-platform-budgets | DELETE | `/api/v1/admin/platform/budgets/{budget_id}` | Delete Budget |
| admin-platform-domains | GET | `/api/v1/admin/platform/domains` | List Domains |
| admin-platform-domains | POST | `/api/v1/admin/platform/domains` | Create Domain |
| admin-platform-domains | GET | `/api/v1/admin/platform/domains/{domain_id}` | Get Domain |
| admin-platform-domains | POST | `/api/v1/admin/platform/domains/{domain_id}/retire` | Retire Domain |
| admin-platform-price-sheets | GET | `/api/v1/admin/platform/price-sheets` | List Price Sheets |
| admin-platform-price-sheets | POST | `/api/v1/admin/platform/price-sheets` | Upload Price Sheet |
| admin-platform-price-sheets | GET | `/api/v1/admin/platform/price-sheets/{snapshot_id}` | Get Price Sheet |
| admin-platform-price-sheets | GET | `/api/v1/admin/platform/price-sheets/{snapshot_id}/coverage` | Get Price Sheet Coverage |
| admin-platform-review-policy | GET | `/api/v1/admin/platform/review-policy` | Get Review Policy |
| admin-platform-review-policy | PUT | `/api/v1/admin/platform/review-policy` | Put Review Policy |
| admin-producers | GET | `/api/v1/admin/sources/producers` | List Producers |
| admin-producers | POST | `/api/v1/admin/sources/producers` | Create Producer |
| admin-producers | GET | `/api/v1/admin/sources/producers/{producer_id}` | Get Producer |
| admin-producers | POST | `/api/v1/admin/sources/producers/{producer_id}/disable` | Disable Producer |
| admin-producers | POST | `/api/v1/admin/sources/producers/{producer_id}/enable` | Enable Producer |
| admin-producers | POST | `/api/v1/admin/sources/producers/{producer_id}/rotate` | Rotate Producer |
| admin-system | GET | `/api/v1/admin/system/checklist` | System Checklist |
| admin-system | GET | `/api/v1/admin/system/status` | System Status |
| admin-system-settings | GET | `/api/v1/admin/system/settings` | List Settings |
| admin-system-settings | GET | `/api/v1/admin/system/settings/{key}` | Get Setting |
| admin-system-settings | PUT | `/api/v1/admin/system/settings/{key}` | Put Setting |
| agent-identity | GET | `/api/v1/agent-identity/domains/{domain}/aliases` | Read Alias |
| agent-identity | PUT | `/api/v1/agent-identity/domains/{domain}/aliases` | Declare Alias |
| audit | GET | `/api/v1/audit/chains/{chain_id}/records` | List Audit Records |
| audit | GET | `/api/v1/audit/chains/{chain_id}/verify` | Verify Audit Chain |
| audit | GET | `/api/v1/audit/denials` | List Audit Denials |
| audit | GET | `/api/v1/audit/export` | Export Audit Records |
| audit | GET | `/api/v1/audit/search` | Search Audit Records |
| audit | GET | `/api/v1/audit/siem/status` | Audit Siem Status |
| audit | GET | `/audit/chains/{chain_id}/records` | List Audit Records |
| audit | GET | `/audit/chains/{chain_id}/verify` | Verify Audit Chain |
| catalog | POST | `/api/v1/catalog/access/dependents` | Entities affected when a node fails |
| catalog | POST | `/api/v1/catalog/access/query` | Who reads or writes these data assets |
| catalog | GET | `/api/v1/catalog/access/region-groups` | Region groups available to the access query |
| catalog | GET | `/api/v1/catalog/entities` | List Entities |
| catalog | POST | `/api/v1/catalog/entities` | Create Entity |
| catalog | GET | `/api/v1/catalog/entities/{entity_id}` | Get Entity |
| catalog | PUT | `/api/v1/catalog/entities/{entity_id}` | Update Entity |
| catalog | POST | `/api/v1/catalog/entities/{entity_id}/deprecate` | Deprecate Entity |
| catalog | POST | `/api/v1/catalog/entities/{entity_id}/recertify` | Recertify Owner |
| catalog | GET | `/api/v1/catalog/export` | Export |
| catalog | POST | `/api/v1/catalog/grants/{entity_id}/publication` | Record Publication |
| catalog | POST | `/api/v1/catalog/grants/{entity_id}/publish` | Publish Grant |
| catalog | POST | `/api/v1/catalog/grants/{entity_id}/unpublish` | Unpublish Grant |
| catalog | POST | `/api/v1/catalog/import` | Import Entities |
| catalog | POST | `/api/v1/catalog/lineage/impact` | Impact |
| catalog | POST | `/api/v1/catalog/lineage/neighbors` | Neighbors |
| catalog | GET | `/api/v1/catalog/mcp-servers/{entity_id}/publication` | Mcp Publication Status |
| catalog | POST | `/api/v1/catalog/mcp-servers/{entity_id}/publication-record` | Record Mcp Publication |
| catalog | POST | `/api/v1/catalog/mcp-servers/{entity_id}/publish` | Publish Mcp Server |
| catalog | POST | `/api/v1/catalog/mcp-servers/{entity_id}/unpublish` | Unpublish Mcp Server |
| catalog | GET | `/api/v1/catalog/recertifications` | Recertifications |
| catalog | POST | `/api/v1/catalog/reconcile/stale-agents/confirm` | Stale Confirm |
| catalog | POST | `/api/v1/catalog/reconcile/stale-agents/dry-run` | Stale Dry Run |
| catalog | POST | `/api/v1/catalog/search` | Search |
| catalog | POST | `/catalog/access/dependents` | Entities affected when a node fails |
| catalog | POST | `/catalog/access/query` | Who reads or writes these data assets |
| catalog | GET | `/catalog/access/region-groups` | Region groups available to the access query |
| catalog | GET | `/catalog/entities` | List Entities |
| catalog | POST | `/catalog/entities` | Create Entity |
| catalog | GET | `/catalog/entities/{entity_id}` | Get Entity |
| catalog | PUT | `/catalog/entities/{entity_id}` | Update Entity |
| catalog | POST | `/catalog/entities/{entity_id}/deprecate` | Deprecate Entity |
| catalog | POST | `/catalog/entities/{entity_id}/recertify` | Recertify Owner |
| catalog | GET | `/catalog/export` | Export |
| catalog | POST | `/catalog/grants/{entity_id}/publication` | Record Publication |
| catalog | POST | `/catalog/grants/{entity_id}/publish` | Publish Grant |
| catalog | POST | `/catalog/grants/{entity_id}/unpublish` | Unpublish Grant |
| catalog | POST | `/catalog/import` | Import Entities |
| catalog | POST | `/catalog/lineage/impact` | Impact |
| catalog | POST | `/catalog/lineage/neighbors` | Neighbors |
| catalog | GET | `/catalog/mcp-servers/{entity_id}/publication` | Mcp Publication Status |
| catalog | POST | `/catalog/mcp-servers/{entity_id}/publication-record` | Record Mcp Publication |
| catalog | POST | `/catalog/mcp-servers/{entity_id}/publish` | Publish Mcp Server |
| catalog | POST | `/catalog/mcp-servers/{entity_id}/unpublish` | Unpublish Mcp Server |
| catalog | GET | `/catalog/recertifications` | Recertifications |
| catalog | POST | `/catalog/reconcile/stale-agents/confirm` | Stale Confirm |
| catalog | POST | `/catalog/reconcile/stale-agents/dry-run` | Stale Dry Run |
| catalog | POST | `/catalog/search` | Search |
| catalog-curation | GET | `/api/v1/catalog/curation/edges/{edge_id}` | Presented |
| catalog-curation | POST | `/api/v1/catalog/curation/edges/{edge_id}/decisions` | Decide |
| catalog-curation | GET | `/api/v1/catalog/curation/edges/{edge_id}/observations` | Observations |
| catalog-curation | GET | `/api/v1/catalog/curation/edges/{edge_id}/overrides` | Overrides |
| catalog-curation | GET | `/api/v1/catalog/curation/review-queue` | Review Queue |
| catalog-curation | POST | `/api/v1/catalog/curation/review-queue/{item_id}/resolve` | Resolve Review Item |
| catalog-curation | GET | `/catalog/curation/edges/{edge_id}` | Presented |
| catalog-curation | POST | `/catalog/curation/edges/{edge_id}/decisions` | Decide |
| catalog-curation | GET | `/catalog/curation/edges/{edge_id}/observations` | Observations |
| catalog-curation | GET | `/catalog/curation/edges/{edge_id}/overrides` | Overrides |
| catalog-curation | GET | `/catalog/curation/review-queue` | Review Queue |
| catalog-curation | POST | `/catalog/curation/review-queue/{item_id}/resolve` | Resolve Review Item |
| compliance | GET | `/api/v1/compliance/domains/{domain}/bundle` | Get Bundle |
| compliance | GET | `/api/v1/compliance/domains/{domain}/bundle/export` | Export Bundle |
| compliance | GET | `/api/v1/compliance/frameworks` | List Frameworks |
| compliance | GET | `/api/v1/compliance/frameworks/{framework_id}` | Get Framework |
| copilot | GET | `/api/v1/copilot/conversations` | List Conversations |
| copilot | POST | `/api/v1/copilot/conversations` | Create Conversation |
| copilot | GET | `/api/v1/copilot/conversations/{conversation_id}` | Get Conversation |
| copilot | DELETE | `/api/v1/copilot/conversations/{conversation_id}` | Delete Conversation |
| copilot | POST | `/api/v1/copilot/conversations/{conversation_id}/messages` | Post Message |
| copilot | GET | `/api/v1/copilot/status` | Copilot Status |
| dashboards | GET | `/api/v1/dashboards/domains/{domain}/{metric}` | Get Dashboard |
| deploy | POST | `/api/v1/deploy/apply/domains/{domain}/plans/apply` | Apply Plan |
| deploy | POST | `/api/v1/deploy/apply/domains/{domain}/plans/approve` | Approve Plan |
| deploy | POST | `/api/v1/deploy/apply/domains/{domain}/uninstall/preview` | Preview Uninstall |
| deploy | POST | `/api/v1/deploy/plan` | Plan |
| deploy | POST | `/api/v1/deploy/scan` | Scan |
| deploy | POST | `/v1/deploy/plan` | Plan |
| deploy | POST | `/v1/deploy/scan` | Scan |
| evaluation | GET | `/api/v1/evaluation/domains/{domain}/calibration-samples` | Calibration Sample |
| evaluation | GET | `/api/v1/evaluation/domains/{domain}/quality` | Quality |
| evaluation | GET | `/api/v1/evaluation/domains/{domain}/results` | List Results |
| federation | GET | `/api/v1/federation/cell-summary` | Cell Summary |
| federation | GET | `/api/v1/federation/summary` | Merged Summary |
| finops | GET | `/api/v1/finops/domains/{domain}/forecast` | Get Forecast |
| gateways | GET | `/api/v1/gateways/domains/{domain}/gateways` | List Gateways |
| gateways | POST | `/api/v1/gateways/domains/{domain}/gateways` | Register Gateway |
| gateways | GET | `/api/v1/gateways/domains/{domain}/gateways/{gateway_id}` | Get Gateway |
| gateways | GET | `/api/v1/gateways/domains/{domain}/gateways/{gateway_id}/inventory` | Get Inventory |
| gateways | POST | `/api/v1/gateways/domains/{domain}/gateways/{gateway_id}/mode` | Change Gateway Mode |
| gateways | POST | `/api/v1/gateways/domains/{domain}/gateways/{gateway_id}/sync` | Sync Gateway |
| health | GET | `/healthz` | Healthz |
| health | GET | `/readyz` | Readyz |
| ingest | POST | `/api/v1/ingest/events` | Events |
| ingest | POST | `/api/v1/ingest/otlp/metrics` | Metrics |
| ingest | POST | `/api/v1/ingest/otlp/traces` | Traces |
| ingest | POST | `/v1/ingest/events` | Events |
| ingest | POST | `/v1/ingest/otlp/metrics` | Metrics |
| ingest | POST | `/v1/ingest/otlp/traces` | Traces |
| lifecycle | GET | `/api/v1/lifecycle/holds` | List Holds |
| lifecycle | POST | `/api/v1/lifecycle/holds` | Place Hold |
| lifecycle | DELETE | `/api/v1/lifecycle/holds/{hold_id}` | Release Hold |
| lifecycle | GET | `/api/v1/lifecycle/requests` | List Requests |
| lifecycle | POST | `/api/v1/lifecycle/requests` | Submit Request |
| lifecycle | GET | `/api/v1/lifecycle/requests/{request_id}` | Get Request |
| lifecycle | GET | `/api/v1/lifecycle/status` | Status |
| map | GET | `/api/v1/map/domains/{domain_id}/viewport` | Get Viewport |
| mcp-admin | GET | `/api/v1/mcp/admin/servers` | List Servers |
| mcp-admin | POST | `/api/v1/mcp/admin/servers` | Register Server |
| mcp-admin | GET | `/api/v1/mcp/admin/servers/{server_id}` | Get Server |
| mcp-admin | PATCH | `/api/v1/mcp/admin/servers/{server_id}` | Update Server |
| mcp-admin | POST | `/api/v1/mcp/admin/servers/{server_id}/sync` | Sync Server |
| mcp-admin | GET | `/api/v1/mcp/admin/servers/{server_id}/tools` | List Tools |
| mcp-admin | POST | `/api/v1/mcp/admin/servers/{server_id}/tools/{tool_name}/approval` | Approve Tool |
| mcp-admin | DELETE | `/api/v1/mcp/admin/servers/{server_id}/tools/{tool_name}/approval` | Revoke Tool |
| me | GET | `/api/v1/me/access` | My Access |
| me | GET | `/api/v1/me/domains` | My Domains |
| recommendations | GET | `/api/v1/recommendations/domains/{domain}` | List Recommendations |
| recommendations | POST | `/api/v1/recommendations/domains/{domain}/executions` | Refuse Execution |
| recommendations | GET | `/api/v1/recommendations/domains/{domain}/items/{recommendation_id}` | Get Recommendation |
| recommendations | POST | `/api/v1/recommendations/domains/{domain}/match` | Match Agents |
| recommendations | POST | `/api/v1/recommendations/domains/{domain}/match/feedback` | Record Match Feedback |
| recommendations | GET | `/api/v1/recommendations/domains/{domain}/match/metrics` | Match Metrics |
| recommendations | POST | `/api/v1/recommendations/domains/{domain}/review-requests` | Create Review Request |
| reconciliation | GET | `/api/v1/reconciliation/domains/{domain}` | Reconcile |
| replay | GET | `/api/v1/replay/domains/{domain_id}/traces` | List Traces |
| replay | GET | `/api/v1/replay/domains/{domain_id}/traces/{trace_id}` | Get Trace |
| reports | GET | `/api/v1/reports/domains/{domain_id}/reports` | List Reports |
| reports | POST | `/api/v1/reports/domains/{domain_id}/reports` | Create Report |
| reports | GET | `/api/v1/reports/domains/{domain_id}/reports/{report_id}` | Get Report |
| reports | PUT | `/api/v1/reports/domains/{domain_id}/reports/{report_id}` | Update Report |
| reports | DELETE | `/api/v1/reports/domains/{domain_id}/reports/{report_id}` | Delete Report |
| reports | POST | `/api/v1/reports/domains/{domain_id}/reports/{report_id}/publication` | Request Publication |
| reports | POST | `/api/v1/reports/domains/{domain_id}/reports/{report_id}/publication/decision` | Decide Publication |
| reports | POST | `/api/v1/reports/domains/{domain_id}/reports/{report_id}/run` | Run Report |
| reports | POST | `/api/v1/reports/domains/{domain_id}/reports/{report_id}/shares` | Share Report |
| reports | DELETE | `/api/v1/reports/domains/{domain_id}/reports/{report_id}/shares/{principal_id}` | Unshare Report |
| review | GET | `/api/v1/review/domains/{domain}/items` | List Items |
| review | GET | `/api/v1/review/domains/{domain}/items/{item_id}` | Get Item |
| review | POST | `/api/v1/review/domains/{domain}/items/{item_id}/assignment` | Assign Item |
| review | POST | `/api/v1/review/domains/{domain}/items/{item_id}/decisions` | Decide Item |
| sandbox | GET | `/api/v1/sandbox/entities` | Entities |
| sandbox | POST | `/api/v1/sandbox/reset` | Reset |
| sandbox | GET | `/api/v1/sandbox/status` | Status |
| sources-status | GET | `/api/v1/admin/sources/status` | Admin Source Status |
| sources-status | GET | `/api/v1/sources/status` | Source Status |
| ui-adapters | GET | `/api/v1/audit/domains` | Audit Domains |
| ui-adapters | GET | `/api/v1/audit/domains/{domain}/records` | Audit Domain Records |
| ui-adapters | GET | `/api/v1/audit/domains/{domain}/verify` | Audit Domain Verify |
| ui-adapters | GET | `/api/v1/capabilities` | Capabilities |
| ui-adapters | GET | `/api/v1/catalog/domains/{domain}/curation/edges/{edge_id}` | Read Edge In Domain |
| ui-adapters | POST | `/api/v1/catalog/domains/{domain}/curation/edges/{edge_id}/decisions` | Decide In Domain |
| ui-adapters | GET | `/api/v1/catalog/domains/{domain}/entities` | List Domain Entities |
| ui-adapters | POST | `/api/v1/catalog/domains/{domain}/entities` | Create Entity In Domain |
| ui-adapters | PUT | `/api/v1/catalog/domains/{domain}/entities/{entity_id}` | Update Entity In Domain |
| ui-adapters | GET | `/api/v1/catalog/domains/{domain}/export` | Export Domain |
| ui-adapters | POST | `/api/v1/catalog/domains/{domain}/search` | Search Domain |
| workspaces | GET | `/api/v1/workspaces/{role}` | Workspace |

## Endpoints

### Tag: actions

#### GET `/api/v1/actions/domains/{domain}/intents`

- Operation id: `list_intents_api_v1_actions_domains__domain__intents_get`
- Summary: List Intents
- Parameters: `domain` (path, required), `state` (query), `cursor` (query), `limit` (query)
- Responses: `200` `ActionList`; `422` `HTTPValidationError`

#### POST `/api/v1/actions/domains/{domain}/intents`

- Operation id: `draft_intent_api_v1_actions_domains__domain__intents_post`
- Summary: Draft Intent
- Parameters: `domain` (path, required)
- Request body: application/json: `DraftIntentBody` (required)
- Responses: `201` `ActionView`; `422` `HTTPValidationError`

#### GET `/api/v1/actions/domains/{domain}/intents/{intent_id}`

- Operation id: `get_intent_api_v1_actions_domains__domain__intents__intent_id__get`
- Summary: Get Intent
- Parameters: `domain` (path, required), `intent_id` (path, required)
- Responses: `200` `ActionView`; `422` `HTTPValidationError`

#### POST `/api/v1/actions/domains/{domain}/intents/{intent_id}/confirm`

- Operation id: `confirm_intent_api_v1_actions_domains__domain__intents__intent_id__confirm_post`
- Summary: Confirm Intent
- Parameters: `domain` (path, required), `intent_id` (path, required)
- Request body: application/json: `ConfirmBody` (required)
- Responses: `200` `ActionView`; `422` `HTTPValidationError`

#### POST `/api/v1/actions/domains/{domain}/intents/{intent_id}/confirmation`

- Operation id: `present_confirmation_api_v1_actions_domains__domain__intents__intent_id__confirmation_post`
- Summary: Present Confirmation
- Parameters: `domain` (path, required), `intent_id` (path, required)
- Responses: `200` `ActionView`; `422` `HTTPValidationError`

#### POST `/api/v1/actions/domains/{domain}/intents/{intent_id}/decisions`

- Operation id: `decide_intent_api_v1_actions_domains__domain__intents__intent_id__decisions_post`
- Summary: Decide Intent
- Parameters: `domain` (path, required), `intent_id` (path, required)
- Request body: application/json: `neurosphere_api__actions__models__DecisionBody` (required)
- Responses: `200` `ActionView`; `422` `HTTPValidationError`

#### POST `/api/v1/actions/domains/{domain}/intents/{intent_id}/validate`

- Operation id: `validate_intent_api_v1_actions_domains__domain__intents__intent_id__validate_post`
- Summary: Validate Intent
- Parameters: `domain` (path, required), `intent_id` (path, required)
- Responses: `200` `ActionView`; `422` `HTTPValidationError`

#### GET `/api/v1/actions/emergency-disable`

- Operation id: `read_emergency_disable_api_v1_actions_emergency_disable_get`
- Summary: Read Emergency Disable
- Responses: `200` `EmergencyDisableView`

#### PUT `/api/v1/actions/emergency-disable`

- Operation id: `set_emergency_disable_api_v1_actions_emergency_disable_put`
- Summary: Set Emergency Disable
- Request body: application/json: `EmergencyDisableBody` (required)
- Responses: `200` `EmergencyDisableView`; `422` `HTTPValidationError`

### Tag: admin-connectors

#### GET `/api/v1/admin/sources/connectors`

- Operation id: `list_connectors_api_v1_admin_sources_connectors_get`
- Summary: List Connectors
- Parameters: `connector_kind` (query), `include_retired` (query), `limit` (query)
- Responses: `200` `ConnectorPage`; `422` `HTTPValidationError`

#### POST `/api/v1/admin/sources/connectors`

- Operation id: `create_connector_api_v1_admin_sources_connectors_post`
- Summary: Create Connector
- Request body: application/json: `ConnectorConfig` (required)
- Responses: `201` `ConnectorView`; `422` `HTTPValidationError`

#### GET `/api/v1/admin/sources/connectors/{config_id}`

- Operation id: `get_connector_api_v1_admin_sources_connectors__config_id__get`
- Summary: Get Connector
- Parameters: `config_id` (path, required)
- Responses: `200` `ConnectorView`; `422` `HTTPValidationError`

#### PUT `/api/v1/admin/sources/connectors/{config_id}`

- Operation id: `replace_connector_api_v1_admin_sources_connectors__config_id__put`
- Summary: Replace Connector
- Parameters: `config_id` (path, required), `If-Match` (header, required)
- Request body: application/json: `ConnectorConfig` (required)
- Responses: `200` `ConnectorView`; `422` `HTTPValidationError`

#### DELETE `/api/v1/admin/sources/connectors/{config_id}`

- Operation id: `retire_connector_api_v1_admin_sources_connectors__config_id__delete`
- Summary: Retire Connector
- Parameters: `config_id` (path, required), `If-Match` (header, required)
- Responses: `200` `ConnectorView`; `422` `HTTPValidationError`

#### POST `/api/v1/admin/sources/connectors/{config_id}/disable`

- Operation id: `disable_connector_api_v1_admin_sources_connectors__config_id__disable_post`
- Summary: Disable Connector
- Parameters: `config_id` (path, required), `If-Match` (header, required)
- Responses: `200` `ConnectorView`; `422` `HTTPValidationError`

#### POST `/api/v1/admin/sources/connectors/{config_id}/enable`

- Operation id: `enable_connector_api_v1_admin_sources_connectors__config_id__enable_post`
- Summary: Enable Connector
- Parameters: `config_id` (path, required), `If-Match` (header, required)
- Responses: `200` `ConnectorView`; `422` `HTTPValidationError`

### Tag: admin-identity

#### GET `/api/v1/admin/identity/principals`

- Operation id: `list_principals_api_v1_admin_identity_principals_get`
- Summary: List Principals
- Parameters: `cursor` (query), `limit` (query)
- Responses: `200` `PrincipalPage`; `422` `HTTPValidationError`

#### GET `/api/v1/admin/identity/principals/{principal_id}`

- Operation id: `get_principal_api_v1_admin_identity_principals__principal_id__get`
- Summary: Get Principal
- Parameters: `principal_id` (path, required)
- Responses: `200` `PrincipalAccessSummary`; `422` `HTTPValidationError`

#### PUT `/api/v1/admin/identity/principals/{principal_id}/domain-memberships/{domain_id}`

- Operation id: `put_domain_membership_api_v1_admin_identity_principals__principal_id__domain_memberships__domain_id__put`
- Summary: Put Domain Membership
- Parameters: `principal_id` (path, required), `domain_id` (path, required), `If-Match` (header)
- Request body: application/json: `DomainMembershipChange` (required)
- Responses: `200` `PrincipalAccessSummary`; `422` `HTTPValidationError`

#### DELETE `/api/v1/admin/identity/principals/{principal_id}/domain-memberships/{domain_id}`

- Operation id: `delete_domain_membership_api_v1_admin_identity_principals__principal_id__domain_memberships__domain_id__delete`
- Summary: Delete Domain Membership
- Parameters: `principal_id` (path, required), `domain_id` (path, required), `reason` (query), `If-Match` (header)
- Responses: `200` `PrincipalAccessSummary`; `422` `HTTPValidationError`

#### PUT `/api/v1/admin/identity/principals/{principal_id}/grants/{grant_id}`

- Operation id: `put_grant_api_v1_admin_identity_principals__principal_id__grants__grant_id__put`
- Summary: Put Grant
- Parameters: `principal_id` (path, required), `grant_id` (path, required), `If-Match` (header)
- Request body: application/json: `ResourceGrantChange` (required)
- Responses: `200` `PrincipalAccessSummary`; `422` `HTTPValidationError`

#### DELETE `/api/v1/admin/identity/principals/{principal_id}/grants/{grant_id}`

- Operation id: `delete_grant_api_v1_admin_identity_principals__principal_id__grants__grant_id__delete`
- Summary: Delete Grant
- Parameters: `principal_id` (path, required), `grant_id` (path, required), `If-Match` (header)
- Responses: `200` `PrincipalAccessSummary`; `422` `HTTPValidationError`

#### GET `/api/v1/admin/identity/principals/{principal_id}/revocation`

- Operation id: `get_revocation_api_v1_admin_identity_principals__principal_id__revocation_get`
- Summary: Get Revocation
- Parameters: `principal_id` (path, required)
- Responses: `200` `RevocationStatus`; `422` `HTTPValidationError`

#### POST `/api/v1/admin/identity/principals/{principal_id}/revocation`

- Operation id: `revoke_principal_api_v1_admin_identity_principals__principal_id__revocation_post`
- Summary: Revoke Principal
- Parameters: `principal_id` (path, required)
- Request body: application/json: `RevocationRequest` (required)
- Responses: `200` `RevocationStatus`; `422` `HTTPValidationError`

#### DELETE `/api/v1/admin/identity/principals/{principal_id}/revocation`

- Operation id: `lift_revocation_api_v1_admin_identity_principals__principal_id__revocation_delete`
- Summary: Lift Revocation
- Parameters: `principal_id` (path, required), `reason` (query)
- Responses: `200` `RevocationStatus`; `422` `HTTPValidationError`

#### PUT `/api/v1/admin/identity/principals/{principal_id}/role-assignments/{assignment_id}`

- Operation id: `put_role_assignment_api_v1_admin_identity_principals__principal_id__role_assignments__assignment_id__put`
- Summary: Put Role Assignment
- Parameters: `principal_id` (path, required), `assignment_id` (path, required), `If-Match` (header)
- Request body: application/json: `RoleAssignmentChange` (required)
- Responses: `200` `PrincipalAccessSummary`; `422` `HTTPValidationError`

#### DELETE `/api/v1/admin/identity/principals/{principal_id}/role-assignments/{assignment_id}`

- Operation id: `delete_role_assignment_api_v1_admin_identity_principals__principal_id__role_assignments__assignment_id__delete`
- Summary: Delete Role Assignment
- Parameters: `principal_id` (path, required), `assignment_id` (path, required), `reason` (query), `If-Match` (header)
- Responses: `200` `PrincipalAccessSummary`; `422` `HTTPValidationError`

#### GET `/api/v1/admin/identity/role-mapping`

- Operation id: `get_role_mapping_api_v1_admin_identity_role_mapping_get`
- Summary: Get Role Mapping
- Description: The effective Entra claim to role mapping of this deployment, read only: the bound tenant, audience and cloud, and each entry's id, claim kind (`roles` or `groups`), claim value, role, domain mode (`all` or `explicit`) and customer control flag. `active` is false and `entries` empty when no mapping is configured. The mapping is deployment configuration (`NS_AUTH_ROLE_MAPPINGS`) and cannot be changed through the API. Needs `policy.manage` on the whole deployment (the customer control domain).
- Responses: `200` `RoleMappingView`

### Tag: admin-platform-budgets

#### GET `/api/v1/admin/platform/budgets`

- Operation id: `list_budgets_api_v1_admin_platform_budgets_get`
- Summary: List Budgets
- Parameters: `include_retired` (query), `limit` (query)
- Responses: `200` `BudgetPage`; `422` `HTTPValidationError`

#### POST `/api/v1/admin/platform/budgets`

- Operation id: `create_budget_api_v1_admin_platform_budgets_post`
- Summary: Create Budget
- Request body: application/json: `SpendBudget` (required)
- Responses: `201` `BudgetView`; `422` `HTTPValidationError`

#### GET `/api/v1/admin/platform/budgets/{budget_id}`

- Operation id: `get_budget_api_v1_admin_platform_budgets__budget_id__get`
- Summary: Get Budget
- Parameters: `budget_id` (path, required)
- Responses: `200` `BudgetView`; `422` `HTTPValidationError`

#### PUT `/api/v1/admin/platform/budgets/{budget_id}`

- Operation id: `replace_budget_api_v1_admin_platform_budgets__budget_id__put`
- Summary: Replace Budget
- Parameters: `budget_id` (path, required), `If-Match` (header, required)
- Request body: application/json: `SpendBudget` (required)
- Responses: `200` `BudgetView`; `422` `HTTPValidationError`

#### DELETE `/api/v1/admin/platform/budgets/{budget_id}`

- Operation id: `delete_budget_api_v1_admin_platform_budgets__budget_id__delete`
- Summary: Delete Budget
- Parameters: `budget_id` (path, required), `If-Match` (header, required)
- Responses: `200` `BudgetView`; `422` `HTTPValidationError`

### Tag: admin-platform-domains

#### GET `/api/v1/admin/platform/domains`

- Operation id: `list_domains_api_v1_admin_platform_domains_get`
- Summary: List Domains
- Parameters: `include_retired` (query), `limit` (query)
- Responses: `200` `DomainPage`; `422` `HTTPValidationError`

#### POST `/api/v1/admin/platform/domains`

- Operation id: `create_domain_api_v1_admin_platform_domains_post`
- Summary: Create Domain
- Request body: application/json: `DomainDefinition` (required)
- Responses: `201` `neurosphere_api__admin__platform__models__DomainView`; `422` `HTTPValidationError`

#### GET `/api/v1/admin/platform/domains/{domain_id}`

- Operation id: `get_domain_api_v1_admin_platform_domains__domain_id__get`
- Summary: Get Domain
- Parameters: `domain_id` (path, required)
- Responses: `200` `neurosphere_api__admin__platform__models__DomainView`; `422` `HTTPValidationError`

#### POST `/api/v1/admin/platform/domains/{domain_id}/retire`

- Operation id: `retire_domain_api_v1_admin_platform_domains__domain_id__retire_post`
- Summary: Retire Domain
- Parameters: `domain_id` (path, required), `If-Match` (header, required)
- Responses: `200` `neurosphere_api__admin__platform__models__DomainView`; `422` `HTTPValidationError`

### Tag: admin-platform-price-sheets

#### GET `/api/v1/admin/platform/price-sheets`

- Operation id: `list_price_sheets_api_v1_admin_platform_price_sheets_get`
- Summary: List Price Sheets
- Responses: `200` `PriceSheetPage`

#### POST `/api/v1/admin/platform/price-sheets`

- Operation id: `upload_price_sheet_api_v1_admin_platform_price_sheets_post`
- Summary: Upload Price Sheet
- Request body: application/json: `PriceSheetUpload` (required)
- Responses: `201` `PriceSheetUploadView`; `422` `HTTPValidationError`

#### GET `/api/v1/admin/platform/price-sheets/{snapshot_id}`

- Operation id: `get_price_sheet_api_v1_admin_platform_price_sheets__snapshot_id__get`
- Summary: Get Price Sheet
- Parameters: `snapshot_id` (path, required)
- Responses: `200` `PriceSheetView`; `422` `HTTPValidationError`

#### GET `/api/v1/admin/platform/price-sheets/{snapshot_id}/coverage`

- Operation id: `get_price_sheet_coverage_api_v1_admin_platform_price_sheets__snapshot_id__coverage_get`
- Summary: Get Price Sheet Coverage
- Parameters: `snapshot_id` (path, required)
- Responses: `200` `CoverageView`; `422` `HTTPValidationError`

### Tag: admin-platform-review-policy

#### GET `/api/v1/admin/platform/review-policy`

- Operation id: `get_review_policy_api_v1_admin_platform_review_policy_get`
- Summary: Get Review Policy
- Responses: `200` `ReviewPolicyView`

#### PUT `/api/v1/admin/platform/review-policy`

- Operation id: `put_review_policy_api_v1_admin_platform_review_policy_put`
- Summary: Put Review Policy
- Parameters: `If-Match` (header, required)
- Request body: application/json: `ReviewPolicyDocument` (required)
- Responses: `200` `ReviewPolicyWriteView`; `422` `HTTPValidationError`

### Tag: admin-producers

#### GET `/api/v1/admin/sources/producers`

- Operation id: `list_producers_api_v1_admin_sources_producers_get`
- Summary: List Producers
- Parameters: `limit` (query)
- Responses: `200` `ProducerPage`; `422` `HTTPValidationError`

#### POST `/api/v1/admin/sources/producers`

- Operation id: `create_producer_api_v1_admin_sources_producers_post`
- Summary: Create Producer
- Request body: application/json: `ProducerCreateRequest` (required)
- Responses: `201` `ProducerSecretIssued`; `422` `HTTPValidationError`

#### GET `/api/v1/admin/sources/producers/{producer_id}`

- Operation id: `get_producer_api_v1_admin_sources_producers__producer_id__get`
- Summary: Get Producer
- Parameters: `producer_id` (path, required)
- Responses: `200` `ProducerView`; `422` `HTTPValidationError`

#### POST `/api/v1/admin/sources/producers/{producer_id}/disable`

- Operation id: `disable_producer_api_v1_admin_sources_producers__producer_id__disable_post`
- Summary: Disable Producer
- Parameters: `producer_id` (path, required), `If-Match` (header)
- Responses: `200` `ProducerView`; `422` `HTTPValidationError`

#### POST `/api/v1/admin/sources/producers/{producer_id}/enable`

- Operation id: `enable_producer_api_v1_admin_sources_producers__producer_id__enable_post`
- Summary: Enable Producer
- Parameters: `producer_id` (path, required), `If-Match` (header)
- Responses: `200` `ProducerView`; `422` `HTTPValidationError`

#### POST `/api/v1/admin/sources/producers/{producer_id}/rotate`

- Operation id: `rotate_producer_api_v1_admin_sources_producers__producer_id__rotate_post`
- Summary: Rotate Producer
- Parameters: `producer_id` (path, required), `If-Match` (header)
- Responses: `200` `ProducerSecretIssued`; `422` `HTTPValidationError`

### Tag: admin-system

#### GET `/api/v1/admin/system/checklist`

- Operation id: `system_checklist_api_v1_admin_system_checklist_get`
- Summary: System Checklist
- Responses: `200` `ChecklistPage`

#### GET `/api/v1/admin/system/status`

- Operation id: `system_status_api_v1_admin_system_status_get`
- Summary: System Status
- Responses: `200` `SystemStatus`

### Tag: admin-system-settings

#### GET `/api/v1/admin/system/settings`

- Operation id: `list_settings_api_v1_admin_system_settings_get`
- Summary: List Settings
- Responses: `200` `SettingsPage`

#### GET `/api/v1/admin/system/settings/{key}`

- Operation id: `get_setting_api_v1_admin_system_settings__key__get`
- Summary: Get Setting
- Parameters: `key` (path, required)
- Responses: `200` `SettingView`; `422` `HTTPValidationError`

#### PUT `/api/v1/admin/system/settings/{key}`

- Operation id: `put_setting_api_v1_admin_system_settings__key__put`
- Summary: Put Setting
- Parameters: `key` (path, required), `If-Match` (header)
- Request body: application/json: `object` (optional)
- Responses: `200` `SettingWriteResult`; `422` `HTTPValidationError`

### Tag: agent-identity

#### GET `/api/v1/agent-identity/domains/{domain}/aliases`

- Operation id: `read_alias_api_v1_agent_identity_domains__domain__aliases_get`
- Summary: Read Alias
- Parameters: `domain` (path, required), `source_id` (query, required), `external_agent_id` (query, required)
- Responses: `200` `AliasView`; `422` `HTTPValidationError`

#### PUT `/api/v1/agent-identity/domains/{domain}/aliases`

- Operation id: `declare_alias_api_v1_agent_identity_domains__domain__aliases_put`
- Summary: Declare Alias
- Description: Declare (or repoint) the alias from an external agent id seen in telemetry to a catalog agent of this domain. A previous active alias for the same key is retired first. `reresolve_needed` is true when events already processed must be re-resolved with the returned operator job (`python -m neurosphere_workers.agent_identity reresolve`).
- Parameters: `domain` (path, required)
- Request body: application/json: `AliasDeclareRequest` (required)
- Responses: `200` `AliasDeclareView`; `422` `HTTPValidationError`

### Tag: audit

#### GET `/api/v1/audit/chains/{chain_id}/records`

- Operation id: `list_audit_records_api_v1_audit_chains__chain_id__records_get`
- Summary: List Audit Records
- Parameters: `chain_id` (path, required), `cursor` (query), `page_size` (query)
- Responses: `200` `Page_AuditRecord_`; `422` `HTTPValidationError`

#### GET `/api/v1/audit/chains/{chain_id}/verify`

- Operation id: `verify_audit_chain_api_v1_audit_chains__chain_id__verify_get`
- Summary: Verify Audit Chain
- Parameters: `chain_id` (path, required)
- Responses: `200` `ChainVerification`; `422` `HTTPValidationError`

#### GET `/api/v1/audit/denials`

- Operation id: `list_audit_denials_api_v1_audit_denials_get`
- Summary: List Audit Denials
- Parameters: `cursor` (query), `page_size` (query)
- Responses: `200` `Page_AuditRecord_`; `422` `HTTPValidationError`

#### GET `/api/v1/audit/export`

- Operation id: `export_audit_records_api_v1_audit_export_get`
- Summary: Export Audit Records
- Parameters: `format` (query), `since` (query, required), `until` (query, required), `domain` (query), `operation` (query), `kind` (query), `outcome` (query), `actor` (query), `correlation_id` (query)
- Responses: `200` no body; `422` `HTTPValidationError`

#### GET `/api/v1/audit/search`

- Operation id: `search_audit_records_api_v1_audit_search_get`
- Summary: Search Audit Records
- Parameters: `cursor` (query), `page_size` (query), `since` (query, required), `until` (query, required), `domain` (query), `operation` (query), `kind` (query), `outcome` (query), `actor` (query), `correlation_id` (query)
- Responses: `200` `AuditSearchPage`; `422` `HTTPValidationError`

#### GET `/api/v1/audit/siem/status`

- Operation id: `audit_siem_status_api_v1_audit_siem_status_get`
- Summary: Audit Siem Status
- Responses: `200` `AuditSiemStatus`

#### GET `/audit/chains/{chain_id}/records`

**Deprecated**

- Operation id: `list_audit_records_audit_chains__chain_id__records_get`
- Summary: List Audit Records
- Parameters: `chain_id` (path, required), `cursor` (query), `page_size` (query)
- Responses: `200` `Page_AuditRecord_`; `422` `HTTPValidationError`

#### GET `/audit/chains/{chain_id}/verify`

**Deprecated**

- Operation id: `verify_audit_chain_audit_chains__chain_id__verify_get`
- Summary: Verify Audit Chain
- Parameters: `chain_id` (path, required)
- Responses: `200` `ChainVerification`; `422` `HTTPValidationError`

### Tag: catalog

#### POST `/api/v1/catalog/access/dependents`

- Operation id: `dependents_api_v1_catalog_access_dependents_post`
- Summary: Entities affected when a node fails
- Description: Entities that depend on a failing service or tool (blast radius), grouped by distance (max_depth 1 to 5; any other value answers 422 with a reason code), each with the relation path. Results are observed or curated edges, not entitlements. A truncated result is partial: truncated_reason says which bound stopped the walk. Only in-scope entities appear. Each call appends one allowed-read audit record holding the domains read and the result count only.
- Request body: application/json: `AccessDependentsRequest` (required)
- Responses: `200` `AccessDependentsResponse`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/access/query`

- Operation id: `access_query_api_v1_catalog_access_query_post`
- Summary: Who reads or writes these data assets
- Description: Which in-scope agents and tools read or wrote the selected data assets. Results are observed edges (who did), not entitlements (who could). An empty sensitivity_categories list or a null value on an asset means not assessed, never no; such assets are listed under unassessed_assets only when include_unassessed is true. When region_group and residency_regions are both given, their regions are unioned. residency_regions values are validated against the known-region list for the caller's cloud; an unknown region answers 422 with reason unknown_region. The eu group is a NeuroSphere classification of Azure region locations and implies nothing about compliance. A truncated result is partial: truncated_reason says which bound stopped the scan and assets_scanned how many assets were examined. Scope comes only from the caller's identity; domain_ids narrows within it. Each call appends one allowed-read audit record holding the domains read and the result count only.
- Request body: application/json: `AccessQueryRequest` (required)
- Responses: `200` `AccessQueryResponse`; `422` `HTTPValidationError`

#### GET `/api/v1/catalog/access/region-groups`

- Operation id: `region_groups_api_v1_catalog_access_region_groups_get`
- Summary: Region groups available to the access query
- Description: Region group names and their member regions for the caller's cloud (the Government cloud has none). The eu group is a NeuroSphere classification of Azure region locations and implies nothing about compliance.
- Responses: `200` `RegionGroupsResponse`

#### GET `/api/v1/catalog/entities`

- Operation id: `list_entities_api_v1_catalog_entities_get`
- Summary: List Entities
- Parameters: `entity_type` (query), `domain_id` (query), `lifecycle` (query), `page_size` (query), `cursor` (query)
- Responses: `200` `Page_Union_Person__Agent__AgentVersion__ModelDeployment__GroundingSource__Tool__Service__Domain__Owner__Policy__RecommendationReference__RunReference__Grant__McpServer__`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/entities`

- Operation id: `create_entity_api_v1_catalog_entities_post`
- Summary: Create Entity
- Request body: application/json: `object` (required)
- Responses: `201` `Person` or `Agent` or `AgentVersion` or `ModelDeployment` or `GroundingSource` or `neurosphere_contracts__catalog__v1__tool__Tool` or `Service` or `Domain` or `neurosphere_contracts__catalog__v1__owner__Owner` or `Policy` or `RecommendationReference` or `RunReference` or `Grant` or `McpServer`; `422` `HTTPValidationError`

#### GET `/api/v1/catalog/entities/{entity_id}`

- Operation id: `get_entity_api_v1_catalog_entities__entity_id__get`
- Summary: Get Entity
- Parameters: `entity_id` (path, required)
- Responses: `200` `Person` or `Agent` or `AgentVersion` or `ModelDeployment` or `GroundingSource` or `neurosphere_contracts__catalog__v1__tool__Tool` or `Service` or `Domain` or `neurosphere_contracts__catalog__v1__owner__Owner` or `Policy` or `RecommendationReference` or `RunReference` or `Grant` or `McpServer`; `422` `HTTPValidationError`

#### PUT `/api/v1/catalog/entities/{entity_id}`

- Operation id: `update_entity_api_v1_catalog_entities__entity_id__put`
- Summary: Update Entity
- Parameters: `entity_id` (path, required), `If-Match` (header, required)
- Request body: application/json: `object` (required)
- Responses: `200` `Person` or `Agent` or `AgentVersion` or `ModelDeployment` or `GroundingSource` or `neurosphere_contracts__catalog__v1__tool__Tool` or `Service` or `Domain` or `neurosphere_contracts__catalog__v1__owner__Owner` or `Policy` or `RecommendationReference` or `RunReference` or `Grant` or `McpServer`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/entities/{entity_id}/deprecate`

- Operation id: `deprecate_entity_api_v1_catalog_entities__entity_id__deprecate_post`
- Summary: Deprecate Entity
- Parameters: `entity_id` (path, required), `If-Match` (header, required)
- Request body: application/json: `DeprecateRequest` or `null` (optional)
- Responses: `200` `Person` or `Agent` or `AgentVersion` or `ModelDeployment` or `GroundingSource` or `neurosphere_contracts__catalog__v1__tool__Tool` or `Service` or `Domain` or `neurosphere_contracts__catalog__v1__owner__Owner` or `Policy` or `RecommendationReference` or `RunReference` or `Grant` or `McpServer`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/entities/{entity_id}/recertify`

- Operation id: `recertify_owner_api_v1_catalog_entities__entity_id__recertify_post`
- Summary: Recertify Owner
- Parameters: `entity_id` (path, required), `If-Match` (header, required)
- Request body: application/json: `RecertifyRequest` (required)
- Responses: `200` `Person` or `Agent` or `AgentVersion` or `ModelDeployment` or `GroundingSource` or `neurosphere_contracts__catalog__v1__tool__Tool` or `Service` or `Domain` or `neurosphere_contracts__catalog__v1__owner__Owner` or `Policy` or `RecommendationReference` or `RunReference` or `Grant` or `McpServer`; `422` `HTTPValidationError`

#### GET `/api/v1/catalog/export`

- Operation id: `export_api_v1_catalog_export_get`
- Summary: Export
- Parameters: `entity_type` (query), `domain_id` (query), `lifecycle` (query), `page_size` (query), `cursor` (query)
- Responses: `200` `ExportPage`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/grants/{entity_id}/publication`

- Operation id: `record_publication_api_v1_catalog_grants__entity_id__publication_post`
- Summary: Record Publication
- Parameters: `entity_id` (path, required)
- Request body: application/json: `PublicationRecordBody` (required)
- Responses: `200` `Person` or `Agent` or `AgentVersion` or `ModelDeployment` or `GroundingSource` or `neurosphere_contracts__catalog__v1__tool__Tool` or `Service` or `Domain` or `neurosphere_contracts__catalog__v1__owner__Owner` or `Policy` or `RecommendationReference` or `RunReference` or `Grant` or `McpServer`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/grants/{entity_id}/publish`

- Operation id: `publish_grant_api_v1_catalog_grants__entity_id__publish_post`
- Summary: Publish Grant
- Parameters: `entity_id` (path, required)
- Request body: application/json: `GrantPublishBody` (required)
- Responses: `200` `ActionView`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/grants/{entity_id}/unpublish`

- Operation id: `unpublish_grant_api_v1_catalog_grants__entity_id__unpublish_post`
- Summary: Unpublish Grant
- Parameters: `entity_id` (path, required)
- Request body: application/json: `GrantUnpublishBody` (required)
- Responses: `200` `ActionView`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/import`

- Operation id: `import_entities_api_v1_catalog_import_post`
- Summary: Import Entities
- Request body: application/json: `ImportRequest` (required)
- Responses: `200` `ImportResult`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/lineage/impact`

- Operation id: `impact_api_v1_catalog_lineage_impact_post`
- Summary: Impact
- Request body: application/json: `LineageImpactRequest` (required)
- Responses: `200` `GraphResult`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/lineage/neighbors`

- Operation id: `neighbors_api_v1_catalog_lineage_neighbors_post`
- Summary: Neighbors
- Request body: application/json: `LineageNeighborsRequest` (required)
- Responses: `200` `GraphResult`; `422` `HTTPValidationError`

#### GET `/api/v1/catalog/mcp-servers/{entity_id}/publication`

- Operation id: `mcp_publication_status_api_v1_catalog_mcp_servers__entity_id__publication_get`
- Summary: Mcp Publication Status
- Description: Publication state of the server, the gateway resources it owns, and diagnostics.
- Parameters: `entity_id` (path, required)
- Responses: `200` `McpPublicationStatus`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/mcp-servers/{entity_id}/publication-record`

- Operation id: `record_mcp_publication_api_v1_catalog_mcp_servers__entity_id__publication_record_post`
- Summary: Record Mcp Publication
- Description: Record a succeeded, verified publication stage on the catalog McpServer.
- Parameters: `entity_id` (path, required)
- Request body: application/json: `McpPublicationRecordBody` (required)
- Responses: `200` `Person` or `Agent` or `AgentVersion` or `ModelDeployment` or `GroundingSource` or `neurosphere_contracts__catalog__v1__tool__Tool` or `Service` or `Domain` or `neurosphere_contracts__catalog__v1__owner__Owner` or `Policy` or `RecommendationReference` or `RunReference` or `Grant` or `McpServer`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/mcp-servers/{entity_id}/publish`

- Operation id: `publish_mcp_server_api_v1_catalog_mcp_servers__entity_id__publish_post`
- Summary: Publish Mcp Server
- Description: Draft the next publish stage (``publish``, or ``deny`` then ``change``).
- Parameters: `entity_id` (path, required)
- Request body: application/json: `McpPublishBody` (required)
- Responses: `201` `McpPublicationDraft`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/mcp-servers/{entity_id}/unpublish`

- Operation id: `unpublish_mcp_server_api_v1_catalog_mcp_servers__entity_id__unpublish_post`
- Summary: Unpublish Mcp Server
- Description: Draft the next unpublish stage (``deny``, then ``remove``).
- Parameters: `entity_id` (path, required)
- Request body: application/json: `McpUnpublishBody` (required)
- Responses: `201` `McpPublicationDraft`; `422` `HTTPValidationError`

#### GET `/api/v1/catalog/recertifications`

- Operation id: `recertifications_api_v1_catalog_recertifications_get`
- Summary: Recertifications
- Parameters: `within_days` (query), `include` (query), `page_size` (query), `cursor` (query)
- Responses: `200` `RecertificationPage`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/reconcile/stale-agents/confirm`

- Operation id: `stale_confirm_api_v1_catalog_reconcile_stale_agents_confirm_post`
- Summary: Stale Confirm
- Request body: application/json: `StaleAgentConfirm` (required)
- Responses: `200` `StaleAgentOutcome`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/reconcile/stale-agents/dry-run`

- Operation id: `stale_dry_run_api_v1_catalog_reconcile_stale_agents_dry_run_post`
- Summary: Stale Dry Run
- Request body: application/json: `StaleAgentRequest` (required)
- Responses: `200` `StaleAgentPlan`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/search`

- Operation id: `search_api_v1_catalog_search_post`
- Summary: Search
- Request body: application/json: `GraphSearchRequest` (required)
- Responses: `200` `GraphResult`; `422` `HTTPValidationError`

#### POST `/catalog/access/dependents`

**Deprecated**

- Operation id: `dependents_catalog_access_dependents_post`
- Summary: Entities affected when a node fails
- Description: Entities that depend on a failing service or tool (blast radius), grouped by distance (max_depth 1 to 5; any other value answers 422 with a reason code), each with the relation path. Results are observed or curated edges, not entitlements. A truncated result is partial: truncated_reason says which bound stopped the walk. Only in-scope entities appear. Each call appends one allowed-read audit record holding the domains read and the result count only.
- Request body: application/json: `AccessDependentsRequest` (required)
- Responses: `200` `AccessDependentsResponse`; `422` `HTTPValidationError`

#### POST `/catalog/access/query`

**Deprecated**

- Operation id: `access_query_catalog_access_query_post`
- Summary: Who reads or writes these data assets
- Description: Which in-scope agents and tools read or wrote the selected data assets. Results are observed edges (who did), not entitlements (who could). An empty sensitivity_categories list or a null value on an asset means not assessed, never no; such assets are listed under unassessed_assets only when include_unassessed is true. When region_group and residency_regions are both given, their regions are unioned. residency_regions values are validated against the known-region list for the caller's cloud; an unknown region answers 422 with reason unknown_region. The eu group is a NeuroSphere classification of Azure region locations and implies nothing about compliance. A truncated result is partial: truncated_reason says which bound stopped the scan and assets_scanned how many assets were examined. Scope comes only from the caller's identity; domain_ids narrows within it. Each call appends one allowed-read audit record holding the domains read and the result count only.
- Request body: application/json: `AccessQueryRequest` (required)
- Responses: `200` `AccessQueryResponse`; `422` `HTTPValidationError`

#### GET `/catalog/access/region-groups`

**Deprecated**

- Operation id: `region_groups_catalog_access_region_groups_get`
- Summary: Region groups available to the access query
- Description: Region group names and their member regions for the caller's cloud (the Government cloud has none). The eu group is a NeuroSphere classification of Azure region locations and implies nothing about compliance.
- Responses: `200` `RegionGroupsResponse`

#### GET `/catalog/entities`

**Deprecated**

- Operation id: `list_entities_catalog_entities_get`
- Summary: List Entities
- Parameters: `entity_type` (query), `domain_id` (query), `lifecycle` (query), `page_size` (query), `cursor` (query)
- Responses: `200` `Page_Union_Person__Agent__AgentVersion__ModelDeployment__GroundingSource__Tool__Service__Domain__Owner__Policy__RecommendationReference__RunReference__Grant__McpServer__`; `422` `HTTPValidationError`

#### POST `/catalog/entities`

**Deprecated**

- Operation id: `create_entity_catalog_entities_post`
- Summary: Create Entity
- Request body: application/json: `object` (required)
- Responses: `201` `Person` or `Agent` or `AgentVersion` or `ModelDeployment` or `GroundingSource` or `neurosphere_contracts__catalog__v1__tool__Tool` or `Service` or `Domain` or `neurosphere_contracts__catalog__v1__owner__Owner` or `Policy` or `RecommendationReference` or `RunReference` or `Grant` or `McpServer`; `422` `HTTPValidationError`

#### GET `/catalog/entities/{entity_id}`

**Deprecated**

- Operation id: `get_entity_catalog_entities__entity_id__get`
- Summary: Get Entity
- Parameters: `entity_id` (path, required)
- Responses: `200` `Person` or `Agent` or `AgentVersion` or `ModelDeployment` or `GroundingSource` or `neurosphere_contracts__catalog__v1__tool__Tool` or `Service` or `Domain` or `neurosphere_contracts__catalog__v1__owner__Owner` or `Policy` or `RecommendationReference` or `RunReference` or `Grant` or `McpServer`; `422` `HTTPValidationError`

#### PUT `/catalog/entities/{entity_id}`

**Deprecated**

- Operation id: `update_entity_catalog_entities__entity_id__put`
- Summary: Update Entity
- Parameters: `entity_id` (path, required), `If-Match` (header, required)
- Request body: application/json: `object` (required)
- Responses: `200` `Person` or `Agent` or `AgentVersion` or `ModelDeployment` or `GroundingSource` or `neurosphere_contracts__catalog__v1__tool__Tool` or `Service` or `Domain` or `neurosphere_contracts__catalog__v1__owner__Owner` or `Policy` or `RecommendationReference` or `RunReference` or `Grant` or `McpServer`; `422` `HTTPValidationError`

#### POST `/catalog/entities/{entity_id}/deprecate`

**Deprecated**

- Operation id: `deprecate_entity_catalog_entities__entity_id__deprecate_post`
- Summary: Deprecate Entity
- Parameters: `entity_id` (path, required), `If-Match` (header, required)
- Request body: application/json: `DeprecateRequest` or `null` (optional)
- Responses: `200` `Person` or `Agent` or `AgentVersion` or `ModelDeployment` or `GroundingSource` or `neurosphere_contracts__catalog__v1__tool__Tool` or `Service` or `Domain` or `neurosphere_contracts__catalog__v1__owner__Owner` or `Policy` or `RecommendationReference` or `RunReference` or `Grant` or `McpServer`; `422` `HTTPValidationError`

#### POST `/catalog/entities/{entity_id}/recertify`

**Deprecated**

- Operation id: `recertify_owner_catalog_entities__entity_id__recertify_post`
- Summary: Recertify Owner
- Parameters: `entity_id` (path, required), `If-Match` (header, required)
- Request body: application/json: `RecertifyRequest` (required)
- Responses: `200` `Person` or `Agent` or `AgentVersion` or `ModelDeployment` or `GroundingSource` or `neurosphere_contracts__catalog__v1__tool__Tool` or `Service` or `Domain` or `neurosphere_contracts__catalog__v1__owner__Owner` or `Policy` or `RecommendationReference` or `RunReference` or `Grant` or `McpServer`; `422` `HTTPValidationError`

#### GET `/catalog/export`

**Deprecated**

- Operation id: `export_catalog_export_get`
- Summary: Export
- Parameters: `entity_type` (query), `domain_id` (query), `lifecycle` (query), `page_size` (query), `cursor` (query)
- Responses: `200` `ExportPage`; `422` `HTTPValidationError`

#### POST `/catalog/grants/{entity_id}/publication`

**Deprecated**

- Operation id: `record_publication_catalog_grants__entity_id__publication_post`
- Summary: Record Publication
- Parameters: `entity_id` (path, required)
- Request body: application/json: `PublicationRecordBody` (required)
- Responses: `200` `Person` or `Agent` or `AgentVersion` or `ModelDeployment` or `GroundingSource` or `neurosphere_contracts__catalog__v1__tool__Tool` or `Service` or `Domain` or `neurosphere_contracts__catalog__v1__owner__Owner` or `Policy` or `RecommendationReference` or `RunReference` or `Grant` or `McpServer`; `422` `HTTPValidationError`

#### POST `/catalog/grants/{entity_id}/publish`

**Deprecated**

- Operation id: `publish_grant_catalog_grants__entity_id__publish_post`
- Summary: Publish Grant
- Parameters: `entity_id` (path, required)
- Request body: application/json: `GrantPublishBody` (required)
- Responses: `200` `ActionView`; `422` `HTTPValidationError`

#### POST `/catalog/grants/{entity_id}/unpublish`

**Deprecated**

- Operation id: `unpublish_grant_catalog_grants__entity_id__unpublish_post`
- Summary: Unpublish Grant
- Parameters: `entity_id` (path, required)
- Request body: application/json: `GrantUnpublishBody` (required)
- Responses: `200` `ActionView`; `422` `HTTPValidationError`

#### POST `/catalog/import`

**Deprecated**

- Operation id: `import_entities_catalog_import_post`
- Summary: Import Entities
- Request body: application/json: `ImportRequest` (required)
- Responses: `200` `ImportResult`; `422` `HTTPValidationError`

#### POST `/catalog/lineage/impact`

**Deprecated**

- Operation id: `impact_catalog_lineage_impact_post`
- Summary: Impact
- Request body: application/json: `LineageImpactRequest` (required)
- Responses: `200` `GraphResult`; `422` `HTTPValidationError`

#### POST `/catalog/lineage/neighbors`

**Deprecated**

- Operation id: `neighbors_catalog_lineage_neighbors_post`
- Summary: Neighbors
- Request body: application/json: `LineageNeighborsRequest` (required)
- Responses: `200` `GraphResult`; `422` `HTTPValidationError`

#### GET `/catalog/mcp-servers/{entity_id}/publication`

**Deprecated**

- Operation id: `mcp_publication_status_catalog_mcp_servers__entity_id__publication_get`
- Summary: Mcp Publication Status
- Description: Publication state of the server, the gateway resources it owns, and diagnostics.
- Parameters: `entity_id` (path, required)
- Responses: `200` `McpPublicationStatus`; `422` `HTTPValidationError`

#### POST `/catalog/mcp-servers/{entity_id}/publication-record`

**Deprecated**

- Operation id: `record_mcp_publication_catalog_mcp_servers__entity_id__publication_record_post`
- Summary: Record Mcp Publication
- Description: Record a succeeded, verified publication stage on the catalog McpServer.
- Parameters: `entity_id` (path, required)
- Request body: application/json: `McpPublicationRecordBody` (required)
- Responses: `200` `Person` or `Agent` or `AgentVersion` or `ModelDeployment` or `GroundingSource` or `neurosphere_contracts__catalog__v1__tool__Tool` or `Service` or `Domain` or `neurosphere_contracts__catalog__v1__owner__Owner` or `Policy` or `RecommendationReference` or `RunReference` or `Grant` or `McpServer`; `422` `HTTPValidationError`

#### POST `/catalog/mcp-servers/{entity_id}/publish`

**Deprecated**

- Operation id: `publish_mcp_server_catalog_mcp_servers__entity_id__publish_post`
- Summary: Publish Mcp Server
- Description: Draft the next publish stage (``publish``, or ``deny`` then ``change``).
- Parameters: `entity_id` (path, required)
- Request body: application/json: `McpPublishBody` (required)
- Responses: `201` `McpPublicationDraft`; `422` `HTTPValidationError`

#### POST `/catalog/mcp-servers/{entity_id}/unpublish`

**Deprecated**

- Operation id: `unpublish_mcp_server_catalog_mcp_servers__entity_id__unpublish_post`
- Summary: Unpublish Mcp Server
- Description: Draft the next unpublish stage (``deny``, then ``remove``).
- Parameters: `entity_id` (path, required)
- Request body: application/json: `McpUnpublishBody` (required)
- Responses: `201` `McpPublicationDraft`; `422` `HTTPValidationError`

#### GET `/catalog/recertifications`

**Deprecated**

- Operation id: `recertifications_catalog_recertifications_get`
- Summary: Recertifications
- Parameters: `within_days` (query), `include` (query), `page_size` (query), `cursor` (query)
- Responses: `200` `RecertificationPage`; `422` `HTTPValidationError`

#### POST `/catalog/reconcile/stale-agents/confirm`

**Deprecated**

- Operation id: `stale_confirm_catalog_reconcile_stale_agents_confirm_post`
- Summary: Stale Confirm
- Request body: application/json: `StaleAgentConfirm` (required)
- Responses: `200` `StaleAgentOutcome`; `422` `HTTPValidationError`

#### POST `/catalog/reconcile/stale-agents/dry-run`

**Deprecated**

- Operation id: `stale_dry_run_catalog_reconcile_stale_agents_dry_run_post`
- Summary: Stale Dry Run
- Request body: application/json: `StaleAgentRequest` (required)
- Responses: `200` `StaleAgentPlan`; `422` `HTTPValidationError`

#### POST `/catalog/search`

**Deprecated**

- Operation id: `search_catalog_search_post`
- Summary: Search
- Request body: application/json: `GraphSearchRequest` (required)
- Responses: `200` `GraphResult`; `422` `HTTPValidationError`

### Tag: catalog-curation

#### GET `/api/v1/catalog/curation/edges/{edge_id}`

- Operation id: `presented_api_v1_catalog_curation_edges__edge_id__get`
- Summary: Presented
- Parameters: `edge_id` (path, required)
- Responses: `200` `PresentedEdge`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/curation/edges/{edge_id}/decisions`

- Operation id: `decide_api_v1_catalog_curation_edges__edge_id__decisions_post`
- Summary: Decide
- Parameters: `edge_id` (path, required)
- Request body: application/json: `EdgeOverride-Input` (required)
- Responses: `201` `DecisionResult`; `422` `HTTPValidationError`

#### GET `/api/v1/catalog/curation/edges/{edge_id}/observations`

- Operation id: `observations_api_v1_catalog_curation_edges__edge_id__observations_get`
- Summary: Observations
- Parameters: `edge_id` (path, required), `page_size` (query), `cursor` (query)
- Responses: `200` `Page_EdgeObservation_`; `422` `HTTPValidationError`

#### GET `/api/v1/catalog/curation/edges/{edge_id}/overrides`

- Operation id: `overrides_api_v1_catalog_curation_edges__edge_id__overrides_get`
- Summary: Overrides
- Parameters: `edge_id` (path, required)
- Responses: `200` `OverrideHistory`; `422` `HTTPValidationError`

#### GET `/api/v1/catalog/curation/review-queue`

- Operation id: `review_queue_api_v1_catalog_curation_review_queue_get`
- Summary: Review Queue
- Description: Open conflicts in the caller's scope, oldest first, in domains they may curate.
- Parameters: `limit` (query)
- Responses: `200` `ReviewQueuePage`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/curation/review-queue/{item_id}/resolve`

- Operation id: `resolve_review_item_api_v1_catalog_curation_review_queue__item_id__resolve_post`
- Summary: Resolve Review Item
- Parameters: `item_id` (path, required)
- Request body: application/json: `ReviewResolveBody` (required)
- Responses: `200` `ReviewItem`; `422` `HTTPValidationError`

#### GET `/catalog/curation/edges/{edge_id}`

**Deprecated**

- Operation id: `presented_catalog_curation_edges__edge_id__get`
- Summary: Presented
- Parameters: `edge_id` (path, required)
- Responses: `200` `PresentedEdge`; `422` `HTTPValidationError`

#### POST `/catalog/curation/edges/{edge_id}/decisions`

**Deprecated**

- Operation id: `decide_catalog_curation_edges__edge_id__decisions_post`
- Summary: Decide
- Parameters: `edge_id` (path, required)
- Request body: application/json: `EdgeOverride-Input` (required)
- Responses: `201` `DecisionResult`; `422` `HTTPValidationError`

#### GET `/catalog/curation/edges/{edge_id}/observations`

**Deprecated**

- Operation id: `observations_catalog_curation_edges__edge_id__observations_get`
- Summary: Observations
- Parameters: `edge_id` (path, required), `page_size` (query), `cursor` (query)
- Responses: `200` `Page_EdgeObservation_`; `422` `HTTPValidationError`

#### GET `/catalog/curation/edges/{edge_id}/overrides`

**Deprecated**

- Operation id: `overrides_catalog_curation_edges__edge_id__overrides_get`
- Summary: Overrides
- Parameters: `edge_id` (path, required)
- Responses: `200` `OverrideHistory`; `422` `HTTPValidationError`

#### GET `/catalog/curation/review-queue`

**Deprecated**

- Operation id: `review_queue_catalog_curation_review_queue_get`
- Summary: Review Queue
- Description: Open conflicts in the caller's scope, oldest first, in domains they may curate.
- Parameters: `limit` (query)
- Responses: `200` `ReviewQueuePage`; `422` `HTTPValidationError`

#### POST `/catalog/curation/review-queue/{item_id}/resolve`

**Deprecated**

- Operation id: `resolve_review_item_catalog_curation_review_queue__item_id__resolve_post`
- Summary: Resolve Review Item
- Parameters: `item_id` (path, required)
- Request body: application/json: `ReviewResolveBody` (required)
- Responses: `200` `ReviewItem`; `422` `HTTPValidationError`

### Tag: compliance

#### GET `/api/v1/compliance/domains/{domain}/bundle`

- Operation id: `get_bundle_api_v1_compliance_domains__domain__bundle_get`
- Summary: Get Bundle
- Parameters: `domain` (path, required), `framework_id` (query, required), `window_days` (query)
- Responses: `200` `EvidenceBundle`; `422` `HTTPValidationError`

#### GET `/api/v1/compliance/domains/{domain}/bundle/export`

- Operation id: `export_bundle_api_v1_compliance_domains__domain__bundle_export_get`
- Summary: Export Bundle
- Parameters: `domain` (path, required), `framework_id` (query, required), `format` (query), `window_days` (query)
- Responses: `200` no body; `422` `HTTPValidationError`

#### GET `/api/v1/compliance/frameworks`

- Operation id: `list_frameworks_api_v1_compliance_frameworks_get`
- Summary: List Frameworks
- Responses: `200` `FrameworkListResponse`

#### GET `/api/v1/compliance/frameworks/{framework_id}`

- Operation id: `get_framework_api_v1_compliance_frameworks__framework_id__get`
- Summary: Get Framework
- Parameters: `framework_id` (path, required)
- Responses: `200` `FrameworkDetailResponse`; `422` `HTTPValidationError`

### Tag: copilot

#### GET `/api/v1/copilot/conversations`

- Operation id: `list_conversations_api_v1_copilot_conversations_get`
- Summary: List Conversations
- Parameters: `cursor` (query), `limit` (query)
- Responses: `200` `ConversationList`; `422` `HTTPValidationError`

#### POST `/api/v1/copilot/conversations`

- Operation id: `create_conversation_api_v1_copilot_conversations_post`
- Summary: Create Conversation
- Responses: `201` `ConversationCreated`

#### GET `/api/v1/copilot/conversations/{conversation_id}`

- Operation id: `get_conversation_api_v1_copilot_conversations__conversation_id__get`
- Summary: Get Conversation
- Parameters: `conversation_id` (path, required)
- Responses: `200` `ConversationView`; `422` `HTTPValidationError`

#### DELETE `/api/v1/copilot/conversations/{conversation_id}`

- Operation id: `delete_conversation_api_v1_copilot_conversations__conversation_id__delete`
- Summary: Delete Conversation
- Parameters: `conversation_id` (path, required)
- Responses: `204` no body; `422` `HTTPValidationError`

#### POST `/api/v1/copilot/conversations/{conversation_id}/messages`

- Operation id: `post_message_api_v1_copilot_conversations__conversation_id__messages_post`
- Summary: Post Message
- Parameters: `conversation_id` (path, required)
- Request body: application/json: `MessageBody` (required)
- Responses: `200` no body; `422` `HTTPValidationError`

#### GET `/api/v1/copilot/status`

- Operation id: `copilot_status_api_v1_copilot_status_get`
- Summary: Copilot Status
- Responses: `200` `CopilotStatus`

### Tag: dashboards

#### GET `/api/v1/dashboards/domains/{domain}/{metric}`

- Operation id: `get_dashboard_api_v1_dashboards_domains__domain___metric__get`
- Summary: Get Dashboard
- Parameters: `domain` (path, required), `metric` (path, required), `days` (query), `grain` (query), `max_series` (query), `max_points` (query)
- Responses: `200` `DashboardResponse`; `422` `HTTPValidationError`

### Tag: deploy

#### POST `/api/v1/deploy/apply/domains/{domain}/plans/apply`

- Operation id: `apply_plan_api_v1_deploy_apply_domains__domain__plans_apply_post`
- Summary: Apply Plan
- Parameters: `domain` (path, required)
- Request body: application/json: `ApplyBody` (required)
- Responses: `201` `ApplyView`; `422` `HTTPValidationError`

#### POST `/api/v1/deploy/apply/domains/{domain}/plans/approve`

- Operation id: `approve_plan_api_v1_deploy_apply_domains__domain__plans_approve_post`
- Summary: Approve Plan
- Parameters: `domain` (path, required)
- Request body: application/json: `ApprovePlanBody` (required)
- Responses: `201` `ApprovedPlanView`; `422` `HTTPValidationError`

#### POST `/api/v1/deploy/apply/domains/{domain}/uninstall/preview`

**Preview/unverified**

- Operation id: `preview_uninstall_api_v1_deploy_apply_domains__domain__uninstall_preview_post`
- Summary: Preview Uninstall
- Parameters: `domain` (path, required)
- Request body: application/json: `UninstallPreviewBody` (required)
- Responses: `201` `UninstallPreviewView`; `422` `HTTPValidationError`

#### POST `/api/v1/deploy/plan`

- Operation id: `plan_api_v1_deploy_plan_post`
- Summary: Plan
- Request body: application/json: `PlanRequest` (required)
- Responses: `200` `PlanResponse`; `422` `HTTPValidationError`

#### POST `/api/v1/deploy/scan`

- Operation id: `scan_api_v1_deploy_scan_post`
- Summary: Scan
- Request body: application/json: `ScanRequest` (required)
- Responses: `200` `ScanResponse`; `422` `HTTPValidationError`

#### POST `/v1/deploy/plan`

**Deprecated**

- Operation id: `plan_v1_deploy_plan_post`
- Summary: Plan
- Request body: application/json: `PlanRequest` (required)
- Responses: `200` `PlanResponse`; `422` `HTTPValidationError`

#### POST `/v1/deploy/scan`

**Deprecated**

- Operation id: `scan_v1_deploy_scan_post`
- Summary: Scan
- Request body: application/json: `ScanRequest` (required)
- Responses: `200` `ScanResponse`; `422` `HTTPValidationError`

### Tag: evaluation

#### GET `/api/v1/evaluation/domains/{domain}/calibration-samples`

- Operation id: `calibration_sample_api_v1_evaluation_domains__domain__calibration_samples_get`
- Summary: Calibration Sample
- Parameters: `domain` (path, required), `subject_ref` (query, required)
- Responses: `200` `CalibrationSampleOut`; `422` `HTTPValidationError`

#### GET `/api/v1/evaluation/domains/{domain}/quality`

- Operation id: `quality_api_v1_evaluation_domains__domain__quality_get`
- Summary: Quality
- Parameters: `domain` (path, required), `subject_id` (query)
- Responses: `200` `QualityResponse`; `422` `HTTPValidationError`

#### GET `/api/v1/evaluation/domains/{domain}/results`

- Operation id: `list_results_api_v1_evaluation_domains__domain__results_get`
- Summary: List Results
- Parameters: `domain` (path, required), `subject_id` (query), `dimension` (query), `cursor` (query), `limit` (query)
- Responses: `200` `ResultsList`; `422` `HTTPValidationError`

### Tag: federation

#### GET `/api/v1/federation/cell-summary`

- Operation id: `cell_summary_api_v1_federation_cell_summary_get`
- Summary: Cell Summary
- Parameters: `days` (query)
- Responses: `200` `CellSummary`; `422` `HTTPValidationError`

#### GET `/api/v1/federation/summary`

- Operation id: `merged_summary_api_v1_federation_summary_get`
- Summary: Merged Summary
- Parameters: `days` (query), `cells` (query)
- Responses: `200` `MergedSummary`; `422` `HTTPValidationError`

### Tag: finops

#### GET `/api/v1/finops/domains/{domain}/forecast`

- Operation id: `get_forecast_api_v1_finops_domains__domain__forecast_get`
- Summary: Get Forecast
- Parameters: `domain` (path, required), `history_days` (query), `horizon_days` (query), `currency` (query), `as_of` (query)
- Responses: `200` `ForecastResponse`; `422` `HTTPValidationError`

### Tag: gateways

#### GET `/api/v1/gateways/domains/{domain}/gateways`

- Operation id: `list_gateways_api_v1_gateways_domains__domain__gateways_get`
- Summary: List Gateways
- Parameters: `domain` (path, required), `cursor` (query), `limit` (query)
- Responses: `200` `GatewayList`; `422` `HTTPValidationError`

#### POST `/api/v1/gateways/domains/{domain}/gateways`

- Operation id: `register_gateway_api_v1_gateways_domains__domain__gateways_post`
- Summary: Register Gateway
- Parameters: `domain` (path, required)
- Request body: application/json: `RegisterGatewayBody` (required)
- Responses: `201` `GatewayRegistration`; `422` `HTTPValidationError`

#### GET `/api/v1/gateways/domains/{domain}/gateways/{gateway_id}`

- Operation id: `get_gateway_api_v1_gateways_domains__domain__gateways__gateway_id__get`
- Summary: Get Gateway
- Parameters: `domain` (path, required), `gateway_id` (path, required)
- Responses: `200` `GatewayDetail`; `422` `HTTPValidationError`

#### GET `/api/v1/gateways/domains/{domain}/gateways/{gateway_id}/inventory`

- Operation id: `get_inventory_api_v1_gateways_domains__domain__gateways__gateway_id__inventory_get`
- Summary: Get Inventory
- Parameters: `domain` (path, required), `gateway_id` (path, required)
- Responses: `200` `GatewayInventory`; `422` `HTTPValidationError`

#### POST `/api/v1/gateways/domains/{domain}/gateways/{gateway_id}/mode`

- Operation id: `change_gateway_mode_api_v1_gateways_domains__domain__gateways__gateway_id__mode_post`
- Summary: Change Gateway Mode
- Description: Draft the audited ``gateway_mode_change`` intent (the switch runs in the executor).
- Parameters: `domain` (path, required), `gateway_id` (path, required)
- Request body: application/json: `GatewayModeBody` (required)
- Responses: `201` `ActionView`; `422` `HTTPValidationError`

#### POST `/api/v1/gateways/domains/{domain}/gateways/{gateway_id}/sync`

- Operation id: `sync_gateway_api_v1_gateways_domains__domain__gateways__gateway_id__sync_post`
- Summary: Sync Gateway
- Parameters: `domain` (path, required), `gateway_id` (path, required)
- Responses: `200` `GatewayDetail`; `422` `HTTPValidationError`

### Tag: health

#### GET `/healthz`

- Operation id: `healthz_healthz_get`
- Summary: Healthz
- Responses: `200` `HealthzResponse`

#### GET `/readyz`

- Operation id: `readyz_readyz_get`
- Summary: Readyz
- Responses: `200` `ReadyzResponse`; `503` `ReadyzResponse`

### Tag: ingest

#### POST `/api/v1/ingest/events`

- Operation id: `events_api_v1_ingest_events_post`
- Summary: Events
- Responses: `202` `IngestResult`

#### POST `/api/v1/ingest/otlp/metrics`

- Operation id: `metrics_api_v1_ingest_otlp_metrics_post`
- Summary: Metrics
- Responses: `202` `IngestResult`

#### POST `/api/v1/ingest/otlp/traces`

- Operation id: `traces_api_v1_ingest_otlp_traces_post`
- Summary: Traces
- Responses: `202` `IngestResult`

#### POST `/v1/ingest/events`

**Deprecated**

- Operation id: `events_v1_ingest_events_post`
- Summary: Events
- Responses: `202` `IngestResult`

#### POST `/v1/ingest/otlp/metrics`

**Deprecated**

- Operation id: `metrics_v1_ingest_otlp_metrics_post`
- Summary: Metrics
- Responses: `202` `IngestResult`

#### POST `/v1/ingest/otlp/traces`

**Deprecated**

- Operation id: `traces_v1_ingest_otlp_traces_post`
- Summary: Traces
- Responses: `202` `IngestResult`

### Tag: lifecycle

#### GET `/api/v1/lifecycle/holds`

- Operation id: `list_holds_api_v1_lifecycle_holds_get`
- Summary: List Holds
- Responses: `200` array of `HoldView`

#### POST `/api/v1/lifecycle/holds`

- Operation id: `place_hold_api_v1_lifecycle_holds_post`
- Summary: Place Hold
- Request body: application/json: `HoldCreate` (required)
- Responses: `201` `HoldView`; `422` `HTTPValidationError`

#### DELETE `/api/v1/lifecycle/holds/{hold_id}`

- Operation id: `release_hold_api_v1_lifecycle_holds__hold_id__delete`
- Summary: Release Hold
- Parameters: `hold_id` (path, required)
- Responses: `204` no body; `422` `HTTPValidationError`

#### GET `/api/v1/lifecycle/requests`

- Operation id: `list_requests_api_v1_lifecycle_requests_get`
- Summary: List Requests
- Parameters: `limit` (query)
- Responses: `200` array of `RequestView`; `422` `HTTPValidationError`

#### POST `/api/v1/lifecycle/requests`

- Operation id: `submit_request_api_v1_lifecycle_requests_post`
- Summary: Submit Request
- Request body: application/json: `RequestCreate` (required)
- Responses: `202` `RequestAccepted`; `422` `HTTPValidationError`

#### GET `/api/v1/lifecycle/requests/{request_id}`

- Operation id: `get_request_api_v1_lifecycle_requests__request_id__get`
- Summary: Get Request
- Parameters: `request_id` (path, required)
- Responses: `200` `RequestView`; `422` `HTTPValidationError`

#### GET `/api/v1/lifecycle/status`

- Operation id: `status_api_v1_lifecycle_status_get`
- Summary: Status
- Responses: `200` `StatusView`

### Tag: map

#### GET `/api/v1/map/domains/{domain_id}/viewport`

- Operation id: `get_viewport_api_v1_map_domains__domain_id__viewport_get`
- Summary: Get Viewport
- Parameters: `domain_id` (path, required), `cluster_id` (query), `cursor` (query), `node_budget` (query), `edge_budget` (query)
- Responses: `200` `ViewportResponse`; `422` `HTTPValidationError`

### Tag: mcp-admin

#### GET `/api/v1/mcp/admin/servers`

- Operation id: `list_servers_api_v1_mcp_admin_servers_get`
- Summary: List Servers
- Parameters: `cursor` (query), `limit` (query)
- Responses: `200` `ServerPage`; `422` `HTTPValidationError`

#### POST `/api/v1/mcp/admin/servers`

- Operation id: `register_server_api_v1_mcp_admin_servers_post`
- Summary: Register Server
- Request body: application/json: `RegisterServerBody` (required)
- Responses: `201` `ServerView`; `422` `HTTPValidationError`

#### GET `/api/v1/mcp/admin/servers/{server_id}`

- Operation id: `get_server_api_v1_mcp_admin_servers__server_id__get`
- Summary: Get Server
- Parameters: `server_id` (path, required)
- Responses: `200` `ServerView`; `422` `HTTPValidationError`

#### PATCH `/api/v1/mcp/admin/servers/{server_id}`

- Operation id: `update_server_api_v1_mcp_admin_servers__server_id__patch`
- Summary: Update Server
- Parameters: `server_id` (path, required), `If-Match` (header, required)
- Request body: application/json: `UpdateServerBody` (required)
- Responses: `200` `ServerView`; `422` `HTTPValidationError`

#### POST `/api/v1/mcp/admin/servers/{server_id}/sync`

- Operation id: `sync_server_api_v1_mcp_admin_servers__server_id__sync_post`
- Summary: Sync Server
- Parameters: `server_id` (path, required), `If-Match` (header)
- Responses: `200` `SyncView`; `422` `HTTPValidationError`

#### GET `/api/v1/mcp/admin/servers/{server_id}/tools`

- Operation id: `list_tools_api_v1_mcp_admin_servers__server_id__tools_get`
- Summary: List Tools
- Parameters: `server_id` (path, required)
- Responses: `200` `ToolList`; `422` `HTTPValidationError`

#### POST `/api/v1/mcp/admin/servers/{server_id}/tools/{tool_name}/approval`

- Operation id: `approve_tool_api_v1_mcp_admin_servers__server_id__tools__tool_name__approval_post`
- Summary: Approve Tool
- Parameters: `server_id` (path, required), `tool_name` (path, required), `If-Match` (header, required)
- Request body: application/json: `ApproveToolBody` (required)
- Responses: `200` `ToolList`; `422` `HTTPValidationError`

#### DELETE `/api/v1/mcp/admin/servers/{server_id}/tools/{tool_name}/approval`

- Operation id: `revoke_tool_api_v1_mcp_admin_servers__server_id__tools__tool_name__approval_delete`
- Summary: Revoke Tool
- Parameters: `server_id` (path, required), `tool_name` (path, required), `reason` (query), `If-Match` (header, required)
- Responses: `200` `ToolList`; `422` `HTTPValidationError`

### Tag: me

#### GET `/api/v1/me/access`

- Operation id: `my_access_api_v1_me_access_get`
- Summary: My Access
- Description: The caller's own role assignments and where each came from: `entra_app_role` or `entra_group` (applied from the deployment's Entra claim role mapping, with the mapping entry id) or `policy_store`. Per role: domain count, whether it covers the customer control domain, and its expiry. Any authenticated caller may read it, including one with no role (**200 with an empty `roles` list**). Never returns domain ids, claim values, group object ids, the mapping itself or anything about another principal.
- Responses: `200` `MeAccess`

#### GET `/api/v1/me/domains`

- Operation id: `my_domains_api_v1_me_domains_get`
- Summary: My Domains
- Description: The domains the caller may read (an unexpired role conferring `data.read`, in the caller's own cloud and customer), with display names from the catalog. A caller whose only `data.read` comes from a resource-scoped grant gets **200 with an empty `items` list**: the grant covers one resource, never a domain. A caller holding `data.read` nowhere gets 403.
- Responses: `200` `MeDomains`

### Tag: recommendations

#### GET `/api/v1/recommendations/domains/{domain}`

- Operation id: `list_recommendations_api_v1_recommendations_domains__domain__get`
- Summary: List Recommendations
- Parameters: `domain` (path, required), `kind` (query), `q` (query), `cursor` (query), `limit` (query)
- Responses: `200` `RecommendationList`; `422` `HTTPValidationError`

#### POST `/api/v1/recommendations/domains/{domain}/executions`

- Operation id: `refuse_execution_api_v1_recommendations_domains__domain__executions_post`
- Summary: Refuse Execution
- Parameters: `domain` (path, required)
- Responses: `409` no body; `422` `HTTPValidationError`

#### GET `/api/v1/recommendations/domains/{domain}/items/{recommendation_id}`

- Operation id: `get_recommendation_api_v1_recommendations_domains__domain__items__recommendation_id__get`
- Summary: Get Recommendation
- Parameters: `domain` (path, required), `recommendation_id` (path, required)
- Responses: `200` `RecommendationDetail`; `422` `HTTPValidationError`

#### POST `/api/v1/recommendations/domains/{domain}/match`

- Operation id: `match_agents_api_v1_recommendations_domains__domain__match_post`
- Summary: Match Agents
- Parameters: `domain` (path, required)
- Request body: application/json: `AgentMatchRequest` (required)
- Responses: `200` `AgentMatchView`; `422` `HTTPValidationError`

#### POST `/api/v1/recommendations/domains/{domain}/match/feedback`

- Operation id: `record_match_feedback_api_v1_recommendations_domains__domain__match_feedback_post`
- Summary: Record Match Feedback
- Parameters: `domain` (path, required)
- Request body: application/json: `AgentMatchFeedbackRequest` (required)
- Responses: `202` `FeedbackAccepted`; `422` `HTTPValidationError`

#### GET `/api/v1/recommendations/domains/{domain}/match/metrics`

- Operation id: `match_metrics_api_v1_recommendations_domains__domain__match_metrics_get`
- Summary: Match Metrics
- Parameters: `domain` (path, required), `since` (query), `until` (query)
- Responses: `200` `MatchMetricsView`; `422` `HTTPValidationError`

#### POST `/api/v1/recommendations/domains/{domain}/review-requests`

- Operation id: `create_review_request_api_v1_recommendations_domains__domain__review_requests_post`
- Summary: Create Review Request
- Parameters: `domain` (path, required)
- Request body: application/json: `ReviewRequestBody` (required)
- Responses: `202` `ReviewRequestCreated`; `422` `HTTPValidationError`

### Tag: reconciliation

#### GET `/api/v1/reconciliation/domains/{domain}`

- Operation id: `reconcile_api_v1_reconciliation_domains__domain__get`
- Summary: Reconcile
- Parameters: `domain` (path, required), `days` (query)
- Responses: `200` `ReconciliationResponse`; `422` `HTTPValidationError`

### Tag: replay

#### GET `/api/v1/replay/domains/{domain_id}/traces`

- Operation id: `list_traces_api_v1_replay_domains__domain_id__traces_get`
- Summary: List Traces
- Parameters: `domain_id` (path, required), `cursor` (query), `page_size` (query)
- Responses: `200` `TracePage`; `422` `HTTPValidationError`

#### GET `/api/v1/replay/domains/{domain_id}/traces/{trace_id}`

- Operation id: `get_trace_api_v1_replay_domains__domain_id__traces__trace_id__get`
- Summary: Get Trace
- Parameters: `domain_id` (path, required), `trace_id` (path, required), `include_payload` (query)
- Responses: `200` `TraceDetail`; `422` `HTTPValidationError`

### Tag: reports

#### GET `/api/v1/reports/domains/{domain_id}/reports`

- Operation id: `list_reports_api_v1_reports_domains__domain_id__reports_get`
- Summary: List Reports
- Parameters: `domain_id` (path, required), `publication_state` (query), `cursor` (query), `limit` (query)
- Responses: `200` `ReportList`; `422` `HTTPValidationError`

#### POST `/api/v1/reports/domains/{domain_id}/reports`

- Operation id: `create_report_api_v1_reports_domains__domain_id__reports_post`
- Summary: Create Report
- Parameters: `domain_id` (path, required)
- Request body: application/json: `ReportBody` (required)
- Responses: `201` `ReportView`; `422` `HTTPValidationError`

#### GET `/api/v1/reports/domains/{domain_id}/reports/{report_id}`

- Operation id: `get_report_api_v1_reports_domains__domain_id__reports__report_id__get`
- Summary: Get Report
- Parameters: `domain_id` (path, required), `report_id` (path, required)
- Responses: `200` `ReportView`; `422` `HTTPValidationError`

#### PUT `/api/v1/reports/domains/{domain_id}/reports/{report_id}`

- Operation id: `update_report_api_v1_reports_domains__domain_id__reports__report_id__put`
- Summary: Update Report
- Parameters: `domain_id` (path, required), `report_id` (path, required), `If-Match` (header, required)
- Request body: application/json: `ReportBody` (required)
- Responses: `200` `ReportView`; `422` `HTTPValidationError`

#### DELETE `/api/v1/reports/domains/{domain_id}/reports/{report_id}`

- Operation id: `delete_report_api_v1_reports_domains__domain_id__reports__report_id__delete`
- Summary: Delete Report
- Parameters: `domain_id` (path, required), `report_id` (path, required), `If-Match` (header, required)
- Responses: `204` no body; `422` `HTTPValidationError`

#### POST `/api/v1/reports/domains/{domain_id}/reports/{report_id}/publication`

- Operation id: `request_publication_api_v1_reports_domains__domain_id__reports__report_id__publication_post`
- Summary: Request Publication
- Parameters: `domain_id` (path, required), `report_id` (path, required), `If-Match` (header, required)
- Responses: `200` `ReportView`; `422` `HTTPValidationError`

#### POST `/api/v1/reports/domains/{domain_id}/reports/{report_id}/publication/decision`

- Operation id: `decide_publication_api_v1_reports_domains__domain_id__reports__report_id__publication_decision_post`
- Summary: Decide Publication
- Parameters: `domain_id` (path, required), `report_id` (path, required), `If-Match` (header, required)
- Request body: application/json: `neurosphere_api__reports__models__DecisionBody` (required)
- Responses: `200` `ReportView`; `422` `HTTPValidationError`

#### POST `/api/v1/reports/domains/{domain_id}/reports/{report_id}/run`

- Operation id: `run_report_api_v1_reports_domains__domain_id__reports__report_id__run_post`
- Summary: Run Report
- Parameters: `domain_id` (path, required), `report_id` (path, required)
- Responses: `200` `RunView`; `422` `HTTPValidationError`

#### POST `/api/v1/reports/domains/{domain_id}/reports/{report_id}/shares`

- Operation id: `share_report_api_v1_reports_domains__domain_id__reports__report_id__shares_post`
- Summary: Share Report
- Parameters: `domain_id` (path, required), `report_id` (path, required), `If-Match` (header, required)
- Request body: application/json: `ShareBody` (required)
- Responses: `200` `ReportView`; `422` `HTTPValidationError`

#### DELETE `/api/v1/reports/domains/{domain_id}/reports/{report_id}/shares/{principal_id}`

- Operation id: `unshare_report_api_v1_reports_domains__domain_id__reports__report_id__shares__principal_id__delete`
- Summary: Unshare Report
- Parameters: `domain_id` (path, required), `report_id` (path, required), `principal_id` (path, required), `If-Match` (header, required)
- Responses: `200` `ReportView`; `422` `HTTPValidationError`

### Tag: review

#### GET `/api/v1/review/domains/{domain}/items`

- Operation id: `list_items_api_v1_review_domains__domain__items_get`
- Summary: List Items
- Parameters: `domain` (path, required), `kind` (query), `state` (query), `cursor` (query), `limit` (query)
- Responses: `200` `ReviewItemList`; `422` `HTTPValidationError`

#### GET `/api/v1/review/domains/{domain}/items/{item_id}`

- Operation id: `get_item_api_v1_review_domains__domain__items__item_id__get`
- Summary: Get Item
- Parameters: `domain` (path, required), `item_id` (path, required)
- Responses: `200` `ReviewItemView`; `422` `HTTPValidationError`

#### POST `/api/v1/review/domains/{domain}/items/{item_id}/assignment`

- Operation id: `assign_item_api_v1_review_domains__domain__items__item_id__assignment_post`
- Summary: Assign Item
- Parameters: `domain` (path, required), `item_id` (path, required)
- Request body: application/json: `AssignmentBody` (required)
- Responses: `200` `ReviewItemView`; `422` `HTTPValidationError`

#### POST `/api/v1/review/domains/{domain}/items/{item_id}/decisions`

- Operation id: `decide_item_api_v1_review_domains__domain__items__item_id__decisions_post`
- Summary: Decide Item
- Parameters: `domain` (path, required), `item_id` (path, required)
- Request body: application/json: `ReviewDecisionBody` (required)
- Responses: `200` `ReviewItemView`; `422` `HTTPValidationError`

### Tag: sandbox

#### GET `/api/v1/sandbox/entities`

- Operation id: `entities_api_v1_sandbox_entities_get`
- Summary: Entities
- Parameters: `kind` (query, required), `limit` (query), `offset` (query)
- Responses: `200` `EntityPage`; `422` `HTTPValidationError`

#### POST `/api/v1/sandbox/reset`

- Operation id: `reset_api_v1_sandbox_reset_post`
- Summary: Reset
- Responses: `200` `ResetResult`

#### GET `/api/v1/sandbox/status`

- Operation id: `status_api_v1_sandbox_status_get`
- Summary: Status
- Responses: `200` `SandboxSummary`

### Tag: sources-status

#### GET `/api/v1/admin/sources/status`

- Operation id: `admin_source_status_api_v1_admin_sources_status_get`
- Summary: Admin Source Status
- Description: The source summary plus a reason code per source and the run status, last attempt time and counts per connector kind. Customer-level `config.manage` only.
- Responses: `200` `SourcesAdminListView`

#### GET `/api/v1/sources/status`

- Operation id: `source_status_api_v1_sources_status_get`
- Summary: Source Status
- Description: The four data sources (Foundry, API Management gateway, billing, Application Insights telemetry) with a state (`not_connected`, `connected_no_data`, `connected`, `failing`) and the last success time. Any caller who can read at least one domain; no reason, count, id, name or host. Application Insights telemetry is always `not_connected` with `available: false`.
- Responses: `200` `SourceStatusListView`

### Tag: ui-adapters

#### GET `/api/v1/audit/domains`

- Operation id: `audit_domains_api_v1_audit_domains_get`
- Summary: Audit Domains
- Responses: `200` `AuditDomainList`

#### GET `/api/v1/audit/domains/{domain}/records`

- Operation id: `audit_domain_records_api_v1_audit_domains__domain__records_get`
- Summary: Audit Domain Records
- Parameters: `domain` (path, required), `cursor` (query), `page_size` (query)
- Responses: `200` `Page_AuditRecord_`; `422` `HTTPValidationError`

#### GET `/api/v1/audit/domains/{domain}/verify`

- Operation id: `audit_domain_verify_api_v1_audit_domains__domain__verify_get`
- Summary: Audit Domain Verify
- Parameters: `domain` (path, required)
- Responses: `200` `ChainVerification`; `422` `HTTPValidationError`

#### GET `/api/v1/capabilities`

- Operation id: `capabilities_api_v1_capabilities_get`
- Summary: Capabilities
- Parameters: `cloud` (query), `region` (query)
- Responses: `200` `CapabilityMatrixView`; `422` `HTTPValidationError`

#### GET `/api/v1/catalog/domains/{domain}/curation/edges/{edge_id}`

- Operation id: `read_edge_in_domain_api_v1_catalog_domains__domain__curation_edges__edge_id__get`
- Summary: Read Edge In Domain
- Parameters: `domain` (path, required), `edge_id` (path, required)
- Responses: `200` `CurationEdgeView`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/domains/{domain}/curation/edges/{edge_id}/decisions`

- Operation id: `decide_in_domain_api_v1_catalog_domains__domain__curation_edges__edge_id__decisions_post`
- Summary: Decide In Domain
- Parameters: `domain` (path, required), `edge_id` (path, required)
- Request body: application/json: `CurationDecisionRequest` (required)
- Responses: `201` `DecisionResult`; `422` `HTTPValidationError`

#### GET `/api/v1/catalog/domains/{domain}/entities`

- Operation id: `list_domain_entities_api_v1_catalog_domains__domain__entities_get`
- Summary: List Domain Entities
- Parameters: `domain` (path, required), `entity_type` (query), `lifecycle` (query), `page_size` (query), `cursor` (query)
- Responses: `200` `Page_Union_Person__Agent__AgentVersion__ModelDeployment__GroundingSource__Tool__Service__Domain__Owner__Policy__RecommendationReference__RunReference__Grant__McpServer__`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/domains/{domain}/entities`

- Operation id: `create_entity_in_domain_api_v1_catalog_domains__domain__entities_post`
- Summary: Create Entity In Domain
- Parameters: `domain` (path, required)
- Request body: application/json: `CatalogEntityCreateRequest` (required)
- Responses: `201` `Person` or `Agent` or `AgentVersion` or `ModelDeployment` or `GroundingSource` or `neurosphere_contracts__catalog__v1__tool__Tool` or `Service` or `Domain` or `neurosphere_contracts__catalog__v1__owner__Owner` or `Policy` or `RecommendationReference` or `RunReference` or `Grant` or `McpServer`; `422` `HTTPValidationError`

#### PUT `/api/v1/catalog/domains/{domain}/entities/{entity_id}`

- Operation id: `update_entity_in_domain_api_v1_catalog_domains__domain__entities__entity_id__put`
- Summary: Update Entity In Domain
- Parameters: `domain` (path, required), `entity_id` (path, required), `If-Match` (header, required)
- Request body: application/json: `CatalogEntityUpdateRequest` (required)
- Responses: `200` `Person` or `Agent` or `AgentVersion` or `ModelDeployment` or `GroundingSource` or `neurosphere_contracts__catalog__v1__tool__Tool` or `Service` or `Domain` or `neurosphere_contracts__catalog__v1__owner__Owner` or `Policy` or `RecommendationReference` or `RunReference` or `Grant` or `McpServer`; `422` `HTTPValidationError`

#### GET `/api/v1/catalog/domains/{domain}/export`

- Operation id: `export_domain_api_v1_catalog_domains__domain__export_get`
- Summary: Export Domain
- Parameters: `domain` (path, required), `entity_type` (query), `lifecycle` (query), `page_size` (query), `cursor` (query)
- Responses: `200` `ExportPage`; `422` `HTTPValidationError`

#### POST `/api/v1/catalog/domains/{domain}/search`

- Operation id: `search_domain_api_v1_catalog_domains__domain__search_post`
- Summary: Search Domain
- Parameters: `domain` (path, required)
- Request body: application/json: `CatalogDomainSearchRequest` (required)
- Responses: `200` `GraphResult`; `422` `HTTPValidationError`

### Tag: workspaces

#### GET `/api/v1/workspaces/{role}`

- Operation id: `workspace_api_v1_workspaces__role__get`
- Summary: Workspace
- Parameters: `role` (path, required)
- Responses: `200` `WorkspaceBody`; `422` `HTTPValidationError`

