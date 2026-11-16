---
name: PRP-86-contracts-platform-dimension-and-credential-kinds
status: backlog
priority: P1
order: 77
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 8
ns: NS-07, NS-08, NS-09
depends_on: [PRP-85-deployment-target-ports-and-adapter-boundary, PRP-70-contracts-revision-restored-scope]
wave: W25
branch: prp-86-contracts-platform
allow_parallel: true
issues: []
---

# PRP-86: Contracts for platforms (capability-matrix platform dimension, deployment target, credential-reference kinds)

## Goal
Ship, in one Tier-1 pass, the additive `v1` contract changes the multi-cloud program needs, plus the core code that reads them, so no later multi-cloud PRP edits contracts: the capability matrix gains a `platform` dimension (default `azure`) with provider-neutral region wording and loader rules; the deployment manifest gains the deployment target and the non-Azure hosting profiles; `CredentialReference` gains five reference kinds for AWS Secrets Manager, Google Secret Manager, Kubernetes secrets, the Vault KV API and workload identity, each with exact-member validation and with the admin write path refusing any kind the deployment has not enabled; capability rows for the AWS and GCP managed services the reference IaC uses; and identity-facing contract descriptions that say "identity provider" where they do not mean Entra specifically. Canonical IDs are not touched (D-1). It is for the implementers of PRP-94 (secret readers), PRP-95 (analytics), PRP-96 (Helm) and PRP-97 (Terraform), who code against "Interfaces provided", and it is the only contracts owner in W25. Opus with a required review, following the PRP-70 precedent.

Out of scope: secret readers and allowlists per account or project, and widening the accepted kinds from the platform (PRP-94); the frontend credential field (PRP-94); the PostgreSQL analytics adapter (PRP-95); Helm and Terraform consumers (PRP-96, PRP-97); OIDC claim handling and pseudonym minting for non-Entra issuers (PRP-93); the canonical-ID grammar (unchanged by D-1); `connectors/v1` `credential_refs.vault_ref` (Azure connector manifests, unchanged); every composition change (PRP-87, PRP-88).

## Why
- Original PRD 5f (`git show 9fbf5f4c:docs/PRD.md`, lines 96-107): "Platform deployable via containerized/IaC templates to Azure, AWS, GCP, or on-prem Kubernetes, with provider-specific managed-service substitutions (e.g., Event Hubs vs. MSK vs. Pub/Sub) behind a common abstraction layer"; criterion "Core platform logic ... is cloud-agnostic; only infra adapters differ." v1.2 excluded it (`docs/PRD.md:4` "not a commitment to deploy the platform on AWS/GCP/on-prem"; `:57` "AWS/GCP hosting ... outside the initial baseline"; `PRP.md:7` "No commitment to platform hosting on AWS/GCP/on-prem."). The owner restored it on 2026-11-16 with all four targets; PRP-85 amends the build authority.
- The capability row is Azure by contract: `cloud` is "Azure cloud this row describes" and `region` is "Lowercase ARM region name" with pattern `^(\*|[a-z][a-z0-9]{2,39})$`, which rejects every hyphenated AWS and GCP region (`packages/contracts/python/neurosphere_contracts/deployment/v1/capability_matrix_entry.py:38-44`); the loader checks only `usgov*` region rules (`packages/core/neurosphere_core/capabilities/loader.py:81-86`); `DeploymentProfile` hosting is `aks|appservice` and analytics `fabric|synapse|databricks` (`capabilities/validate.py:59-61`).
- The deployment manifest says "The single Azure cloud" and "Approved Azure region names" (`packages/contracts/schemas/deployment/v1/deployment-manifest.schema.json:30-41`) and `hosting_profile` is `aks|appservice` (`:43-47`).
- `CredentialReference.kind` is `key_vault_secret|managed_identity` with a Key Vault-only URI pattern (`packages/contracts/python/neurosphere_contracts/admin/v1/credential_reference.py:22-36`). The core admin write path only recognises those two kinds as credentials (`packages/core/neurosphere_core/admin/models.py:136-140`), so a node with any other kind is walked past unchecked: widening the enum without widening that check would store an unvalidated reference.
- The pseudonymous principal-id pattern hard-codes the Entra issuer: `^(commercial|government):[a-z0-9._-]{1,128}:entra:(person|principal):p-[0-9a-f]{64}$` (`packages/contracts/schemas/admin/v1/common.schema.json:36-39`); 86 example and fixture files carry `:entra:` ids. PRP-93 needs a decision before it can mint ids for OIDC issuers.

## Acceptance criteria
- [ ] Additive only: `tests/contracts/test_additive_only.py` passes; its `ALLOWED_TIGHTENINGS` gains exactly the region-pattern entries of Clarification 2 (each with a reason, recorded in ADR-0004); every existing example and every existing capability YAML row still validates; documents without the new fields validate unchanged.
- [ ] Given a capability row without `platform`, Then it loads as `azure` with the same id, key and resolution result as before (existing `tests/unit/capabilities` and every consumer suite listed in the gates pass unchanged). Given a row with `platform: aws`, `cloud: government`, Then JSON Schema and the loader refuse it; given `platform: aws`, `cloud: commercial`, `region: us-gov-west-1` (or any `usgov`/`usdod`/`us-gov-` region), Then the loader refuses it.
- [ ] Given `DeploymentProfile(platform=aws, hosting=eks, ...)` requesting an Azure-only service (for example `fabric`, `apim`, `foundry`, `ai_search`), Then that capability resolves `disabled` with `reason_code: platform_not_supported` and no row of another platform or cloud is used to fill it; the same profile with `platform=azure` resolves exactly as today.
- [ ] Deployment manifest: `platform` (default `azure`), `hosting_profile` adds `eks`, `gke`, `kubernetes`, `analytics_backend` adds `postgres`; conditional rules refuse `government` with a non-azure platform, `aks|appservice` or `fabric|synapse` with a non-azure platform, `eks` without `aws`, `gke` without `gcp`; valid and invalid examples cover each rule.
- [ ] `CredentialReference` accepts the five new kinds with exactly their own members (Interfaces provided) and refuses any extra member, a secret-shaped value, a query string, an ARN outside the commercial `aws` partition, and any new kind on a Government document (`check_credential_reference_cloud`); `test_admin_no_credential_values.py` still finds no field that can hold a value.
- [ ] Given a connector config or system setting whose credential has a new kind, When it is written through the core admin path with the default `accepted_kinds`, Then it is refused with `credential_reference_invalid` reason `credential_kind_not_enabled` and nothing is stored; with `accepted_kinds` including the kind, Then the exact-member checks run.
- [ ] Capability rows exist for EKS, RDS for PostgreSQL, MSK, S3 and Secrets Manager (`platform: aws`) and GKE, Cloud SQL for PostgreSQL, Managed Service for Apache Kafka, Cloud Storage and Secret Manager (`platform: gcp`), each citing a provider page fetched at execution with its date, `authorization_scope: none_claimed`, and region `*` only where the cited page says the row holds everywhere.
- PRP exit: `generate.py --check`, `tests/contracts`, capability and admin suites, frontend typecheck, ruff, pyright and `validate_planning.py` pass; PR open with CI green; `services/api/openapi.json` regenerated.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| D-1 | Hosting axis (program decision D-1) | new `DeploymentTarget` axis beside `NS_CLOUD`; widen the cloud enum | Decided by the owner 2026-11-16: a new `DeploymentTarget` axis (`NS_PLATFORM` = azure, aws, gcp, kubernetes; default azure) beside the existing `NS_CLOUD` boundary class; `government` is valid only with azure; canonical IDs are unchanged (they keep the `commercial:` first segment on AWS, GCP and on-prem). Recorded in the PRP-85 multicloud-hosting ADR |
| D-2 | Backend strategy (program decision D-2) | a native service adapter per cloud; one portable backend set | Decided by the owner 2026-11-16: one portable backend set (PostgreSQL, Kafka API, S3 API plus native GCS, generic OIDC, OTLP, OpenAI-compatible/Bedrock/Vertex model adapters) running on each cloud's managed service or in-cluster, not a native service adapter per cloud (no DynamoDB, Firestore or Pub/Sub adapters). Recorded in the PRP-85 multicloud-hosting ADR |
| 1 | D-1 outcome at the PRP-85 ADR | proceed; stop | Decided by the owner 2026-11-16 (D-1 accepted): proceed; the platform axis sits beside `cloud`, which stays the boundary class |
| 2 | Hyphenated AWS/GCP regions (owner decision D-4 in PRP-85) | new `provider_region` field; widen the `region` pattern | Decided by the owner 2026-11-16 (D-4 default accepted): widen the `region` pattern in `capability-matrix-entry` and the deployment-manifest `$defs/region` to accept every existing value plus lowercase hyphenated provider regions (exact regex fixed at execution, tested against every existing row); a pattern change is a reviewed `ALLOWED_TIGHTENINGS` entry (it loosens; the test cannot prove that), recorded in ADR-0004. This departs from PRP-70's empty allowlist on purpose |
| 3 | Row id and uniqueness with a platform | unchanged; prefix non-Azure ids | Azure ids unchanged; non-Azure ids are `<platform>.<service>.<feature>.<cloud>.<region>.<sku-or-any>`; the uniqueness key becomes (platform, service, feature, cloud, region, sku) in the loader and `check_capability_matrix` |
| 4 | Credential kinds and members | design list; fewer | Design M2 list. ASSUMPTION on member names: `aws_secrets_manager` -> `secret_arn`; `gcp_secret_manager` -> `secret_version_name` (`projects/<p>/secrets/<s>/versions/<n or latest>`); `kubernetes_secret` -> `kubernetes_secret_name`, `kubernetes_secret_key` (same namespace as the workload); `vault_kv` -> `vault_mount`, `vault_path`, `vault_key` (no address: the address is deployment configuration); `workload_identity` -> `workload_identity_subject` (an IAM role ARN or a Google service-account email). Exact patterns are taken from the provider identifier documentation at execution and cited in the description |
| 5 | Who enables the new kinds at runtime | this PRP from `NS_PLATFORM`; PRP-94 | PRP-94. Here the core check gains `accepted_kinds` (default the two Azure kinds), so the wider enum cannot be used before a reader exists |
| 6 | The `:entra:` segment of principal ids (owner decision D-3 in PRP-85) | keep the literal segment as a label; widen to `(entra|oidc)` | Decided by the owner 2026-11-16 (D-3 default accepted): keep it unchanged; PRP-93 mints OIDC principals under it. History: the alternative (widening the pattern to `(entra|oidc)` as a reviewed `ALLOWED_TIGHTENINGS` entry) was not chosen |
| 7 | Analytics value for PostgreSQL | add `postgres` now; leave to PRP-95 | ASSUMPTION: add it now (`analytics_backend`, `DeploymentProfile.analytics`) so PRP-95 needs no contracts change; it resolves `disabled` with `capability_unverified` until PRP-95 adds its rows |
| 8 | Rows for `kubernetes` | rows per in-cluster component; none | ASSUMPTION: none. In-cluster PostgreSQL, Kafka, object store and Keycloak are customer-run and not matrix-gated; only Azure-only services resolve `platform_not_supported` there |
| 9 | Contract wording "Entra" | change everywhere; only where it means "identity provider" | Descriptions only, and only where generic (`admin/v1/common.schema.json` principal description). `catalog/v1/grant.schema.json` and `mcp_server.schema.json` describe Azure gateway mechanics and stay |

## Context manifest

### Files to read first
- `PRPs/shipped/PRP-70-contracts-revision-restored-scope.md` (or `PRPs/backlog/` if not yet moved) - "Interfaces provided" and its ADR-0004 note; this PRP builds on its baseline.
- The multicloud-hosting ADR written by PRP-85 (`docs/adr/*-multicloud-hosting.md`) - D-1, D-2, D-3 outcome.
- `docs/adr/0004-contract-versioning.md` - additive-only rule, `ALLOWED_TIGHTENINGS` procedure.
- `packages/contracts/schemas/deployment/v1/capability-matrix-entry.schema.json`, `deployment-manifest.schema.json` and their `examples/` and `expectations.json`.
- `packages/contracts/schemas/admin/v1/credential-reference.schema.json`, `common.schema.json:30-40`.
- `tests/contracts/test_additive_only.py`, `validators.py:950-1010` (`check_deployment_manifest`, `capability_row_id`, `check_capability_matrix`) and `:1155-1215` (`check_credential_reference_cloud`, `check_connector_config_cloud`).
- `packages/core/neurosphere_core/capabilities/loader.py:36-100`, `validate.py:59-245`.
- `packages/core/neurosphere_core/admin/models.py:130-160`, `admin/connectors/references.py:38-120`.
- `tests/unit/capabilities/rows.py`, `test_government_isolation.py`.

### Interfaces consumed
- PRP-85: `DeploymentTarget` values (`azure`, `aws`, `gcp`, `kubernetes`) mirrored as the contract enum; the ADR decisions.
- PRP-70 (W19, shipped): the refreshed additive-only baseline and the `v1` area set; no names from it are changed here.
- Shipped: PRP-01 conventions (`schema_version` `1.x.y`, `additionalProperties: false`, relative `$ref`, examples with `expectations.json`); `CapabilityMatrix`, `validate_profile`, `CapabilityResult`; `check_credential_reference`, `parse_key_vault_secret`.

### Interfaces provided
- `deployment/v1/capability-matrix-entry.schema.json` -> `CapabilityMatrixEntry.platform`: `azure|aws|gcp|kubernetes`, default `azure`; `region` widened (Clarification 2); description of `service`, `cloud`, `region`, `authorization_scope` provider-neutral; appended `allOf`: `cloud: government` requires `platform: azure`. Rows using the new field carry `schema_version` `1.2.0`.
- `deployment/v1/deployment-manifest.schema.json` -> `DeploymentManifest.platform` (default `azure`); `hosting_profile` adds `eks|gke|kubernetes`; `analytics_backend` adds `postgres`; the conditional rules of criterion 4; `cloud` described as the data-boundary class.
- `admin/v1/credential-reference.schema.json` -> `CredentialReference.kind` adds `aws_secrets_manager`, `gcp_secret_manager`, `kubernetes_secret`, `vault_kv`, `workload_identity`; members `secret_arn`, `secret_version_name`, `kubernetes_secret_name`, `kubernetes_secret_key`, `vault_mount`, `vault_path`, `vault_key`, `workload_identity_subject`; appended `allOf` per kind (required own members, no other member).
- Core: `neurosphere_core.capabilities` - `Platform` literal, `DeploymentProfile.platform` (default `azure`), `Hosting` adds `eks|gke|kubernetes`, `Analytics` adds `postgres`, `derive_row_id` and `row_key` with platform, `AZURE_ONLY_SERVICES`, reason code `platform_not_supported`; data files `capabilities/data/aws_platform.yaml`, `gcp_platform.yaml`.
- Core: `neurosphere_core.admin.connectors.references` - frozen parsed refs `AwsSecretRef(partition, region, account_id, name)`, `GcpSecretVersionRef(project, secret, version)`, `KubernetesSecretRef(name, key)`, `VaultKvRef(mount, path, key)`, `WorkloadIdentityRef(subject, provider)`; `parse_credential_reference(ref, *, cloud) -> ParsedReference`; `check_credential_reference(ref, cloud, *, accepted_kinds=AZURE_KINDS)`; `AZURE_KINDS`, `ALL_KINDS`; reason `credential_kind_not_enabled`. `neurosphere_core.admin.models` recognises all seven kinds.
- Validators: `check_capability_matrix` (platform key, platform/region rules), `check_deployment_manifest` (platform rules), `check_credential_reference_cloud` (Government refuses new kinds).

### Patterns to match
- Appended per-kind conditionals: `admin/v1/credential-reference.schema.json:27-42`.
- Government conditional on a manifest: `deployment-manifest.schema.json:70-85`.
- Valid and invalid examples with expectations: `deployment/v1/examples/` and `admin/v1/examples/{valid,invalid}/credential-reference.*.json`.
- Row lint and isolation tests: `tests/unit/capabilities/test_row_lint.py`, `test_government_isolation.py`.
- Field walker for "no value-holding field": `tests/contracts/test_admin_no_credential_values.py`.

### Gotchas
- Pydantic ignores `if/then` (ADR-0004): the per-kind exact-member rule and the Government rules are JSON Schema tests plus the core checks, not model behaviour; test both layers.
- `packages/contracts/scripts/test_generate.py` pins the area set; no new area is added here, so it should not change. Run `python packages/contracts/scripts/generate.py` and commit the generated Python and TypeScript.
- Changing descriptions of models used as `response_model` changes `services/api/openapi.json` components text: regenerate at close-out only.
- The hand-written frontend `credentialReference.ts` treats any non-`key_vault_secret` kind as managed identity (`frontend/src/features/admin/sources/credentialReference.ts:43-46`). It does not import the generated types, so typecheck still passes, but a new-kind reference returned by the API would display wrongly; the default `accepted_kinds` keeps such references out of the store until PRP-94 updates the field.
- ARN and resource-name patterns must not be asserted from memory: fetch the AWS and Google identifier documentation in the session and cite the URL and date in the schema description.
- Capability rows are documentation facts: one fetch per row source, `observed_on` the fetch date; never invent availability.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/contracts/**
  - tests/contracts/**
  - docs/adr/0004-contract-versioning.md
  - packages/core/neurosphere_core/capabilities/**
  - packages/core/neurosphere_core/admin/connectors/references.py
  - packages/core/neurosphere_core/admin/models.py
  - packages/core/tests/admin_connectors/test_credential_reference.py
  - packages/core/tests/admin_credential_kinds/**
  - tests/unit/capabilities/**
tier1:
  - packages/contracts/schemas/**
tier2_appends: []
must_not_touch:
  - services/**
  - frontend/**
  - infra/**
  - packages/core/neurosphere_core/platform/**
  - packages/core/neurosphere_core/auth/**
  - packages/core/neurosphere_core/cloud/**
  - pyproject.toml
  - uv.lock
```

## Implementation blueprint

Parallelization: items 1 and 3 [P] (different schema files and different core modules); item 2 after 1; item 4 after 2; item 5 after 3; item 6 last.

### Item 1 - Capability matrix and deployment manifest schemas  [P]
- Deliverable: `platform` on both schemas, widened region patterns, manifest hosting and analytics values, appended conditionals, neutral descriptions, examples (valid: an AWS commercial row, a GCP row with a hyphenated region, an EKS manifest; invalid: AWS Government row, GovCloud-looking region, `eks` with `gcp`, `fabric` on `aws`), `ALLOWED_TIGHTENINGS` entries, validator updates, generated code.
- Owned files: `packages/contracts/schemas/deployment/v1/**`, generated `packages/contracts/python/neurosphere_contracts/deployment/**` and `packages/contracts/ts/**` output, `tests/contracts/validators.py` (capability and manifest functions), `tests/contracts/test_additive_only.py` (allowlist entries), `tests/contracts/test_platform_dimension.py` (new).
- Must NOT touch: `admin/v1/**` (item 3), the canonical-ID schema.
- Depends on: PRP-85 merged.
- Acceptance criteria: criteria 1, 4 and the schema half of 2.
- Tests: `tests/contracts/test_platform_dimension.py`, `test_capability_matrix.py`, `test_deployment_manifest.py`, `test_additive_only.py`, `test_schemas.py`, `test_roundtrip.py`, `test_golden_fixtures.py`.
- Pattern references: `deployment-manifest.schema.json:70-85`.

### Item 2 - Capability loader and resolution with a platform
- Deliverable: `loader.py` row key, id derivation, platform and region rules; `validate.py` `Platform`, `DeploymentProfile.platform`, `Hosting`, `Analytics`, `AZURE_ONLY_SERVICES` and `platform_not_supported` resolution; existing behaviour byte-identical for `azure`.
- Owned files: `packages/core/neurosphere_core/capabilities/{loader,validate,__init__}.py`, `tests/unit/capabilities/test_platform_resolution.py` (new), `tests/unit/capabilities/rows.py` (helper additions).
- Must NOT touch: capability consumers (analytics registry, search fallback, gateway mode, copilot gating, Fabric provisioner).
- Depends on: item 1.
- Acceptance criteria: criteria 2 and 3; every existing consumer suite in the gates passes unchanged.
- Tests: `tests/unit/capabilities`, `packages/core/tests/copilot/test_adapter_gating.py`, `packages/core/tests/search/test_azure_search_scope.py`, `tests/integration/analytics/test_profile_gating.py` (unmarked cases), `tests/integration/deploy/test_scan_to_plan.py` (unmarked cases).
- Pattern references: `loader.py:81-97`, `validate.py:198-245`.

### Item 3 - Credential-reference kinds  [P]
- Deliverable: schema members and conditionals, invalid examples (extra member, value-shaped string, `aws-us-gov` ARN, query string, Government document with a new kind), `check_credential_reference_cloud` update, generated code; core `references.py` parsers and `accepted_kinds`; `admin/models.py` recognises all seven kinds and applies exact-member checks; the principal-id description wording of Clarification 9; D-3 outcome applied (no pattern change if the recommendation stands).
- Owned files: `packages/contracts/schemas/admin/v1/**`, generated `packages/contracts/python/neurosphere_contracts/admin/**` and `packages/contracts/ts/**` output, `tests/contracts/test_credential_reference_kinds.py` (new), `packages/core/neurosphere_core/admin/connectors/references.py`, `packages/core/neurosphere_core/admin/models.py`, `packages/core/tests/admin_connectors/test_credential_reference.py`, `packages/core/tests/admin_credential_kinds/**` (new).
- Must NOT touch: `services/workers/neurosphere_workers/connector_config/**` (readers: PRP-94), frontend.
- Depends on: PRP-85 merged.
- Acceptance criteria: criteria 5 and 6.
- Tests: `tests/contracts/test_credential_reference_kinds.py`, `test_admin_no_credential_values.py`, `test_validators.py`, `packages/core/tests/admin_connectors`, `packages/core/tests/admin_credential_kinds`, `services/api/tests/admin_connectors_api`, `tests/security/authz/test_admin_connectors.py`.
- Pattern references: `credential-reference.schema.json:27-42`, `references.py:70-120`.

### Item 4 - AWS and GCP capability rows
- Deliverable: `capabilities/data/aws_platform.yaml` and `gcp_platform.yaml` (criterion 7), each row fetched and cited in the session; a lint test that every non-Azure row has `authorization_scope: none_claimed` and a provider-owned `source_url`.
- Owned files: `packages/core/neurosphere_core/capabilities/data/{aws_platform,gcp_platform}.yaml` (new), `tests/unit/capabilities/test_platform_rows.py` (new).
- Must NOT touch: existing Azure data files.
- Depends on: item 2.
- Acceptance criteria: criterion 7; `load_matrix()` loads the whole matrix.
- Tests: `tests/unit/capabilities`.
- Pattern references: `capabilities/data/aks.yaml`, `tests/unit/capabilities/test_row_lint.py`.

### Item 5 - Contract-consumer sweep
- Deliverable: grep `services/`, `packages/core/`, `connectors/` and `frontend/src/` for `CredentialReference`, `hosting_profile`, `analytics_backend`, `CapabilityMatrixEntry` and the `Hosting`/`Analytics` literals; prove each consumer still type-checks and refuses or ignores the new values safely; file follow-ups for PRP-94/95/96 where a consumer must learn a new value; no edit outside owned files.
- Owned files: this PRP's Execution state notes; tests under owned test paths only.
- Depends on: items 2 and 3.
- Acceptance criteria: repo-wide pyright and `pnpm --filter @neurosphere/frontend typecheck` pass; the sweep list is in the completion note.
- Tests: the full gate command list.
- Pattern references: `PRPs/reference/parallel-build-reference.md` section 4 (cross-test grep).

### Item 6 - Integration and close-out
- Deliverable: ADR-0004 amendment (platform dimension, region-pattern exceptions, credential kinds, D-3 outcome); refresh the additive-only baseline and empty `ALLOWED_TIGHTENINGS` in the same commit; rebase; regenerate Tier-3 (`services/api/openapi.json`, `docs/reference/**`, status table, `PRPs/INDEX.md`, `PRPs/EXECUTION-PLAN.md`); changelog fragment `changelog.d/PRP-86-contracts-platform-dimension-and-credential-kinds.md`; completion note repeating every provided name for PRP-93..97 authors.
- Owned files: `docs/adr/0004-contract-versioning.md`, `tests/contracts/fixtures/v1-baseline/**`, the changelog fragment, this PRP file, Tier-3 files.
- Depends on: items 1-5.
- Acceptance criteria: validation gates pass; CI green including the `contracts` job.

## Validation gates
```bash
python packages/contracts/scripts/generate.py --check
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q tests/contracts packages/contracts/scripts tests/unit/capabilities packages/core/tests/admin_connectors packages/core/tests/admin_credential_kinds packages/core/tests/admin packages/core/tests/copilot/test_adapter_gating.py packages/core/tests/search/test_azure_search_scope.py tests/integration/analytics/test_profile_gating.py tests/integration/deploy/test_scan_to_plan.py services/api/tests/admin_connectors_api tests/security/authz/test_admin_connectors.py services/api/tests/test_openapi_drift.py
pnpm --filter @neurosphere/frontend typecheck
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No stored-data migration: every new field defaults to the Azure value or is absent, so stored connector configs, settings, manifests and capability rows validate unchanged. New credential kinds cannot be stored until PRP-94 widens `accepted_kinds`. Rollback is a revert of the PR before any later PRP depends on the names; after that, a revert must be paired with reverting the consumer. The additive-only baseline makes an accidental tightening fail CI.

## Live and open gates
None: no live call. The capability rows are documentation facts with dates, not availability tests; real AWS and GCP availability in a customer account is part of the PRP-98 live gates (handed to PRP-64/66).

## NOT building
Secret readers; workload-identity token exchange; the frontend credential field; OIDC principal minting; a widened canonical-ID grammar; Government-class rows for AWS GovCloud or Google Assured Workloads (OPEN); rows for in-cluster components; `connectors/v1` manifest auth modes.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (D-1 and D-2 were decided by the owner 2026-11-16; rows 2, 4, 6, 7 and 8 are ASSUMPTIONS; rows 2 and 6 are owner decisions D-4 and D-3 in PRP-85)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | prp-86-contracts-platform | |
| 2 | todo | prp-86-contracts-platform | |
| 3 | todo | prp-86-contracts-platform | D-3 outcome |
| 4 | todo | prp-86-contracts-platform | rows fetched and cited in session |
| 5 | todo | prp-86-contracts-platform | |
| 6 | todo | prp-86-contracts-platform | |

## Completion note (filled at ship)
- Date and PR:
- Provided names (for PRP-93..97 authors):
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator: none expected.
- Follow-up issues:
- Product check (can an operator use it without editing files): no, by design; contracts and capability data only.
