# API reference

> Generated file. Do not edit; run `uv run python docs/reference/generate.py`.
> Source commit: `68de97365a704bc44cccfd5f75c8cd27beb3b42c`. Generated: 2026-10-30.
> Sources: `services/api/openapi.json`, `packages/contracts/schemas/errors/v1/error-codes.json`.

NeuroSphere API version 0.1.0, OpenAPI 3.1.0. 136 operations on 121 paths.

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
| audit | GET | `/api/v1/audit/chains/{chain_id}/records` | List Audit Records |
| audit | GET | `/api/v1/audit/chains/{chain_id}/verify` | Verify Audit Chain |
| audit | GET | `/audit/chains/{chain_id}/records` | List Audit Records |
| audit | GET | `/audit/chains/{chain_id}/verify` | Verify Audit Chain |
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
| catalog-curation | GET | `/catalog/curation/edges/{edge_id}` | Presented |
| catalog-curation | POST | `/catalog/curation/edges/{edge_id}/decisions` | Decide |
| catalog-curation | GET | `/catalog/curation/edges/{edge_id}/observations` | Observations |
| catalog-curation | GET | `/catalog/curation/edges/{edge_id}/overrides` | Overrides |
| copilot | GET | `/api/v1/copilot/conversations` | List Conversations |
| copilot | POST | `/api/v1/copilot/conversations` | Create Conversation |
| copilot | GET | `/api/v1/copilot/conversations/{conversation_id}` | Get Conversation |
| copilot | DELETE | `/api/v1/copilot/conversations/{conversation_id}` | Delete Conversation |
| copilot | POST | `/api/v1/copilot/conversations/{conversation_id}/messages` | Post Message |
| dashboards | GET | `/api/v1/dashboards/domains/{domain}/{metric}` | Get Dashboard |
| deploy | POST | `/api/v1/deploy/plan` | Plan |
| deploy | POST | `/api/v1/deploy/scan` | Scan |
| deploy | POST | `/v1/deploy/plan` | Plan |
| deploy | POST | `/v1/deploy/scan` | Scan |
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
| map | GET | `/api/v1/map/domains/{domain_id}/viewport` | Get Viewport |
| mcp-admin | GET | `/api/v1/mcp/admin/servers` | List Servers |
| mcp-admin | POST | `/api/v1/mcp/admin/servers` | Register Server |
| mcp-admin | GET | `/api/v1/mcp/admin/servers/{server_id}` | Get Server |
| mcp-admin | PATCH | `/api/v1/mcp/admin/servers/{server_id}` | Update Server |
| mcp-admin | POST | `/api/v1/mcp/admin/servers/{server_id}/sync` | Sync Server |
| mcp-admin | GET | `/api/v1/mcp/admin/servers/{server_id}/tools` | List Tools |
| mcp-admin | POST | `/api/v1/mcp/admin/servers/{server_id}/tools/{tool_name}/approval` | Approve Tool |
| mcp-admin | DELETE | `/api/v1/mcp/admin/servers/{server_id}/tools/{tool_name}/approval` | Revoke Tool |
| me | GET | `/api/v1/me/domains` | My Domains |
| recommendations | GET | `/api/v1/recommendations/domains/{domain}` | List Recommendations |
| recommendations | POST | `/api/v1/recommendations/domains/{domain}/executions` | Refuse Execution |
| recommendations | GET | `/api/v1/recommendations/domains/{domain}/items/{recommendation_id}` | Get Recommendation |
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
| ui-adapters | GET | `/api/v1/audit/domains` | Audit Domains |
| ui-adapters | GET | `/api/v1/audit/domains/{domain}/records` | Audit Domain Records |
| ui-adapters | GET | `/api/v1/audit/domains/{domain}/verify` | Audit Domain Verify |
| ui-adapters | GET | `/api/v1/capabilities` | Capabilities |
| ui-adapters | GET | `/api/v1/catalog/domains/{domain}/curation/edges/{edge_id}` | Read Edge In Domain |
| ui-adapters | POST | `/api/v1/catalog/domains/{domain}/curation/edges/{edge_id}/decisions` | Decide In Domain |
| ui-adapters | GET | `/api/v1/catalog/domains/{domain}/entities` | List Domain Entities |
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

### Tag: dashboards

#### GET `/api/v1/dashboards/domains/{domain}/{metric}`

- Operation id: `get_dashboard_api_v1_dashboards_domains__domain___metric__get`
- Summary: Get Dashboard
- Parameters: `domain` (path, required), `metric` (path, required), `days` (query), `grain` (query), `max_series` (query), `max_points` (query)
- Responses: `200` `DashboardResponse`; `422` `HTTPValidationError`

### Tag: deploy

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

#### GET `/api/v1/me/domains`

- Operation id: `my_domains_api_v1_me_domains_get`
- Summary: My Domains
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
- Parameters: `domain_id` (path, required), `report_id` (path, required), `If-Match` (header)
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
- Parameters: `domain_id` (path, required), `report_id` (path, required), `If-Match` (header)
- Request body: application/json: `ShareBody` (required)
- Responses: `200` `ReportView`; `422` `HTTPValidationError`

#### DELETE `/api/v1/reports/domains/{domain_id}/reports/{report_id}/shares/{principal_id}`

- Operation id: `unshare_report_api_v1_reports_domains__domain_id__reports__report_id__shares__principal_id__delete`
- Summary: Unshare Report
- Parameters: `domain_id` (path, required), `report_id` (path, required), `principal_id` (path, required), `If-Match` (header)
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

