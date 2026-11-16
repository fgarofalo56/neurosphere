---
name: PRP-124-openai-chatgpt-enterprise-connector
status: backlog
priority: P1
order: 124
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-09, NS-01, NS-02
depends_on: [PRP-110-governance-contracts-b, PRP-117-connector-runner-and-estate-foundation]
wave: W29
branch: prp-124-openai-enterprise-connector
allow_parallel: true
issues: []
---

# PRP-124: OpenAI ChatGPT Enterprise connector

## Goal
Bring ChatGPT Enterprise usage into the governed estate through `connectors/reference/openai-enterprise/` (kind `openai_enterprise`), scaffolded `not_built` by PRP-117 and run by the generic `connector_runner` role. The first item is verify-first: fetch OpenAI's current official documentation at execution and record exactly which admin-authorized, documented signals exist for a workspace (users, usage, custom GPT inventory, and compliance-API conversation records), the permissions, plan or licence and workspace role each needs, latency, granularity and availability. Only what is verified is built and tested with fixtures from the documentation's examples: workspace users and usage aggregates, custom GPT inventory into the catalog as observed assistants, and conversation metadata only if a compliance API is verified, licensed and authorized. Conversation content is out of the default build: if the compliance API returns it, it can enter only through the capture policy of PRP-103 and is otherwise dropped inside the connector; that one item runs under opus. It is for the governance lead who wants ChatGPT Enterprise use visible beside the Azure-hosted estate, and for a coverage page that says what is not seen.

Out of scope: the runner, descriptor, sinks and conformance enrolment (PRP-117); schema and kind values (PRP-110, PRP-99); capture, detection, redaction and encrypted storage of content (PRP-103, PRP-101, PRP-102); the OpenAI API platform usage and cost of customer-built agents (not a ChatGPT Enterprise signal; PRP-125's Anthropic work is separate and an OpenAI platform-usage connector is not planned here); blocking or enforcement inside ChatGPT; shadow-AI discovery (PRP-126); the live run (PRP-136).

## Why
- The target is missing from the product's own coverage inventory: `docs/connectors/coverage.md` lists Microsoft, GitHub, Anthropic, Google, xAI, Palantir, Cursor and Claude Code, and does not list OpenAI or ChatGPT Enterprise at all (design G-e). `docs/PRD.md` NS-09 asks to "publish coverage/latency/license/API limitations; no invented APIs or endpoint agents without consent."
- No kind exists to configure: `connector_kind` is a closed four-value enum (`packages/contracts/schemas/admin/v1/connector-config.schema.json:25`); PRP-99 opens it with `openai_enterprise` and PRP-117 scaffolds the package.
- Conversation content is the most sensitive signal in the estate, and the product is metadata-only by construction in six places (`services/api/neurosphere_api/ingest/service.py:124` calling `drop_body_fields`; `packages/core/neurosphere_core/payload/guard.py:21-55`; the worker `BODY_FIELD_PRESENT` check; quarantine; archive; the audit seal `packages/core/neurosphere_core/audit/content_guard.py`). A connector that read content straight into the product would bypass all six, so the design routes any vendor content only through PRP-103's capture path (policy match, detection, redaction, encryption).
- The SDK contract can express partial truth: capabilities `usage_reports`, `audit_events`, `catalog_discovery` (`connectors/sdk-python/neurosphere_connector/manifest.py:31-40`), unknown-as-null coverage and freshness (`health.py`), and create-only observed discovery exists as a pattern (`services/workers/neurosphere_workers/ingestion/foundry_discovery/poller.py`).
- Owner direction 2026-11-16: "the ultimate team AI governance and auditing tool", every identified gap planned. Design order D-9 puts ChatGPT Enterprise third.

## Acceptance criteria
- [ ] Verification record: `docs/connectors/verification/openai-enterprise.md` exists with every template heading and states per signal (workspace users, usage, custom GPT inventory, compliance-API records) the URL and retrieval date, the documented endpoint or export, authentication type and who may create the credential, required plan or licence and workspace role, granularity, latency, rate limits, data-residency or regional availability as documented, fields present, which are content-like, and "not found" where absent. `scripts/connector_estate_check.py` passes.
- [ ] Only verified signals are coded; a test greps the package for URL and path literals absent from the verification file and fails on any.
- [ ] Given fixtures of the verified user and usage payloads, When the connector collects, Then `UsageSink` rows carry the vendor's granularity and period only, unknown values null, per-user detail only under `user_detail=pseudonymous` with `ctx.pseudonymize`, and coverage and freshness reflect what answered.
- [ ] Given a verified custom GPT (or equivalent assistant) inventory, Then entries appear as `draft` observed assistants (`discovered_from = "openai_enterprise"`) through `InventorySink`, create-only; given none, none are created and the coverage page says so.
- [ ] Given a verified, licensed and authorized compliance API, Then conversation metadata only (pseudonymous principal, assistant or GPT id, model name if given, time, counts) is emitted; the response body fields that hold message text, file text or attachments are dropped at parse time; given no such API, the `audit_events` capability is reported unavailable.
- [ ] Degradation: usage export only, or `not_built` with a reason, if the compliance API or inventory is not verified; every missing signal is named in coverage and recorded OPEN; no estimate replaces a missing number.
- [ ] Content: default `content_mode=off`. A fixture with full conversation text yields output, logs, status documents and exception text with none of it (negative tests per sink and per log). The conditional content item, if executed, sends a `ContentEnvelope` to the ingest edge only; with no matching PRP-103 capture policy the edge drops it, and the connector stores, caches and logs nothing.
- [ ] Credential: reference only (PRP-42); the credential type, owner role and rotation notes are those in the verification file; a rejected credential yields `credential_rejected` and no body text; nothing credential-like in settings.
- [ ] Cloud and host: `supported_clouds` and `allowed_hosts` come only from the verification file; a Government deployment refuses a config unless verified, never rerouting; no Government data goes to a vendor endpoint outside its verified scope.
- [ ] The connector passes PRP-117's discovered-conformance test with a fake transport and a broken variant; no file outside the owned directory and verification file is edited.
- PRP exit: touched suites, ruff, pyright, `scripts/connector_estate_check.py`, `validate_planning.py` pass; PR open with CI green; live run recorded OPEN and handed to PRP-136.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | What OpenAI exposes | Assume; verify | Verify first from the official documentation at execution. This PRP asserts no endpoint, report, field, permission, licence tier or admin setting |
| 2 | Content | In scope; metadata only | Decided by the owner 2026-11-16 (GD-3): captured content is not shown to the copilot or MCP; tools see metadata and findings only; revisit after the north star. Decided by the owner 2026-11-16 (GD-4): credentials and secrets always redacted; payment card numbers redacted by default; other detected types redacted or kept per capture policy, default redact. Here: metadata only. Content from a compliance API is conditional and only through PRP-103's capture policy; the model for that item is opus, the rest sonnet (design: "opus if content is in scope") |
| 3 | If the compliance API is absent or unlicensed | Estimate; degrade | Degrade visibly: usage export only, or `not_built` with reason; the OPEN criterion is recorded; nothing is inferred |
| 4 | Credential | Stored secret; reference | Reference through PRP-42; the credential kind and its scope are whatever the verification file records |
| 5 | Scope of the connector | ChatGPT Enterprise only; plus platform API | ChatGPT Enterprise workspace signals only. Platform API usage and cost for customer-built agents is a different surface and is not planned here |
| 6 | Per-user data | Ids; pseudonyms | Aggregate by default; per-user only if the verified payload is per-user, opt-in, pseudonymised; emails and names never leave the connector call |
| 7 | Estate order (GD-9) | Recommended; by licences held | Decided by the owner 2026-11-16 (GD-9): estate connector order M365 Copilot and Copilot Studio, GitHub Copilot, ChatGPT Enterprise, Anthropic, Cursor; Entra shadow AI last. Here: Third in the estate order; live verification needs a workspace and, for compliance records, an enterprise licence the owner holds |
| 8 | Config cardinality | Many workspaces; one | One active config per kind (PRP-117 clarification 5); one workspace per customer in this PRP |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-117-connector-runner-and-estate-foundation.md` - descriptor, `RunContext`, sinks, shared-file rules.
- `connectors/reference/openai-enterprise/neurosphere_connector_openai_enterprise/__init__.py` (new in PRP-117) - scaffold to complete.
- `connectors/sdk-python/neurosphere_connector/{connector.py,manifest.py,health.py,vault.py}`.
- `services/api/neurosphere_api/ingest/service.py:3-6,124` and `packages/core/neurosphere_core/payload/guard.py:21-55` - the metadata-only edge the content path must not bypass.
- `PRPs/backlog/PRP-99-governance-contracts-a.md` - `ContentEnvelope`, `capture_source: connector`.
- `connectors/reference/azure-billing/neurosphere_connector_azure_billing/connector.py` and `tests/fixtures/`.
- `docs/connectors/coverage.md` (rows for neighbouring vendors; OpenAI is absent) and `docs/connectors/verification/_TEMPLATE.md`.
- `tests/unit/connector_conformance/test_reference_connectors_conformance.py:53-74`.

### Interfaces consumed
- PRP-117: `ConnectorDescriptor`, `EstateConnector`, `RunContext`, `UsageSink`, `InventorySink`, `EventSink`, `ctx.pseudonymize`, `ctx.http`, template, discovered-conformance test.
- PRP-110 (W25, not written at drafting time; consumed by purpose): `usage-report` model; names confirmed at execution.
- PRP-99: kind `openai_enterprise`, `ContentEnvelope`. PRP-42: `ConnectorConfig`, `CredentialReference`.
- PRP-103 (by purpose; only for the conditional content item): the edge capture policy, detection, redaction, encryption and store (PRP-101, PRP-102 behind it).

### Interfaces provided
- Package `neurosphere-connector-openai-enterprise` (module `neurosphere_connector_openai_enterprise`): `DESCRIPTOR` (status per verification), `OpenAiEnterpriseConnector`, `signals` module, `live_check.py` (refuses without `NS_LIVE_APPROVED=1`).
- `docs/connectors/verification/openai-enterprise.md`; row in generated `docs/connectors/estate-coverage.md`; evidence path `docs/evidence/G04/openai-enterprise-<stamp>.json`.

### Patterns to match
- Per-call credential via the broker: `connector.py` `credential()`.
- Partial coverage reporting: `connectors/reference/foundry/neurosphere_connector_foundry/connector.py`.
- Create-only discovery: `ingestion/foundry_discovery/poller.py`.
- Body-drop with a post-check: `connectors/reference/otel-generic`.
- Operator gate script: `scripts/gates/g04_connectors_live.py`.

### Gotchas
- UNVERIFIED (design U-15, verbatim): "ChatGPT Enterprise has a compliance API and admin/usage APIs available to workspace owners." If false: "Usage export only, or `not_built`."
- Who may create the credential, whether it is workspace-owner only, any approval step OpenAI requires for compliance access, and retention are facts to read and record, not assume.
- Conversation records may include uploaded file text, tool output and other users' data; the guard drops anything beyond the metadata allowlist, not the reverse (allowlist parse, not denylist).
- Use `httpx` through `ctx.http`; no vendor SDK. A needed SDK becomes a `[serial-after]` lockfile item raised with the orchestrator.
- Shared files are off limits (PRP-117 Gotchas, "Shared-file rules for the connector wave"); the opus content item, if run, still edits only this directory and relies on PRP-103 as merged.
- Fixtures are built from documentation examples and marked synthetic; live-run payloads are scrubbed before commit.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - connectors/reference/openai-enterprise/**
  - docs/connectors/verification/openai-enterprise.md
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
  - connectors/reference/anthropic-claude/**
```

## Implementation blueprint

### Item 1 - Verify first: record what OpenAI documents
- Deliverable: `docs/connectors/verification/openai-enterprise.md` from the template for users, usage, custom GPT inventory and compliance records: documented endpoint or export, credential type, plan or licence, workspace role, granularity, latency, limits, availability, fields used, content-like fields present and dropped, degradation, and a build or do-not-build decision per signal.
- Owned files: the verification file.
- Must NOT touch: code.
- Depends on: PRP-117 merged.
- Acceptance criteria: verification criterion; unknown stays "not found".
- Tests: `python scripts/connector_estate_check.py`.
- Pattern references: `docs/connectors/coverage.md` row format.

### Item 2 - Models, fixtures and manifest
- Deliverable: allowlist models for exactly the verified metadata fields (content-like fields never modelled), synthetic fixtures from documentation examples, manifest from `build_manifest` with verified capabilities only and `advisory=True`.
- Owned files: `connectors/reference/openai-enterprise/**`.
- Depends on: item 1.
- Acceptance criteria: only-verified criterion; manifest validates; unknowns null.
- Tests: `tests/test_models.py`, `tests/test_manifest.py`.
- Pattern references: `azure-billing` fixtures and manifest.

### Item 3 - Users, usage and inventory collection  [P]
- Deliverable: `collect` for verified user and usage signals (paging, documented rate-limit handling, period watermark, coverage and freshness, pseudonymised users) and the custom GPT inventory through `InventorySink` if verified.
- Owned files: the package.
- Depends on: item 2.
- Acceptance criteria: usage, inventory, degradation and credential criteria.
- Tests: `tests/test_usage_collect.py`, `tests/test_inventory.py`, `tests/test_credential_rejected.py` with `httpx.MockTransport`.
- Pattern references: `azure-monitor` bounded poll, `foundry_discovery/poller.py`.

### Item 4 - Compliance-record metadata (conditional)  [P]
- Deliverable: only if item 1 verified a licensed, authorized compliance API: metadata-only event emission through `EventSink`/`UsageSink` with an allowlist parser; otherwise the "audit_events unavailable" state and descoping note.
- Owned files: the package.
- Depends on: item 2.
- Acceptance criteria: compliance-metadata and degradation criteria; fixtures with full message text produce nothing but metadata.
- Tests: `tests/test_compliance_metadata.py`, `tests/test_no_content.py`.
- Pattern references: `otel-generic` body drop.

### Item 5 - Content item (conditional, opus)
- Deliverable: executed only if item 1 found content in the compliance API and the owner approves in the session: build a `ContentEnvelope` per part and send it to the ingest edge so PRP-103's policy decides; the connector drops it when the config has `content_mode=off` (the default) and never caches it; tests prove no sink, log or status document holds content and that with no capture policy nothing is stored. Otherwise recorded as descoped.
- Owned files: the package.
- Depends on: item 4.
- Acceptance criteria: content criterion.
- Tests: `tests/test_content_envelope.py`, `tests/test_content_off.py`, `tests/test_content_no_leak.py`.
- Pattern references: `PRP-99` `ContentEnvelope`, `ingest/service.py:3-6`.

### Item 6 - Descriptor, conformance and live-check script
- Deliverable: `DESCRIPTOR` (`built` only for verified signals else `not_built` with reason), `allowed_hosts`, `supported_clouds`, `conformance_factory` with fakes, a broken variant, host and cloud tests, and `live_check.py` refusing without `NS_LIVE_APPROVED=1`, a named workspace and a budget statement.
- Owned files: the package.
- Depends on: items 3 to 5.
- Acceptance criteria: conformance, cloud and host criteria.
- Tests: `tests/test_conformance_enrolment.py`, `tests/test_hosts_clouds.py`, the discovered-conformance suite.
- Pattern references: `scripts/gates/g04_connectors_live.py`.

### Item 7 - Integration and close-out
- Deliverable: README (covered, not covered, enabling), changelog fragment, Tier-3 regeneration of `estate-coverage.md` after rebase, completion note listing every signal as verified-built, not found, or OPEN, and whether the content item ran.
- Owned files: README, this PRP file.
- Depends on: items 1 to 6.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q connectors/reference/openai-enterprise tests/unit/connector_conformance tests/unit/estate_check
python scripts/connector_estate_check.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration; usage rows and `draft` observed assistants are additive. Rollback: disable the stored config for the kind, set the descriptor to `not_built`, or revert the PR; observed drafts retire through the catalog flow.

## Live and open gates
Every live call is operator-gated: `NS_LIVE_APPROVED=1`, a workspace the operator names, a credential the operator creates and installs in the vault (never seen by the session) and, for compliance records, the licence. Not run here; handed to PRP-136. Each unverified-at-runtime signal stays OPEN.

## NOT building
Blocking or enforcement inside ChatGPT (no enforcement hook is verified; observation and alerts only); per-prompt content unless a compliance API, the licence and an admin authorization all exist and PRP-103's capture policy matches; browser, endpoint or network DLP; scraping, undocumented endpoints or session-token use; OpenAI platform API usage and cost; a parity claim with any product or affiliation with OpenAI; a vendor SDK dependency; any guessed endpoint.

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
- Product check (can an operator see ChatGPT Enterprise adoption and what is not covered):
