---
name: PRP-109-north-star-scenario-acceptance
status: backlog
priority: P0
order: 109
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 9
ns: NS-01, NS-04, NS-06, NS-08
depends_on: [PRP-100-telemetry-tool-service-identity-and-aggregates, PRP-101-sensitive-information-detectors-and-redaction, PRP-102-encrypted-interaction-store-and-retention, PRP-103-interaction-capture-policy-and-edge, PRP-104-interaction-explorer-and-export, PRP-105-policy-engine-core, PRP-106-policy-violations-and-exceptions-ui, PRP-107-notification-channels-and-subscriptions, PRP-108-agent-approval-gate-and-platform-control-actions, PRP-82-hosted-profile-everything-on, PRP-63-delivery-pipeline-to-hosted, PRP-71-realistic-seeded-world-and-demo-profile]
wave: W24
branch: prp-109-north-star-acceptance
allow_parallel: true
issues: []
---

# PRP-109: North-star scenario acceptance (the governance definition of done)

## Goal
Ship the product's definition of done for the governance core as one executable scenario: an agent version is registered and approved; its interactions are captured and classified; a policy flags a violation; the owner is notified; the fix (suspending the agent version) goes through maker-checker approval and is executed and verified; and the audit trail shows the whole chain. Concretely: a governance extension of the seeded demo world with a local notification sink, a "governance trail" API and page that assemble the chain for one violation from audit search and the governance stores, the acceptance test as pytest against the local compose stack (in the `real-stack` CI job) and as a signed-in Playwright run against the hosted Azure app, the hosted governance profile (Key Vault key, content blob container, the new worker roles, capture enabled for the synthetic demo domain only, turned on by the same approval action a customer uses), and a demo script. It is for the owner and every later session: "the governance core works" means this test passes, locally on every merge and in the hosted app once an operator has run it.

Out of scope: building any step of the chain (PRP-100 to PRP-108 own them; a failing step here is a defect filed against its owner, not fixed here); estate connectors, identity, labels, risk, incidents (PRP-110 onward); the general hosted "everything on" walk (PRP-82); the delivery pipeline itself (PRP-63); the live-gates campaign (PRP-136, which re-runs the hosted scenario).

## Why
- The owner asked on 2026-11-16 for "the ultimate team AI governance and auditing tool" and directed that every identified gap be planned; the design's north star (G-j) is exactly this chain, and it is reachable at the end of W24 (`temp/audit/governance-core-design.md` section 0 item 4).
- `docs/PRD.md:12` (NS-01) promises "Redact before persistence and external transmission; prompt/response bodies disabled by default"; `docs/PRD.md:23` (NS-04) promises reviewers for "policy exceptions" with "SLA timers, reassignment, notifications and immutable decisions". No test proves any of these work together today: the deployed-app tests are one manual smoke (`frontend/tests/hosted/hosted-smoke.spec.ts:33`) and `scripts/gates/hosted_demo.py smoke`; no workflow in `.github/workflows/` deploys to Azure (PRP-63 adds `deploy-hosted.yml`).
- The pieces only add up if their ids line up: audit search can already filter by correlation id (`services/api/neurosphere_api/audit/search_store.py:53-78`, route `/api/v1/audit/search` at `audit/search.py:40`), but nothing assembles register, capture, violation, notification and fix into one view, and the audit chain verifier (`packages/core/neurosphere_core/audit/chain.py:125` `verify_chain`) is never pointed at such a segment.
- The 2026-11-06 validation found the app unusable as a product despite passing PRPs (`docs/validation/PRODUCT-VALIDATION-2026-11-06.md`); this PRP makes "done" a product behaviour measured end to end, not a set of green unit suites.

## Acceptance criteria
- [ ] Local (compose emulators, synthetic content only): Given `make north-star-up`, When `uv run pytest -q -m integration tests/integration/real_stack/test_north_star.py` runs, Then all ten steps pass in order: (S1) a draft AgentVersion of the synthetic agent is registered; (S2) it is approved through `agent_version_approve` by a second steward (self-approval refused first) and the executor reads back `approval.state: approved`; (S3) its interactions sent through the ingest edge are captured under the demo capture policy, which was activated by an approved `capture_policy_change`; (S4) each `InteractionRecord` has findings for the synthetic identifiers and `payload_ref.detected_categories`; (S5) the policy evaluator opens a `PolicyViolation` whose evidence names those interaction ids; (S6) the local sink receives a `policy_violation_opened` delivery for the steward subscription; (S7) the owner drafts `agent_version_suspend` from the violation; (S8) a second steward approves it; (S9) the executor applies and verifies it (`verified: true`, read-back `approval.state: suspended`); (S10) the violation is `resolved` with that intent id.
- [ ] Given the auditor calls `GET /api/v1/governance/trail?violation_id=<id>`, Then the response lists the ten steps with audit ids, timestamps and actor pseudonyms, `complete: true`, and `chain_verified: true` from `verify_chain` over the included audit records; a missing step is returned as `status: missing` (never synthesized), and a caller without `audit.read` on the violation's domain gets 403, an out-of-scope id 404.
- [ ] Content and secrecy hold across the whole run: the raw synthetic identifiers and the synthetic credential string placed in a prompt never appear in any Event Hubs message, quarantine or archive record, audit record, SIEM event, sink payload, trail response, captured log line or `services/api/openapi.json`; the investigator's audited content read (PRP-104) returns placeholders such as `[[ns-redacted:us_ssn]]` and the read's audit record carries a purpose code and no content.
- [ ] The trail page renders the ten steps for a violation (mock API e2e and axe clean), links each step to its source (agent version, interaction metadata, violation, delivery, action intent, audit record) and shows a missing step as missing.
- [ ] Hosted (operator-approved, `NS_LIVE_APPROVED=1`): the hosted governance profile deploys through the PRP-63 pipeline with `governanceProfile=north-star`; the readiness job reports the capture, policy evaluation, notification and key-wrap components `ok`; the operator runs `frontend/tests/hosted/north-star.spec.ts` signed in as two stewards and an auditor; the evidence directory validates with `scripts/gates/north_star_evidence.py`. Until that run happens the criterion is recorded OPEN, never passed.
- [ ] `docs/demo/north-star.md` lets a presenter run the scenario locally in under 15 minutes from a clean checkout, and states what is synthetic and what is not claimed.
- PRP exit: touched suites, the local north-star test, frontend unit and e2e, `validate_planning.py` and the gates pass; PR open with CI green including `real-stack`; the hosted run evidenced or recorded OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | What "the fix" is | suspend the agent version; publish an exception; change enforcement mode | Suspend through `agent_version_suspend` (PRP-108, maker-checker); the exception path through HITL `policy_exception` is shown in the demo script only |
| 2 | Who may read the trail | `govpolicy.read`; `audit.read` | ASSUMPTION: `audit.read` on the violation's domain (security auditor); the trail exposes audit metadata, and no new disclosure path is opened. Owner may widen it to stewards later |
| 3 | How steps are linked | one correlation id end to end; follow ids | Follow ids from the violation: subject agent version, evidence interaction ids, the violation's `correlation_id` on deliveries, intents whose evidence names the violation's canonical id `<cloud>:<customer>:neurosphere:policy_violation:<id>` (PRP-105). PRP-108's suspend route accepts `evidence` and copies it into the intent, and PRP-106's "Propose suspension" sends the violation id there |
| 4 | Trail response contract | new contract schema; API-local model | API-local Pydantic model (no contracts owner in W24); promote to a contract only if MCP or copilot need it (PRP-116) |
| 5 | Hosted run by the pipeline or by an operator | pipeline signs in; operator signs in | ASSUMPTION (GD-43, recommended default): the hosted north-star run is operator-attended: the operator supplies two steward identities, an auditor and a webhook endpoint stored in Key Vault; the deploy pipeline runs only a non-interactive readiness check. Here: the pipeline deploys, seeds and runs a non-interactive readiness check; the signed-in Playwright run is operator-attended (interactive Entra sign-in, two steward identities for maker-checker), as `playwright.hosted.config.ts` already requires. Storing session tokens in CI is refused. Deviation from the design's "run by the deploy pipeline", reported |
| 6 | Hosted notification target | local sink; operator webhook | `local_sink` is local-only (PRP-107 clarification 7); hosted uses a webhook whose URL the operator stores in Key Vault. ASSUMPTION: if none is supplied, S6 is recorded OPEN and the trail shows the real delivery status |
| 7 | Synthetic identifiers | committed fixtures; generated | Generated at test time by PRP-101's synthetic corpus generator; the credential-shaped string is assembled at runtime (gitleaks) |
| 8 | Capture default and who approves a `capture_policy_change` | (a) a second steward approves; (b) the maker-checker approver rule is relaxed for the governance action kinds so an admin approves | ASSUMPTION (GD-1, recommended default): capture is off everywhere and turned on per domain and source only by an approved `capture_policy_change`, proposed by a domain steward and never self-approved. Core requires a maker-checker approver to hold `action.approve` (`packages/core/neurosphere_core/admin/platform/review_policy.py:88-93`), which admin does not hold; recommended default (a): a second steward approves; no change to who holds `action.approve`. OPEN for the owner. Here: the demo capture policy is scoped to the synthetic demo domain and source only and enabled by the action in the scenario (the second steward identity approves), never by seed outside `NS_ENV=local` |
| 9 | Content to the copilot or MCP | as design | ASSUMPTION (GD-3, recommended default): captured content is not shown to the copilot or MCP; tools see metadata and findings only; revisit after the north star. Here: the scenario asserts the copilot and MCP tool lists contain no content tool |
| 10 | Slot conflict W21 to W24 | as design | ASSUMPTION (GD-12, recommended default): keep the north star at W24; PRP-75 and PRP-76 slip to W24. Here: wave W24 |

## Context manifest

### Files to read first
- `temp/audit/governance-core-design.md` sections 2.1, 2.4, 4 (PRP-109 entry) and 8 item 12.
- The "Interfaces provided" of PRP-99 to PRP-108 in `PRPs/backlog/` (names below are theirs; re-read them, they win on any difference).
- `tests/integration/real_stack/conftest.py:1-80` - `emulator_env`, stand-in issuer and tokens, `composed_app`, `real_stack_client`.
- `tests/integration/real_stack/test_copilot_loop.py` and `test_operator_grant.py` - an end-to-end real-stack flow with workers in process.
- `.github/workflows/real-stack.yml:36-60` - the CI job that runs `-m integration tests/integration/real_stack`.
- `frontend/playwright.hosted.config.ts` and `frontend/tests/hosted/{global-setup.ts,hosted-smoke.spec.ts}` - the manual hosted pattern (storageState, MSAL session replay).
- `services/api/neurosphere_api/audit/search.py:38-60`, `audit/search_store.py:53-78` - collecting audit records by filter.
- `packages/core/neurosphere_core/audit/chain.py:125` - `verify_chain`.
- `PRPs/backlog/PRP-82-hosted-profile-everything-on.md` and `PRP-63-delivery-pipeline-to-hosted.md` "Interfaces provided" - `hostedProfile`, evidence layout, `deploy-hosted.yml` jobs.
- `PRPs/backlog/PRP-71-realistic-seeded-world-and-demo-profile.md` "Interfaces provided" - `demo-world`, `make demo-up`, `sandbox/demo/README.md`.

### Interfaces consumed
- PRP-99: `CapturePolicy`, `InteractionRecord`, `PayloadRef` additions, `PolicyDefinition` (`content_rule`, `data_sensitivity_access`), `PolicyViolation`, `NotificationChannel` (`local_sink`, `local_sink_url`), `NotificationSubscription`, `NotificationDelivery`, `AgentVersionApproval`, action kinds `agent_version_approve`, `agent_version_suspend`, `capture_policy_change`, system settings `interaction_capture`, `notifications`, `enforcement`; audit operation names `interaction.capture`, `govpolicy.violation_open`, `govpolicy.violation_resolve`, `notification.delivery`.
- PRP-101: the synthetic corpus generator and default detector set. PRP-102: `InteractionStore`, containers, `NS_INTERACTION_LOCAL_KEY_FILE`, blob container default `ns-interaction-content`. PRP-103: `seed_local_capture_policy` (local only), capture counters, `/api/v1/admin/interactions/capture-status`. PRP-104: `POST /api/v1/domains/{domain_id}/interactions/{interaction_id}/content-reads`, `Role.INTERACTION_INVESTIGATOR` permissions. PRP-105: worker role `policy_eval`, `NS_GOVPOLICY_ENABLED`, `ViolationStore`, `PolicyLifecycle.publish`, violation canonical ids. PRP-106: the violations page and its "suspend agent version" entry. PRP-107: worker role `notifications`, `/api/v1/admin/notifications/*`, `OutboxStore`. PRP-108: `/api/v1/catalog/approvals/domains/{domain}/agent-versions/{entity_id}/submit|suspend`, platform-control target, `NS_PLATFORM_CONTROL_ENABLED`.
- PRP-71: `demo-world` seed and `make demo-up`. PRP-82: `hostedProfile`, `hosted_profile_evidence.py`, evidence layout. PRP-63: `deploy-hosted.yml` (`plan`, `apply`, environments `hosted-demo-plan`, `hosted-demo`), `scripts/gates/hosted_smoke.py`.
- Shipped: real-stack fixtures (PRP-38), audit search (PRP-40), `verify_chain`, `RouterRegistry`.

### Interfaces provided
- Seed: `sandbox/demo/governance/` (new) with `world.py` (synthetic agent `north-star-assistant` and its draft version, data asset `north-star-claims-store` with `sensitivity_categories: [pii]`, policy `north-star-pii-in-prompts` with a `content_rule` on `us_ssn`/`email_address` and a `data_sensitivity_access` rule, capture policy `north-star-capture` in state `proposed`, channel `north-star-sink` and a `domain_steward` subscription), `interactions.py` (generated interactions through the ingest edge), and `sink/` (stdlib HTTP receiver writing deliveries to a volume). Stable ids documented in `sandbox/demo/governance/README.md`.
- Compose profile `governance` with service `notification-sink`; Make targets `north-star-up`, `north-star-check`, `north-star-down`.
- Route `GET /api/v1/governance/trail` (`audit.read`; query `violation_id` required; returns `GovernanceTrail` {`violation_id`, `domain_id`, `steps` (10 of {`step` (`registered`|`approved`|`captured`|`classified`|`violation_opened`|`notified`|`fix_proposed`|`fix_approved`|`fix_verified`|`violation_resolved`), `status` (`present`|`missing`|`failed`), `at`, `audit_ids`, `actor`, `refs`}), `complete`, `chain_verified`, `truncated`}); audit operation `governance.trail_read`.
- Frontend route `governance/trail` (`GOVERNANCE_TRAIL_ROUTE`), deep link `/governance/trail?violation_id=...`, added by item 3 as one entry in the `ViolationLinks` slot of PRP-106's `ViolationPage.tsx`; mock handlers `frontend/tests/mock-api/features/governance-trail.ts`.
- Bicep parameter `governanceProfile` (`off`|`north-star`, default `off`) on `infra/demo/main.bicep` and `infra/appservice/main.bicep`; Helm values block `governance` (values only).
- `scripts/gates/north_star_seed.py` (new; seeds the hosted demo domain through admin and action APIs, never direct store writes) and `scripts/gates/north_star_evidence.py` (new; offline validator). Evidence layout `docs/evidence/north-star/<yyyy-mm-dd>-<image-tag>/{readiness.json, trail.json, steps.json, deliveries.json, playwright.md, README.md}`.
- `deploy-hosted.yml` job `north-star-readiness` (after `apply`, only when the dispatch input `governance_profile` is `north-star`).

### Patterns to match
- Real-stack end-to-end flow with stand-in tokens: `tests/integration/real_stack/test_operator_grant.py`.
- Manual hosted spec: `frontend/tests/hosted/hosted-smoke.spec.ts:33-60` (session replay, axe without Tabster sentinels).
- Router hook: `services/api/neurosphere_api/routers.py:54-58`; read audited: `authz/read_audit.py:176-195`.
- Feature page with mock API: `frontend/src/features/audit/` and `frontend/tests/mock-api/features/audit.ts`.
- Evidence validator: PRP-82's `scripts/gates/hosted_profile_evidence.py`.

### Gotchas
- The compose project name is shared across worktrees (memory: compose shared): only this PRP runs compose in W24; PRP-76 does not.
- Emulators on `127.0.0.1`, never `localhost` (Cosmos 8081, Event Hubs AMQP): set it in the north-star env and the sink URL uses the compose service name, never `localhost`, inside containers.
- Real-stack Playwright and e2e ports cross worktrees: use unique `NS_E2E_APP_PORT`/`NS_MOCK_API_PORT` for the trail e2e.
- Tests that pin `default_builders` order and components (`services/api/tests/runtime_api/test_readiness.py`, `runtime_gateway_builder/test_gateway_builder.py`, `runtime_data/data_helpers.py`): the trail adds NO builder; it reads components the north-star PRPs put on `app.state`.
- Key Vault purge protection blocks re-creating a deleted key name; the key and container names must be stable and the Bicep idempotent. Role-assignment scope casing must match the resource id exactly (memory: PRP-32 S3 live). Resource groups need the `project` and `owner` tags (G05 policy).
- Hosted capture must be enabled by the `capture_policy_change` action with two signed-in stewards; `seed_local_capture_policy` refuses outside `NS_ENV=local` and must not be used.
- UNVERIFIED (design U-1): Key Vault key wrap and unwrap over REST with the workload identity in Commercial and Government; PRP-102 builds it, this PRP's hosted run is its first live proof. If it fails, capture is disabled in that cloud with the reason shown and S3/S4 are recorded OPEN.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - sandbox/demo/governance/**
  - sandbox/tests/test_north_star_world.py
  - services/api/neurosphere_api/governance/trail/**
  - services/api/tests/governance_trail/**
  - frontend/src/features/governance/trail/**
  - frontend/tests/mock-api/features/governance-trail.ts
  - frontend/tests/e2e/governance-trail.spec.ts
  - frontend/src/features/governance/policy/ViolationPage.tsx
  - tests/integration/real_stack/test_north_star.py
  - tests/integration/real_stack/fixtures/north_star/**
  - frontend/tests/hosted/north-star.spec.ts
  - scripts/gates/north_star_seed.py
  - scripts/gates/north_star_evidence.py
  - tests/unit/gates/test_north_star_evidence.py
  - docs/demo/north-star.md
  - docs/evidence/north-star/**
tier1:
  - infra/demo/main.bicep
  - infra/appservice/main.bicep
  - infra/helm/values.yaml
  - .github/workflows/deploy-hosted.yml
  - docker-compose.yml
  - Makefile
tier2_appends:
  - services/api/neurosphere_api/routers.py
  - services/api/neurosphere_api/authz/routes.py
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/workspaceNav.ts
  - frontend/src/app/route-manifest.json
  - frontend/tests/e2e/a11y/route-samples.ts
  - frontend/tests/real-stack/routes.spec.ts
  - frontend/tests/mock-api/features/index.ts
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - packages/core/neurosphere_core/**
  - services/api/neurosphere_api/governance/policy/**
  - services/api/neurosphere_api/interactions/**
  - services/api/neurosphere_api/runtime/builders/**
  - services/workers/**
  - connectors/**
  - scripts/gates/hosted_demo_seed.py
```

## Implementation blueprint

Parallelization: item 1 first (seed and sink the others assert against). Items 2 and 5 are [P] after item 1 (no shared file). Item 3 after 2 (route and response). Item 4 after 1-3. Item 6 after 4 and 5. Item 7 after 4. Item 8 last.

### Item 1 - Governance demo world and local sink
- Deliverable: `sandbox/demo/governance/` world, generated interactions (PRP-101 generator; synthetic credential string assembled at runtime), the sink receiver, README with stable ids; compose service `notification-sink` (profile `governance`, compose-network only, no host port except an optional `127.0.0.1` binding for the demo); Make targets `north-star-up` (= `demo-up` plus the profile, worker roles `policy_eval`, `notifications`, `actions`, `NS_GOVPOLICY_ENABLED=true`, `NS_PLATFORM_CONTROL_ENABLED=true`, local key file), `north-star-check`, `north-star-down`.
- Owned files: `sandbox/demo/governance/**`, `sandbox/tests/test_north_star_world.py`, `docker-compose.yml`, `Makefile`.
- Must NOT touch: `sandbox/demo/` outside `governance/` (PRP-71), any core store.
- Depends on: PRP-71 and PRP-100 to PRP-108 merged.
- Acceptance criteria: the world builds offline and deterministically; the seed writes only through APIs and only under `NS_ENV=local`; no committed identifier passes a detector.
- Tests: `sandbox/tests/test_north_star_world.py`.
- Pattern references: PRP-71's `sandbox/demo/` layout; `infra/compose/` profiles.

### Item 2 - Governance trail API  [P]
- Deliverable: `services/api/neurosphere_api/governance/trail/{__init__,models,assembler,router}.py`: assemble the ten steps from the violation (PRP-105 store), the subject's approval and intents (action store), interaction metadata (PRP-102 index), deliveries (PRP-107 outbox) and audit search by the collected ids; `verify_chain` over the audit records gathered; bounded (at most 200 audit records, `truncated`); `audited_read` with operation `governance.trail_read`; router hook and route-inventory entry.
- Owned files: `services/api/neurosphere_api/governance/trail/**`, `services/api/tests/governance_trail/**`, Tier-2 `routers.py`, `authz/routes.py`.
- Must NOT touch: `services/api/neurosphere_api/governance/policy/**` (PRP-105), `runtime/builders/**`.
- Depends on: item 1.
- Acceptance criteria: criterion 2 (unit level with in-memory stores: complete chain, each step missing in turn, a tampered audit record gives `chain_verified: false`, 403/404 cases).
- Tests: `services/api/tests/governance_trail/`.
- Pattern references: `audit/search.py:38-60`, `authz/read_audit.py:176-195`.

### Item 3 - Trail page
- Deliverable: `frontend/src/features/governance/trail/` page (step list with status, timestamps, actor pseudonym, links; missing and failed states; empty state), route and nav entry for roles holding `audit.read`, mock handlers, e2e with axe; the "Governance trail" link (`/governance/trail?violation_id=`) added as one entry in the `ViolationLinks` slot PRP-106 provides in `ViolationPage.tsx`.
- Owned files: `frontend/src/features/governance/trail/**`, `frontend/tests/mock-api/features/governance-trail.ts`, `frontend/tests/e2e/governance-trail.spec.ts`, the one `ViolationLinks` entry in `frontend/src/features/governance/policy/ViolationPage.tsx`; Tier-2 `frontend/src/app/appRoutes.ts`, `frontend/src/app/workspaceNav.ts` (Governance group), `frontend/src/app/route-manifest.json`, `frontend/tests/e2e/a11y/route-samples.ts`, `frontend/tests/real-stack/routes.spec.ts`, mock-api `index.ts`.
- Depends on: item 2.
- Acceptance criteria: criterion 4.
- Tests: colocated vitest files, `frontend/tests/e2e/governance-trail.spec.ts`.
- Pattern references: `frontend/src/features/audit/`.

### Item 4 - Local executable acceptance test
- Deliverable: `tests/integration/real_stack/test_north_star.py` (`pytestmark = pytest.mark.integration`): composes the API and the `ingestion`, `projections`, `actions`, `policy_eval` and `notifications` roles in process over the emulators with stand-in tokens for steward A (maker), steward B (checker), an admin, an investigator and an auditor; drives S1-S10 through public APIs only; asserts the trail; runs the content and secrecy sweep of criterion 3 (Event Hubs messages read back, quarantine and archive, audit search, SIEM formatter output, sink files, `caplog`, `openapi.json`); asserts the copilot and MCP tool lists have no content tool.
- Owned files: `tests/integration/real_stack/test_north_star.py`, `tests/integration/real_stack/fixtures/north_star/**`.
- Depends on: items 1-3.
- Acceptance criteria: criteria 1 and 3; the `real-stack` CI job runs it unchanged.
- Tests: the file itself.
- Pattern references: `tests/integration/real_stack/test_operator_grant.py`, `test_copilot_loop.py`.

### Item 5 - Hosted governance profile  [P]
- Deliverable: `governanceProfile` parameter on both Bicep templates (Key Vault key with a stable name, blob container `ns-interaction-content`, Key Vault Crypto User and Storage Blob Data Contributor for the API and worker identities, worker roles appended, settings values only), Helm `governance` values block, `deploy-hosted.yml` dispatch input `governance_profile` and job `north-star-readiness` (readiness components, no sign-in), `scripts/gates/north_star_seed.py` (API-only seeding of the demo domain; the capture policy stays `proposed`).
- Owned files: `infra/demo/main.bicep`, `infra/appservice/main.bicep`, `infra/helm/values.yaml`, `.github/workflows/deploy-hosted.yml`, `scripts/gates/north_star_seed.py`.
- Must NOT touch: `infra/bicep/modules/**` (PRP-83 later), `scripts/gates/hosted_demo_seed.py` (PRP-82).
- Depends on: item 1.
- Acceptance criteria: `az bicep build` of both templates passes with `governanceProfile` `off` and `north-star`; `off` renders byte-identical resources to today; the what-if is attached to the PR, never applied by this session.
- Tests: `tests/security/network/test_bicep_network.py` (the existing Bicep network checks must still pass with both profile values), `helm template` render check, actionlint on the workflow.
- Pattern references: PRP-82 `hostedProfile`; PRP-67 hardening parameters.

### Item 6 - Hosted spec and evidence
- Deliverable: `frontend/tests/hosted/north-star.spec.ts` (two steward storage states and an auditor state under `temp/hosted-demo/`, refused by global setup when missing; drives S1-S10 through the UI; writes `steps.json`, `trail.json`); `scripts/gates/north_star_evidence.py` and `tests/unit/gates/test_north_star_evidence.py`; `docs/evidence/north-star/README.md` (layout, how to run, OPEN rules).
- Owned files: those files.
- Depends on: items 4 and 5.
- Acceptance criteria: `playwright test -c playwright.hosted.config.ts --list` lists the spec offline; the validator accepts a complete synthetic evidence directory and rejects one with a missing step marked passed.
- Tests: `tests/unit/gates/test_north_star_evidence.py`.
- Pattern references: `frontend/tests/hosted/hosted-smoke.spec.ts`, PRP-82 evidence validator.

### Item 7 - Demo script
- Deliverable: `docs/demo/north-star.md`: prerequisites, `make north-star-up`, the ten steps with the screen and the API call for each, the exception alternative, what is synthetic, what is not claimed (design section 8), teardown; mkdocs nav entry; a rendered screenshot only if actually produced.
- Owned files: `docs/demo/north-star.md`, Tier-2 `mkdocs.yml`.
- Depends on: item 4.
- Acceptance criteria: criterion 6; `tests/docs` reference checks pass.

### Item 8 - Integration and close-out
- Deliverable: Tier-2 appends merged; Tier-3 regeneration (`services/api/openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`, `PRPs/EXECUTION-PLAN.md`); changelog fragment `changelog.d/PRP-109-north-star-scenario-acceptance.md`; completion note with the local result, any step that failed and its owning PRP, and the hosted status (evidenced or OPEN).
- Owned files: this PRP file, Tier-3 files per reference section 6.
- Depends on: items 1-7.
- Acceptance criteria: validation gates pass; CI green including `real-stack`.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q services/api/tests/governance_trail sandbox/tests/test_north_star_world.py tests/unit/gates/test_north_star_evidence.py tests/security/network/test_bicep_network.py services/api/tests/test_openapi_drift.py services/api/tests/runtime_api tests/docs
docker compose up -d --wait
uv run pytest -q -m integration tests/integration/real_stack/test_north_star.py
az bicep build --file infra/demo/main.bicep --stdout
az bicep build --file infra/appservice/main.bicep --stdout
helm template infra/helm
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend exec playwright test tests/e2e/governance-trail.spec.ts
pnpm --filter @neurosphere/frontend exec playwright test -c playwright.hosted.config.ts --list
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration. The trail route and page are new and read-only. `governanceProfile` defaults to `off`, which renders today's resources unchanged; turning it off on a deployed environment leaves the Key Vault key and blob container in place (purge protection) and stops the roles. Revert is `git revert`; the compose profile and Make targets disappear with it.

## Live and open gates
- Hosted north-star run: needs `NS_LIVE_APPROVED=1`, an approved pipeline run with `governance_profile=north-star`, two signed-in steward identities and an auditor, and an operator-supplied webhook. Recorded OPEN until evidenced under `docs/evidence/north-star/`. PRP-136 re-runs it; PRP-66 lists it among the sign-off gates.
- Key Vault key wrap in each cloud (U-1): first proven here; Government is OPEN unless run in a Government subscription.

## NOT building
Any step of the chain (owners: PRP-100 to PRP-108). A pipeline that signs in as a person or stores session tokens. Production or real customer data in the demo: synthetic only. Copilot or MCP access to captured content (GD-3). Blocking inside third-party SaaS, endpoint or browser DLP, or a claim of parity with Microsoft Purview or any product (design section 8 items 1, 2, 5). A claim that the hosted scenario passed before an operator ran it (item 12). Detection of names or free-text PII: the scenario uses structured identifiers only (item 4).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 2, 3, 5, 6 and the GD rows are ASSUMPTIONS for plan approval)

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
- Local north-star result (S1-S10, trail, secrecy sweep):
- Hosted run: evidence path or OPEN with reason:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues (one per failing step, filed against its owning PRP):
- Product check (can an operator use it without editing files):
