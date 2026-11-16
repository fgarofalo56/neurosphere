---
name: PRP-133-ticketing-integration
status: backlog
priority: P2
order: 133
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 9
ns: NS-05, NS-08, NS-09
depends_on: [PRP-132-alert-rules-and-incidents, PRP-117-connector-runner-and-estate-foundation, PRP-101-sensitive-information-detectors-and-redaction]
wave: W31
branch: prp-133-ticketing
allow_parallel: true
issues: []
---

# PRP-133: Ticketing integration

## Goal
Let an incident be handed to the team's ticket system through the same governed path as every other external change. A user (button), the copilot or MCP drafts a `ticket_create` action against an incident; the confirmation shows the exact ticket that would be created; a second person approves it; the durable action executor calls a new write connector, `connectors/reference/github-issues/` (kind `github_issues`, mode `write`, scaffolded `not_built` by PRP-117), which creates a GitHub issue, then reads it back to verify, and NeuroSphere records a `TicketRef` on the incident (PRP-132 `Incident.ticket_refs`, timeline entry `incident.ticket_linked`). The issue carries ids, a severity, a title built from a fixed template and links back to NeuroSphere, never captured content and never a secret. ServiceNow and Jira are verify-first targets: their official documentation is recorded and they ship `not_built` with the reason. It is for the operator who today must copy an incident into a tracker by hand, and for the auditor who needs to see who approved that an external record was created.

Out of scope: the incident model, alert rules, incident routes and pages (PRP-132); the contracts `TicketRef` and the `ticket_create` manifest action (PRP-110); the executor, confirmation hashing, approval and rollback machinery (shipped; PRP-108 added `platform-control`, which this PRP does not use); notification delivery (PRP-107); two-way sync of ticket state into incidents (not built); ServiceNow and Jira write connectors (verification and `not_built` registry rows only; their packages need a lockfile owner, see Cut line); the live run (PRP-136).

## Why
- No incident exists today and no ticket reference anywhere (design G-g, `temp/audit/governance-core-design.md` section 1); PRP-132 adds incidents and leaves "Display only here (`ticket-ref` list on the incident); PRP-133 creates them through the executor" (PRP-132 clarification 8).
- The executor refuses to pretend: `ACTION_CONNECTORS` is the one table from kind to connector and "a kind outside it is advisory" (`packages/core/neurosphere_core/actions/targets.py:3-7,59-72`). No ticket kind or ticket connector is in it, so a ticket today could only be a pretend change.
- The executor's approval default fits: `ActionApiSettings.requires_approval` returns True for any kind without a policy (`services/api/neurosphere_api/actions/settings.py:35-59`), and self-approval is forbidden by default for maker-checker (`hitl/policy.py:64-66`, cited by PRP-108). Creating a record in an external system is exactly such a change.
- Incident and violation material can touch captured content; the product keeps content in a separate encrypted channel (design section 2.1). A ticket is stored in a third party the product does not control, so its body must be an allowlisted template over ids and links (design section 4, PRP-133 "ticket bodies carry ids and links, never captured content").
- The SDK write protocol exists: `WriteConnector` with `dry_run`, `apply`, `verify`, `rollback` (`connectors/sdk-python/neurosphere_connector/write/write_protocol.py:23-50`), registered through `WriteTargetRegistry` (`write_registry.py:54`); the APIM and Foundry connectors are the patterns.
- Owner direction 2026-11-16: "the ultimate team AI governance and auditing tool"; all gaps planned. Design D-9/U-20: GitHub Issues first.

## Acceptance criteria
- [ ] Verification record: `docs/connectors/verification/github-issues.md` states, with URL and retrieval date, the documented create, read and search endpoints for issues, the authentication options (and which the verification recommends: a credential scoped to one repository), required permissions, rate limits, secondary-rate-limit behaviour, issue body size limit, how repository and organization hosts differ for GitHub Enterprise Server and data-residency offerings, and "not found" where absent. `docs/connectors/verification/servicenow.md` and `jira.md` record the same for those systems. `scripts/connector_estate_check.py` passes.
- [ ] Only verified endpoints are coded (grep test as in the sibling connector PRPs).
- [ ] Ticket template: Given an incident, When a ticket is drafted, Then title and body are rendered from a fixed template containing only: incident id, severity, status, alert rule id and name, link kinds and refs, affected entity canonical ids, the NeuroSphere deep link, the draft intent id and the idempotency marker; no free text from timeline comments, no captured content, no person identifier other than a pseudonymous owner id.
- [ ] Content and secret guard: Given an incident whose title or rule name contains a synthetic secret (token, key, connection string, private-key block) or a payment-card-like number, When the ticket is drafted, Then the draft is refused with `ticket_body_rejected` and a reason code, nothing is sent, and the refused text appears in no log, audit payload or response; a test uses PRP-101 detectors and generated identifiers only.
- [ ] Executor path: Given a `ticket_create` intent, Then `ACTION_CONNECTORS["ticket_create"]` resolves to `github-issues`; dry run returns the exact issue (repository, title, body, labels) as the diff the confirmation hash binds; apply cannot run without approval; self-approval is refused by default; the intent, approval and result are audited with the intent id and ticket key (never the body).
- [ ] Verify: Given an applied intent, Then verify reads the issue back and compares title, body digest, labels and state; a changed or missing issue yields a mismatch that the executor reports, not a success.
- [ ] Idempotency: Given a retry after an unknown outcome (timeout after send), Then the connector searches by the idempotency marker and does not create a second issue; a test injects a lost response.
- [ ] Rollback: Given a failed verify or an owner-requested undo, Then rollback closes the created issue with a comment stating it was created in error (ASSUMPTION (GD-29, recommended default): undo closes, a ticket is never deleted); stated in the dry run so the approver knows.
- [ ] Incident link: Given a verified ticket, Then the incident gains a `TicketRef` (system `github_issues`, key, https URL without query or userinfo, `intent_id`, `audit_id`) and an `incident.ticket_linked` timeline entry through PRP-132's append API; a second ticket for the same system is allowed only with an explicit `allow_additional`.
- [ ] Violations: a ticket can be requested from a policy violation page by creating (or reusing) the incident that links it; no `ticket_refs` field is added to `policy-violation` (PRP-110 gives only `Incident` that field).
- [ ] Scope and permission: drafting requires the incident's domain write permission plus `incident.manage` (PRP-132) and `action.propose`; a caller outside the domain gets 404; the ticket body never lists entities outside the caller's scope (entities are filtered by the caller's scope at draft time, the filtered count is stated).
- [ ] Repository allowlist: the connector writes only to the configured repository (`repository` setting, `owner/name`); a draft naming another repository is refused; Government and boundary rule: a deployment refuses a configuration whose host is outside its verified cloud scope and never reroutes.
- [ ] ServiceNow and Jira: each appears in the ticket system registry as `not_built` with the reason from its verification file; a `ticket_create` aimed at them is refused as advisory with that reason; nothing is stubbed to succeed.
- [ ] Credential: reference only (PRP-42); never in settings, intents, audit, logs or the issue; a rejected credential yields `credential_rejected` with no response body text.
- [ ] No Tier-1 file is edited unless the orchestrator granted it for the wave (see Ownership and item 5); without the grant, items 1 to 4 and 7 to 8 merge and the kind stays advisory (Cut line).
- PRP exit: touched suites, ruff, pyright, `scripts/connector_estate_check.py`, `validate_planning.py` pass; PR open with CI green; live run recorded OPEN and handed to PRP-136.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | What GitHub, ServiceNow and Jira expose | Assume; verify | Verify first from the official documentation at execution (design U-20 is UNVERIFIED). This PRP asserts no endpoint, permission, limit or field |
| 2 | Ticket body | Free text; fixed template | Fixed template over ids and links only; free text and timeline comments are never copied; PRP-101 detectors are a fail-closed final guard |
| 3 | Who may create | Anyone with incident access; maker-checker | Maker-checker through the existing executor (GD-20: who approves each governance action kind); approval required (the default for kinds without a policy), self-approval refused by default; ASSUMPTION: no stored review policy is added by this PRP |
| 4 | Where the credential comes from | Stored secret; reference | Reference through PRP-42 to the narrowest credential the verification file recommends; the operator installs it |
| 5 | Which repository | Per incident; one configured | One configured repository per deployment (setting `repository`); ASSUMPTION: multi-repository routing by domain is a follow-up |
| 6 | Dedup of repeated tickets | None; marker search | Idempotency marker in the body plus search before create; plus the incident-level `allow_additional` guard |
| 7 | Undo | Delete; close | Close with a comment; the dry run says so |
| 8 | Two-way sync of ticket state | In scope; not built | Not built; the incident holds the reference and link, status stays in the tracker |
| 9 | ServiceNow and Jira | Build now; verify and register | Verify and register as `not_built`; real packages need lockfile and image changes owned by a connector-wave scaffold PRP (see Cut line). ASSUMPTION |
| 10 | Violations | Add `ticket_refs` to the violation; via incident | Via the incident, no contract change |
| 11 | Dependency on PRP-101 | Own guard; reuse detectors | Reuse PRP-101's secret and card detectors (W21, already merged by this wave); added to `depends_on` beyond the design's list |
| 12 | Where the write connector's code runs | API; worker | Both, as for APIM: the API only dry-runs, the executor worker applies, verifies and rolls back |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-132-alert-rules-and-incidents.md` - `Incident`, `ticket_refs` append API, timeline kinds, routes, frontend files; `PRPs/backlog/PRP-110-governance-contracts-b.md` (`TicketRef`, `ticket_create`).
- `PRPs/backlog/PRP-117-connector-runner-and-estate-foundation.md` - scaffold of `github-issues`, shared-file rules ("write connectors are reached through the action executor, never scheduled").
- `packages/core/neurosphere_core/actions/targets.py:1-80` - `ACTION_CONNECTORS`, `TARGET_KIND_CONNECTORS`, the advisory rule.
- `connectors/sdk-python/neurosphere_connector/write/{write_protocol.py,write_models.py,write_registry.py,advisory.py}` - the contract to implement.
- `connectors/reference/apim-gateway/neurosphere_connector_apim_gateway/{connector.py,dispatch.py,records.py}` and `connectors/reference/foundry-actions` - write connector patterns (dry run, apply records, verify).
- `services/workers/neurosphere_workers/runtime/factories.py` (`register_write_targets`) and `services/api/neurosphere_api/runtime/builders/write_targets.py` - how connectors are registered in worker and API.
- `services/api/neurosphere_api/actions/settings.py:25-60` - approval default; `packages/core/neurosphere_core/actions/hashing.py:45-51` - confirmation binds target, version, diff, expiry, actor.
- `packages/core/neurosphere_core/classification/` (PRP-101) - detector protocol for the body guard.
- `docs/connectors/verification/_TEMPLATE.md` (PRP-117).

### Interfaces consumed
- PRP-132: `Incident`, `Incident.ticket_refs` append API, timeline kind `incident.ticket_linked`, permission `incident.manage`, `/api/v1/incidents` routes and detail page, store.
- PRP-110 (W25): `TicketRef` {`system`, `ticket_key`, `url`, `created_at`, `intent_id`, `audit_id`}; manifest action `ticket_create`; SDK `WriteAction` literal. PRP-99: connector kind `github_issues`.
- PRP-117: scaffold `connectors/reference/github-issues/` (`mode="write"`, `not_built`), verification template, discovered-conformance.
- Shipped: the action executor and intent API (`POST /api/v1/actions/domains/{domain}/intents`), `WriteTargetRegistry`, `AdvisoryWriteMixin`, `run_audited_mutation`, HITL maker-checker.
- PRP-101: detector protocol and secret and card detectors, by name and purpose (confirm module names at execution).
- PRP-105 and PRP-108 (by purpose): violations link to incidents; PRP-108 owns `targets.py` and `write_targets.py` earlier in the program.

### Interfaces provided
- Package `neurosphere-connector-github-issues` (module `neurosphere_connector_github_issues`): `GitHubIssuesConnector` (a `WriteConnector`), `DESCRIPTOR`, `live_check.py` (refuses without `NS_LIVE_APPROVED=1`).
- Core `neurosphere_core.incidents.ticketing`: `TicketDraft`, `render_ticket(incident, scope) -> TicketDraft`, `TicketBodyGuard`, `TicketSystemRegistry` (rows `github_issues` built per verification, `servicenow` and `jira` `not_built` with reasons), `TicketLinker` (appends `TicketRef`, timeline entry).
- Action kind `ticket_create` in `ACTION_CONNECTORS` (item 5), target entity type `incident`.
- API: `POST /api/v1/incidents/{id}/tickets/draft` (returns the rendered draft and an unsigned action intent body; the intent itself is created through the existing intents API); optional component `incident_ticketing`.
- Settings: `NS_TICKETS_GITHUB_ENABLED`, `NS_TICKETS_GITHUB_REPOSITORY` (`owner/name`), `NS_TICKETS_GITHUB_HOST` (host only; value from the verification file); credential by reference.
- Docs: `docs/connectors/verification/{github-issues,servicenow,jira}.md`, runbook section `docs/runbooks/incidents.md#tickets` (appended; file owned by PRP-132, append only).

### Patterns to match
- Write connector with dry run, records and verify: `connectors/reference/apim-gateway/neurosphere_connector_apim_gateway/connector.py`.
- Advisory mixin for unsupported kinds: `connectors/sdk-python/neurosphere_connector/write/advisory.py:18-44`.
- Guarded registration with a logged reason code: `services/api/neurosphere_api/runtime/builders/write_targets.py` (skipped targets are logged, never pretend).
- Optional component with a reason code: `services/api/neurosphere_api/runtime/builders/edge.py:17-27`.
- Test that a content canary never appears in any sink: `tests/security/capture/` (PRP-103) style.

### Gotchas
- UNVERIFIED (design U-20, verbatim): "GitHub Issues, ServiceNow and Jira have documented create/read APIs usable with a scoped token." If false: "GitHub only; others `not_built`."
- Registering the connector and the kind touches three files owned by earlier waves and not granted to this PRP: `packages/core/neurosphere_core/actions/targets.py` (PRP-108), `services/api/neurosphere_api/runtime/builders/write_targets.py` (PRP-108, Tier-1) and `services/workers/neurosphere_workers/runtime/factories.py` (`register_write_targets`; PRP-107 was the wave owner in W22). W31 has no declared owner for them. This PRP does not add them to its ownership; item 5 is `[serial-after: orchestrator grants the three Tier-1 files for W31]`.
- Write connectors are not scheduled by the connector runner (PRP-117 clarification 3); the descriptor exists for status and coverage only.
- Issue body size and label limits are vendor facts; render against the limit recorded in the verification file, and truncate only the link list with an explicit "and N more" line.
- A GitHub issue can notify watchers and may be public if the repository is public: the runbook says use a private repository, and `live_check.py` prints the repository visibility check result if the verified API exposes it.
- The idempotency marker is the intent id in a hidden-comment line; search by marker only if item 1 verified a suitable search; otherwise rely on the executor's own single-apply guarantee and say so (retry-safety criterion becomes OPEN).
- Titles of incidents and rule names are operator-written text; treat them as untrusted for the guard.
- Fixtures are synthetic, built from documentation examples; never commit a live response containing real repository names.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - connectors/reference/github-issues/**
  - docs/connectors/verification/github-issues.md
  - docs/connectors/verification/servicenow.md
  - docs/connectors/verification/jira.md
  - packages/core/neurosphere_core/incidents/ticketing/**
  - packages/core/tests/incident_ticketing/**
  - services/api/neurosphere_api/incidents/tickets.py
  - services/api/tests/incident_tickets_api/**
  - frontend/src/features/incidents/ticketing/**
  - tests/security/authz/test_ticket_create_access.py
  - changelog.d/PRP-133-ticketing-integration.md
tier1: []
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/authz/routes.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - docs/runbooks/incidents.md
must_not_touch:
  - packages/contracts/**
  - pyproject.toml
  - uv.lock
  - services/workers/pyproject.toml
  - services/api/Dockerfile
  - services/workers/Dockerfile
  - docs/licenses.md
  - docs/connectors/coverage.md
  - docs/connectors/estate-coverage.md
  - tests/unit/connector_conformance/**
  - packages/core/neurosphere_core/stores/containers.py
  - packages/core/neurosphere_core/incidents/models.py
  - packages/core/neurosphere_core/notifications/**
  - connectors/reference/apim-gateway/**
```

## Implementation blueprint

### Item 1 - Verify first: record what the three trackers document
- Deliverable: three verification files from the template: documented create, read and search of issues or tickets, authentication options and the narrowest credential, permissions, rate and secondary limits, body and label limits, host variants and cloud or residency availability, fields used, degradation, and a build or do-not-build decision per system.
- Owned files: the three verification files.
- Must NOT touch: code.
- Depends on: PRP-117 merged.
- Acceptance criteria: verification criterion; unknown stays "not found".
- Tests: `python scripts/connector_estate_check.py`.
- Pattern references: `docs/connectors/coverage.md` row format.

### Item 2 - Ticket rendering, body guard and system registry  [P]
- Deliverable: `render_ticket` with the fixed template and scope filtering, `TicketBodyGuard` using PRP-101 detectors (fail closed, reason codes, no echo of matched text), `TicketSystemRegistry` with GitHub built per verification and ServiceNow and Jira `not_built` with the recorded reason.
- Owned files: `packages/core/neurosphere_core/incidents/ticketing/{render.py,guard.py,registry.py,__init__.py}`, `packages/core/tests/incident_ticketing/**`.
- Must NOT touch: `incidents/models.py`.
- Depends on: item 1.
- Acceptance criteria: template, guard, scope and not-built criteria.
- Tests: `packages/core/tests/incident_ticketing/test_render.py`, `test_guard.py`, `test_registry.py`, `test_scope_filter.py`.
- Pattern references: `core/audit/content_guard.py` (fail closed, no echo).

### Item 3 - GitHub Issues write connector  [P]
- Deliverable: `GitHubIssuesConnector` implementing `dry_run` (exact issue as diff), `apply` (create with marker), `verify` (read back, digest comparison), `rollback` (close with comment), repository allowlist, credential per call through the broker, host allowlist, advisory behaviour when not verified; synthetic fixtures; manifest with `ticket_create` only.
- Owned files: `connectors/reference/github-issues/**`.
- Depends on: item 1.
- Acceptance criteria: executor-method, verify, idempotency, rollback, repository and credential criteria.
- Tests: `tests/test_dry_run.py`, `test_apply_verify.py`, `test_idempotent_retry.py`, `test_rollback.py`, `test_repository_allowlist.py`, `test_credential_rejected.py` with `httpx.MockTransport`; the SDK write contract kit.
- Pattern references: APIM connector `connector.py`, `records.py`.

### Item 4 - Linker and draft API  [P]
- Deliverable: `TicketLinker` (append `TicketRef` and timeline entry through PRP-132's API, `allow_additional` rule, violation-to-incident reuse), `POST /api/v1/incidents/{id}/tickets/draft` with authorization, scope filtering and 404 outside the domain, optional component `incident_ticketing`.
- Owned files: `packages/core/neurosphere_core/incidents/ticketing/linker.py`, `services/api/neurosphere_api/incidents/tickets.py`, `services/api/tests/incident_tickets_api/**`, `tests/security/authz/test_ticket_create_access.py`; Tier-2 route registry lines.
- Depends on: item 2.
- Acceptance criteria: incident-link, violations and scope criteria.
- Tests: `services/api/tests/incident_tickets_api`, `tests/security/authz/test_ticket_create_access.py`, route inventory tests.
- Pattern references: PRP-132 incident routes; `mcp/admin/router.py:96-198` (`ETag`, audited mutation).

### Item 5 - Executor registration  [serial-after: Tier-1 grant for W31]
- Deliverable: row `ticket_create` in `ACTION_CONNECTORS` and target entity type `incident`; registration of the connector in `register_write_targets` and in the API write-target builder under the `NS_TICKETS_GITHUB_*` settings, skipped with a logged reason when disabled, unverified or the host is outside the cloud; an end-to-end test: draft, approve by a second principal, apply against a fake transport, verify, link, audit.
- Owned files: `packages/core/neurosphere_core/actions/targets.py`, `services/api/neurosphere_api/runtime/builders/write_targets.py`, `services/workers/neurosphere_workers/runtime/factories.py` (registration lines only), `tests/integration/incident_ticketing/**` (new). Not in this PRP's ownership block until granted; if refused, mark this item `descoped` and the kind stays advisory.
- Depends on: items 3 and 4.
- Acceptance criteria: executor-path criterion end to end; no-Tier-1-edit criterion.
- Tests: `tests/integration/incident_ticketing/test_ticket_create_flow.py`, `services/api/tests/runtime_api/test_readiness.py` (component set update), `services/workers/tests/worker_roles` if touched.
- Pattern references: how `budget_cap_change` rows were added with the APIM connector.

### Item 6 - Incident page action
- Deliverable: a "Create ticket" control on the incident detail page that fetches the draft, shows the exact rendered ticket, and opens the standard confirmation flow; ticket links shown from `ticket_refs`; strings through the feature's strings table.
- Owned files: `frontend/src/features/incidents/ticketing/**` plus one mount line in the detail page created by PRP-132 (path confirmed at execution; an append, not a rewrite).
- Depends on: item 4 (item 5 for a working flow).
- Acceptance criteria: draft preview shows body verbatim; button absent without permission; reduced-motion and keyboard operable.
- Tests: `pnpm --filter @neurosphere/frontend test -- incidents`; `typecheck`; mock-api entry in the incidents feature mocks (new file only).
- Pattern references: `frontend/src/features/admin/sources/ConnectorsPage.tsx`, existing action confirmation components.

### Item 7 - Descriptor, conformance and live-check script
- Deliverable: `DESCRIPTOR` (`built` only if item 1 verified; else `not_built` with reason), `allowed_hosts`, `supported_clouds` from the verification file, discovered-conformance enrolment for a write kind as PRP-117 provides, `live_check.py` refusing without `NS_LIVE_APPROVED=1`, a named private repository and a statement that it creates then closes one test issue.
- Owned files: `connectors/reference/github-issues/**`.
- Depends on: item 3.
- Acceptance criteria: cloud, host and conformance criteria.
- Tests: `tests/test_conformance_enrolment.py`, `tests/test_hosts_clouds.py`.
- Pattern references: `scripts/gates/g04_connectors_live.py`.

### Item 8 - Integration and close-out
- Deliverable: README, runbook append (private repository advice, what a ticket contains, who approves), changelog fragment, Tier-3 regeneration (`openapi.json`, route manifests, `estate-coverage.md`) after rebase, completion note listing GitHub, ServiceNow and Jira each as verified-built, not found, or OPEN.
- Owned files: README, the runbook append, the changelog fragment, this PRP file.
- Depends on: items 1 to 7.
- Acceptance criteria: validation gates pass; CI green.

## Cut line
If the orchestrator does not grant the Tier-1 files for item 5, items 1 to 4, 7 and 8 still merge: rendering, guard, linker, connector, draft API and verification all work, and `ticket_create` remains advisory with that reason shown; item 5 and item 6's working flow become a one-item follow-up. ServiceNow and Jira connector packages are a separate scaffold-plus-connector follow-up because each needs lockfile and image changes.

## Validation gates
```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q connectors/reference/github-issues packages/core/tests/incident_ticketing packages/core/tests/incidents services/api/tests/incident_tickets_api services/api/tests/authz tests/security/authz/test_ticket_create_access.py tests/unit/connector_conformance tests/unit/estate_check
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test -- incidents
python scripts/connector_estate_check.py
python scripts/changelog_assemble.py --check
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration: `ticket_refs` is an additive field PRP-110 and PRP-132 already define; existing incidents have none. Turn off by not setting `NS_TICKETS_GITHUB_ENABLED` (the kind stays advisory) or by disabling the connector config; revert by reverting the PR. Tickets already created remain in the tracker and on the incident; they are closed by hand or by the rollback of their intent.

## Live and open gates
Every live call is operator-gated: `NS_LIVE_APPROVED=1`, a private test repository the operator names, a narrowly scoped credential the operator installs in the vault (never seen by the session) and a budget statement (it creates then closes one issue). Not run here; handed to PRP-136. ServiceNow and Jira live runs are not planned. Item 5, if not granted, is recorded OPEN.

## NOT building
Two-way sync of ticket status; deleting tickets; ServiceNow and Jira write connectors (verification and `not_built` rows only); tickets carrying captured content, prompts, secrets or personal data; automatic ticket creation without human approval; routing to many repositories; attachments; a general webhook ticket sink; a claim of integration with any vendor's product beyond what the verification file records.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 3, 5, 9 and 11 are ASSUMPTIONS or deviations for plan approval; item 5 needs a Tier-1 grant)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | serial-after Tier-1 grant |
| 6 | todo | | |
| 7 | todo | | |
| 8 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items (GitHub, ServiceNow, Jira each: verified-built, not found, or OPEN; whether item 5 was granted):
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an approver see the exact ticket, and does the incident show the created ticket):
