---
name: PRP-126-shadow-ai-discovery-identity-and-cloud-apps
status: backlog
priority: P1
order: 126
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-03, NS-07, NS-09
depends_on: [PRP-61-configuration-detections-and-shadow-ai-discovery, PRP-110-governance-contracts-b, PRP-117-connector-runner-and-estate-foundation, PRP-118-agent-identity-and-entra-entitlements]
wave: W29
branch: prp-126-shadow-ai-identity
allow_parallel: true
issues: []
---

# PRP-126: Shadow-AI discovery from identity and cloud-app data

## Goal
Extend PRP-61's shadow-AI detections, which see only Azure Resource Graph accounts of kind OpenAI or AIServices, with two further sources: identity data (sign-ins to, and consent grants for, known AI applications in the customer's Entra tenant) and cloud-app discovery data where the customer already has it (for example from a cloud access security broker). A new read connector `connectors/reference/entra-shadow-ai/` (kind `entra_shadow_ai`, scaffolded `not_built` by PRP-117, run by the `connector_runner`) collects per-application aggregates; a new rule package `packages/core/neurosphere_core/detections/shadow_ai/` turns them into advisory `shadow_ai_finding` recommendations, one per application, through PRP-61's `detections` role. The known-application list is product-maintained and customer-editable. The first item is verify-first: fetch the current official documentation at execution and record exactly which identity and discovery signals exist, their permissions, licence and cloud availability; build only what is recorded, with fixtures; anything absent is a visible coverage gap and an OPEN criterion. This is discovery after the fact, from data the customer already has: it produces findings, never blocks, and never shows personal activity beyond what the caller's scope allows. People are pseudonymous in this product: a finding carries counts per application and no person identifiers.

Out of scope: Azure Resource Graph account detection (PRP-61, unchanged); run-as identities and entitlements of registered agents (PRP-118, PRP-119); the connector runner and scaffold (PRP-117); the `shadow_ai_finding` kind and `UsageReport` shape (PRP-110); alert rules and incidents on findings (PRP-132); blocking, conditional access or consent revocation (never built here; remediation of a consent grant is a customer action in their identity provider); endpoint, browser and network DLP (cannot be delivered); the live run (PRP-136).

## Why
- The PRD asks for it and the product has half of it: the validation found "no working shadow-AI discovery" (`docs/validation/PRODUCT-VALIDATION-2026-11-06.md:67-72`); PRP-61 builds only the Resource Graph source (`detect.shadow_ai_account`, a customer-owned account that is not in the catalog). Nothing reads sign-in, consent or cloud-app data (design G-e).
- Where identity shadow AI shows up is outside Azure resources: employees using a SaaS assistant with a work account. The only server-side evidence is identity and cloud-app records, "after the fact, and only as good as that data" (design section 8, item 2).
- People are pseudonymous by design: `packages/contracts/schemas/catalog/v1/person.schema.json:6` says "Person as a pseudonymous principal only. There is deliberately no email, name, UPN, display_name"; `docs/PRD.md` NS-05 says "pseudonymize people by default"; the minting service is `PrincipalPseudonymizer` (`packages/core/neurosphere_core/auth/scope/pseudonym.py:72`). Raw sign-in logs are name-bearing activity records, so the design here is aggregate-first.
- The connector contract can express partial truth and carries a pseudonymising port (PRP-117 `RunContext.pseudonymize`, `UsageSink`), and PRP-110 adds the `shadow_ai_finding` recommendation kind with the score exemption.
- Owner direction 2026-11-16: "the ultimate team AI governance and auditing tool"; all identified gaps planned. Design D-9 puts Entra shadow AI last in the estate order.

## Acceptance criteria
- [ ] Verification record: `docs/connectors/verification/entra-shadow-ai.md` exists with every template heading and states, per signal (sign-in records for an application, consent and permission grants, application catalogue or well-known-application metadata, cloud-app discovery export), the URL and retrieval date, documented endpoint or export, required permission type and admin consent, licence or plan, retention window, granularity, latency, rate limits, Commercial and Government availability, fields present, which fields identify a person, and "not found" where absent. `scripts/connector_estate_check.py` passes.
- [ ] Only verified signals are coded; a test greps the package for URL and path literals absent from the verification file and fails on any.
- [ ] Given fixtures of the verified sign-in and consent payloads, When the connector collects, Then it emits one `UsageSink` aggregate per known application and period: distinct-user count, sign-in count, consent-grant counts by admin or user consent if the payload distinguishes them, first and last seen; unknown values are null, never 0; the user principal, name, email and IP never leave the collect call (negative test over sinks, logs, status document and exception text with a fixture full of synthetic identities).
- [ ] Small-cell rule: an application with fewer than `min_users_reported` distinct users (default 5; GD-28) is suppressed: it is reported only as a count bucket "fewer than 5" and no finer; a test with 1, 4, 5 and 6 users proves the boundary.
- [ ] Given a known-application list (shipped list plus customer additions and exclusions), When an application matches and is neither sanctioned nor excluded, Then the rule emits a `shadow_ai_finding` recommendation per application with evidence window, source and coverage (what answered, what did not), uncertainty and owner of the finding domain, `advisory=True`, no score; re-running with unchanged data yields no duplicate; the finding updates its counts and last-seen.
- [ ] Sanctioned means: the application id appears in the customer's approved list, or matches an alias or external id of a catalog entity read through the catalog reader; a sanctioned application never produces a finding, and an application removed from the approved list produces one on the next run.
- [ ] Scope: findings live in the single domain configured for the detections role; the finding payload contains application name, counts and window only, with no person identifier of any kind; a caller without read in that domain gets nothing (authorization test through the recommendations route, which PRP-61 already scopes).
- [ ] Coverage honesty: each finding and the coverage page state which sources contributed (identity sign-ins, consent grants, cloud-app discovery) and which were not collected; with the identity source absent the rule emits nothing from it and the page says `not_collected`, with no estimate.
- [ ] Cloud-app discovery source: built only if item 1 verified a documented, exportable interface; otherwise descoped with the recorded reason and the identity source ships alone.
- [ ] Never blocks: no write capability in the manifest, `advisory=True`, no action kind added; a test asserts the manifest declares no write action.
- [ ] Cloud and host: `supported_clouds` and `allowed_hosts` come only from the verification file; a Government deployment refuses a config unless verified, never rerouting.
- [ ] The connector passes PRP-117's discovered-conformance test with a fake transport and a broken variant; edits outside the owned paths are limited to the one registration line named in Ownership.
- PRP exit: touched suites, ruff, pyright, `scripts/connector_estate_check.py`, `validate_planning.py` pass; PR open with CI green; live run recorded OPEN and handed to PRP-136.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | What the identity provider and discovery tools expose | Assume; verify | Verify first from official documentation at execution. This PRP asserts no endpoint, log, field, permission, licence tier or admin setting (design U-7 and U-17 are UNVERIFIED) |
| 2 | Person data | Store pseudonymous ids; aggregates only | Decided by the owner 2026-11-16 (GD-28): shadow-AI findings report counts only, never person ids (not even pseudonyms), and groups smaller than 5 are suppressed. Here: the finding carries distinct-user counts, never person ids, even pseudonymous ones; per-person detail is not built here and would need its own scope design and owner decision |
| 3 | Small counts | Show; suppress | Decided by the owner 2026-11-16 (GD-28): counts below `min_users_reported` (default 5) show as "fewer than N"; the value is a setting with a floor of 2 |
| 4 | Which domain owns a finding | Per department; one configured domain | One configured domain (PRP-61's detections domain). Sign-ins do not map to catalog domains without per-user data that this PRP does not store |
| 5 | Known-application list | Hard-coded; data file; customer editable | A product-maintained, dated data file shipped in the package, each entry with a source label and retrieval date (entries are fetched or written at execution, not invented), plus customer additions and exclusions as connector settings. ASSUMPTION: PRP-117's `SettingSpec` can express a bounded list of application ids; if not, the additions go through a `[serial-after]` request to extend it and the PRP ships with the shipped list only |
| 6 | What "sanctioned" means | Any catalog entity; approved list | Approved list in settings, or a catalog entity whose alias or external id equals the application id; no inference from names |
| 7 | Where aggregates travel | New sink; existing `UsageSink` | `UsageSink` rows (PRP-117, PRP-110 `UsageReport`) with `source_system` as PRP-110 lists it for this source (confirmed at execution; `other` with a feature token if no dedicated value exists), `per_user_available=false` |
| 8 | Rule runs where | New role; PRP-61's `detections` role | PRP-61's role; one registration line appended to its rule list (named in Ownership) |
| 9 | Credential | Stored secret; reference | Reference through PRP-42 to a read-only, admin-consented application the operator creates; permissions are the ones the verification file records, least privilege, no write permission |
| 10 | Estate order (GD-9) | Recommended; by licences held | Decided by the owner 2026-11-16 (GD-9): estate connector order M365 Copilot and Copilot Studio, GitHub Copilot, ChatGPT Enterprise, Anthropic, Cursor; Entra shadow AI last. Here: Last in the estate order, after the SaaS connectors |

## Context manifest

### Files to read first
- `PRPs/backlog/PRP-61-configuration-detections-and-shadow-ai-discovery.md` - `DetectionRule`, `Finding`, `finding_to_recommendation`, reader protocols, role and settings; extended not changed.
- `PRPs/backlog/PRP-117-connector-runner-and-estate-foundation.md` - descriptor, sinks, `ctx.pseudonymize`, `estate_usage` container, shared-file rules.
- `PRPs/backlog/PRP-110-governance-contracts-b.md` - `UsageReport`, `shadow_ai_finding` kind; `PRPs/backlog/PRP-118-agent-identity-and-entra-entitlements.md` (when present) for the Graph credential and reader patterns it establishes (this PRP depends on it for ordering; it consumes nothing from its schema).
- `packages/contracts/schemas/catalog/v1/person.schema.json` and `packages/core/neurosphere_core/auth/scope/pseudonym.py:72` - how people are represented.
- `services/workers/neurosphere_workers/ingestion/foundry_discovery/poller.py:176-227` - the "known" side of matching (catalog deployments).
- `connectors/sdk-python/neurosphere_connector/{connector.py,manifest.py,health.py}`; `connectors/reference/azure-billing` - aggregate-only connector pattern.
- `docs/connectors/verification/_TEMPLATE.md` (new in PRP-117), `docs/connectors/coverage.md`.
- `scripts/gates/p29_entra_local.py:55-264` - existing operator Graph calls (read to see what a live Graph script looks like; copy no endpoint into the verification file without a documentation source).

### Interfaces consumed
- PRP-61: `DetectionRule`, `Finding`, `finding_to_recommendation`, recommendation kinds, role `detections`, `NS_WORKER_DETECT_DOMAIN_ID` and `NS_WORKER_DETECT_*` settings, `CatalogDeploymentReader`.
- PRP-117: `ConnectorDescriptor`, `EstateConnector`, `RunContext`, `UsageSink`, `ctx.pseudonymize` (unused by default), `ctx.http`, container `estate_usage`, discovered conformance.
- PRP-110 (W25): `UsageReport`; `recommendations/v1` kind `shadow_ai_finding` with the score exemption. PRP-99: kind `entra_shadow_ai`. PRP-42 (shipped): `ConnectorConfig`, `CredentialReference`.
- PRP-118 (not written at drafting time; consumed by purpose and name): the Entra and Graph credential kind and the reader and test patterns it sets for Graph calls; if it merged a shared Graph helper, reuse it, otherwise write a minimal one inside this package.

### Interfaces provided
- Package `neurosphere-connector-entra-shadow-ai` (module `neurosphere_connector_entra_shadow_ai`): `DESCRIPTOR`, `EntraShadowAiConnector`, `live_check.py` (refuses without `NS_LIVE_APPROVED=1`), data file `known_ai_apps.yaml`.
- Core `neurosphere_core.detections.shadow_ai`: `ShadowAiIdentityRule` (generator id `detect.shadow_ai_identity`, versioned), `AiAppObservationReader` protocol, `KnownAiApps` loader, `SanctionedResolver`.
- `docs/connectors/verification/entra-shadow-ai.md`; a row in generated `docs/connectors/estate-coverage.md`; evidence path `docs/evidence/G04/entra-shadow-ai-<stamp>.json`.

### Patterns to match
- Rule and finding shape: PRP-61 items 1 and 3 (`neurosphere_core.detections`).
- Aggregate-only collection with null for unknown: `connectors/reference/azure-billing/neurosphere_connector_azure_billing/connector.py`.
- Partial coverage: `connectors/reference/foundry/neurosphere_connector_foundry/connector.py`.
- Idempotent put keyed by application: PRP-61's `unregistered_ai_resource` handling.
- DNS-label suffix comparison, never substring: `services/workers/neurosphere_workers/ingestion/billing_export/settings.py:23,86-95`.

### Gotchas
- UNVERIFIED (design U-7, verbatim): "Microsoft Graph exposes app registrations, service principals, app role assignments, delegated permission grants, sign-in logs and consent grants to an admin-consented application, in both clouds." If false: "Declared identities only; shadow-AI identity source `not_built`."
- UNVERIFIED (design U-17, verbatim): "Cloud-app discovery data (for example from a cloud access security broker the customer runs) is exportable through a documented API." If false: "Identity source only."
- Sign-in records may need a licence tier and have a short retention window; both are facts to record. A tenant without the needed licence yields a visible `not_collected`, not zero findings.
- A sign-in to an application is not proof of an AI interaction, and an application on the list may have many non-AI features; the finding says "sign-ins to an application on the list", never "AI use".
- The known-application list ages. Its file carries a `retrieved` date per entry and a test fails when an entry has none; the page shows the list version.
- Person-identifying fields (user principal, display name, email, IP, device id) must be dropped at parse time by an allowlist model, not scrubbed afterwards; the allowlist excludes them from the model entirely.
- Findings in one domain are visible to anyone with read there; nothing in the finding may therefore identify, or allow re-identification of, a person (hence the small-cell rule and no per-person detail).
- Use `httpx` through `ctx.http`; no vendor SDK. Shared files are off limits (PRP-117 "Shared-file rules for the connector wave"); the single exception is the one rule-registration line in PRP-61's role module, appended last.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - connectors/reference/entra-shadow-ai/**
  - docs/connectors/verification/entra-shadow-ai.md
  - packages/core/neurosphere_core/detections/shadow_ai/**
  - packages/core/tests/detections_shadow_ai/**
  - services/workers/tests/detections_worker/test_shadow_ai_wiring.py
  - changelog.d/PRP-126-shadow-ai-discovery-identity-and-cloud-apps.md
tier1: []
tier2_appends:
  - services/workers/neurosphere_workers/detections/role.py
  - services/api/neurosphere_api/recommendations/router.py
  - frontend/src/features/recommendations/types.ts
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
  - packages/core/neurosphere_core/detections/rules/**
  - packages/core/neurosphere_core/detections/finding.py
  - services/workers/neurosphere_workers/runtime/**
  - services/api/neurosphere_api/catalog/**
  - services/api/neurosphere_api/ingest/**
  - packages/contracts/**
  - connectors/reference/entra-identity/**
```

## Implementation blueprint

### Item 1 - Verify first: record what identity and discovery sources document
- Deliverable: `docs/connectors/verification/entra-shadow-ai.md` from the template for sign-in records, consent grants, application metadata and the cloud-app discovery export: documented endpoint or export, permission type, admin consent, licence, retention, granularity, latency, limits, cloud availability, fields used, person-identifying fields present and dropped, degradation, and a build or do-not-build decision per source.
- Owned files: the verification file.
- Must NOT touch: code.
- Depends on: PRP-117 merged.
- Acceptance criteria: verification criterion; unknown stays "not found".
- Tests: `python scripts/connector_estate_check.py`.
- Pattern references: `docs/connectors/coverage.md` row format.

### Item 2 - Known-application list and sanctioned resolver  [P]
- Deliverable: `known_ai_apps.yaml` with entries written from sources fetched at execution (name, application identifier as the vendor documents it, category, source URL, retrieved date), a loader that rejects an entry without a source and date, merge of customer additions and exclusions, and `SanctionedResolver` (approved list plus catalog alias or external-id match).
- Owned files: `connectors/reference/entra-shadow-ai/**` (data file and loader), `packages/core/neurosphere_core/detections/shadow_ai/{known_apps.py,sanctioned.py}`, `packages/core/tests/detections_shadow_ai/test_known_apps.py`, `test_sanctioned.py`.
- Must NOT touch: PRP-61 rule files.
- Depends on: item 1 (for the identifier forms the sources use).
- Acceptance criteria: list and sanctioned criteria.
- Tests: `packages/core/tests/detections_shadow_ai/test_known_apps.py`, `test_sanctioned.py`.
- Pattern references: `catalog` alias lookup through `CatalogRepository`; PRP-61 `CatalogDeploymentReader`.

### Item 3 - Models, fixtures and manifest
- Deliverable: allowlist models containing only application identity and aggregates fields (person fields never modelled), synthetic fixtures from documentation examples including a fixture full of synthetic identities, manifest from `build_manifest` with `usage_reports` only, `advisory=True`, no write action.
- Owned files: `connectors/reference/entra-shadow-ai/**`.
- Depends on: item 1.
- Acceptance criteria: only-verified, never-blocks and person-field negative criteria.
- Tests: `tests/test_models.py`, `tests/test_manifest_no_write.py`.
- Pattern references: `azure-billing` fixtures.

### Item 4 - Identity aggregation  [P]
- Deliverable: `collect` for verified sign-in and consent signals: page, filter to the known list, aggregate in memory to per-application per-period counts, apply the small-cell rule, emit `UsageSink` rows, report coverage and freshness per source; user fields exist only inside the parse step.
- Owned files: the connector package.
- Depends on: items 2, 3.
- Acceptance criteria: aggregation, small-cell, coverage-honesty and credential criteria.
- Tests: `tests/test_identity_aggregate.py`, `tests/test_small_cell.py`, `tests/test_no_person_data.py`, `tests/test_credential_rejected.py` with `httpx.MockTransport`.
- Pattern references: `azure-monitor` bounded poll.

### Item 5 - Cloud-app discovery source (conditional)  [P]
- Deliverable: only if item 1 verified a documented, exportable interface: collect per-application aggregates from it with the same allowlist and small-cell rules; otherwise the descoping note and `cloud_app_discovery` reported `not_collected`.
- Owned files: the connector package.
- Depends on: items 2, 3.
- Acceptance criteria: cloud-app discovery criterion.
- Tests: `tests/test_cloud_app_discovery.py`, `tests/test_cloud_app_absent.py`.
- Pattern references: item 4.

### Item 6 - Shadow-AI identity rule and wiring
- Deliverable: `ShadowAiIdentityRule` (generator id `detect.shadow_ai_identity`, version), `AiAppObservationReader` over `estate_usage`, one finding per application with evidence window, sources and coverage, idempotent update, scope-correct domain; the one registration line in PRP-61's role module, the `shadow_ai_finding` kind (PRP-110) added as one `Kind` literal line in `recommendations/router.py` and one line in `frontend/src/features/recommendations/types.ts` so the API list and the UI can filter on it, and a wiring test with in-memory readers and recommendation store.
- Owned files: `packages/core/neurosphere_core/detections/shadow_ai/{rule.py,reader.py,__init__.py}`, `packages/core/tests/detections_shadow_ai/**`, `services/workers/tests/detections_worker/test_shadow_ai_wiring.py`; Tier-2 appends in `services/workers/neurosphere_workers/detections/role.py`, `services/api/neurosphere_api/recommendations/router.py` and `frontend/src/features/recommendations/types.ts` (one line each).
- Must NOT touch: other detection rules or `finding.py`.
- Depends on: items 2 and 4.
- Acceptance criteria: finding, sanctioned, scope, idempotence and coverage criteria.
- Tests: `packages/core/tests/detections_shadow_ai/test_rule.py`, `test_scope.py`, `test_idempotent.py`, `services/workers/tests/detections_worker/test_shadow_ai_wiring.py`.
- Pattern references: PRP-61 end-to-end test (`test_end_to_end.py`).

### Item 7 - Descriptor, conformance and live-check script
- Deliverable: `DESCRIPTOR` (`built` only for verified sources, else `not_built` with reason), `allowed_hosts`, `supported_clouds`, `conformance_factory` with fakes, a broken variant, host and cloud tests, and `live_check.py` refusing without `NS_LIVE_APPROVED=1`, a named tenant and a statement that only aggregates are printed.
- Owned files: the connector package.
- Depends on: items 3 to 5.
- Acceptance criteria: conformance, cloud and host criteria.
- Tests: `tests/test_conformance_enrolment.py`, `tests/test_hosts_clouds.py`, the discovered-conformance suite.
- Pattern references: `scripts/gates/g04_connectors_live.py`.

### Item 8 - Integration and close-out
- Deliverable: README (what is and is not seen, licence and retention caveats, how to edit the known-application list, the privacy position), changelog fragment, Tier-3 regeneration of `estate-coverage.md` after rebase, completion note per source: verified-built, not found, or OPEN.
- Owned files: README, the changelog fragment, this PRP file.
- Depends on: items 1 to 7.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q connectors/reference/entra-shadow-ai packages/core/tests/detections_shadow_ai packages/core/tests/detections_core services/workers/tests/detections_worker tests/unit/connector_conformance tests/unit/estate_check
python scripts/connector_estate_check.py
python scripts/changelog_assemble.py --check
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration; usage rows and recommendations are additive (existing containers). Rollback: disable the stored config for the kind, set the descriptor to `not_built`, remove the rule registration line, or revert the PR; open `shadow_ai_finding` recommendations expire through the recommendation lifecycle.

## Live and open gates
Every live call is operator-gated: `NS_LIVE_APPROVED=1`, a tenant the operator names, a read-only admin-consented application the operator creates and installs in the vault (never seen by the session), and any licence the verified source needs. Not run here; handed to PRP-136. Each source not verified stays OPEN. Sign-in data is personal data in the customer's tenant: the live run prints aggregates only.

## NOT building
Blocking, conditional access, consent revocation or any write; per-person activity, even pseudonymous; endpoint, browser or network DLP; inspection of what was typed into any application; detection of AI use inside applications not on the list; a claim that a sign-in is AI use; parity claim with any product; CASB-specific connectors beyond what is verified; a file-upload importer for exports; shadow-AI detection in AWS or other clouds (PRP-62 area); alerts or incidents on findings (PRP-132); a vendor SDK dependency.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 2, 3, 5 and 10 are ASSUMPTIONS for plan approval)

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
| 8 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items (each source: verified-built, not found, or OPEN):
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an operator see unsanctioned AI applications in use, with what coverage, and without seeing any person):
