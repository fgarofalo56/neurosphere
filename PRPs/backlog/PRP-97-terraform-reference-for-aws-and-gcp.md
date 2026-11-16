---
name: PRP-97-terraform-reference-for-aws-and-gcp
status: backlog
priority: P2
order: 88
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 8
ns: NS-07, NS-08
depends_on: [PRP-85-deployment-target-ports-and-adapter-boundary, PRP-94-secret-readers-and-workload-identity]
wave: W28
branch: prp-97-terraform-reference-for-aws-and-gcp
allow_parallel: true
issues: []
---

# PRP-97: Reference Terraform for AWS and GCP

## Goal
Provide reference infrastructure-as-code for the two cloud targets that have none: `infra/terraform/aws` and `infra/terraform/gcp`. Each provisions the managed services the portable backends run on (network, Kubernetes cluster, managed PostgreSQL, managed Kafka, object storage, secret entries without values, identities for the workloads, optionally an identity provider) and emits one platform-outputs document, in the schema PRP-85 fixed, that the Helm values from PRP-96 consume. Nothing is applied: the deliverable is HCL that validates, formats, passes static policy tests and produces a reviewable plan-level contract, plus an operator runbook with an approval gate. It is for the architect who wants an AWS or GCP landing zone for NeuroSphere and for PRP-98, which hands the real `apply` to the live gates. It runs in W28 beside PRP-96 and shares no file with it. Azure stays on Bicep; this PRP does not re-implement Azure in Terraform, and the on-prem target has no Terraform because the cluster belongs to the customer (PRP-96 owns its reference).

Out of scope: Helm values and charts (PRP-96); the adapters and settings the outputs feed (PRP-89 to PRP-95); the conformance matrix and the live `apply` scripts (PRP-98, PRP-64); AKS cluster IaC and Bicep changes; AWS GovCloud, Google Assured Workloads and any Government-class boundary; multi-region or cross-region DR design; a Pub/Sub or OpenSearch module; edits to workflows (the CI step is data-driven or a `[serial-after]` item).

## Why
- Original-PRD 5f (`git show 9fbf5f4c:docs/PRD.md`): "Reference IaC (Terraform/Bicep) provided for each of the four target environments." and "As an architect, I want to deploy NeuroSphere into our existing Azure landing zone using Bicep/Terraform." v1.2 removed it: `PRP.md:11` ("Primary Azure IaC: Bicep ... Terraform is not a second mandatory implementation"), `docs/PRD.md:4` and `docs/PRD.md:57` ("AWS/GCP hosting ... outside the initial baseline"). The owner's 2026-11-16 decision overrides these for the non-Azure targets only; the PRP-85 ADR and authority edits amend the sentence, and this PRP supplies the artefact.
- No Terraform exists: `infra/` holds `appservice`, `bicep`, `demo`, `dev`, `dr`, `helm`, `observability`, `scripts` (verified); `.gitignore` carries no state, `.terraform` or `*.tfvars` entries (grep, none), so state and variable files would be committable today.
- The Azure IaC is the shape to match for tagging, naming, private networking and deletion protection: modules under `infra/bicep/modules/` (`cosmos`, `eventhubs`, `storage`, `keyvault`, `network/`, `policies/`) and `infra/demo/`; budget and ownership rules came from PRP-32 and PRP-67.
- The ports the modules serve are defined by PRP-85 to PRP-94 (PostgreSQL stores, Kafka, S3 and GCS object stores, generic OIDC, secret readers and workload identity); the chart that consumes the outputs is PRP-96.
- Terraform has been BUSL-1.1 since 1.6 (design section 5.2); the design's assumption is to write HCL that both Terraform and OpenTofu accept and validate in CI with OpenTofu (MPL-2.0). Neither tool is a packaged Python dependency, so `scripts/licenses_report.py` does not see them and they need ADR-0002 rows (PRP-87 pins tool versions; this PRP records the ones it actually used).

## Acceptance criteria
- [ ] Given a clean checkout and no cloud credential in the environment, When `tofu fmt -check -recursive infra/terraform` and `tofu init -backend=false` plus `tofu validate` run for each root module (`aws`, `gcp`), Then they pass; no command contacts a cloud account (provider plugin download is the only network use and is stated in the runbook).
- [ ] Each root module declares inputs for names, region or location, CIDRs, tags or labels, and optional customer-managed-key identifiers, with `validation` blocks (required tags or labels present, CIDRs valid, deletion protection not disabled without an explicit override variable) and no default that names a real account, project, domain or secret.
- [ ] Each root module produces one output named `platform_outputs` whose JSON shape equals the PRP-85 platform-outputs schema (endpoints, role or service-account identifiers, bucket names, topic names, secret entry names); a test validates a rendered sample against the schema and fails when a required field is missing or an extra credential-shaped field appears.
- [ ] Data stores are private by default (no public endpoint, private subnets or private service connect), encrypted at rest with provider-managed keys with an optional customer-managed key variable, with deletion protection and backups on; the test asserts these properties on the parsed configuration, not on a plan.
- [ ] Secret entries (AWS Secrets Manager, GCP Secret Manager) are created empty: no `secret_string`, `secret_data`, generated password or random secret resource exists anywhere (test greps and parses); database and broker authentication use IAM or workload identity as the PRP-94 providers expect, or the module documents the operator-supplied alternative.
- [ ] Workload identity bindings for the chart's service account exist (IAM role for service accounts or EKS Pod Identity on AWS; GKE Workload Identity binding on GCP), with least-privilege intent stated per role in the module README; exact policy statements are written at execution from provider documentation and each cites its source page and date.
- [ ] No file under `infra/terraform` contains a credential, access key, account id, state file or `*.tfvars` with values; `.gitignore` gains state, `.terraform/`, plan-file and `*.tfvars` entries (examples use `*.tfvars.example`); the repository secret guards pass.
- [ ] An operator runbook per cloud states the approval gate (`NS_LIVE_APPROVED=1` and the owner's written approval), cost and quota warnings, that Terraform state is sensitive and where it must live, the order (plan, review, apply, outputs to values), and the teardown order; it makes no compliance or availability claim.
- [ ] Every provider argument used for MSK, Google Managed Kafka, Cloud SQL, RDS, EKS, GKE and the identity bindings is traced to provider documentation fetched during execution (recorded in a `SOURCES.md` per module with URL and date); an argument that could not be verified is left out and listed.
- PRP exit: touched suites, ruff, `validate_planning.py` pass; PR open with CI green; `apply` on AWS and GCP written OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| D-1 | Hosting axis (program decision D-1) | new `DeploymentTarget` axis beside `NS_CLOUD`; widen the cloud enum | Decided by the owner 2026-11-16: a new `DeploymentTarget` axis (`NS_PLATFORM` = azure, aws, gcp, kubernetes; default azure) beside the existing `NS_CLOUD` boundary class; `government` is valid only with azure; canonical IDs are unchanged (they keep the `commercial:` first segment on AWS, GCP and on-prem). Recorded in the PRP-85 multicloud-hosting ADR |
| D-2 | Backend strategy (program decision D-2) | a native service adapter per cloud; one portable backend set | Decided by the owner 2026-11-16: one portable backend set (PostgreSQL, Kafka API, S3 API plus native GCS, generic OIDC, OTLP, OpenAI-compatible/Bedrock/Vertex model adapters) running on each cloud's managed service or in-cluster, not a native service adapter per cloud (no DynamoDB, Firestore or Pub/Sub adapters). Recorded in the PRP-85 multicloud-hosting ADR |
| 3 | Tool and licence | Terraform; OpenTofu; both | ASSUMPTION: write HCL both accept; validate with OpenTofu in CI; confirm the licence and the version from the OpenTofu release page at execution (nothing from memory) |
| 4 | Provider versions | pin exact; ranges | Pin exact provider versions in `.terraform.lock.hcl` committed per root module (hashes, no secret); versions chosen at execution from the registry, recorded with date |
| 5 | Remote state | include a backend; none | No backend block with real names; a `backend.tf.example` documents an S3 or GCS backend with variables only; state is sensitive and never committed |
| 6 | Scope of AWS | all services; the minimum the portable set needs | VPC with private subnets, EKS, RDS for PostgreSQL (or Aurora PostgreSQL: pick one at execution and say why), MSK, S3 buckets, Secrets Manager entries, IAM roles for service accounts, optional Cognito user pool |
| 7 | Scope of GCP | same | VPC, GKE, Cloud SQL for PostgreSQL, Google Cloud Managed Service for Apache Kafka, GCS buckets, Secret Manager entries, service accounts with Workload Identity; the identity provider choice is OPEN (design: no Google-native IdP is promised) |
| 8 | Managed Kafka and IAM auth arguments | from memory; from docs | UNVERIFIED in the design; resolved only by reading provider documentation during execution |
| 9 | Plan-level test | real `plan`; static parse | Static parse of HCL plus `tofu validate`; OpenTofu `tofu test` with mocked providers is UNVERIFIED as a feature in the design: check the OpenTofu documentation at execution and use it only if available, otherwise parse with a verified HCL parser. A `plan` against a real account is never run here |
| 10 | CI wiring | edit workflows; data-driven | A new `scripts/terraform/validate.py` (this PRP's file) that PRP-98 or CI invokes; a workflow edit is a `[serial-after: PRP-96]` item because PRP-96 owns the new workflow files and `.github/workflows/*.yml` is Tier 1 |
| 11 | Tool pins | here; PRP-87 | PRP-87 records tool pins in ADR-0002 as part of its dependency scaffold; this PRP adds ADR-0002 rows only if a tool it needs was not pinned, via a `[serial-after: PRP-87]` item (Tier 1) |
| 12 | `.gitignore` | edit; leave | Edit additively (credential-shaped paths rule in the owner's global rules); not in any other PRP's ownership |

## Context manifest

### Files to read first
- `infra/bicep/modules/{cosmos,eventhubs,storage,keyvault}.bicep` and `infra/bicep/modules/network/` - naming, tagging, private-endpoint and deletion-protection conventions to mirror.
- `infra/demo/main.bicep` (parameters, tags, budget) and `infra/appservice/main.bicep` - how parameters carry names only.
- `infra/helm/values.yaml`, `values-government.yaml` - what the values consume (PRP-96 adds the `backends` block and platform values files).
- `docs/adr/0002-stack-pins.md` - infrastructure table where tool and provider pins are recorded.
- `docs/ops/dr-runbook.md` - runbook tone and the "measured versus target" rule.
- `tests/unit/infra/test_bicep_build.py` - the pattern for a static infra test that skips with a reason when a tool is missing.
- `.gitignore`, `.gitleaks.toml` (read only), `.github/workflows/secret-scan.yml` - what already guards credential-shaped files.
- PRP-85's multicloud-hosting ADR (`docs/adr/*-multicloud-hosting.md`; number settled by PRP-85, expected 0010), the platform-outputs schema `packages/core/neurosphere_core/platform/outputs.schema.json`, and PRP-85's registry of platform settings.
- PRP-94's secret-reader and workload-identity design (which identity mechanism each cloud uses; reference names of secret entries).
- `temp/audit/multicloud-program-design.md` sections 5.2, 5.3 and 7 (design source, read only).

### Interfaces consumed
- PRP-85: the platform-outputs document schema (JSON Schema and field list), `DeploymentTarget` values, the ADR that records D-1 and D-2 and the tool-licence assumption, the sentence amendment for `PRP.md:11`, and the registry of platform settings, consumed by reference: every `platform_outputs` field maps to a registry row (names and identifiers only), and the module emits no output for a row that does not exist.
- PRP-94: the names and shapes of secret entries it reads (AWS Secrets Manager, Google Secret Manager), and which credential mechanisms it implements (IAM role for service accounts, EKS Pod Identity, RDS IAM database tokens, MSK IAM, GKE Workload Identity, Cloud SQL IAM, Managed Kafka authentication). Modules must create what those readers expect and no more.
- PRP-89 to PRP-93 (indirect, through PRP-85's schema): database name and engine version expectations (PostgreSQL features used: `jsonb`, `json`, `FOR UPDATE`, `tsvector`, `text[]`; PRP-91 does not use `pg_trgm`), Kafka topics and partition keys, bucket roles (archive, quarantine, replay, lifecycle archive), OIDC issuer settings.
- PRP-87: pinned tool and provider versions in ADR-0002 if recorded.

### Interfaces provided
- `infra/terraform/aws/` and `infra/terraform/gcp/` root modules with `modules/` children, variables documented in each README, output `platform_outputs`.
- `infra/terraform/schema_check.py` (new) validating a rendered outputs document against the PRP-85 schema; sample documents `infra/terraform/{aws,gcp}/examples/platform_outputs.example.json` with placeholder identifiers.
- `docs/deploy/aws-infrastructure.md`, `docs/deploy/gcp-infrastructure.md`; `scripts/terraform/validate.py` entry point for CI.
- Tests under `tests/unit/terraform_reference/` that PRP-98 lists as the "validates" row of the conformance matrix.

### Patterns to match
- Parameter and tag conventions: `infra/bicep/modules/storage.bicep`, `infra/demo/main.bicep` tags section.
- Static infra test with an explicit skip reason when the tool is missing, and the shared `skip_or_fail` rule: `tests/unit/infra/test_helm_render.py:30-60`.
- Secret hygiene tests that grep a directory for credential shapes: `tests/security/` secret-scan tests and `tests/unit/infra/test_helm_render.py:128` (`test_no_secret_objects_or_literals`).
- Operator-only gate wording: `scripts/gates/g01_analytics_live.py:778-785` (refusal text, no connection attempted).

### Gotchas
- Never write a provider argument from memory. MSK, Google Managed Kafka, Cloud SQL IAM authentication, EKS Pod Identity and Workload Identity argument names change between provider versions; each is checked against the pinned provider's documentation at execution (clarification 8).
- Terraform state can contain generated values. Do not use any resource that generates a secret (random passwords, access keys, `aws_db_instance` `password`); if the engine requires an initial administrator credential, use the provider's managed-secret option if the documentation confirms it, otherwise document an operator-supplied path. Mark this as an open decision in the completion note if unresolved.
- Tool availability: `tofu` may not be installed locally or in the CI image. Tests skip with an explicit reason locally and fail (not skip) in CI by the shared rule once a CI step exists; until then say so in the report.
- Provider plugin download needs network access; state it in the runbook and do not vendor providers.
- `*.tfvars` and state in `.gitignore`: add `*.tfvars.example` as an allowed pattern so examples remain committable.
- CI python suite is sharded by top-level test root; `tests/unit/terraform_reference` is under `tests`, fine.
- Tags and labels differ: AWS tags are key/value on resources, GCP uses `labels` with lowercase restrictions; validate with each cloud's rules, not a shared regex.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - infra/terraform/**
  - scripts/terraform/**
  - tests/unit/terraform_reference/**
  - docs/deploy/aws-infrastructure.md
  - docs/deploy/gcp-infrastructure.md
tier1: []
tier2_appends:
  - .gitignore
  - mkdocs.yml
must_not_touch:
  - infra/helm/**
  - infra/bicep/**
  - infra/demo/**
  - infra/appservice/**
  - infra/onprem/**
  - docker-compose.yml
  - Makefile
  - .github/workflows/**
  - pyproject.toml
  - uv.lock
  - docs/adr/0002-stack-pins.md
```

## Implementation blueprint

### Item 1 - Tool, providers and sources (verify first)
- Deliverable: decide and record the tool (OpenTofu by assumption), exact tool and provider versions, the licence checked from the project pages, and the documentation pages each module will rely on; write `infra/terraform/README.md` (layout, conventions, what is verified and what is not) and a `SOURCES.md` skeleton per root; generate nothing that needs credentials. Output of this item is the list of arguments that could be verified; later items use only those.
- Owned files: `infra/terraform/README.md`, `infra/terraform/{aws,gcp}/SOURCES.md`, `.gitignore` additions, `tests/unit/terraform_reference/test_repo_hygiene.py`.
- Must NOT touch: `docs/adr/0002-stack-pins.md` (a `[serial-after: PRP-87]` follow-up adds rows if PRP-87 did not).
- Depends on: none.
- Acceptance criteria: criteria 7 (gitignore part), 9 (sources part).
- Tests: `.gitignore` covers state, `.terraform/`, plan files and `*.tfvars` and still allows `*.tfvars.example`; no state or tfvars is tracked (`git ls-files` based).
- Pattern references: `.github/workflows/secret-scan.yml:50`.

### Item 2 - AWS root module  [P]
- Deliverable: `infra/terraform/aws/` with child modules for network, cluster, database, stream, object storage, secrets (entries only), workload roles, optional identity provider; variables with validation; `platform_outputs` output; `examples/platform_outputs.example.json`; README with least-privilege intent per role (statements written from documentation, each with source and date).
- Owned files: `infra/terraform/aws/**`.
- Must NOT touch: `infra/terraform/gcp/**`.
- Depends on: item 1 and the PRP-85 outputs schema.
- Acceptance criteria: criteria 1 to 6 for AWS.
- Tests: `tests/unit/terraform_reference/test_aws_static.py` (parsed configuration properties: private, encrypted, protected, no generated secrets, tags required); `test_aws_validate.py` (`tofu validate`, skipped with a reason if absent).
- Pattern references: Bicep modules; test pattern above.

### Item 3 - GCP root module  [P]
- Deliverable: the GCP counterpart: network, GKE, Cloud SQL for PostgreSQL, Managed Kafka, GCS buckets, Secret Manager entries (empty), service accounts and Workload Identity bindings; same outputs document.
- Owned files: `infra/terraform/gcp/**`.
- Must NOT touch: `infra/terraform/aws/**`.
- Depends on: item 1 and the PRP-85 outputs schema.
- Acceptance criteria: criteria 1 to 6 for GCP.
- Tests: `tests/unit/terraform_reference/test_gcp_static.py`, `test_gcp_validate.py`.

### Item 4 - Outputs contract and validate entry point
- Deliverable: `infra/terraform/schema_check.py` validating a rendered outputs document and the two sample documents against the PRP-85 schema; `scripts/terraform/validate.py` running format, init without backend, validate and the static tests for both roots, printing a result per root and refusing any command that would plan or apply.
- Owned files: `infra/terraform/schema_check.py`, `scripts/terraform/validate.py`, `tests/unit/terraform_reference/{test_outputs_schema,test_validate_entrypoint}.py`.
- Depends on: items 2 and 3.
- Acceptance criteria: criteria 3 and 1; the entry point exits non-zero when a root fails and when the tool is missing in CI mode.
- Tests: a deliberately broken outputs sample (missing field, extra `secret_key` field) fails the checker.
- Pattern references: `scripts/gates/g01_analytics_live.py:778-785` for refusals.

### Item 5 - Operator runbooks  [P]
- Deliverable: `docs/deploy/aws-infrastructure.md` and `gcp-infrastructure.md`: prerequisites, approval gate, variables, plan review checklist, apply, outputs to Helm values (via PRP-96's overlay generator), teardown, cost and quota warnings, state handling, what is OPEN; `mkdocs.yml` nav lines.
- Owned files: the two docs, `mkdocs.yml` (additive).
- Depends on: items 2 and 3 (variables) and PRP-96's generator name (read PRP-96 if merged, else cite by purpose).
- Acceptance criteria: criterion 8; docs tests pass.

### Item 6 - CI wiring  [serial-after: PRP-96]
- Deliverable: a CI step (or a workflow job) that runs `scripts/terraform/validate.py` with OpenTofu installed; added only after PRP-96 merged because `.github/workflows/*.yml` is Tier 1 and PRP-96 owns the new workflows in this wave. If a data-driven runner from PRP-89 (`scripts/portable/run_conformance.py`) can call it without a workflow edit, use that and skip this item.
- Owned files: none in `owns`; the workflow edit is granted only by the serial-after rule; report it.
- Acceptance criteria: CI job green; the step fails (not skips) when `tofu` is absent.

### Item 7 - Integration and close-out
- Deliverable: rebase, Tier-3 regeneration, changelog fragment `changelog.d/PRP-97-terraform-reference-for-aws-and-gcp.md`, completion note (verified arguments, unverified list, OPEN `apply`, the ADR-0002 rows owed).
- Owned files: this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1 to 6.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q tests/unit/terraform_reference tests/unit/infra tests/docs/test_nav_allowlist.py
python scripts/terraform/validate.py --check
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
`python scripts/terraform/validate.py --check` needs OpenTofu installed; where it is not, the command exits with a stated reason and the report says "validate did not run".

## Migration and rollback
None: new files only, plus additive `.gitignore` and `mkdocs.yml` lines. Rollback is reverting the PR. Nothing in this PRP changes an existing environment, and no resource is created anywhere. A future `apply` is an operator action with its own teardown in the runbook.

## Live and open gates
OPEN, operator-only (`NS_LIVE_APPROVED=1` plus written owner approval; handed to PRP-64, with PRP-66 for operations sign-off): `plan` and `apply` on a real AWS account and a real GCP project, EKS and GKE cluster creation, RDS and Cloud SQL IAM database authentication, MSK and Managed Kafka authentication, Secrets Manager and Secret Manager, optional Cognito pool, `destroy`. Both need a cloud account the project does not have today. Reported OPEN, no claim of working infrastructure.

## NOT building
Azure Terraform; on-prem Terraform; AKS IaC; GovCloud or Assured Workloads; multi-region or DR topology; a Pub/Sub, OpenSearch or Kinesis module; CMK key creation (only an optional input to reference an operator-owned key); a Terraform provider or module registry publication; a state backend with real names; any cost estimate presented as a commitment.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (D-1 and D-2 were decided by the owner 2026-11-16; rows 3, 9, 10, 11 and 12 are ASSUMPTIONS for plan approval; owner decision D-4 in PRP-85 (hyphenated regions) applies to the region inputs)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | serial-after PRP-96 |
| 7 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issue numbers:
- Product check (can an operator use it without editing files):
