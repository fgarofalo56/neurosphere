---
name: PRP-125-anthropic-claude-connector
status: backlog
priority: P1
order: 125
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-09, NS-01, NS-02
depends_on: [PRP-110-governance-contracts-b, PRP-117-connector-runner-and-estate-foundation]
wave: W29
branch: prp-125-anthropic-claude-connector
allow_parallel: true
issues: []
---

# PRP-125: Anthropic Claude connector

## Goal
Bring Anthropic organization usage into the governed estate through `connectors/reference/anthropic-claude/` (kind `anthropic_claude`), scaffolded `not_built` by PRP-117 and run by the generic `connector_runner` role. The first item is verify-first: fetch Anthropic's current official documentation at execution and record exactly which admin-authorized, documented signals exist (organization usage and cost, workspace and key inventory, Claude Code usage analytics, and any compliance or audit data), the credential type and who may create it, plan or licence, granularity, latency, rate limits and cloud availability. Only what is verified is built and tested with fixtures taken from the documentation's examples: usage and cost aggregates per workspace and model, workspace and key inventory (ids and names, never key material) as observed estate entries, Claude Code usage if verified, and compliance or audit records only if verified, licensed and authorized. Conversation content is out of the default build: if a verified compliance surface returns it, it can enter only through the capture policy of PRP-103 and is otherwise dropped inside the connector; that one item runs under opus (the design: "model as PRP-124", which is opus if content is handled). It is for the governance lead who wants Anthropic use, cost and key sprawl visible beside the Azure-hosted estate, and for a coverage page that says what is not seen.

Out of scope: the runner, descriptor, sinks and conformance enrolment (PRP-117); schema and kind values (PRP-110 `UsageReport`, PRP-99 `connector_kind`, `ContentEnvelope`); capture, detection, redaction and encrypted storage of content (PRP-103, PRP-101, PRP-102); Claude models served through Azure AI Foundry or the customer's APIM gateway (already seen through the telemetry path, not through this vendor connector); blocking or enforcement inside Anthropic's products; shadow-AI discovery of unsanctioned Claude accounts (PRP-126); the live run (PRP-136).

## Why
- The target is in the product's own coverage inventory as "not built": `docs/connectors/coverage.md:36` (Anthropic) and `:41` (Claude Code, "not built (no dedicated connector)"). The first records a prior documentation lead only (an admin credential distinct from workspace keys, not for individual accounts) and says it was "Not built because PRP-09 builds only four reference connectors"; this PRP re-verifies that lead rather than trusting it. `docs/PRD.md` NS-09 requires "coverage/latency/license/API limitations; no invented APIs or endpoint agents without consent".
- No kind exists to configure: `connector_kind` is a closed four-value enum (`packages/contracts/schemas/admin/v1/connector-config.schema.json:25`); PRP-99 opens it with `anthropic_claude` and PRP-117 scaffolds the package.
- Conversation content is the most sensitive signal and the product is metadata-only by construction in six places (`services/api/neurosphere_api/ingest/service.py:124` calling `drop_body_fields`; `packages/core/neurosphere_core/payload/guard.py:21-55`; the worker `BODY_FIELD_PRESENT` check; quarantine; archive; `packages/core/neurosphere_core/audit/content_guard.py`). A connector that read content straight in would bypass all six, so vendor content may enter only through PRP-103's capture path.
- The SDK already supports partial truth: capabilities `usage_reports`, `audit_events`, `catalog_discovery` (`connectors/sdk-python/neurosphere_connector/manifest.py:31-40`), unknown-as-null coverage and freshness (`health.py`), and the create-only observed-discovery pattern (`services/workers/neurosphere_workers/ingestion/foundry_discovery/poller.py`).
- Owner direction 2026-11-16: "the ultimate team AI governance and auditing tool"; every identified gap planned. Design order D-9 puts Anthropic fourth.

## Acceptance criteria
- [ ] Verification record: `docs/connectors/verification/anthropic-claude.md` exists with every template heading and states, per signal (organization usage, cost, workspace and key inventory, Claude Code usage, compliance or audit records), the URL and retrieval date, documented endpoint or export, authentication type and who may create the credential, required plan or licence, granularity, latency, rate limits, availability by cloud or region as documented, fields present, which are content-like, and "not found" where absent. `scripts/connector_estate_check.py` passes.
- [ ] Only verified signals are coded; a test greps the package for URL and path literals absent from the verification file and fails on any.
- [ ] Given fixtures of the verified usage and cost payloads, When the connector collects, Then `UsageSink` rows carry the vendor's granularity and period only, unknown values null (never 0), cost with its currency, and coverage and freshness reflect which signals answered.
- [ ] Given a verified workspace or key inventory, Then entries appear as observed, `draft` estate entries through `InventorySink` carrying ids, names, creator reference (pseudonymised through `ctx.pseudonymize`) and created and last-used times only; no key value, key hint or secret-like string is read into a model, and a test with a fixture containing a full key string proves it appears nowhere in output, logs or the status document.
- [ ] Given verified Claude Code usage analytics, Then they map to `UsageSink` aggregates (per user only when the payload is per user, opt-in `user_detail=pseudonymous`); anything resembling prompts, file paths or code is dropped at parse time. If only a telemetry export is documented (coverage.md:41 says it may be receivable by the generic OTel connector, which is not claimed), the connector reports Claude Code `not_built` and points to that path; nothing is assumed.
- [ ] Given a verified, licensed and authorized compliance or audit surface, Then metadata only (pseudonymous principal, workspace id, model name if given, time, counts) is emitted; fields holding message text, file text or attachments are dropped by an allowlist parser; given none, `audit_events` is reported unavailable.
- [ ] Degradation: if the compliance surface, inventory or Claude Code analytics is not verified, the connector ships usage and cost only, or `not_built` with a reason; every missing signal is named in coverage and recorded OPEN; no estimate replaces a missing number.
- [ ] Content: default `content_mode=off`. A fixture with full conversation text yields output, logs, status documents and exception text with none of it (negative tests per sink and per log). The conditional content item, if executed, sends a `ContentEnvelope` to the ingest edge only; with no matching PRP-103 capture policy the edge drops it and the connector stores, caches and logs nothing.
- [ ] Credential: reference only (PRP-42); the credential type, owner role and rotation notes are those in the verification file; the document's own warning, if any, that an admin credential differs from an ordinary workspace key is carried into the runbook text; a rejected credential yields `credential_rejected` with no body text; nothing credential-like in settings.
- [ ] Cloud and host: `supported_clouds` and `allowed_hosts` come only from the verification file; a Government deployment refuses a config unless verified, never rerouting; no Government data goes to a vendor endpoint outside its verified scope.
- [ ] The connector passes PRP-117's discovered-conformance test with a fake transport and a broken variant; no file outside the owned directory, its verification file and a changelog fragment is edited.
- PRP exit: touched suites, ruff, pyright, `scripts/connector_estate_check.py`, `validate_planning.py` pass; PR open with CI green; live run recorded OPEN and handed to PRP-136.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | What Anthropic exposes | Assume; verify | Verify first from the official documentation at execution. This PRP asserts no endpoint, report, field, permission, licence tier or admin setting; `coverage.md:36` is a lead to re-check, not evidence |
| 2 | Content | In scope; metadata only | ASSUMPTION (GD-3, recommended default): captured content is not shown to the copilot or MCP; tools see metadata and findings only; revisit after the north star. ASSUMPTION (GD-4, recommended default): credentials and secrets always redacted; payment card numbers redacted by default; other detected types redacted or kept per capture policy, default redact. Here: metadata only. Content from a compliance surface is conditional and only through PRP-103's capture policy; model for that item is opus, the rest sonnet |
| 3 | If the compliance surface is absent or unlicensed | Estimate; degrade | Degrade visibly: usage and cost only, or `not_built` with reason; the OPEN criterion is recorded; nothing inferred |
| 4 | Credential | Stored secret; reference | Reference through PRP-42; the credential kind and its scope are whatever the verification file records |
| 5 | Scope | Anthropic organization signals only; plus cloud-hosted Claude | Organization signals from Anthropic's own admin surfaces. Claude served via Foundry or the APIM gateway is observed through the existing telemetry path, not here |
| 6 | Per-user data | Ids; pseudonyms | Aggregate by default; per-user only if the verified payload is per-user, opt-in, pseudonymised; emails and names never leave the connector call |
| 7 | Estate order (GD-9) | Recommended; by licences held | ASSUMPTION (GD-9, recommended default): estate connector order M365 Copilot and Copilot Studio, GitHub Copilot, ChatGPT Enterprise, Anthropic, Cursor; Entra shadow AI last. Here: Fourth in the estate order; live verification needs an organization with an admin credential the operator holds |
| 8 | Config cardinality | Many organizations; one | One active config per kind (PRP-117 clarification 5); one organization per customer in this PRP |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-117-connector-runner-and-estate-foundation.md` - descriptor, `RunContext`, sinks, "Shared-file rules for the connector wave".
- `PRPs/backlog/PRP-124-openai-chatgpt-enterprise-connector.md` and `PRPs/backlog/PRP-122-m365-copilot-and-copilot-studio-connector.md` - sibling structure to match.
- `connectors/reference/anthropic-claude/neurosphere_connector_anthropic_claude/__init__.py` (new in PRP-117) - scaffold to complete.
- `connectors/sdk-python/neurosphere_connector/{connector.py,manifest.py,health.py,vault.py}`.
- `services/api/neurosphere_api/ingest/service.py:3-6,124` and `packages/core/neurosphere_core/payload/guard.py:21-55` - the metadata-only edge the content path must not bypass.
- `PRPs/backlog/PRP-99-governance-contracts-a.md` - `ContentEnvelope`, `capture_source: connector`; `PRPs/backlog/PRP-110-governance-contracts-b.md` - `UsageReport`.
- `connectors/reference/azure-billing/neurosphere_connector_azure_billing/connector.py` and its fixtures - cost and period pattern.
- `docs/connectors/coverage.md` (rows 36 and 41) and `docs/connectors/verification/_TEMPLATE.md` (new in PRP-117).
- `tests/unit/connector_conformance/test_reference_connectors_conformance.py:53-74` - socket guard.

### Interfaces consumed
- PRP-117: `ConnectorDescriptor`, `EstateConnector`, `RunContext`, `UsageSink`, `InventorySink`, `EventSink`, `ctx.pseudonymize`, `ctx.http`, the verification template, the discovered-conformance test.
- PRP-110 (W25; consumed by the names in its "Interfaces provided"): `UsageReport` with `source_system` values `anthropic_claude` and `claude_code`, `metrics` with null for unknown, `per_user_available`.
- PRP-99: kind `anthropic_claude`, `ContentEnvelope`. PRP-42 (shipped): `ConnectorConfig`, `CredentialReference`.
- PRP-103 (by purpose; only for the conditional content item): edge capture policy, detection, redaction, encryption and store (PRP-101, PRP-102 behind it).

### Interfaces provided
- Package `neurosphere-connector-anthropic-claude` (module `neurosphere_connector_anthropic_claude`): `DESCRIPTOR` (status per verification), `AnthropicClaudeConnector`, `signals` module, `live_check.py` (refuses without `NS_LIVE_APPROVED=1`).
- `docs/connectors/verification/anthropic-claude.md`; a row in the generated `docs/connectors/estate-coverage.md`; evidence path `docs/evidence/G04/anthropic-claude-<stamp>.json`.

### Patterns to match
- Per-call credential via the broker: `connectors/sdk-python/neurosphere_connector/connector.py` `credential()`.
- Partial coverage reporting: `connectors/reference/foundry/neurosphere_connector_foundry/connector.py`.
- Create-only discovery: `services/workers/neurosphere_workers/ingestion/foundry_discovery/poller.py`.
- Body drop with a post-check: `connectors/reference/otel-generic`.
- Operator gate script: `scripts/gates/g04_connectors_live.py`.

### Gotchas
- UNVERIFIED (design U-16, verbatim): "Anthropic has organization admin, usage/cost and compliance or audit APIs, and Claude Code usage analytics." If false: "Usage and cost only."
- Who may create the credential, whether it is organization-admin only, whether it exists for individual or team plans, and what its lifetime is, are facts to read and record, not assume. Inventory listings may expose key identifiers or partial key strings; the allowlist parser takes ids and names only.
- Compliance or audit records, where they exist, may contain other users' prompts and file text; parse by allowlist, never by denylist.
- Use `httpx` through `ctx.http`; no vendor SDK. A needed SDK becomes a `[serial-after]` lockfile item raised with the orchestrator.
- Shared files are off limits (PRP-117 Gotchas, "Shared-file rules for the connector wave"); the opus content item still edits only this directory and relies on PRP-103 as merged.
- Fixtures are built from documentation examples and marked synthetic; live-run payloads are scrubbed before commit. Never paste a real key, even a revoked one.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - connectors/reference/anthropic-claude/**
  - docs/connectors/verification/anthropic-claude.md
  - changelog.d/PRP-125-anthropic-claude-connector.md
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
  - connectors/reference/m365-copilot/**
  - connectors/reference/github-copilot/**
  - connectors/reference/openai-enterprise/**
  - connectors/reference/entra-shadow-ai/**
```

## Implementation blueprint

### Item 1 - Verify first: record what Anthropic documents
- Deliverable: `docs/connectors/verification/anthropic-claude.md` from the template for organization usage, cost, workspace and key inventory, Claude Code usage and compliance or audit records: documented endpoint or export, credential type, plan or licence, granularity, latency, limits, availability, fields used, content-like fields present and dropped, degradation, and a build or do-not-build decision per signal.
- Owned files: the verification file.
- Must NOT touch: code.
- Depends on: PRP-117 merged.
- Acceptance criteria: verification criterion; unknown stays "not found".
- Tests: `python scripts/connector_estate_check.py`.
- Pattern references: `docs/connectors/coverage.md` row format.

### Item 2 - Models, fixtures and manifest
- Deliverable: allowlist models for exactly the verified metadata fields (content-like and key-like fields never modelled), synthetic fixtures from documentation examples, manifest from `build_manifest` with verified capabilities only and `advisory=True`.
- Owned files: `connectors/reference/anthropic-claude/**`.
- Must NOT touch: anything outside the package.
- Depends on: item 1.
- Acceptance criteria: only-verified criterion; manifest validates; unknowns null.
- Tests: `tests/test_models.py`, `tests/test_manifest.py`.
- Pattern references: `azure-billing` fixtures and manifest.

### Item 3 - Usage, cost and inventory collection  [P]
- Deliverable: `collect` for verified usage and cost signals (paging, documented rate-limit handling, period watermark, coverage and freshness) and the workspace and key inventory through `InventorySink` if verified, with the key-material negative test.
- Owned files: the package.
- Depends on: item 2.
- Acceptance criteria: usage, inventory, degradation and credential criteria.
- Tests: `tests/test_usage_collect.py`, `tests/test_inventory.py`, `tests/test_no_key_material.py`, `tests/test_credential_rejected.py` with `httpx.MockTransport`.
- Pattern references: `azure-monitor` bounded poll, `foundry_discovery/poller.py`.

### Item 4 - Claude Code usage and compliance metadata (conditional)  [P]
- Deliverable: only for what item 1 verified: Claude Code usage aggregates, and metadata-only compliance or audit event emission through `EventSink` with an allowlist parser; otherwise `audit_events` reported unavailable and the signal descoped in the completion note.
- Owned files: the package.
- Depends on: item 2.
- Acceptance criteria: Claude Code, compliance-metadata and degradation criteria; fixtures with full message text yield only metadata.
- Tests: `tests/test_claude_code_usage.py`, `tests/test_compliance_metadata.py`, `tests/test_no_content.py`.
- Pattern references: `otel-generic` body drop.

### Item 5 - Content item (conditional, opus)
- Deliverable: executed only if item 1 found content in a verified compliance surface and the owner approves in the session: build a `ContentEnvelope` per part and send it to the ingest edge so PRP-103's policy decides; with `content_mode=off` (default) the connector drops it and never caches it; tests prove no sink, log or status document holds content and that with no capture policy nothing is stored. Otherwise recorded as descoped.
- Owned files: the package.
- Depends on: item 4.
- Acceptance criteria: content criterion.
- Tests: `tests/test_content_envelope.py`, `tests/test_content_off.py`, `tests/test_content_no_leak.py`.
- Pattern references: PRP-99 `ContentEnvelope`, `ingest/service.py:3-6`.

### Item 6 - Descriptor, conformance and live-check script
- Deliverable: `DESCRIPTOR` (`built` only for verified signals, else `not_built` with reason), `allowed_hosts`, `supported_clouds`, `conformance_factory` with fakes, a broken variant, host and cloud tests, and `live_check.py` refusing without `NS_LIVE_APPROVED=1`, a named organization and a budget statement.
- Owned files: the package.
- Depends on: items 3 to 5.
- Acceptance criteria: conformance, cloud and host criteria.
- Tests: `tests/test_conformance_enrolment.py`, `tests/test_hosts_clouds.py`, the discovered-conformance suite.
- Pattern references: `scripts/gates/g04_connectors_live.py`.

### Item 7 - Integration and close-out
- Deliverable: README (covered, not covered, how to enable, credential warning), changelog fragment, Tier-3 regeneration of `estate-coverage.md` after rebase, completion note listing every signal as verified-built, not found, or OPEN, and whether the content item ran.
- Owned files: README, the changelog fragment, this PRP file.
- Depends on: items 1 to 6.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q connectors/reference/anthropic-claude tests/unit/connector_conformance tests/unit/estate_check
python scripts/connector_estate_check.py
python scripts/changelog_assemble.py --check
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration; usage rows and observed `draft` entries are additive. Rollback: disable the stored config for the kind, set the descriptor to `not_built`, or revert the PR; observed drafts retire through the catalog flow.

## Live and open gates
Every live call is operator-gated: `NS_LIVE_APPROVED=1`, an organization the operator names, a credential the operator creates and installs in the vault (never seen by the session), and for any compliance surface the licence. Not run here; handed to PRP-136. Each signal not verified at execution stays OPEN. Anthropic usage calls may be billable or rate limited: the live script states the budget.

## NOT building
Blocking or enforcement inside Anthropic's products (no enforcement hook is verified; observation and alerts only); per-prompt content unless a compliance surface, the licence and an admin authorization all exist and PRP-103's capture policy matches; browser, endpoint or network DLP; scraping, undocumented endpoints or session-token use; a parity claim with any product or affiliation with Anthropic; a vendor SDK dependency; any guessed endpoint; reading, storing or displaying API key values.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 2 and 7 are ASSUMPTIONS for plan approval)

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
- Descoped items (each signal: verified-built, not found, or OPEN; whether the content item ran):
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an operator see Anthropic use and cost and what is not covered):
