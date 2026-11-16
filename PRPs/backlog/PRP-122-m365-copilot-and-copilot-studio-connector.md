---
name: PRP-122-m365-copilot-and-copilot-studio-connector
status: backlog
priority: P1
order: 122
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-09, NS-01, NS-02
depends_on: [PRP-110-governance-contracts-b, PRP-117-connector-runner-and-estate-foundation]
wave: W28
branch: prp-122-m365-copilot-connector
allow_parallel: true
issues: []
---

# PRP-122: Microsoft 365 Copilot and Copilot Studio connector

## Goal
Bring Microsoft 365 Copilot and Copilot Studio into the governed estate, as far as Microsoft's own admin-authorized, documented signals allow and no further. The connector is `connectors/reference/m365-copilot/` (kind `m365_copilot`), scaffolded `not_built` by PRP-117 and run by the generic `connector_runner` role. Its first item is a verify-first step: fetch Microsoft's current official documentation at execution and record exactly which usage reports, agent (Copilot Studio) inventory and audit or compliance records exist, their permissions and licences, latency and granularity and cloud availability. Only what that record supports is built: usage and adoption aggregates, Copilot Studio agents entered into the catalog as observed agents, and interaction audit events (metadata) if and only if an admin-authorized audit or compliance API exposes them. What cannot be verified ships as a visible, recorded-OPEN gap. It is for the security or governance lead who today has no view of the Copilot estate, and for the coverage page that must say honestly what is and is not seen.

Out of scope: the runner, scaffold, descriptor, sinks and conformance enrolment (PRP-117); the `usage-report` schema and the `connector_kind` value (PRP-110, PRP-99); capture, detection, redaction and storage of any content (PRP-103, PRP-101, PRP-102); blocking or policy enforcement inside Microsoft 365 (cannot be delivered, see NOT building); Entra identity and entitlements of Copilot Studio agents (PRP-118); shadow-AI discovery of unsanctioned apps (PRP-126); the Graph reads used for Purview labels (PRP-120); the live run (an operator step handed to PRP-136).

## Why
- NS-09 names this target and nothing was built: `docs/PRD.md` NS-09 lists "Microsoft Graph/M365/GitHub Copilot reports ... where documented/admin-authorized signals exist. Publish coverage/latency/license/API limitations; no invented APIs or endpoint agents without consent." `docs/connectors/coverage.md` (row "Microsoft Graph / Microsoft 365 (Copilot usage)") records "not built", "Not evaluated" for permissions, granularity, freshness and privacy, and names only two Microsoft Learn pages located by search, not evaluated.
- No connector exists and no kind can be configured: `connector_kind` is closed at four values (`packages/contracts/schemas/admin/v1/connector-config.schema.json:25`); PRP-99 opens it and PRP-117 scaffolds `connectors/reference/m365-copilot/` with a `not_built` descriptor, which is this PRP's starting point.
- The catalog already supports observed discovery with create-only semantics (`services/workers/neurosphere_workers/ingestion/foundry_discovery/poller.py`: a discovered entity is a `draft` marked `attributes.discovered_from`, never overwrites a steward), the pattern for Copilot Studio agents if an inventory exists.
- The SDK manifest already has the capabilities this connector would declare, `usage_reports`, `catalog_discovery` and `audit_events` (`connectors/sdk-python/neurosphere_connector/manifest.py:31-40`), and reports coverage and freshness with unknown as null (`health.py`), which is how a partial signal is shown.
- Owner direction 2026-11-16: "the ultimate team AI governance and auditing tool"; the design's G-e gap is that the AI the organisation actually uses (SaaS assistants) is invisible to the product. The design is explicit that blocking inside SaaS and per-prompt content are not deliverable unless the vendor exposes them.

## Acceptance criteria
- [ ] Verification record: `docs/connectors/verification/m365-copilot.md` exists with every heading of the template and states, per signal (usage reports, Copilot Studio agent inventory, audit or compliance records): the documentation URL and retrieval date, the endpoint or report as documented, required permission and admin role, required licence or plan, granularity, latency, rate limits, Commercial and Government (GCC, GCC High, DoD) availability, and "not found" where documentation has no such signal. `scripts/connector_estate_check.py` passes.
- [ ] Only verified signals are coded: each built signal cites the verification row; a signal marked not found has no code, no fixture and no endpoint string anywhere in the package (a test greps the package for URL literals not present in the verification file).
- [ ] Given recorded fixtures of the verified usage payloads, When the connector collects, Then it emits `usage-report` rows through `UsageSink` with the granularity the vendor reports (never finer), the period, unknown values as null and never 0, and `coverage` and `freshness` reflecting what answered.
- [ ] Given a verified Copilot Studio agent list, Then agents appear in the catalog as `draft` observed agents (`discovered_from = "m365_copilot"`) through `InventorySink`, never overwriting an existing entity; given no verified list, Then none are created and the coverage page says "agent inventory: not available".
- [ ] Given a verified audit or compliance API, Then interaction audit events enter as metadata only (who as a pseudonymous `person_id`, which Copilot surface or agent, when) through `EventSink` or `UsageSink` as the verification decides; given none, Then the connector reports `audit_events` as an unavailable capability, not as zero events.
- [ ] Degradation: with every signal absent the descriptor stays `not_built` with a reason; with usage only the status is `built` and coverage reports the missing signals by name; each missing signal is a recorded OPEN criterion in the completion note.
- [ ] Content: the default configuration requests metadata only; a fixture that contains prompt, response, file or message text produces output with none of those fields (negative test per output sink, logs and status document); content, if the verified API offers it, is reachable only by a separate item gated on PRP-103's capture policy and is not part of the default build (see Clarifications row 4).
- [ ] User-level data: any per-user vendor identifier, UPN or email is converted to a pseudonymous `person_id` by `ctx.pseudonymize` before leaving the connector call; a test asserts no email-shaped or UPN-shaped string reaches a sink, log or status document.
- [ ] Cloud: `supported_clouds` lists exactly the clouds the verification file proves; a Government deployment refuses the config unless verified; no Government data is sent to a Commercial endpoint.
- [ ] Network: every request goes through the runner's egress-guarded client; `allowed_hosts` holds only hosts named in the verification file; no real socket is opened by any test.
- [ ] The connector passes the contract kit through PRP-117's discovered-conformance test with a fake transport and a broken variant that the kit rejects; no edit to any file outside the owned directory is needed.
- PRP exit: touched suites, ruff, pyright, `scripts/connector_estate_check.py`, `validate_planning.py` pass; PR open with CI green; the live run is written OPEN and handed to PRP-136.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | What exists at Microsoft | Assume from memory; verify | Verify first. Nothing about an endpoint, report, field, permission, licence tier or admin setting is asserted in this PRP; item 1 fetches the current official documentation (Microsoft Learn through the repo's docs tooling or the page itself) and records it. The two pages in `docs/connectors/coverage.md` are starting points only |
| 2 | Order of signals | All at once; by value | Usage and adoption first, agent inventory second, audit or compliance records third; each independently shippable behind its own verification row |
| 3 | If a signal is absent | Fake it; degrade | The connector reports the coverage it has, visibly; the missing signal is a criterion recorded OPEN, never inferred from another source |
| 4 | Content (prompts, responses) | In scope; metadata only | Decided by the owner 2026-11-16 (GD-3): captured content is not shown to the copilot or MCP; tools see metadata and findings only; revisit after the north star. Decided by the owner 2026-11-16 (GD-4): credentials and secrets always redacted; payment card numbers redacted by default; other detected types redacted or kept per capture policy, default redact. Here: metadata only. If verification finds a compliance API that returns interaction content, it is in scope only through the PRP-103 capture policy (policy match, PRP-101 detection and redaction, PRP-102 encrypted store) and is otherwise dropped inside the connector; the model for that one item becomes opus. The default connector configuration (`content_mode=off`) requests metadata only |
| 5 | Credential | Stored secret; reference | Reference only (PRP-42): a Key Vault secret or workload identity reference on the `ConnectorConfig`; the exact application permission names come from the verification file, never from this PRP. Tenant admin consent is an operator step |
| 6 | Estate order (GD-9) | Recommended; by licences held | Decided by the owner 2026-11-16 (GD-9): estate connector order M365 Copilot and Copilot Studio, GitHub Copilot, ChatGPT Enterprise, Anthropic, Cursor; Entra shadow AI last. Here: This connector is first in the estate order. The live run depends on a tenant with a Copilot licence the owner holds |
| 7 | Config cardinality | Many tenants; one | One active config per kind (PRP-117 clarification 5); one Microsoft 365 tenant per customer in this PRP |
| 8 | Granularity of user data | Per user; aggregate | Aggregate by default. Per-user rows only if the verified report is per-user, the config sets `user_detail=pseudonymous`, and the user ids are pseudonymised; otherwise discarded at the connector |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-117-connector-runner-and-estate-foundation.md` - "Interfaces provided" (descriptor, `RunContext`, sinks) and the shared-file rules in Gotchas.
- `connectors/reference/m365-copilot/neurosphere_connector_m365_copilot/__init__.py` (new in PRP-117) - the scaffold descriptor to flesh out.
- `connectors/sdk-python/neurosphere_connector/{connector.py,manifest.py,health.py,vault.py}` - `guarded_call`, `build_manifest`, `CoverageReport`, `CredentialBroker`.
- `connectors/reference/foundry/neurosphere_connector_foundry/connector.py` - read-only connector with partial capability reporting; `connectors/reference/azure-billing/.../connector.py` - advisory manifest.
- `services/workers/neurosphere_workers/ingestion/foundry_discovery/poller.py` - create-only observed discovery.
- `docs/connectors/coverage.md` (M365 row) and `docs/connectors/verification/_TEMPLATE.md` (PRP-117).
- `PRPs/backlog/PRP-99-governance-contracts-a.md` (content envelope, `capture_source: connector`), `docs/PRD.md` NS-09.
- `tests/unit/connector_conformance/test_reference_connectors_conformance.py:53-74` - socket guard to copy into package tests.

### Interfaces consumed
- PRP-117: `ConnectorDescriptor`, `EstateConnector`, `RunContext`, `RunResult`, `UsageSink`, `InventorySink`, `EventSink`, `ctx.pseudonymize`, the egress-guarded `ctx.http`, the verification template and the discovered-conformance test.
- PRP-110 (W25; not written when this PRP was drafted, consumed by purpose): `usage-report` (seat, active users, feature, period, declared granularity) generated model and any estate fields it defines; names confirmed against the merged schema at execution.
- PRP-99: `connector_kind` value `m365_copilot`; `ContentEnvelope` and `capture_source: connector` (only for the conditional content item).
- PRP-42 (shipped): `ConnectorConfig`, `CredentialReference`, the settings bounds.
- PRP-103 (consumed by purpose, only for the conditional content item): the ingest edge capture path that decides, detects, redacts and encrypts.

### Interfaces provided
- Package `neurosphere-connector-m365-copilot` (module `neurosphere_connector_m365_copilot`): `DESCRIPTOR` (kind `m365_copilot`, status `built` for verified signals), `M365CopilotConnector`, a `signals` module listing which signals were verified and built, and `live_check.py` (operator gate, refuses without `NS_LIVE_APPROVED=1`).
- Settings accepted (declared in the descriptor, final names fixed after verification): tenant identifier, interval, `content_mode` (`off` only unless the conditional item ships), `user_detail`.
- `docs/connectors/verification/m365-copilot.md`; row in the generated `docs/connectors/estate-coverage.md`.
- Evidence path for the live run: `docs/evidence/G04/m365-copilot-<stamp>.json`.

### Patterns to match
- Per-call credential through the broker (never stored on the instance): `connector.py` `credential()`.
- Partial capability and coverage reporting: `connectors/reference/foundry/neurosphere_connector_foundry/connector.py`.
- Create-only discovery and collision counting: `ingestion/foundry_discovery/poller.py`.
- Recorded fixtures and a scripted transport in connector tests: `connectors/reference/azure-billing/tests/fixtures/`, `connectors/reference/azure-monitor/tests`.
- Operator gate script that refuses without approval: `scripts/gates/g04_connectors_live.py`.

### Gotchas
- UNVERIFIED (design U-12, verbatim): "Microsoft 365 Copilot has admin usage reports and an audit or compliance API for interactions; Copilot Studio agents are listable by an admin API." If false: "Usage aggregates only, or `not_built`." Every part of this sentence is checked in item 1; none is relied on before.
- Licence and tenant requirements (Copilot licence, audit log retention, admin roles, any compliance or premium add-on) are facts to record from the documentation, not to assume; state them in the verification file and the runbook.
- Microsoft documentation moves; record the retrieval date and the page's own revision date, and prefer the page over a search snippet.
- Fixtures are built from the documentation's example payloads and marked synthetic; real recorded payloads come only from the operator-gated run and must be scrubbed of identifiers before commit (gitleaks and PII rules).
- Per-user reports can identify people; the user-level path is opt-in, pseudonymised and documented.
- Do not add a Microsoft SDK. Use `httpx` through `ctx.http`; if verification shows an SDK is unavoidable, stop and file a `[serial-after]` lockfile item with the orchestrator rather than editing `pyproject.toml`.
- Shared files are off limits (PRP-117 Gotchas, "Shared-file rules for the connector wave").
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - connectors/reference/m365-copilot/**
  - docs/connectors/verification/m365-copilot.md
tier1: []
tier2_appends: []
must_not_touch:
  - pyproject.toml
  - uv.lock
  - services/workers/pyproject.toml
  - services/api/Dockerfile
  - services/workers/Dockerfile
  - docs/licenses.md
  - docs/adr/0002-stack-pins.md
  - docs/connectors/coverage.md
  - docs/connectors/estate-coverage.md
  - tests/unit/connector_conformance/**
  - services/workers/neurosphere_workers/**
  - services/api/neurosphere_api/**
  - packages/contracts/**
  - connectors/reference/github-copilot/**
  - connectors/reference/cursor/**
  - connectors/reference/openai-enterprise/**
```

## Implementation blueprint

### Item 1 - Verify first: record what Microsoft documents
- Deliverable: `docs/connectors/verification/m365-copilot.md` from the template: for usage reports, Copilot Studio agent inventory and audit or compliance records, the exact documented endpoint or report, permissions, admin role, licence, granularity, latency, limits, cloud availability, fields used, fields present but dropped (anything content-like), and the degradation if absent; a one-table decision "build / do not build" per signal.
- Owned files: the verification file.
- Must NOT touch: code in this item.
- Depends on: PRP-117 merged.
- Acceptance criteria: the verification criterion; every claim has a URL and date; unknown stays "not found" and is not guessed.
- Tests: `python scripts/connector_estate_check.py`.
- Pattern references: `docs/connectors/coverage.md` row format.

### Item 2 - Models, fixtures and manifest
- Deliverable: pydantic models for exactly the verified payload fields (`extra="ignore"` only for documented extras, content-like fields never modelled), synthetic fixtures from documentation examples under `tests/fixtures/`, and a manifest from `build_manifest` with capabilities limited to verified signals and `advisory=True`, scopes and granularity copied from the verification file.
- Owned files: `connectors/reference/m365-copilot/**`.
- Must NOT touch: anything outside the directory.
- Depends on: item 1.
- Acceptance criteria: only-verified-signals criterion; manifest validates; unknown values null.
- Tests: `connectors/reference/m365-copilot/tests/test_models.py`, `test_manifest.py`.
- Pattern references: `azure-billing` manifest and fixtures.

### Item 3 - Usage and adoption collection
- Deliverable: `collect` for the verified usage signal: bounded paging, rate-limit handling (honour documented retry guidance only), watermark by period, `UsageSink` rows, coverage and freshness; failure reasons as codes.
- Owned files: the package.
- Depends on: item 2.
- Acceptance criteria: usage criterion; 429 and 5xx recorded, no partial period written as complete.
- Tests: `tests/test_usage_collect.py` with a scripted `httpx.MockTransport`.
- Pattern references: `azure-monitor` bounded poll and partial reporting.

### Item 4 - Copilot Studio agent inventory and audit metadata  [P]
- Deliverable: only for signals verified in item 1: observed-agent entities through `InventorySink` (canonical id scheme per the catalog rules, `discovered_from = "m365_copilot"`), and audit-record metadata events with pseudonymous principals; each behind its own flag; absent signals produce the visible "not available" state.
- Owned files: the package.
- Depends on: item 2.
- Acceptance criteria: inventory and audit criteria; create-only; no content field in any output.
- Tests: `tests/test_inventory.py`, `tests/test_audit_metadata.py`, `tests/test_no_content.py`.
- Pattern references: `foundry_discovery/poller.py`.

### Item 5 - Content guard and conditional content item
- Deliverable: a parse-time guard that drops content-like fields before any model is built; negative tests per sink and per log; a conditional sub-item, executed only if item 1 found a compliance API with content and the owner approves in the session, that sends a `ContentEnvelope` to the edge under PRP-103 policy (opus for that sub-item); otherwise recorded as descoped.
- Owned files: the package.
- Depends on: items 3 and 4.
- Acceptance criteria: content criterion; the conditional sub-item never stores or logs content and drops it when no capture policy matches.
- Tests: `tests/test_content_guard.py`, `tests/test_pseudonymization.py`.
- Pattern references: `otel-generic` body drop with post-check.

### Item 6 - Descriptor, conformance and live-check script
- Deliverable: `DESCRIPTOR` with `status` `built` (or `not_built` with reason if nothing verified), `allowed_hosts` from the verification file, `supported_clouds`, `conformance_factory` with fakes, a broken variant test, and `live_check.py`.
- Owned files: the package.
- Depends on: items 3 to 5.
- Acceptance criteria: conformance, cloud and network criteria; `live_check.py` exits non-zero without `NS_LIVE_APPROVED=1`, a budget statement and the operator-named tenant.
- Tests: `connectors/reference/m365-copilot/tests/test_conformance_enrolment.py`, the discovered-conformance suite.
- Pattern references: `scripts/gates/g04_connectors_live.py`.

### Item 7 - Integration and close-out
- Deliverable: package README (what is covered, what is not, how to enable); changelog fragment; Tier-3 regeneration of `estate-coverage.md` after rebase; completion note listing each signal as verified-built, not-found or OPEN.
- Owned files: package README, this PRP file.
- Depends on: items 1 to 6.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q connectors/reference/m365-copilot tests/unit/connector_conformance tests/unit/estate_check
python scripts/connector_estate_check.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration. Observed agents are `draft` catalog entities marked `discovered_from = "m365_copilot"`; usage rows are additive. Rollback: disable the stored config (the runner idles that kind) or set the descriptor back to `not_built`; revert the PR. Created draft entities can be retired through the existing catalog flow.

## Live and open gates
Every live call is operator-gated: it needs `NS_LIVE_APPROVED=1`, a tenant the operator names, an admin-consented application and a Copilot licence. Not run here; the run is handed to PRP-136 and each unverified-at-runtime signal stays OPEN. Hosted egress to Microsoft hosts and the Key Vault grants are PRP-109 and PRP-63.

## NOT building
Blocking, throttling or policy enforcement inside Microsoft 365 Copilot or Copilot Studio (no enforcement hook is verified, so none is claimed; the product can observe what the admin APIs expose and alert, and can block only on paths it controls); an endpoint, browser or desktop collector; per-prompt content unless a compliance API, the tenant's licence and an admin authorization all exist and PRP-103's capture policy matches; any claim of parity with Microsoft Purview or any other product, or affiliation with Microsoft; claims of Government availability that were not verified; reading Microsoft Graph for unrelated purposes; any guessed endpoint.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 4 and 6 are ASSUMPTIONS for plan approval)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items (each signal: verified-built, not found, or OPEN):
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an operator see what Copilot coverage exists and what is missing):
