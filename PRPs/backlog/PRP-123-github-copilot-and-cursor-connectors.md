---
name: PRP-123-github-copilot-and-cursor-connectors
status: backlog
priority: P1
order: 123
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-09, NS-01
depends_on: [PRP-110-governance-contracts-b, PRP-117-connector-runner-and-estate-foundation]
wave: W28
branch: prp-123-github-copilot-cursor-connectors
allow_parallel: true
issues: []
---

# PRP-123: GitHub Copilot and Cursor connectors

## Goal
Give the governance product a view of coding assistants: seats, usage metrics and, where the vendor exposes them, audit events, for GitHub Copilot (`connectors/reference/github-copilot/`, kind `github_copilot`) and Cursor (`connectors/reference/cursor/`, kind `cursor`). Both packages are scaffolded `not_built` by PRP-117 and run by the generic `connector_runner` role. Each connector starts with a verify-first item that fetches the vendor's current official documentation at execution and records exactly which admin-authorized, documented signals exist, the permissions and licence or plan each needs, latency and granularity and cloud availability. Only what is verified is built, tested with fixtures taken from the documentation's examples. No prompt or code content is assumed or requested. Cursor stays a recorded GAP, as `docs/connectors/coverage.md` shows today, unless its documentation verifies an admin or analytics API for teams. It is for the platform lead who wants to know how many developers use which assistant, at what adoption, and for the coverage page that must not over-claim.

Out of scope: the runner, descriptors, sinks and conformance enrolment (PRP-117); the `usage-report` schema and kind values (PRP-110, PRP-99); content capture (PRP-103, 101, 102); any endpoint agent, IDE plugin or desktop collector (never built without consent, per `docs/PRD.md` NS-09); blocking or policy enforcement inside either product; Claude Code usage (PRP-125); GitHub Issues ticketing (PRP-133, a different package); the live run (PRP-136).

## Why
- NS-09 lists both targets: `docs/PRD.md` NS-09 "Microsoft Graph/M365/GitHub Copilot reports, Anthropic, Google, xAI, Palantir, Cursor and Claude Code where documented/admin-authorized signals exist ... no invented APIs or endpoint agents without consent."
- `docs/connectors/coverage.md` records GitHub Copilot as "not built" (a docs.github.com Copilot usage metrics page exists, "content not evaluated"; plan, scope, granularity, freshness and residency availability "Not evaluated") and Cursor as "GAP: not implemented" (an admin API docs page exists with usage and spending sections "not reviewed for fields, auth, plan eligibility, rate limits or terms"). Neither has a connector.
- No kind can be configured today: `connector_kind` is a closed four-value enum (`packages/contracts/schemas/admin/v1/connector-config.schema.json:25`); PRP-99 opens it and PRP-117 scaffolds both packages with `not_built` descriptors.
- The connector contract already expresses partial truth: manifest capabilities `usage_reports` and `audit_events` (`connectors/sdk-python/neurosphere_connector/manifest.py:31-40`), `CoverageReport` and `FreshnessReport` with unknown as null (`health.py`), and the contract kit (`contract_kit.py:100`).
- Owner direction 2026-11-16: all identified gaps planned, "the ultimate team AI governance and auditing tool"; the design's G-e finding is that the AI the organisation actually uses is not governed. Order of estate connectors (design D-9): GitHub Copilot second, Cursor fifth.

## Acceptance criteria
- [ ] Verification records: `docs/connectors/verification/github-copilot.md` and `docs/connectors/verification/cursor.md` exist with every template heading; each states per signal (seats, usage metrics, audit events; for Cursor whatever the admin documentation lists) the URL and retrieval date, the documented endpoint, required token type and scopes, required plan or licence, granularity, latency, rate limits, cloud or hosting availability (for GitHub: github.com, data residency, Enterprise Server as documented), and "not found" where absent. `scripts/connector_estate_check.py` passes.
- [ ] Only verified signals are coded; a test greps both packages for URL and path literals absent from the matching verification file and fails on any.
- [ ] Given fixtures of the verified GitHub seat and metrics payloads, When the connector collects, Then `UsageSink` receives rows at the vendor's declared granularity and period (never finer, never invented per-user detail), unknown values null, coverage and freshness populated.
- [ ] Given a verified GitHub audit signal for Copilot events, Then metadata events (actor as a pseudonymous `person_id`, action, time, organisation) are emitted and nothing that carries code or prompt text; given none, the capability is reported unavailable.
- [ ] Cursor: given verification finds an admin or analytics API usable with a team admin credential, Then usage rows are built the same way; given not, Then the descriptor stays `not_built` with reason "no documented admin API verified", the coverage page shows GAP, and the completion note records the criterion OPEN. Neither outcome fails the PRP.
- [ ] Degradation: each missing signal is reported by name in coverage and recorded OPEN; the connector never substitutes an inferred or estimated number for a missing one.
- [ ] Content: default `content_mode=off`; fixtures that carry content-like fields (suggestion text, chat text, code, file names beyond repository identity) yield output, logs and status documents without them; there is no code path that stores or forwards content in this PRP.
- [ ] Credential: reference only (PRP-42); the token type and scopes are those the verification file records; nothing about a token appears in settings (the config schema rejects secret-like setting names); a test confirms an unauthorised or wrong-scope response yields reason `credential_rejected` with no body text.
- [ ] Cloud and host: `supported_clouds` and `allowed_hosts` come only from the verification files; a Government deployment refuses a config for a vendor not verified there; nothing is rerouted to another cloud.
- [ ] Both connectors pass PRP-117's discovered-conformance test with fakes and a broken variant; no file outside the two owned directories and two verification files is edited.
- PRP exit: touched suites, ruff, pyright, `scripts/connector_estate_check.py`, `validate_planning.py` pass; PR open with CI green; live runs written OPEN and handed to PRP-136.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | What each vendor exposes | Assume; verify | Verify first, per connector, from the official documentation fetched at execution. This PRP asserts no endpoint, report, field, permission, plan or setting |
| 2 | One PRP, two packages | Split; keep | Keep as the design has it (size M): two disjoint directories, items 1 to 2 and 3 to 4 run in parallel |
| 3 | Cursor with no verified admin API | Build a scraper; leave GAP | Leave `not_built`/GAP. No endpoint agent, scraping, browser automation or undocumented call is ever built |
| 4 | Content | In scope; out | Out. ASSUMPTION (GD-3, recommended default): captured content is not shown to the copilot or MCP; tools see metadata and findings only; revisit after the north star. ASSUMPTION (GD-4, recommended default): credentials and secrets always redacted; payment card numbers redacted by default; other detected types redacted or kept per capture policy, default redact. Here: neither vendor's content is requested or stored; if a verified API returned content it would be dropped at the connector, and adding a content path is a separate PRP through PRP-103's capture policy (model opus then) |
| 5 | Credential | Stored secret; reference | Reference through PRP-42 `credential`; the organisation or enterprise identifier is a bounded setting (`organization`, `enterprise`) whose exact form comes from verification |
| 6 | Per-user rows | Store ids; pseudonymise | Aggregate unless the verified payload is per-user and `user_detail=pseudonymous` is set; ids pass `ctx.pseudonymize` before leaving the call; logins and emails are never stored |
| 7 | Estate order (GD-9) | Recommended; by licences | ASSUMPTION (GD-9, recommended default): estate connector order M365 Copilot and Copilot Studio, GitHub Copilot, ChatGPT Enterprise, Anthropic, Cursor; Entra shadow AI last. Here: GitHub Copilot before Cursor; live verification depends on an organisation or team the owner holds |
| 8 | Hosting variants of GitHub | All; documented only | Only the variants the documentation shows and the verification file records; an unlisted variant is refused with `connector_cloud_unsupported` |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-117-connector-runner-and-estate-foundation.md` - descriptor, `RunContext`, sinks, shared-file rules.
- `connectors/reference/{github-copilot,cursor}/` (scaffolds from PRP-117) - the two descriptors to complete.
- `connectors/sdk-python/neurosphere_connector/{connector.py,manifest.py,health.py,vault.py}` - base class, manifest builder, health models.
- `connectors/reference/azure-billing/neurosphere_connector_azure_billing/connector.py` and `tests/fixtures/` - advisory read connector with fixtures.
- `connectors/reference/foundry/neurosphere_connector_foundry/connector.py` - partial capability reporting.
- `docs/connectors/coverage.md` (GitHub Copilot and Cursor rows) and `docs/connectors/verification/_TEMPLATE.md`.
- `PRPs/backlog/PRP-99-governance-contracts-a.md` (kind values), `docs/PRD.md` NS-09.
- `tests/unit/connector_conformance/test_reference_connectors_conformance.py:53-74` - socket guard.

### Interfaces consumed
- PRP-117: `ConnectorDescriptor`, `EstateConnector`, `RunContext`, `RunResult`, `UsageSink`, `EventSink`, `ctx.pseudonymize`, egress-guarded `ctx.http`, template, discovered-conformance test.
- PRP-110 (W25, not written at drafting time; consumed by purpose): `usage-report` generated model and its granularity declaration; confirmed against the merged schema at execution.
- PRP-99: kind values `github_copilot` and `cursor`. PRP-42: `ConnectorConfig`, `CredentialReference`.

### Interfaces provided
- Packages `neurosphere-connector-github-copilot` and `neurosphere-connector-cursor` with `DESCRIPTOR` (status per verification), connector classes, `signals` modules, and one `live_check.py` each (refuses without `NS_LIVE_APPROVED=1`).
- `docs/connectors/verification/github-copilot.md`, `docs/connectors/verification/cursor.md`; rows in the generated `docs/connectors/estate-coverage.md`.
- Evidence paths `docs/evidence/G04/github-copilot-<stamp>.json` and `docs/evidence/G04/cursor-<stamp>.json`.

### Patterns to match
- Credential fetched per call through the broker: `connector.py` `credential()`.
- Fixtures plus scripted transport: `connectors/reference/azure-billing/tests/fixtures/`, `connectors/reference/azure-monitor/tests`.
- Bounded paging and `rate_limited` mapping: `connectors/reference/foundry` REST reader.
- Operator gate script: `scripts/gates/g04_connectors_live.py`.

### Gotchas
- UNVERIFIED (design U-13, verbatim): "GitHub Copilot has organization or enterprise APIs for seats and usage metrics, and Copilot events in the audit log." If false: "Seats only."
- UNVERIFIED (design U-14, verbatim): "Cursor has an admin or analytics API for teams." If false: "Stays GAP."
- Plan, role and token requirements, metric retention and reporting delay, and whether metrics are per user or per organisation are facts to read from the documentation, never from this PRP or from the coverage file's "page exists" note.
- Reports can be per user; GitHub logins are personal data. Pseudonymise before any sink, and test it.
- Use `httpx` via `ctx.http`; a vendor SDK is out; if one becomes unavoidable, stop and raise a `[serial-after]` lockfile item with the orchestrator.
- Do not edit shared files (PRP-117 Gotchas, "Shared-file rules for the connector wave"); the two packages here must not import each other.
- Fixtures come from documentation examples and are marked synthetic; real payloads from the live run are scrubbed before commit.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - connectors/reference/github-copilot/**
  - connectors/reference/cursor/**
  - docs/connectors/verification/github-copilot.md
  - docs/connectors/verification/cursor.md
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
  - connectors/reference/openai-enterprise/**
  - connectors/reference/anthropic-claude/**
```

## Implementation blueprint

Parallelization: items 1 and 2 [P] (disjoint directories); items 3 and 4 [P] after their verification item; items 5 and 6 after 3 and 4.

### Item 1 - Verify first: GitHub Copilot  [P]
- Deliverable: `docs/connectors/verification/github-copilot.md` from the template covering seats, usage metrics and audit events, each with documented endpoint, token type and scopes, plan, granularity, latency, limits, hosting availability, content-like fields present and dropped, degradation, and a build or do-not-build decision per signal.
- Owned files: that file.
- Must NOT touch: code.
- Depends on: PRP-117 merged.
- Acceptance criteria: verification criterion; unknown stays "not found".
- Tests: `python scripts/connector_estate_check.py`.
- Pattern references: `docs/connectors/coverage.md` row format.

### Item 2 - Verify first: Cursor  [P]
- Deliverable: `docs/connectors/verification/cursor.md` the same way; if no admin or analytics API usable by a team admin is documented, the file says so plainly and item 4 is descoped.
- Owned files: that file.
- Depends on: PRP-117 merged.
- Acceptance criteria: verification criterion; the Cursor outcome is explicit either way.
- Tests: `python scripts/connector_estate_check.py`.

### Item 3 - GitHub Copilot connector  [P]
- Deliverable: models for verified payloads only, synthetic fixtures, manifest from `build_manifest` (capabilities limited to verified signals, advisory), `collect` for seats, usage metrics and audit metadata with paging, rate-limit handling per the documentation, watermark, coverage and freshness, pseudonymised principals.
- Owned files: `connectors/reference/github-copilot/**`.
- Must NOT touch: `cursor`, shared files.
- Depends on: item 1.
- Acceptance criteria: usage, audit, degradation, credential and content criteria for GitHub.
- Tests: `connectors/reference/github-copilot/tests/test_models.py`, `test_usage_collect.py`, `test_audit_metadata.py`, `test_no_content.py`, `test_credential_rejected.py`.
- Pattern references: `azure-billing` fixtures and manifest.

### Item 4 - Cursor connector (conditional)  [P]
- Deliverable: same shape for whatever item 2 verified; if nothing is verified, only the descriptor reason, the README GAP statement and a test that the package performs no network call.
- Owned files: `connectors/reference/cursor/**`.
- Must NOT touch: `github-copilot`, shared files.
- Depends on: item 2.
- Acceptance criteria: Cursor criterion; no scraper, no undocumented endpoint.
- Tests: `connectors/reference/cursor/tests/test_signals.py`, `test_no_network.py` (and usage tests if built).
- Pattern references: as item 3.

### Item 5 - Guards: content, pseudonymisation, cloud and host
- Deliverable: parse-time content-field drop and per-sink negative tests in both packages; user-id pseudonymisation tests; `supported_clouds` and `allowed_hosts` tests tied to the verification files.
- Owned files: both package directories.
- Depends on: items 3 and 4.
- Acceptance criteria: content, cloud and host criteria; no login or email-shaped string in any sink, log or status document.
- Tests: `tests/test_content_guard.py`, `tests/test_pseudonymization.py`, `tests/test_hosts_clouds.py` in each package.
- Pattern references: `otel-generic` body-drop post-check.

### Item 6 - Descriptors, conformance and live-check scripts
- Deliverable: both `DESCRIPTOR`s (`built` only for verified signals, otherwise `not_built` with reason), `conformance_factory` with fakes, broken-variant tests, and two `live_check.py` scripts that refuse without `NS_LIVE_APPROVED=1`, a named organisation or team and a budget statement.
- Owned files: both package directories.
- Depends on: item 5.
- Acceptance criteria: conformance criterion.
- Tests: `tests/test_conformance_enrolment.py` per package plus the discovered-conformance suite.
- Pattern references: `scripts/gates/g04_connectors_live.py`.

### Item 7 - Integration and close-out
- Deliverable: package READMEs (covered, not covered, how to enable), changelog fragment, Tier-3 regeneration of `estate-coverage.md` after rebase, completion note listing every signal as verified-built, not found, or OPEN, and Cursor's final state.
- Owned files: READMEs, this PRP file.
- Depends on: items 1 to 6.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q connectors/reference/github-copilot connectors/reference/cursor tests/unit/connector_conformance tests/unit/estate_check
python scripts/connector_estate_check.py
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration; usage rows are additive. Rollback: disable the stored config for the kind, set the descriptor to `not_built`, or revert the PR. Cursor's outcome of `not_built` is the shipped state today, so descoping it changes nothing.

## Live and open gates
Every live call is operator-gated (`NS_LIVE_APPROVED=1`, an organisation or team the operator names, a licence or plan the owner holds, and for each vendor a credential the operator installs in the vault; this session never sees it). Not run here; handed to PRP-136. Cursor remains GAP if no documented admin API exists, recorded OPEN.

## NOT building
Blocking or policy enforcement inside GitHub Copilot or Cursor (no enforcement hook is verified; observation and alerts only); endpoint, IDE-plugin or desktop collectors and browser or network DLP; scraping or undocumented endpoints; code, prompt or chat content in any form; per-prompt content from either assistant; a parity claim with any product or affiliation with either vendor; a claim that Cursor is covered before a documented API is verified; a vendor SDK dependency.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 4 and 7 are ASSUMPTIONS for plan approval)

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
- Descoped items (each signal per vendor: verified-built, not found, or OPEN; Cursor final state):
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an operator see assistant adoption and what is not covered):
