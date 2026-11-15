---
name: PRP-40-audit-search-export-and-siem-sink
status: shipped
shipped: 2026-11-15
pr: 291
priority: P0
order: 28
review: required
created: 2026-11-14
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 6
ns: NS-08, NS-09
depends_on: [PRP-37-contracts-revision-admin-cost-and-permissions, PRP-65-admin-permissions-policy-repository-and-config-store]
wave: W14
branch: prp-40-audit-siem
allow_parallel: true
issues: [234]
---

# PRP-40: Audit search, export, readable denials and an Event Hubs SIEM sink

## Goal
Make the audit trail usable by a security auditor and by the customer's SIEM. Ship an Event Hubs SIEM sink (A2) authenticated by managed identity, with its configuration state in readiness and its runtime health on an authenticated status route; an audit search API that filters by domain, operation, kind, outcome, actor pseudonym, correlation id and time range over the chains the caller may read; a bounded NDJSON/CSV export that needs the new `audit.export` permission and is itself audited; a customer-level route that finally lets an auditor read the `<customer>.authz-denials` chain; and a recorded decision plus implementation for auditing pre-scope failures (401, 503, revoked), the open PRP-06 follow-up (6). It is the backend for the PRP-53 audit page and closes lane-d step 6 except push revocation (PRP-39). It runs in W14, after PRP-37/PRP-65 adds `audit.export` and the customer-wide helper.

Out of scope: audit chain internals and #206 chain follow-ups (PRP-48 owns `packages/core/neurosphere_core/audit/` chain files in W15); allowed-read audit for search and analytics (#69, PRP-48); the audit UI (PRP-53); Bicep, Helm and App Service settings for the sink (PRP-58 hosted wiring, PRP-52 for Helm/Bicep modules); Azure Monitor Logs Ingestion, Splunk or syslog sinks; the revoke route (PRP-39); WORM storage for the audit container.

## Why
- SIEM export is stdout or file only: `JsonLinesFileSink` and `StdoutSink` (`packages/core/neurosphere_core/audit/siem.py:98-120`), `NS_AUDIT_SIEM_SINK` is `none|stdout|file` (`services/api/neurosphere_api/runtime/settings.py:121-131`), wired in `runtime/builders/data.py:320-333` (lane-d step 6).
- Sink failures are swallowed and only counted (`siem.py:74-92`, `self.failures`); PRP-06 review asked to surface them in readiness and move `to_siem_event` inside the `try` (`PRPs/shipped/PRP-06-identity-authz-and-audit.md:294`).
- No search or export: the audit page "pages and verifies only" (`frontend/src/features/audit/AuditPage.tsx:253`); routes are `/chains/{chain_id}/records|verify` (`services/api/neurosphere_api/audit/router.py:75-106`) and `/api/v1/audit/domains/{domain}/records|verify` (`ui_adapters/audit.py:140-190`); lane4 4.2 lists filter by actor, action and time and export as missing.
- Denials for non-member targets go to `<customer>.authz-denials` (`runtime/builders/authz.py:103-107`), which no role can read through the audit routes (`PRP-06-*.md:292`).
- Pre-scope failures (401, 503, revoked) are not audited; PRP-06 left it as an open decision (`PRP-06-*.md:285,293`).

## Acceptance criteria
- [x] With `NS_AUDIT_SIEM_SINK=eventhubs` plus namespace and hub settings, each audit append emits one redacted event to Event Hubs through `DefaultAzureCredential` (no key, no connection string outside `NS_ENV=local`); tested with a fake producer.
- [x] Missing or invalid Event Hubs settings make component `audit_siem` `failed` with reason `audit_siem_settings_invalid`; sink `none` reports `disabled`; the audit append path never fails because a sink fails.
- [x] A Government profile builds the namespace host with `.servicebus.usgovcloudapi.net` from `CloudProfile`; a Commercial host on a Government profile is refused (no cross-cloud send).
- [x] `GET /api/v1/audit/siem/status` (needs `audit.read` on the customer-control domain) reports sink kind, last success time, consecutive failures and last failure reason code; never a host, key or exception text.
- [x] Given an auditor with `audit.read` on domains D1 and D2, `GET /api/v1/audit/search` with filters returns only matching records from D1 and D2 chains, newest first, page size at most 500, with an opaque cursor; a filter naming D3 returns 403; time range is required and capped (constant documented in the runbook).
- [x] `GET /api/v1/audit/export?format=ndjson|csv` streams at most the documented row cap, needs `audit.export` on every domain it reads, appends an `audit.export` record (filters, row count, no record bodies) to each domain chain before streaming, and refuses with 403 when `audit.export` is missing; CSV cells are escaped against formula injection.
- [x] `GET /api/v1/audit/denials` returns `<customer>.authz-denials` records only when `permits_customer_wide(scope, AUDIT_READ)`; a domain-only auditor gets 403 `customer_scope_required`.
- [x] The pre-scope decision (Clarification 3) is recorded in the completion note and `docs/security/` is not edited here; its implementation is the `[serial-after: PRP-21]` item and is tested: revoked principals and policy-store 503s produce denial records with a reason code, and unauthenticated 401s produce a SIEM event and a counter but no chain record.
- [x] No search or export path accepts query text, SQL or a raw chain id from the caller; every Cosmos query is parameterized and single-partition per chain.
- [x] PRP exit: touched suites, ruff, pyright, `validate_planning.py` pass; `openapi.json` regenerated; PR open with CI green; runbook `docs/runbooks/audit-siem.md` lists every new env var.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | SIEM target | Event Hubs; Logs Ingestion; both | ASSUMPTION A2: Event Hubs only. Sentinel, Splunk and others read from the hub. RBAC role for the API identity: "Azure Event Hubs Data Sender" (verified on Microsoft Learn, `event-hubs/authenticate-managed-identity`) |
| 2 | Search engine | Cosmos parameterized queries per chain; AI Search index; scan with `read_range` | Parameterized single-partition Cosmos queries per readable chain behind an `AuditSearchStore` protocol, with an in-memory twin; no new index |
| 3 | Pre-scope failures | audit all; audit none; split | ASSUMPTION (recommended, confirm at plan approval): identity-known failures (revoked, policy-store 503) get a denial record on `<customer>.authz-denials`; unauthenticated 401s get a SIEM event and a counter only, because an anonymous caller could otherwise flood the hash chain |
| 4 | Export permission | `audit.read`; `data.export`; `audit.export` | `audit.export` from PRP-37/PRP-65 (Security Auditor only) |
| 5 | Who reads `authz-denials` | any auditor; customer-wide auditor | Customer-wide auditor via the control domain (PRP-37/PRP-65 helper); the chain names other domains' targets |
| 6 | Export form | async job + blob; bounded stream | Bounded synchronous stream; async jobs are a follow-up if the cap proves too small |
| 7 | `NS_AUDIT_SIEM_SINK` literal | new settings class; extend existing | Extend the existing `AuditSiemSettings.sink` literal with `eventhubs` and add new `NS_AUDIT_SIEM_EVENTHUBS_*` fields; this is the one existing-line edit in `runtime/settings.py` |

## Context manifest

### Files to read first
- `packages/core/neurosphere_core/audit/siem.py` - `SiemSink`, `SiemExporter`, `to_siem_event`.
- `packages/core/neurosphere_core/clients/factories.py:100-120` - `create_eventhub_producer` (identity vs connection string rule).
- `packages/core/neurosphere_core/cloud/profile.py:30-45` - `eventhubs_suffix` per cloud.
- `services/api/neurosphere_api/runtime/settings.py:121-152` and `runtime/builders/data.py:316-350` - SIEM settings and `_audit`.
- `services/api/neurosphere_api/runtime/status.py:1-60` - component states and lists.
- `services/api/neurosphere_api/ui_adapters/audit.py` - `auditable_chain`, `AuditAnywhere`, domain routes.
- `services/api/neurosphere_api/audit/router.py` and `audit/__init__.py` - prefixes and `register`.
- `services/api/neurosphere_api/runtime/builders/authz.py:101-160` - `DENIAL_CHAIN_NAME`, `AuditDenialRecorder`.
- `packages/core/neurosphere_core/audit/chains.py` - chain id encoding (read only).
- `packages/core/neurosphere_core/audit/cosmos_store.py` - document shape the search store queries (read only).
- `services/api/tests/runtime_data/test_audit_siem.py` and `services/api/tests/auditor_access/` - tests that pin current behaviour.

### Interfaces consumed
- From PRP-37/PRP-65: `Permission.AUDIT_EXPORT`, `Permission.AUDIT_READ`, `permits_customer_wide`, `customer_control_domain_id`, `NotFoundError`.
- From PRP-06 / PRP-31 (shipped): `AuditRepository`, `AuditRecord`, `domain_audit_chain_id`, `domain_from_audit_chain`, `require`, `AuditDenialRecorder`, `DENIAL_CHAIN_NAME`.
- From PRP-21 (W13): the merged `authz/dependencies.py` (pre-scope hook point).

### Interfaces provided
- Core: `neurosphere_core.audit.siem_eventhubs.EventHubsSiemSink`, `neurosphere_core.audit.siem_health.SiemSinkHealth` (last success, consecutive failures, last reason code).
- Settings: `NS_AUDIT_SIEM_SINK=eventhubs`, `NS_AUDIT_SIEM_EVENTHUBS_NAMESPACE`, `NS_AUDIT_SIEM_EVENTHUBS_NAME`, `NS_AUDIT_SIEM_EVENTHUBS_CLIENT_ID` (optional user-assigned identity).
- Component `audit_siem` in `OPTIONAL_COMPONENTS`; shared keys `AUDIT_SEARCH_STORE`, `SIEM_SINK_HEALTH`.
- Routes: `GET /api/v1/audit/search`, `GET /api/v1/audit/export`, `GET /api/v1/audit/denials`, `GET /api/v1/audit/siem/status`; API models `AuditSearchPage`, `AuditSiemStatus` in `neurosphere_api.audit.models`.
- Audit operation `audit.export`.

### Patterns to match
- Optional sink selection: `runtime/builders/data.py:320-333`; credential through identity: `clients/factories.py:100-120`.
- Domain-scoped audit routes with `require(..., resource=...)`: `ui_adapters/audit.py:82-190`.
- Customer-level check order: `services/api/neurosphere_api/actions/customer_control.py`.
- Parameterized single-partition queries: `packages/core/neurosphere_core/gateway/cosmos_store.py:156-192`.

### Gotchas
- `audit/` chain files (`repository.py`, `store.py`, `cosmos_store.py`, `chains.py`, `builders.py`) belong to PRP-48 in W15: search reads the container through its own store, never by editing them. `siem.py` matches this PRP's `siem*.py` glob.
- `AuditRecord` is a `response_model`: wrapping it in a new page model renames `openapi.json` components; regenerate at merge only.
- Do not log the namespace host or hub name with a secret-looking key (CodeQL); never put record bodies in the export audit record.
- `services/api/tests/audit` and `packages/core/tests/audit` already share a name; new tests go in `audit_api` and `audit_siem`.
- The Event Hubs producer is async and must be closed on app shutdown (lifetime registry), or tests leak sockets (WinError 10055 noise locally).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/audit/siem*.py
  - services/api/neurosphere_api/audit/**
  - services/api/neurosphere_api/ui_adapters/audit.py
  - services/api/tests/audit_api/**
  - packages/core/tests/audit_siem/**
  - services/api/tests/runtime_data/test_audit_siem.py
  - docs/runbooks/audit-siem.md
tier1:
  - services/api/neurosphere_api/runtime/builders/data.py
tier2_appends:
  - services/api/neurosphere_api/runtime/settings.py
  - services/api/neurosphere_api/runtime/status.py
  - services/api/neurosphere_api/runtime/builders/__init__.py
  - services/api/tests/authz/test_route_inventory.py
  - services/api/tests/authz/test_startup_route_check.py
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - mkdocs.yml
must_not_touch:
  - packages/core/neurosphere_core/audit/repository.py
  - packages/core/neurosphere_core/audit/store.py
  - packages/core/neurosphere_core/audit/cosmos_store.py
  - packages/core/neurosphere_core/audit/chains.py
  - packages/contracts/**
  - infra/**
  - frontend/**
```

## Implementation blueprint

Parallelization: items 1 and 3 are [P] (core sink vs API search store). Item 2 after 1. Item 4 after 3. Item 5 is serial-after PRP-21. Item 6 last.

### Item 1 - Event Hubs sink and sink health  [P]
- Deliverable: `siem_eventhubs.py` (`EventHubsSiemSink` taking an injected producer; batch per append; Government suffix from `CloudProfile`), `siem_health.py`, `to_siem_event` moved inside the exporter `try`, exporter reports to `SiemSinkHealth`.
- Owned files: `packages/core/neurosphere_core/audit/siem*.py`, `packages/core/tests/audit_siem/**` (new).
- Must NOT touch: other `audit/` files.
- Depends on: none.
- Acceptance criteria: fake-producer tests for emit, failure counting, recovery, redaction preserved (existing redaction scan still passes), cross-cloud host refused.
- Tests: `packages/core/tests/audit_siem`, `packages/core/tests/audit/test_redaction_scan.py`.
- Pattern references: `siem.py:98-120`, `clients/factories.py:100-120`.

### Item 2 - Compose the sink and readiness
- Deliverable: `AuditSiemSettings` literal plus `NS_AUDIT_SIEM_EVENTHUBS_*` fields; `_siem_exporter` builds the Event Hubs sink with `DefaultAzureCredential` through the lifetime registry; `audit_siem` component state; `SIEM_SINK_HEALTH` published.
- Owned files: `runtime/builders/data.py`, Tier-2 lines in `runtime/settings.py`, `runtime/status.py`, `builders/__init__.py`, `services/api/tests/runtime_data/test_audit_siem.py`.
- Depends on: item 1.
- Acceptance criteria: the first three PRP criteria; existing `stdout` and `file` behaviour unchanged.
- Tests: `services/api/tests/runtime_data`.
- Pattern references: `data.py:320-350`.

### Item 3 - Audit search store and search route  [P]
- Deliverable: `audit/search_store.py` (`AuditSearchStore` protocol, in-memory twin, Cosmos implementation over the `audit` container), `audit/search.py` router with filters, readable-chain resolution through `auditable_chain`, cursor, caps; `audit/models.py`.
- Owned files: `services/api/neurosphere_api/audit/{search_store,search,models}.py` (new), `audit/__init__.py`, `services/api/tests/audit_api/test_search.py` (new).
- Must NOT touch: `ui_adapters/audit.py` (item 4), `builders/data.py` (item 2 publishes the store; this item takes it from `app.state` with a 503 `capability_unavailable` fallback until then).
- Depends on: PRP-37/PRP-65 merged.
- Acceptance criteria: search criteria above; a Cosmos-emulator test marked `integration`.
- Tests: `services/api/tests/audit_api`.
- Pattern references: `ui_adapters/audit.py:140-190`, `gateway/cosmos_store.py:156-192`.

### Item 4 - Export, denials and SIEM status routes
- Deliverable: export stream with `audit.export`, pre-stream `audit.export` audit record per domain, CSV escaping; `/denials` with the customer-wide check; `/siem/status`; publication of `AUDIT_SEARCH_STORE` in `builders/data.py` (coordinated with item 2, same owner).
- Owned files: `services/api/neurosphere_api/audit/{export,denials,siem_status}.py` (new), `ui_adapters/audit.py` (only to share `auditable_chain`), `services/api/tests/audit_api/test_export.py`, `test_denials.py`, `test_siem_status.py` (new).
- Depends on: items 2 and 3.
- Acceptance criteria: export, denials and status criteria above; existing `services/api/tests/auditor_access` passes unchanged.
- Tests: `services/api/tests/audit_api`, `services/api/tests/auditor_access`.
- Pattern references: `actions/customer_control.py`, `ui_adapters/audit.py:82-95`.

### Item 5 - Pre-scope failure auditing  [serial-after: PRP-21]
- Deliverable: implement Clarification 3 at the scope-derivation failure points in `authz/dependencies.py` (`current_derivation`), recording through the existing denial recorder for identity-known failures and through the SIEM exporter plus a counter for 401s. Needs `authz/dependencies.py`, a Tier-1 file PRP-40 does not own: run only after PRP-21 has merged and the branch is rebased, and confirm with the orchestrator that no other W14 PRP holds it.
- Owned files: `services/api/neurosphere_api/authz/dependencies.py` (this item only), `services/api/tests/audit_api/test_prescope.py` (new).
- Depends on: item 2; PRP-21 merged.
- Acceptance criteria: the pre-scope criterion above; `services/api/tests/authz` passes.
- Tests: `services/api/tests/audit_api/test_prescope.py`, `services/api/tests/authz`.
- Pattern references: `authz/dependencies.py:240-262` (`_denial`).

### Item 6 - Integration and close-out
- Deliverable: route inventories, runbook and `mkdocs.yml` nav, env var list for the operator (no `.env.example` edit), rebase and Tier-3 regeneration, CHANGELOG, completion note with the pre-scope decision and the operator product check.
- Owned files: Tier-2 lines, `docs/runbooks/audit-siem.md` (new), Tier-3 files.
- Depends on: items 1-5.
- Acceptance criteria: gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/core/tests/audit_siem packages/core/tests/audit services/api/tests/audit_api services/api/tests/audit services/api/tests/auditor_access services/api/tests/runtime_data services/api/tests/runtime_api services/api/tests/authz services/api/tests/runtime_routes tests/security/authz services/api/tests/test_openapi_drift.py tests/docs
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Emulator suite (local): `docker compose up -d --wait` then `uv run pytest -q -m integration services/api/tests/audit_api`.

## Migration and rollback
No data migration: the search store reads existing audit documents. Default `NS_AUDIT_SIEM_SINK=none` keeps current behaviour; set it back to `none` to turn the sink off. Routes are additive; revert the PR to remove them. The pre-scope item only adds records, never changes an authorization decision.

## Live and open gates
A live Event Hubs send (managed identity with "Azure Event Hubs Data Sender", Commercial) needs `NS_LIVE_APPROVED=1` and an operator-approved namespace; Government stays OPEN (no subscription). Hand both to PRP-64 as a new item and report them OPEN here.

## NOT building
Logs Ingestion, Splunk HEC or syslog sinks; async export jobs; audit retention or legal-hold controls; UI; changes to chain naming or verification; WORM storage.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1 and 3 are ASSUMPTIONS; item 5 needs a Tier-1 file)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | verifying | prp-40-audit-siem | `siem_eventhubs.py`, `siem_health.py`, exporter guarded + `export_signal`; `packages/core/tests/audit_siem` |
| 2 | verifying | prp-40-audit-siem | `audit_siem` optional component, `SIEM_SINK_HEALTH`; deviation: one-line allowance in `runtime_data/test_data_builder.py` for `audit_siem` disabled |
| 3 | verifying | prp-40-audit-siem | `audit/{search_store,search,models,access}.py`; store published from `data.py` (Cosmos, or the repository twin with an overridden repository); emulator test written, not run (no compose) |
| 4 | verifying | prp-40-audit-siem | `audit/{export,denials,siem_status}.py` registered by a new `audit.router.register_views` hook appended to `routers.py` REGISTERED (Tier-2 line; keeps the pinned `audit.register` prefixes); `ui_adapters/audit.py` unchanged (shared `auditable_chain` imported); route inventory test added |
| 5 | verifying | prp-40-audit-siem | PRP-21 shipped; no W14 PRP holds `authz/dependencies.py` (PRP-41 lists it must_not_touch; PRP-48 owns it in W15). Hook `PrescopeAudit` in `current_derivation`, `audit/prescope.py`, installed by `data.py` |
| 6 | in-progress | prp-40-audit-siem | Done on branch: runbook `docs/runbooks/audit-siem.md` + mkdocs nav, route inventory test, env var list (below). Left for merge: rebase, Tier-3 regen (`openapi.json` drift test fails until regenerated, docs/reference), changelog fragment, completion note, CI |

## Completion note (filled at ship)
- Date and PR: 2026-11-15, PR #291 (issue #234).
- Deviations: one-line allowance in `runtime_data/test_data_builder.py` for the `audit_siem` disabled component; views registered through a new `audit.router.register_views` hook appended to `routers.py` REGISTERED (Tier-2 line). Item 5 ran after PRP-21 shipped (no W14 PRP held `authz/dependencies.py`). Pre-scope decision (Clarification 3, assumption accepted): identity-known failures (revoked principal, policy or revocation store outage, timeout, invalid derived scope) write a `denied` record with reason code on `<customer>.authz-denials` using a fixed no-scope `scope_hash`; unauthenticated 401s write no chain record, only a redacted SIEM signal and an in-process counter. Behaviour change: an invalid `NS_AUDIT_SIEM_*` setting used to fail `audit`; it now leaves `audit` ok and marks only the optional `audit_siem` component failed, so a misconfigured SIEM export no longer blocks readiness (operators should be told).
- Descoped items: none of the PRP items; the Cosmos-emulator test `test_search_cosmos_integration.py` is written but not run (marked integration, no compose in this session).
- OPEN gates: live Event Hubs send, Commercial (needs `NS_LIVE_APPROVED=1` and an approved namespace) and Government (no subscription); both handed to PRP-64 as a new item. Cosmos-emulator search test not run.
- Env vars for the operator: `NS_AUDIT_SIEM_SINK`, `NS_AUDIT_SIEM_FILE_PATH`, `NS_AUDIT_SIEM_EVENTHUBS_NAMESPACE`, `NS_AUDIT_SIEM_EVENTHUBS_NAME`, `NS_AUDIT_SIEM_EVENTHUBS_CLIENT_ID` (see `docs/runbooks/audit-siem.md`; `.env.example` not edited).
- Follow-up issues (reviewer follow-ups, not yet filed as issues):
  1. `authz/dependencies.py` `_audit_prescope`: the hook is awaited inline with no timeout, so a slow or hung append on `<customer>.authz-denials` (for example during the Cosmos outage that caused the policy-store 503) delays every failing auth response. Wrap in `asyncio.timeout(state.timeout_seconds)` or a small fixed bound.
  2. Clarification 3 accepts one chain record per identity-known failure, so a revoked principal with a still-valid token can keep appending to `<customer>.authz-denials`. Consider a per-principal rate limit or dedupe window for `authz.derive` denials.
  3. `runtime/builders/data.py` `build`: `_siem_exporter(ctx)` runs outside `ctx.attempt` and handles only `ComponentUnavailableError` and `ValidationError`; an unexpected exception from `DefaultAzureCredential(...)` or `EventHubProducerClient(...)` would abort the data builder instead of marking `audit_siem` failed. Catch `Exception` and map to `audit_siem_settings_invalid` (or a distinct code).
  4. `audit/export.py`: if the `audit.export` append succeeds on domain 1 and fails on domain 2, the export is refused with 503 but domain 1 still records an export that never happened. Accepted (fail closed); say so in the runbook.
  5. PRP-64: live Event Hubs send gate (Commercial and Government).
- Product check (can an operator use it without editing files): partial. Search, export, denials and SIEM status are API only (no UI, per NOT building); the sink is configured by env vars and the runbook, with no admin-console setting. Gap noted.
