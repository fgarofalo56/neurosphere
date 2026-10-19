# NeuroSphere threat model (STRIDE per trust boundary)

| Field | Value |
|---|---|
| Version | 1.0 (PRP-12 item 1) |
| Date | 2026-10-18 |
| Build authority | `docs/ARCHITECTURE.md` sections 1 to 5, `docs/PRD.md` NS-06, NS-08, NS-09 |
| Cited by | PRP-20 (Government verification), PRP-23 (ATO evidence accelerator) |
| Gates | G02, G08, G12 in `docs/RESEARCH-AND-GATES.md` |
| Review | Re-review whenever a boundary in ARCHITECTURE section 1 changes, and at each PRP that adds a boundary marked Planned below |

## Compliance statement

NeuroSphere is **not FedRAMP authorized**. This threat model **does not constitute an ATO**, grants
no authorization and makes **no compliance-parity claim** between Azure Commercial, Azure
Government, GCC, GCC High or DoD impact levels. Agency authorizing officials determine ATO;
inherited Azure controls do not authorize this application. Service availability, feature GA and
authorization are separate facts. This document is engineering input to the customer's own
assessment (PRP-23) and to the Government profile (PRP-20); gate G02 stays OPEN and is not
narrowed by it.

## Scope

In scope: the customer-hosted NeuroSphere deployment as drawn in `docs/ARCHITECTURE.md`: the UI,
APIM, the API and its authorization layer, catalog and graph queries on Cosmos NoSQL, the bounded
analytics query service and its Fabric, Synapse or Azure Databricks adapter, the copilot
orchestrator and its tools, the approved model endpoint, the durable action and HITL service,
target write connectors, append-only audit, plus the telemetry ingest path, live-view push,
search, MCP, deployment intelligence, federation and DR, the public docs-only assistant, and the
build supply chain.

Out of scope: the customer's Entra tenant configuration (conditional access, MFA, PIM), Azure
platform internals, third-party provider APIs beyond the connector boundary, and endpoint
devices. Those are customer or provider responsibilities recorded by PRP-23.

Cloud stance: Azure Government is **gated, not banned**. An option that the capability matrix
(`packages/core/neurosphere_core/capabilities/validate.py`, PRP-02) cannot verify for a cloud,
region or feature is disabled with a reason. **Government data never routes to Commercial**, not
to fill a feature gap, not for a model call, not for DR, not for telemetry.

## How to read the tables

Every boundary has one row per STRIDE category: **S**poofing, **T**ampering, **R**epudiation,
**I**nformation disclosure, **D**enial of service, **E**levation of privilege.

- **Mitigation** cites the repo mechanism where one exists (path relative to the repo root).
- **State**: *In repo* means the mechanism is merged on `main` and covered by tests. *In progress*
  means another PRP-12 item is building it now. *Planned* means the owning PRP has not shipped.
  *Gap* means no PRP currently covers it; it is recorded as a follow-up.
- **Owner** is a PRP id from `PRPs/PRP-MASTER-neurosphere.md`. Where two ids appear, the first
  owns the control and the second consumes or extends it.

## Boundary checklist

The nine required boundaries map 1:1 to the edges of the ARCHITECTURE section 1 flowchart
(`U --> I`, `UI --> G`, `G --> P`, `C --> DB`, `Q --> A`, `O --> M`, `T --> X`, `X --> Z`,
`X --> AU`). Additional boundaries come from sections 1 to 5 and are marked as additional.

| Id | Boundary | ARCHITECTURE source | Owner PRPs |
|---|---|---|---|
| B1 | User to Entra authentication | section 1, `U --> I` | PRP-04, PRP-06 |
| B2 | UI to APIM | section 1, `UI --> G` | PRP-04, PRP-12, PRP-08, PRP-05, PRP-19 |
| B3 | APIM to API authorization and policy | section 1, `G --> P` | PRP-06 |
| B4 | API to Cosmos NoSQL (catalog and scoped graph) | section 1, `P --> C --> DB` | PRP-10, PRP-06, PRP-05, PRP-12, PRP-21 |
| B5 | API to analytics adapter | section 1, `P --> Q --> A` | PRP-11, PRP-02, PRP-06, PRP-08 |
| B6 | Orchestrator to model endpoint | section 1, `O --> M` | PRP-19, PRP-20, PRP-12 |
| B7 | Tools to action and HITL service | section 1, `T --> X`; section 3 | PRP-17, PRP-19, PRP-22, PRP-06 |
| B8 | Action service to target write connectors | section 1, `X --> Z`; section 3 | PRP-17, PRP-09 |
| B9 | Append-only audit evidence | section 1, `X --> AU`; section 3 | PRP-06, PRP-23 |
| A1 | *Additional*: producers and connectors to ingest edge to Event Hubs to workers | section 2, `S --> R --> H --> N` | PRP-07, PRP-09 |
| A2 | *Additional*: hot aggregates to scoped WebSocket gateway to UI | section 2, `V --> W --> UI` | PRP-18, PRP-06 |
| A3 | *Additional*: API to Azure AI Search | section 1 table (Search), section 6 | PRP-10, PRP-03, PRP-06 |
| A4 | *Additional*: MCP (external client to MCP server, MCP client to external server) | section 3 (chat, button or MCP) | PRP-22, PRP-17 |
| A5 | *Additional*: deployment intelligence (consented scan, plan, approval, IaC) | section 4 | PRP-08, PRP-02, PRP-20 |
| A6 | *Additional*: federation summaries and DR replication | section 5, `D1 --> S --> E`, `P --> R` | PRP-21 |
| A7 | *Additional*: public docs-only assistant | section 5, `Public --> Docs` | PRP-25 |
| A8 | *Additional*: build and supply chain (repo, CI, images, registry, cluster) | NS-08 (supply-chain scanning) | PRP-12, PRP-13, PRP-00 |

## Required boundaries

### B1. User to Entra authentication

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | Phished or replayed credentials; a token from another cloud's authority or another tenant accepted as ours | Cloud-specific authority in MSAL (`frontend/src/auth/msal.ts`; `authority.test.ts` asserts `login.microsoftonline.us` for Government and `login.microsoftonline.com` for Commercial). The API validator binds issuer, `tid` and audience to this deployment's cloud and tenant. MFA and conditional access are customer tenant policy | In repo | PRP-04, PRP-06 |
| T | Forged or altered token (`alg` confusion, `none`, swapped `kid`) | `packages/core/neurosphere_core/auth/jwt/validator.py`: header `alg` allowlist, `kid` lookup in the cloud's own JWKS, algorithm pinned from the key, signature plus `iss`/`aud`, then `tid`, `ver` and lifetime | In repo | PRP-06 |
| R | User denies having signed in or acted | Entra sign-in logs (customer tenant) plus audit records for denials and for every mutation, keyed by an HMAC actor pseudonym of tenant id and object id (`packages/core/neurosphere_core/auth/scope/pseudonym.py`) | In repo | PRP-06 |
| I | Access tokens leak through browser storage or logs | MSAL cache in `sessionStorage` (`frontend/src/auth/msal.ts`); PRP-05 log redaction strips bearer tokens (`packages/core/neurosphere_core/observability/redaction.py`); audit `content_guard.py` refuses tokens and UPNs in records | In repo | PRP-04, PRP-05 |
| D | Entra or JWKS unreachable | Key-infrastructure failure is `dependency_transient` (503/502); no path returns claims on error | In repo | PRP-06 |
| E | Entra role, group or scope claims treated as authority; a dev token accepted in a real deployment | Derivation reads only cloud, tenant, object id, identity type, `iat`, `exp`; Entra roles and groups are never authority (`auth/scope/derivation.py`). `useRoles.ts` reads roles for display only. `DevIssuer` and `JwtConfig` refuse a dev issuer unless `NS_ENV=local` | In repo | PRP-06, PRP-04 |

### B2. UI to APIM

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | Attacker bypasses APIM and calls the API or a data service directly | APIM is the only public ingress; data services default to `publicNetworkAccess: 'Disabled'` (`infra/bicep/modules/*.bicep`); default-deny network module and private endpoints (PRP-12 item 3). The API validates every token itself, so a bypass gains no authority | In progress | PRP-12, PRP-08 |
| T | Script injection in the UI rewrites requests or exfiltrates data; chart specs execute code | React escaping; copilot chart plans are a Vega-Lite subset (no `expr`, signals or external `url` data) rendered by `vega-interpreter` in a sandboxed iframe; CSP for the shell | Planned | PRP-19, PRP-04 |
| R | Requests cannot be correlated across gateway and API | `services/api/neurosphere_api/middleware/correlation.py` accepts a valid caller correlation id or generates a UUID4 and stamps it on responses, logs and audit | In repo | PRP-05 |
| I | Error bodies leak stack traces, hosts or other domains' existence; hidden navigation mistaken for protection | `middleware/problem.py` renders RFC 9457 bodies with a correlation id and never a trace or host. Hidden navigation is not authorization: the API denies regardless of what the UI shows; theme is never permission | In repo | PRP-05, PRP-04 |
| D | Request floods and oversized bodies | API size cap (`middleware/size_limit.py`, 422 `request_too_large`). No APIM rate-limit or quota policy exists in `infra/bicep/modules/apim.bicep` today | Gap (follow-up) | PRP-12 |
| E | A UI-only role check is the only gate on an admin view | Every route uses `require(...)` server-side; the frontend never decides access (`useRoles.ts` comment, NS-10) | In repo | PRP-06, PRP-04 |

### B3. APIM to API authorization and policy

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | Token for another audience, issuer, tenant or cloud; revoked principal replays a valid token | Validator checks `iss`, `aud`, `tid`, `ver`, lifetime; derivation runs the revocation hook (revoked is `forbidden`, checker failure is `dependency_transient`) | In repo | PRP-06 |
| T | Caller- or model-supplied `domain_id`/`customer_id`, extra headers or query parameters reshape the scope | `current_scope` reads only the `Authorization` header (`services/api/neurosphere_api/authz/dependencies.py`); `ScopeDeriver.from_verified_claims` has no request parameter; `IdentityScope` is deliberately not a Pydantic model, so no `model_validate` path exists (`packages/core/neurosphere_core/scope/identity_scope.py`) | In repo | PRP-06 |
| R | Allow or deny decisions are not attributable | Denials go through the `services/api/neurosphere_api/authz/recorder.py` hook (`build_denied` records); allowed mutations write before and after records through `packages/core/neurosphere_core/audit/repository.py`. On a mutating request a failed denial or audit write returns 503 `audit_write_failed`, never an allow | In repo | PRP-06 |
| I | Scope-filtered data served from a cache to a different principal or policy version | `authz/cache_key.py`: `ns:<cloud>:<customer_id>:<namespace>:pv=<policy_version>:<scope_hash>`; only a server-derived scope is accepted; `tests/security/authz/test_cache_paths.py` | In repo | PRP-06 |
| D | Policy store or revocation store outage | **Fail closed: 503 `dependency_transient`**, never an allow. TTL policy cache reduces store load. `services/api/tests/authz/test_fail_closed.py` asserts by AST that every `except` re-raises. Availability is traded for safety by design | In repo | PRP-06 |
| E | Privileged role used as an unrestricted bypass; expired or cross-domain grants | Privileged roles are scoped and time-bound; assignments are clipped to domain memberships of this cloud and customer; grants narrow and never add a role or domain; `tests/security/authz/test_privileged_roles.py` | In repo | PRP-06 |

### B4. API to Cosmos NoSQL (catalog and scoped graph)

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | Workload impersonated with an account key; key leaked from config | Outside `NS_ENV=local` the client factory requires managed identity and refuses keys and connection strings before any client exists (`packages/core/neurosphere_core/clients/factories.py`); `disableLocalAuth: true` in `infra/bicep/modules/cosmos.bicep` | In repo | PRP-05, PRP-08 |
| T | Lost update or overwrite of curated catalog state; steward decisions erased by re-inference | ETag mismatch returns `stale_version`; steward `EdgeOverride` decisions are immutable and folded at read time; observations accumulate and never remove evidence (`packages/core/neurosphere_core/catalog/rules.py`). **G12**: the Cosmos vNext emulator has no stored procedures, triggers or UDFs, so no integrity rule relies on server-side logic | In repo | PRP-10 |
| R | Curation changes without an actor trail | Curation service writes before and after audit records; a failed audit write aborts the change (`services/api/neurosphere_api/catalog/curation/service.py`) | In repo | PRP-10, PRP-06 |
| I | Cross-domain or cross-customer read through a query or a crafted document id | `CatalogRepository` takes the server-derived `IdentityScope` as its first parameter; `domain_id`/`customer_id` inside caller documents are checked against the scope, never trusted (`catalog/protocol.py`). Partition key shape is provisional (`catalog/partitioning.py`). **G12**: the emulator does not enforce data-plane RBAC, so locally the in-query scope filter is the only boundary exercised | In repo | PRP-10, PRP-06 |
| D | Expensive traversal exhausts RU or triggers 429 throttling for every tenant | Traversals are budgeted; G03 live run measured 39 to 58 RU mean per traversal. **G12**: the emulator has no RU accounting, no throttling and no range, composite or spatial indexes, so RU cost and 429 behaviour are evidenced only by the live G03 run; scale limits are PRP-21 | In repo (bounded); live only for RU | PRP-10, PRP-21 |
| E | Data-plane reach from outside the private network; control-plane rights on the workload identity | `publicNetworkAccess` defaults to `Disabled`; private endpoint plus private DNS (PRP-12 item 3). The workload identity has data-plane roles only; database and container creation goes through the control plane (real accounts refuse it under Entra, 403 substatus 5300, recorded in G12) | In progress | PRP-12, PRP-08 |

### B5. API to analytics adapter (Fabric, Synapse or Azure Databricks)

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | Adapter pointed at an attacker host or, in Government, at a Commercial workspace | Hosts come from config validated against per-cloud suffixes (for example `packages/core/neurosphere_core/analytics/fabric/config.py`); `create_adapter` resolves the backend through the capability matrix before importing vendor code; a disabled backend raises `capability_unavailable` with the matrix reason and nothing is routed to another cloud (`analytics/base/registry.py`) | In repo | PRP-11, PRP-02 |
| T | SQL injection, or LLM-generated SQL reaching the engine | No method accepts query text; requests are closed enums, bounded numbers and pattern-checked short values (`analytics/base/models.py`); identifiers come from a closed column whitelist and every value is a bound parameter (`analytics/base/dialect.py`) | In repo | PRP-11 |
| R | Analytics reads cannot be tied to a principal | The calling route's authorization decision is audited with the correlation id; the adapter receives the same scope object | In repo | PRP-06, PRP-11 |
| I | Rows from other customers, domains or clouds returned | `scope` is a required keyword-only argument, never a request field; customer, cloud and allowed domains are always the first predicates and caller filters only narrow (`analytics/base/plan.py`); a scope whose cloud differs from the adapter's is `forbidden` (`cloud_mismatch`) | In repo | PRP-11 |
| D | Unbounded scans exhaust capacity units, DBUs or concurrency | `run_budgeted` enforces time, rows scanned, cost units and returned rows; breach raises `rate_limited` (`analytics/base/enforcement.py`). **G12**: the sqlite stub cannot reproduce throttling, capacity units, DWU or DBU sizing (`G12_PARITY_GAPS` per adapter); live behaviour is OPEN until `g01_analytics_live.py` runs | In repo (stub only) | PRP-11 |
| E | Adapter identity holds write or admin rights on the workspace | Managed identity with a read role on the serving tables; role assignment is deployment configuration recorded in the evidence manifest | Planned | PRP-08, PRP-20 |

### B6. Copilot orchestrator to approved model endpoint

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | Unapproved or spoofed model endpoint; a Government deployment calling a Commercial endpoint | Endpoint from the cloud profile and the approved endpoint register; managed identity to the endpoint; Government egress allowlist excludes Commercial hosts | Planned | PRP-19, PRP-20 |
| T | **Direct and indirect prompt injection** steer the plan (see [AC-1](#ac-1-prompt-injection-direct-and-indirect)) | Allowlisted server-side tools with `StructuredQuery`; retrieved content passed as delimited data with provenance; abstain without evidence; shared corpus `tests/security/injection/` must pass | Planned (corpus in progress) | PRP-19, PRP-12 |
| R | A model-driven answer or draft cannot be reconstructed | Record model deployment and version, tool calls, citations and freshness as metadata; prompt and response bodies off by default | Planned | PRP-19 |
| I | Out-of-scope data or secrets sent to the model provider; retained prompts | Only scope-filtered tool results enter the context; bodies off by default; redaction before any external transmission; Government data only to Government endpoints | Planned | PRP-19, PRP-20 |
| D | Token, cost or loop exhaustion through adversarial prompts | Per-turn tool-call, token and query budgets; endpoint quota; abstain on budget breach | Planned | PRP-19 |
| E | Model output executed as code or as an action | **No LLM-generated SQL, Cypher, KQL or JavaScript**; charts are the Vega-Lite subset; the model can only draft an action, which goes through the single executor with confirmation (B7) | Planned | PRP-19, PRP-17 |

### B7. Copilot tools to durable action and HITL service

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | A tool or MCP client drafts an action as someone else | The actor is the server-derived scope of the requesting principal; MCP forbids token passthrough ([AC-2](#ac-2-confused-deputy)) | Planned | PRP-17, PRP-22 |
| T | Target, version or diff changed between confirmation and execution (TOCTOU) | Confirmation bound to target, version, diff and expiry through the intent hash; permission and target version rechecked at execution; allowlisted state machine | Planned | PRP-17 |
| R | Requester or reviewer denies approving | Durable intent and execution state; reviewer decision recorded; audit before and after | Planned | PRP-17, PRP-06 |
| I | Drafts reveal resources of other domains | Target resolution under the requester's scope (`target_unresolved`, `target_out_of_scope`) | Planned | PRP-17, PRP-06 |
| D | Draft floods; approval fatigue | Idempotency keys; expiry; per-principal rate limits | Planned | PRP-17 |
| E | Injected text makes the copilot execute without a human; a surface with weaker checks | **One action executor for button, chat, REST and MCP** with the same intent hash; explicit user confirmation; reviewer approval when policy requires; emergency disable | Planned | PRP-17, PRP-19, PRP-22 |

### B8. Action service to supported target write connectors

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | Connector talks to a spoofed endpoint or vault | Manifest validation: vault host must match a supported cloud; issues are value-free (`connectors/sdk-python/neurosphere_connector/manifest.py`) | In repo | PRP-09 |
| T | "Pretend" change: catalog metadata edited while the real target is unchanged | `VerifyResult` keeps requested diff and observed post-state apart; a mismatch is a failure, not a success (`write/write_models.py`); failed verify triggers rollback | In repo (verify) / Planned (rollback) | PRP-09, PRP-17 |
| R | Change applied without evidence | Before and after audit, canary and rollback evidence | Planned | PRP-17 |
| I | Connector credentials leak through logs, errors or dumps | Manifests carry `CredentialRef` only (vault references); `SecretValue` never renders in `repr`, `str`, format, Pydantic dump or JSON; `reveal()` only at use; rotation hook drops cached values (`neurosphere_connector/vault.py`) | In repo | PRP-09 |
| D | Faulty change cascades across targets | Dry-run, canary, verify, rollback and emergency disable on every executable path | Planned | PRP-17 |
| E | Read-only connector used to write; broad shared credential | Only connectors with real write capability can register as targets (`write/write_registry.py`); advisory connectors raise on every write method (`write/advisory.py`); delegated credentials per target | In repo | PRP-09, PRP-17 |

### B9. Append-only audit evidence

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | Forged audit records | Records exist only through `seal`; actor is the server pseudonym; the store port is create-only (`packages/core/neurosphere_core/audit/store.py`) | In repo | PRP-06 |
| T | Records altered, deleted, reordered, forked or truncated | Hash chain (`record_hash`, `previous_hash`) with verification that names the first bad index (`audit/chain.py`); no update, upsert, patch or delete in the store protocol; ETag-guarded tail pointer advances by one; sequence-derived ids prevent forks. Immutable retention and legal hold are PRP-23 | In repo; retention Planned | PRP-06, PRP-23 |
| R | A mutation happens without an audit record | **Fail closed**: a failed audit write aborts the mutation (`audit/repository.py`, 503 `audit_write_failed`) | In repo | PRP-06 |
| I | Audit stores prompts, tokens, UPNs or raw object ids; SIEM export leaks them | `audit/content_guard.py` enforces metadata-only inside `seal`; `audit/siem.py` redacts again before export and withholds storage pointers | In repo | PRP-06 |
| D | Audit store outage blocks writes; SIEM sink outage | Writes stop rather than proceed unaudited (by design); a failing SIEM sink is logged and never fails the append. **G12**: the Cosmos emulator has no RU accounting or throttling, so audit-store 429 behaviour is unverified locally | In repo | PRP-06 |
| E | Auditor role edits evidence or reads outside its scope | Security Auditor holds `audit.read` and `evidence.read` only, no `data.read` and no write (`packages/core/neurosphere_core/auth/scope/permissions.py`); the audit router fails closed with 503 until authorization is configured (`services/api/neurosphere_api/audit/router.py`) | In repo | PRP-06 |

## Additional boundaries

### A1. Producers and connectors to ingest edge to Event Hubs to workers (additional)

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | Rogue producer publishes telemetry or cost data | Producer auth at the ingest edge: `Bearer <producer_id>.<secret>`, SHA-256 compared in constant time against a registry that stores hashes only (`services/api/neurosphere_api/ingest/auth.py`); production hub has `disableLocalAuth: true`. **G12**: the Event Hubs emulator lacks Entra, so producer identity is enforced at the ingest edge; Entra producer identity on a real hub is live-only and OPEN | In repo | PRP-07, PRP-09 |
| T | Malformed, replayed or duplicated events corrupt projections | CloudEvents validation, per-item rejection, normalizer dedupe, explicit quarantine container and replay CLI; checkpoints advance only after durable accept or quarantine (Event Hubs has no DLQ) | In repo | PRP-07 |
| R | Event source cannot be proven | The authenticated registration, not the payload, identifies the producer; claims are verified against the registration (403, nothing published) | In repo | PRP-07 |
| I | Prompt or response bodies persisted or archived | `packages/core/neurosphere_core/payload/guard.py` drops bodies by default before persist or publish; archive is redacted | In repo | PRP-07 |
| D | Floods, huge or deeply nested payloads | Streamed body cap and nesting cap before parsing, per-producer throttle 429 (`ingest/limits.py`). **G12**: the emulator has no persistence across restarts and no throughput-unit throttling | In repo | PRP-07 |
| E | Producer writes into another customer, cloud or source | Edge and registration cloud must match (403); payload customer, cloud and source claims are checked against the registration and a mismatch is `CLAIM_MISMATCH` (403); absent claims are filled from the registration, never from the payload (`ingest/service.py`, `resolve_scope`) | In repo | PRP-07 |

### A2. Hot aggregates to scoped WebSocket gateway to UI (additional)

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | Unauthenticated or hijacked socket | Token validated at connect with the same validator and scope derivation as REST | Planned | PRP-18, PRP-06 |
| T | Client injects deltas or forged viewport state | Server-only push; client messages limited to bounded viewport requests | Planned | PRP-18 |
| R | Subscriptions not attributable | Connect and subscribe decisions audited | Planned | PRP-18, PRP-06 |
| I | Delta for another domain pushed to a scoped session | Scope filter per delta; `tests/security/authz/test_push_interface.py` covers the push interface | In repo (interface) / Planned (gateway) | PRP-18, PRP-06 |
| D | Session floods or oversized viewports | Per-session node, edge and rate budgets; fed from hot aggregates, not raw events | Planned | PRP-18 |
| E | Revoked principal keeps a live session | Revocation closes sessions within the configured TTL through `neurosphere_core.auth.revocation` (fan-out exists) | Planned | PRP-18, PRP-06 |

### A3. API to Azure AI Search (additional)

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | Key-based access to the search service | `disableLocalAuth: true` (`infra/bicep/modules/search.bicep`); managed identity via the client factory | In repo | PRP-08, PRP-05 |
| T | Query syntax injection from a model or user | The term is only tokenized, never parsed or evaluated; filters are allowlisted (`packages/core/neurosphere_core/search/protocol.py`) | In repo | PRP-03, PRP-10 |
| R | Search access not attributable | Route decision audited | In repo | PRP-06 |
| I | Out-of-scope documents influence results or scores | Scope applied before ranking; `tests/security/authz/test_search_paths.py` | In repo | PRP-10, PRP-06 |
| D | Expensive searches | `Budget` on every request | In repo | PRP-10 |
| E | Index admin rights on the query identity | Query identity holds index-reader role only; index management is deployment-time | Planned | PRP-08 |

### A4. MCP: external client to MCP server, MCP client to external server (additional)

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | Token for another resource, or for the client app rather than the user | OAuth 2.1 resource server, RFC 9728 metadata, `validate_token_resource=True` set explicitly, audience and resource checked separately; Dynamic Client Registration not used | Planned | PRP-22 |
| T | Poisoned tool manifest or tool output from an external server | Manifest validation; explicit administrator approval for each new tool; tool output treated as untrusted data and run through the shared corpus | Planned | PRP-22, PRP-12 |
| R | MCP-originated actions not attributable | Same intent hash and audit as REST; MCP is a `source` value only | Planned | PRP-22, PRP-17 |
| I | Tool results exceed the caller's scope | Tools run in-process with the caller's `IdentityScope`; bounded results | Planned | PRP-22 |
| D | Slow or huge external responses | Timeouts and result bounds in the client | Planned | PRP-22 |
| E | Token passthrough; stdio exposed in a hosted deployment; SSRF via registered URL | No token forwarding; hosted server is streamable HTTP only (stdio is never authenticated, local dev only); SSRF policy in [AC-3](#ac-3-server-side-request-forgery) | Planned | PRP-22 |

### A5. Deployment intelligence: consented scan, plan, approval, IaC (additional)

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | Scan runs under a credential the operator did not consent to | Keyless credential; route gated by `config.manage`; fails closed 503 (`scan_not_configured`) unless enabled (`services/api/neurosphere_api/deploy/scan/`) | In repo | PRP-08 |
| T | IaC modifies or deletes a reused shared resource | Reuse-or-create modules never write to a reused id (`infra/bicep/modules/apim.bicep` header); reusing a shared resource needs a granted consent record (`services/api/neurosphere_api/deploy/plan/planner.py`); the ownership register's removal guard is the only deletion path and never removes a resource absent from the register (`packages/core/neurosphere_core/deploy/register/guard.py`) | In repo | PRP-08 |
| R | Who consented to reuse, and which plan was approved | Consent records go through an audit sink adapted to the PRP-06 audit repository (`deploy/register/consent.py`); the plan projects to the PRP-01 `DeploymentManifest` | In repo | PRP-08, PRP-06 |
| I | Scan becomes an unrestricted tenant inventory | Visibility is requested intersected with consented intersected with readable (`deploy/scan/service.py`); fixed `SCAN_QUERY` | In repo | PRP-08 |
| D | Resource Graph throttling or unbounded paging stalls planning | Reader timeout (30 s default) and page cap (50 pages) in `deploy/scan/graph.py`; failure is surfaced, not retried silently | In repo | PRP-08 |
| E | Read scan escalates to writes; an unavailable Government feature silently enabled or swapped for Commercial | Read-only by construction (the only POST is the fixed Resource Graph query, `deploy/scan/graph.py`); capability matrix disables unavailable options with a reason; Government is gated, not banned, and never backed by Commercial | In repo; Government profile Planned | PRP-08, PRP-02, PRP-20 |

### A6. Federation summaries and DR replication (additional)

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | Rogue domain cell publishes summaries | Summaries accepted only from registered cells inside the approved boundary, under managed identity | Planned | PRP-21 |
| T | Summary or replica tampering; restore from corrupted data | Idempotent projections rebuildable from the archive; restore tests | Planned | PRP-21 |
| R | Summary provenance lost | Source cell and policy version recorded per summary | Planned | PRP-21 |
| I | Summaries leak identities or prompts; replication crosses the cloud boundary | Permitted aggregates only, keyed per NS-08 secure federation summaries; replication only to approved locations inside the same cloud and geography; never Government to Commercial | Planned | PRP-21, PRP-20 |
| D | Regional outage | Measured RTO and RPO or G07 recorded OPEN; Foundry has no automatic application failover | Planned | PRP-21 |
| E | Secondary region runs with missing or broader RBAC | Event Hubs metadata geo-DR copies neither payloads nor RBAC; failover re-applies role assignments from IaC | Planned | PRP-21 |

### A7. Public docs-only assistant (additional)

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | Assistant impersonates the in-product copilot | Separate deployment and branding; no sign-in | Planned | PRP-25 |
| T | Docs corpus poisoned to inject instructions | Corpus built only from reviewed, published docs | Planned | PRP-25 |
| R | Abuse untraceable | Request logging without bodies | Planned | PRP-25 |
| I | Tenant data reachable | No connection to any tenant store, tool or scope | Planned | PRP-25 |
| D | Anonymous traffic exhausts the model quota | Rate limits and quota | Planned | PRP-25 |
| E | Assistant invokes tools or actions | No tools, no action executor access | Planned | PRP-25 |

### A8. Build and supply chain (additional)

| | Threat | Mitigation | State | Owner |
|---|---|---|---|---|
| S | Unsigned or substituted container image deployed | cosign keyless signing via GitHub OIDC; `id-token: write` only on the signing job | Planned | PRP-13 |
| T | Compromised dependency or base image | Lockfiles (`uv.lock`, pnpm lockfile); pip-audit and pnpm audit in `ci.yml`; Dependabot (`.github/dependabot.yml`); CodeQL; `security.yml` adds syft SBOM per image plus Trivy and Grype, failing on High and Critical (PRP-12 item 2) | In repo; image scans In progress | PRP-00, PRP-12 |
| R | No record of what shipped | SBOM artifact per image; SBOM attached as OCI attestation at release | In progress | PRP-12, PRP-13 |
| I | Secrets or PII committed | `.githooks/` pre-commit and pre-push guards via `core.hooksPath`; `secret-scan.yml` runs gitleaks over full history and a PII scan; vault references only; rotate first, then clean history (runbooks, PRP-12 item 5) | In repo; runbooks In progress | PRP-00, PRP-12 |
| D | Scanner database or registry unavailable | Job fails rather than skipping: no `continue-on-error`, no `\|\| true` (`scripts/validate_planning.py` enforces the latter) | In progress | PRP-12 |
| E | Workflow token over-permissioned; malicious PR workflow | Explicit top-level `permissions:` blocks in `ci.yml`, `codeql.yml` and `secret-scan.yml`; release signing gets `id-token: write` on its own job only | In repo; release Planned | PRP-00, PRP-13 |

## Abuse cases

### AC-1. Prompt injection (direct and indirect)

DFD: [`dfd/prompt-injection.md`](dfd/prompt-injection.md). Boundaries: B6 (primary), B2, B3, B7, A1, A4.

A user types instructions that try to widen scope, run free-form queries or force an action
(direct), or attacker-planted text in telemetry, catalog fields, connector data or an MCP tool
result reaches the model as context (indirect). Expected outcome for every case: **abstain** or
**deny**; never a scope change, never generated code, never an unconfirmed action, never an
external fetch.

| Test path | Owner | State |
|---|---|---|
| `tests/security/injection/` (shared corpus, at least 50 cases, harness takes an adapter callable) | PRP-12 item 4 | In progress |
| Copilot run of the shared corpus | PRP-19 | Planned, owner PRP-19 |
| `tests/security/mcp/test_injection_via_tool_output.py` | PRP-22 | Planned, owner PRP-22 |

### AC-2. Confused deputy

DFD: [`dfd/confused-deputy.md`](dfd/confused-deputy.md). Boundaries: B3 (primary), B7, B8, A4.

A caller gets a NeuroSphere component (API, executor, MCP server) to use its own authority on a
target the caller cannot reach: a smuggled `domain_id`, a token for another audience or for the
client app, token passthrough downstream, or execution after the requester's permission was
revoked. Defences: scope derived only from verified claims and the policy store, separate
audience and resource checks, no token passthrough, permission and target version rechecked at
execution, write registry.

| Test path | Owner | State |
|---|---|---|
| `tests/security/authz/` (ABAC negative suite: API, search, cache, export, push, privileged roles) | PRP-06 | In repo |
| `tests/security/injection/` (`domain_id` and `customer_id` smuggling cases) | PRP-12 item 4 | In progress |
| `tests/security/mcp/test_confused_deputy.py` | PRP-22 | Planned, owner PRP-22 |
| `services/workers/tests/actions/test_recheck.py` | PRP-17 | Planned, owner PRP-17 |

### AC-3. Server-side request forgery

DFD: [`dfd/ssrf.md`](dfd/ssrf.md). Boundaries: A4 (primary), B5, B6, B8, A5.

An attacker-influenced URL (chart plan `url` data, model-suggested link, registered MCP server or
its redirect, connector endpoint) makes a server request the instance metadata service
(169.254.169.254), the platform address 168.63.129.16, a private endpoint, or a Commercial host
from a Government deployment. Defences: no URL parameters on tools, hosts from `CloudProfile`,
chart validator rejects `url` data, MCP client resolves DNS and blocks private, loopback,
link-local, CGNAT and metadata addresses on every redirect hop, default-deny egress, Government
egress allowlist.

| Test path | Owner | State |
|---|---|---|
| `tests/security/injection/` (SSRF URL cases) | PRP-12 item 4 | In progress |
| `tests/security/network/test_networkpolicy_render.py` (default-deny egress render) | PRP-12 item 3 | In progress |
| `packages/core/tests/mcp/test_ssrf.py` | PRP-22 | Planned, owner PRP-22 |
| `tests/security/egress/` (no Commercial egress from Government) | PRP-20 | Planned, owner PRP-20 |

## Emulator limits (G12)

Local and CI evidence runs on the Docker Compose emulators (decision D8). They cannot reproduce
these production behaviours, so the affected rows above rely on live gates for those properties:

| Emulator | Cannot reproduce | Affected rows | Consequence |
|---|---|---|---|
| Event Hubs | Entra authentication; persistence across restarts; throughput-unit throttling | A1 S, A1 D | Producer identity is enforced and tested at the ingest edge; Entra producer identity on a real hub is OPEN until the PRP-07 live run |
| Cosmos vNext | RU accounting; stored procedures, triggers and UDFs; range, composite and spatial indexes; throttling (429); data-plane RBAC; real-account network policy | B4 T, B4 I, B4 D, B4 E, B9 D | No control depends on server-side Cosmos logic; RU and 429 behaviour are evidenced only by the live G03 run; the in-query scope filter is the only boundary exercised locally. G03 emulator evidence is bounded feasibility only |
| Analytics stub (sqlite3) | Vendor SQL dialects, capacity units, DWU and DBU sizing, throttling, Entra auth | B5 D | Contract conformance only; live behaviour OPEN until `g01_analytics_live.py` runs per adapter |

## Gate references

- **G02** (FedRAMP/DoD boundary and agency ATO): OPEN. This model is an input PRP-20 and PRP-23
  cite; it does not narrow or close G02 and makes no authorization claim.
- **G08** (dependency and MCP versions and licences): NARROWED. A8 records the scanning that adds
  evidence; MCP rows (A4) stay Planned until PRP-22 lands its authorization-spec tests.
- **G12** (emulator parity): OPEN. The limits above are restated in the affected rows; no live run
  is part of this item.

## Open items found while modelling

- **B2 D, Gap**: no APIM rate-limit or quota policy exists in `infra/bicep/modules/apim.bicep`.
  Record as a follow-up issue against PRP-12; the API size cap is the only current request bound.
- Every *Planned* row is a dependency on its owning PRP shipping. Re-review this document when
  PRP-17, PRP-18, PRP-19, PRP-20, PRP-21, PRP-22 and PRP-25 ship.
