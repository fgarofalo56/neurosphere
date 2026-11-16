---
name: PRP-61-configuration-detections-and-shadow-ai-discovery
status: backlog
priority: P2
order: 49
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-03, NS-07, NS-08
depends_on: [PRP-56-compliance-control-library-and-evidence-bundles, PRP-15-recommendations-engine, PRP-70-contracts-revision-restored-scope]
wave: W22
branch: prp-61-detections
allow_parallel: true
issues: [255]
---

# PRP-61: Configuration detections and shadow-AI discovery

## Goal
Add a `detections` worker role that reads platform configuration metadata and emits findings as a new kind of stored recommendation (assumption A6): (1) content-filter and PII-protection configuration checks, comparing each Foundry model deployment's content-filter policy name and each registered APIM gateway's policy-fragment names against what the operator declares acceptable; (2) shadow-AI discovery, listing AI accounts that Azure Resource Graph shows but that no catalog entity or configured discovery target references. Findings reach stewards through the existing recommendations list and review path, and become control evidence for PRP-56. It is for security reviewers and stewards who today have no check at all (`docs/validation/PRODUCT-VALIDATION-2026-11-06.md:67-72`). Metadata only: no prompt, response or request-body capture, no policy XML, no keys. Findings say "configuration differs from the declared expectation"; they never say a deployment is safe, compliant or authorized.

Out of scope: the control library and bundles (PRP-56, whose control ids are cited here); any write or auto-remediation (the shared action executor owns writes, PRP-17); the AWS Bedrock connector and AWS shadow discovery (PRP-62); hosted role lists and Bicep/Helm role wiring (PRP-58 and PRP-63; the operator adds `detections` to `NS_WORKER_ROLES` until they do); the live read against a subscription (PRP-64, OPEN); PII detection inside content; Government region support beyond what the capability matrix already says.

## Why
- The validation found "no PII-exposure or content-filter configuration checks, and no working shadow-AI discovery" (`docs/validation/PRODUCT-VALIDATION-2026-11-06.md:67-72`); `grep` finds `content_filter` only as a provider finish-reason handler (`packages/core/neurosphere_core/copilot/models/normalize.py`), and `shadow` only as CSS and test names (lane-d step 7).
- The data to compare exists as metadata: the Foundry deployment PUT preserves `raiPolicyName` (`connectors/reference/foundry-actions/neurosphere_connector_foundry_actions/logic.py:131`), the APIM inventory stores policy-fragment names only ("the fragment XML is never read", `packages/core/neurosphere_core/gateway/models.py:254-258`), and the deployment scan already enumerates AI accounts through Resource Graph (`services/api/neurosphere_api/deploy/scan/graph.py:33-50`, `SCAN_QUERY`) but only inside a consent-bound, in-memory API call (`deploy/scan/store.py:1-9`), so a worker cannot reuse it.
- Catalog discovery creates `model_deployment` entities from Foundry (`services/workers/neurosphere_workers/ingestion/foundry_discovery/poller.py:176-227`), which gives the "known" side of shadow-AI matching.
- Recommendations are the existing surface for advisory findings with review and an owner-unresolved route to stewards (`packages/contracts/schemas/recommendations/v1/recommendation.schema.json`: `owner.resolution`, `advisory`); the kind enum had six values (lines 39-47) until PRP-70 added the two kinds this PRP emits.
- A worker role is a bounded `PeriodicTick` that idles when unconfigured (`services/workers/neurosphere_workers/runtime/factories.py:1240-1257`, `build_billing_export`), so a new role cannot break a deployment that has not configured it.

## Acceptance criteria
- [ ] Contract (shipped by PRP-70, consumed here, not edited): the recommendation `kind` enum already holds `configuration_finding` and `unregistered_ai_resource`; for those kinds `advisory` is `true`, `method` is `rule`, and `evidence_status: sufficient` is valid without a `score`; the frontend kind labels already exist in `strings.ts`. This PRP adds the API `Kind` literal values and the frontend `RECOMMENDATION_KINDS` filter list, and its findings validate against the generated `Recommendation` model.
- [ ] Content-filter check: given settings that list the Foundry accounts to inspect and, optionally, the acceptable policy names, When a deployment has no `raiPolicyName` or a name outside the list, Then one finding per deployment is stored with the deployment's canonical id as subject and the observed policy name (or `unset`); when no acceptable list is configured only `unset` is reported and the rule says so in its `generator` id; a deployment that cannot be read is `unknown` coverage, never a pass.
- [ ] Gateway check: given a declared list of required APIM policy-fragment names (for example a PII-redaction or content-safety fragment the operator uses), When a registered gateway's latest inventory lacks any of them, Then a finding names the gateway and the missing fragment names; with no declared list the rule is `not_evaluated` and emits nothing; no policy XML, key or subscription value is read or stored.
- [ ] Shadow-AI: given a Resource Graph read of AI accounts (kind `OpenAI` or `AIServices`) in the configured subscriptions, When an account name is not referenced by any catalog `model_deployment` entity's project attribute or a configured discovery target, Then an `unregistered_ai_resource` finding is stored with a synthetic canonical subject id derived from cloud, customer and account name, the ARM resource id digest, location and tags keys only; matching rules and the assumption are documented in the runbook.
- [ ] Idempotence: a re-run with unchanged configuration upserts the same recommendation ids (stable hash of rule id, subject and observed value) and does not duplicate; a finding that no longer applies expires (`expires_at` is two intervals ahead and is not extended) rather than being deleted.
- [ ] Metadata only: a test feeds readers whose payloads contain prompt-like text, a key and policy XML and asserts none reaches a stored recommendation, a log line or an audit record; the Resource Graph query is a fixed constant with a column allowlist.
- [ ] Cloud rules: a Government deployment uses the Government ARM and Resource Graph hosts from `CloudProfile`, never a Commercial host; a subscription or account of another cloud is refused with a reason code; where the capability matrix says a read is unavailable the rule reports `capability_unavailable` coverage and emits nothing.
- [ ] Role: `NS_WORKER_ROLES` accepts `detections`; with no `NS_WORKER_DETECT_*` configuration the role idles with an info log; bad configuration fails the role with a machine reason (`detections_domain_id_invalid`, ...), not the process; the role is read-only (no ARM PUT/POST except the Resource Graph query POST).
- [ ] Evidence: a `configuration_findings` evidence source (counts of open findings per kind, window, truncation) is registered with PRP-56 and mapped to the content-filter, monitoring and inventory controls the PRP-56 library already contains, using its status vocabulary; no sentence claims compliance.
- [ ] Review path: an `unregistered_ai_resource` finding appears in `GET /api/v1/recommendations?kind=unregistered_ai_resource` for a steward of the configured domain and not for another domain (existing scope filter, test).
- PRP exit: with fakes for ARM, Resource Graph and the gateway store, the role stores one finding per rule violation, the recommendations API lists them, and a live read is written OPEN (PRP-64).

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where findings surface | New recommendation kind; new finding store | A6: new recommendation kinds, plus control evidence in PRP-56 |
| 2 | What "acceptable" means | Built-in list; operator-declared | Operator-declared lists (`NS_WORKER_DETECT_*`); no built-in claim about which policy is adequate. With no list only `unset` is reported. ASSUMPTION |
| 3 | PII check scope | Content inspection; configuration presence | Configuration presence only (policy-fragment names, content-filter policy name); metadata only by owner decision |
| 4 | Shadow-AI "known" set | Catalog only; catalog plus configured targets | Catalog `model_deployment` project attributes plus configured discovery targets. ASSUMPTION: the project attribute holds `resource/project` as `foundry_discovery` writes it (`poller.py:194`); item 3 confirms |
| 5 | Resource Graph reader | Import the API scan module; new worker reader | New read-only worker reader with its own fixed query (the API module is consent-bound and workers must not import the API package); same type-to-category source of truth is copied, with a test pinning the AI-account filter |
| 6 | Findings with no domain | Reject; configured domain | Configured `NS_WORKER_DETECT_DOMAIN_ID` receives findings whose subject has no catalog domain; owner `unresolved` routes to stewards |
| 7 | Score of a deterministic finding | Fabricate 1.0; allow no score | Allow `sufficient` without score for the two new kinds (schema `if/then`), never a fabricated score. Made final by PRP-70 (its clarification 10); no longer an assumption here |
| 8 | AWS and other clouds | Here; PRP-62 | Out of scope; AWS metadata discovery is the Bedrock connector's job |

## Context manifest

### Files to read first
- `packages/contracts/schemas/recommendations/v1/recommendation.schema.json` - `kind` enum, `owner`, `uncertainty`, `coverage`, the `score` rules and `$defs/canonical_id`.
- `services/workers/neurosphere_workers/runtime/factories.py:1105-1300` and `:1575-1596` - role builders, `_tick_role`, `RoleConfigError` reasons, the `BUILDERS` table.
- `services/workers/neurosphere_workers/runtime/roles.py:19-31` - `ROLE_NAMES`; tests pinning the role list live under `services/workers/tests/worker_roles`.
- `services/workers/neurosphere_workers/ingestion/foundry_discovery/{poller.py,settings.py}` - catalog reads, settings class style, domain id pattern.
- `packages/core/neurosphere_core/recommendations/{store.py,cosmos_store.py}` - `RecommendationStore.put`, `CosmosRecommendationStore.from_client`.
- `services/api/neurosphere_api/deploy/scan/graph.py:1-60` - the fixed Resource Graph query and host handling to imitate (not import).
- `connectors/reference/foundry-actions/neurosphere_connector_foundry_actions/{arm.py,endpoints.py}` - ARM client and deployments API version; `AccountRef`.
- `packages/core/neurosphere_core/gateway/{store.py,models.py:254-289}` - `GatewayStore.list`, `get_inventory`, `PolicyFragmentEntry`.
- `packages/core/neurosphere_core/compliance/**` (from PRP-56) - `EvidenceSource` protocol and library mapping file.
- `docs/connectors/coverage.md` and `packages/core/neurosphere_core/capabilities/data/foundry.yaml` - what is available per cloud.

### Interfaces consumed
- PRP-56: `EvidenceSource`, `load_library()` and the control ids (read-only), the library mapping format (append only, `[serial-after: PRP-56]` item).
- PRP-15: the stored `Recommendation` records, `RecommendationStore`, `HitlReviewRouter` review path, `GET /api/v1/recommendations` (`services/api/neurosphere_api/recommendations/router.py:51` `Kind`).
- PRP-70 (W19, shipped before this runs): in `recommendations/v1/recommendation.schema.json` the `kind` values `configuration_finding` and `unregistered_ai_resource`, the rule that those kinds need no `score` but require `advisory: true` and `method: rule`, their valid and invalid examples, `tests/contracts/test_recommendation_finding_kinds.py`, and the two labels in `frontend/src/features/recommendations/strings.ts` ("Configuration finding", "Unregistered AI resource"). PRP-70 does NOT add the API `Kind` literal in `recommendations/router.py` or the `RECOMMENDATION_KINDS` list in `types.ts`; both stay here.
- PRP-76 (W21, same catalog, different signal): its undeclared-agent list is telemetry-versus-catalog (agents seen in telemetry with no catalog entity); this PRP is ARM-versus-catalog (AI accounts in Resource Graph with no catalog `model_deployment`). The two are complementary, share no code or store, and a resource can appear in both lists.
- PRP-37 (contracts, shipped) and PRP-42 (`ConnectorConfig` for `foundry_discovery`: targets already configured there are part of the "known" set, read through the worker's existing settings loader).
- PRP-11/PRP-35: Cosmos client and identity helpers in `factories.py` (`_cosmos`, `build_policy_stack`, `build_identity`).
- Existing settings: `NS_CLOUD`, customer id, Cosmos database name via `RuntimeConfig`.

### Interfaces provided
- Recommendation kinds `configuration_finding`, `unregistered_ai_resource`; generator ids `detect.content_filter_policy`, `detect.gateway_policy_fragment`, `detect.shadow_ai_account` (each with a version).
- Core `neurosphere_core.detections`: `DetectionRule` protocol, `Finding`, `finding_to_recommendation`, the three rules, reader protocols (`DeploymentConfigReader`, `GatewayInventoryReader`, `AiAccountInventory`, `CatalogDeploymentReader`).
- Worker role `detections` (`neurosphere_workers.detections`), settings prefix `NS_WORKER_DETECT_` (`ENABLED`, `DOMAIN_ID`, `INTERVAL_SECONDS`, `FOUNDRY_ACCOUNTS`, `ACCEPTABLE_RAI_POLICIES`, `REQUIRED_APIM_FRAGMENTS`, `SUBSCRIPTIONS`, `MAX_ITEMS`).
- Evidence source id `configuration_findings` for PRP-56 bundles.
- Runbook `docs/runbooks/detections.md` (new) for PRP-64's live check.

### Patterns to match
- `factories.py:1240-1295` (`build_billing_export`: idle when unconfigured, `RoleConfigError` reasons, `lifetime.register`, `_tick_role`).
- `foundry_discovery/settings.py:1-40` (settings class, domain id regex, bounded intervals).
- `deploy/scan/graph.py:33-50` (fixed query constant, no string-built KQL).
- `recommendations/rules/config.py:1-40` (versioned rule configs; generator cites rule id and version).

### Gotchas
- Never log a name that looks like a secret (CodeQL); do not log ARM ids with keys; log counts and reason codes.
- Hostname checks: compare DNS labels with a leading dot (CodeQL substring trap).
- A new worker role needs the pinned-role tests updated (`services/workers/tests/worker_roles` and any test that lists `ROLE_NAMES`); `all` expands to the full tuple, so the role must be a safe no-op unconfigured.
- Worker code must not import `neurosphere_api`; the worker already imports `neurosphere_connector_foundry_actions` (PRP-35), so reuse its ARM client rather than adding a dependency; this PRP adds no dependency and no workspace member, so no Dockerfile or lock change.
- `Recommendation` has `expires_at`; the in-memory store filters on it (`recommendations/store.py:58`), so expiry is the retirement mechanism.
- The generated TS union gained the two kinds in PRP-70, which also added their labels to `strings.ts` (`Record<RecommendationKind, string>`); this PRP only extends `RECOMMENDATION_KINDS` in `types.ts`.
- Live ARM and Resource Graph reads need `NS_LIVE_APPROVED=1` and an operator; every test here uses fakes.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/detections/**
  - packages/core/tests/detections_core/**
  - services/workers/neurosphere_workers/detections/**
  - services/workers/tests/detections_worker/**
  - docs/runbooks/detections.md
  - frontend/src/features/recommendations/types.ts
tier1: []
tier2_appends:
  - services/workers/neurosphere_workers/runtime/roles.py
  - services/workers/neurosphere_workers/runtime/factories.py
  - services/api/neurosphere_api/recommendations/router.py
  - packages/core/neurosphere_core/compliance/library/**
  - packages/core/neurosphere_core/compliance/sources/__init__.py
  - mkdocs.yml
must_not_touch:
  - packages/core/neurosphere_core/recommendations/**
  - services/workers/neurosphere_workers/recommendations/**
  - services/api/neurosphere_api/deploy/**
  - infra/**
  - pyproject.toml
  - uv.lock
```

## Implementation blueprint

Parallelization map: item 1 first (API literal and filter list; the contract itself is PRP-70's). Items 2 and 3 are independent [P] (core rules versus worker readers). Item 4 needs 2 and 3. Item 5 is `[serial-after: PRP-56]` and needs item 4. Item 6 verifies end to end; item 7 closes out.

### Item 1 - API literal and kind filter list (contract shipped by PRP-70)
- Deliverable: `Kind` literal extension in the API router and the two kinds added to `RECOMMENDATION_KINDS` in `frontend/src/features/recommendations/types.ts`; tests. No contract, example or label change (PRP-70).
- Owned files: `frontend/src/features/recommendations/types.ts`, the `Kind` literal in `services/api/neurosphere_api/recommendations/router.py` (Tier-2 line).
- Must NOT touch: `packages/contracts/**`, `strings.ts`, recommendation store code.
- Depends on: PRP-70 merged.
- Acceptance criteria: `GET /api/v1/recommendations?kind=unregistered_ai_resource` is accepted; `pnpm --filter @neurosphere/frontend typecheck` passes; existing recommendation examples and validators still pass (unchanged by this PRP).
- Tests: `tests/contracts`, `services/api/tests` recommendations suites (`uv run pytest -q tests/contracts services/api/tests/test_openapi_drift.py`), frontend `features/recommendations/__tests__`.
- Pattern references: existing `candidate_duplicate` rule at schema lines 108-118.

### Item 2 - Core rules and the finding-to-recommendation mapper  [P]
- Deliverable: `Finding`, `DetectionRule` protocol, the three rules over reader protocols, deterministic ids (hash of rule id, subject, observed value), `finding_to_recommendation` with coverage `unknown`/`full`, owner `unresolved`, expiry, and the canonical subject id helper for resources without a catalog entity; in-memory reader fakes.
- Owned files: `packages/core/neurosphere_core/detections/**`, `packages/core/tests/detections_core/**`.
- Must NOT touch: `neurosphere_core/recommendations/**`.
- Depends on: item 1.
- Acceptance criteria: rule criteria (content filter, gateway, shadow-AI) and idempotence against fakes; the metadata-only test; the output validates against the generated `Recommendation` model.
- Tests: `packages/core/tests/detections_core`.
- Pattern references: `recommendations/rules/config.py`.

### Item 3 - Worker readers  [P]
- Deliverable: ARM deployment lister (read-only GET of an account's deployments, pinned api-version from `endpoints.py`), Resource Graph AI-account reader with a fixed query and cloud host from `CloudProfile`, gateway-inventory reader over `GatewayStore`, catalog `model_deployment` reader over `CatalogRepository`; each bounded by `MAX_ITEMS` and a page budget and reporting `truncated`; Microsoft Learn facts for `raiPolicyName` and the Resource Graph request shape recorded in module docstrings with the observation date.
- Owned files: `services/workers/neurosphere_workers/detections/readers/**`, `services/workers/tests/detections_worker/test_readers.py`.
- Must NOT touch: `connectors/**`, `services/api/**`.
- Depends on: PRP-70 merged (contract types only).
- Acceptance criteria: fake-transport tests (`httpx.MockTransport`) for success, 403, 429, paging cap and cross-cloud refusal; no request other than GET and the Resource Graph POST; no secret in logs.
- Tests: `services/workers/tests/detections_worker`.
- Pattern references: `deploy/scan/graph.py`, `foundry-actions/.../arm.py:50-125`.

### Item 4 - Role, settings and registration
- Deliverable: `DetectionSettings` (`NS_WORKER_DETECT_*`), `build_detections` in a new module, idle-when-unconfigured behaviour, reason codes, `PeriodicTick` job that runs the rules and `put`s recommendations through `CosmosRecommendationStore`, role name in `ROLE_NAMES`, one import and one `BUILDERS` line, pinned-role test updates.
- Owned files: `services/workers/neurosphere_workers/detections/{settings.py,role.py,__init__.py}`, `services/workers/tests/detections_worker/test_role.py`; Tier-2 lines in `roles.py` and `factories.py`.
- Must NOT touch: existing builder bodies in `factories.py`.
- Depends on: items 2, 3.
- Acceptance criteria: role criterion; `NS_WORKER_ROLES=all` still starts with the role idle; one tick with fakes stores the expected recommendations and logs counts only.
- Tests: `services/workers/tests/detections_worker`, `services/workers/tests/worker_roles`.
- Pattern references: `factories.py:1240-1295`.

### Item 5 - Compliance evidence source  [serial-after: PRP-56]
- Deliverable: `configuration_findings` `EvidenceSource` (counts per kind and window, truncation, `not_collected` when no store), one registration line in PRP-56's sources registry, mapping entries appended to the library (control ids verified to exist in the loaded library; no new framework text).
- Owned files: `packages/core/neurosphere_core/detections/evidence.py`, `packages/core/tests/detections_core/test_evidence.py`; appends under `packages/core/neurosphere_core/compliance/`.
- Must NOT touch: existing library entries or PRP-56 tests.
- Depends on: item 4 and PRP-56 merged and the branch rebased.
- Acceptance criteria: PRP-56's library loader and no-claim scan still pass with the new mapping; the bundle shows the source as `observed` when findings are readable.
- Tests: `packages/core/tests/compliance_lib`, `packages/core/tests/detections_core`.
- Pattern references: PRP-56 `compliance/sources/**`.

### Item 6 - End-to-end test and runbook
- Deliverable: an unmarked in-memory test (fake readers, in-memory recommendation store, API test client) from tick to `GET /api/v1/recommendations?kind=`; runbook `docs/runbooks/detections.md` (settings, how matching works, what findings mean and do not mean, the operator checklist for the live read).
- Owned files: `services/workers/tests/detections_worker/test_end_to_end.py`, `docs/runbooks/detections.md`, `mkdocs.yml` (nav line).
- Depends on: item 4.
- Acceptance criteria: review-path criterion; runbook passes the no-claim scan from PRP-56 when that package exists.
- Tests: `services/workers/tests/detections_worker`, `tests/docs`.
- Pattern references: `tests/integration/recommendations/test_vertical_slice.py`.

### Item 7 - Integration and close-out
- Deliverable: Tier-3 regeneration (`openapi_export` if the `Kind` literal changed the schema, `docs/reference/generate.py`, contracts), `python scripts/prp_status.py --write`, `PRPs/INDEX.md`, CHANGELOG, completion note with "Env vars for the operator" (the `NS_WORKER_DETECT_*` list) and the OPEN live read.
- Owned files: this PRP file, `CHANGELOG.md`.
- Depends on: items 5, 6.

## Validation gates
```bash
python packages/contracts/scripts/generate.py --check
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q tests/contracts packages/core/tests/detections_core packages/core/tests/compliance_lib services/workers/tests/detections_worker services/workers/tests/worker_roles services/api/tests/test_openapi_drift.py tests/docs tests/integration/recommendations
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration: new recommendation documents use the existing container and are additive; the schema change is additive (new enum values). Turn it off by not setting `NS_WORKER_DETECT_ENABLED` (the role idles) or by omitting `detections` from `NS_WORKER_ROLES`. Revert the PR to remove the role and kinds; stored findings expire on their own `expires_at`.

## Live and open gates
A live read of ARM deployments, Resource Graph and a registered APIM gateway needs `NS_LIVE_APPROVED=1`, a Commercial subscription the operator names and read-only RBAC (Reader); it is OPEN here and listed as an optional item in PRP-64. The meaning of `raiPolicyName` values on real accounts and the Resource Graph column set are verified against Microsoft Learn in item 3 but not against a live account. Government stays OPEN (no subscription).

## NOT building
Content or prompt inspection; PII detection in data; policy XML parsing; auto-remediation or any write; AWS or other-cloud discovery; a new findings store or page; scheduled reports; hosted role wiring in Bicep or Helm; a claim that a deployment is safe, compliant or authorized.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (rows 2, 4 and 7 are flagged ASSUMPTIONS)

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
- Date, PR number, merge commit:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues filed:
- Operator product check (can an operator use this without editing files or calling raw APIs?):
