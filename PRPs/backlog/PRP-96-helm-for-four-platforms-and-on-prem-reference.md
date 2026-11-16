---
name: PRP-96-helm-for-four-platforms-and-on-prem-reference
status: backlog
priority: P1
order: 87
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 8
ns: NS-07, NS-10
depends_on: [PRP-89-postgres-foundation-catalog-and-security-stores, PRP-90-postgres-data-plane-stores, PRP-91-postgres-control-plane-stores-and-search, PRP-92-kafka-and-object-store-adapters, PRP-93-generic-oidc-identity, PRP-94-secret-readers-and-workload-identity, PRP-95-model-telemetry-and-analytics-adapters, PRP-58-hosted-data-path-and-environment-hardening, PRP-63-delivery-pipeline-to-hosted, PRP-67-hosted-environment-hardening, PRP-105-policy-engine-core, PRP-107-notification-channels-and-subscriptions, PRP-117-connector-runner-and-estate-foundation, PRP-130-owner-reattestation-campaigns, PRP-132-alert-rules-and-incidents]
wave: W38
branch: prp-96-helm-for-four-platforms-and-on-prem-reference
allow_parallel: true
issues: []
---

# PRP-96: Helm for four platforms, portable compose profile, on-prem reference and air-gap bundle

## Goal
Turn the Helm chart from an AKS-only artefact into the common deploy unit for AKS, EKS, GKE and a plain conformant Kubernetes cluster, and give the on-prem target a reference that stands without any cloud account. Ships: a required `platform` value rendered as `NS_PLATFORM` with the rule "government requires azure"; per-platform service-account identity; a provider-parameterised secret mount plus an `existingSecret` mode; one `backends` values block rendered into the neutral `NS_*` names the portable adapters read; `values-aws.yaml`, `values-gcp.yaml`, `values-onprem.yaml`; an opt-in portable compose profile for developers; `infra/onprem/` with pinned dependency-operator values, an image list with digests and an air-gap mirror script; install and uninstall runbooks; and an opt-in local install smoke on a `kind` cluster. It is for the operator of a non-Azure install, and for PRP-97 (its platform-outputs document feeds these values) and PRP-98 (conformance matrix and live gates). It runs in W38 and is the wave owner of `infra/helm/**`, `docker-compose.yml` and `Makefile`. Azure installs must render byte-identical manifests for the existing value sets.

Out of scope: the Azure Bicep templates and AKS cluster IaC (not in this program; OPEN); AWS and GCP Terraform (PRP-97); the adapters, settings and secret readers themselves (PRP-89 to PRP-95); the conformance matrix, DR runbooks and live-gate scripts (PRP-98); any real cluster install, air-gapped install on customer hardware or cloud apply (OPEN, PRP-64 and PRP-66); autoscaling design (PRP-84 shipped it; this PRP preserves it).

## Why
- Original-PRD 5f (`git show 9fbf5f4c:docs/PRD.md`): "As an enterprise customer with data-residency requirements, I want an on-prem/air-gapped deployment option." and "Platform deployable via containerized/IaC templates to Azure, AWS, GCP, or on-prem Kubernetes". v1.2 removed it: `docs/PRD.md:4` ("not a commitment to deploy the platform on AWS/GCP/on-prem"), `docs/PRD.md:57` ("AWS/GCP hosting, classified/air-gapped deployment ... outside the initial baseline"), `PRP.md:7` and `PRP.md:11` ("Helm 4 for AKS ... Terraform is not a second mandatory implementation"). The owner's 2026-11-16 decision overrides these for AWS, GCP and on-prem Kubernetes; PRP-85 amends the authority text. Classified or Government-class air-gapped deployments remain outside scope.
- The chart fails today unless the cloud is Azure: `deployment.yaml:1-5` requires `env.NS_CLOUD` and accepts only `commercial` or `government`; there is no platform notion.
- Identity is Azure workload identity only: `serviceaccount.yaml:9-14` annotates `azure.workload.identity/client-id`; `deployment.yaml:23-25,29` adds the `azure.workload.identity/use` label and sets `automountServiceAccountToken` from the same flag, so an EKS or GKE pod would get no projected token; `values.yaml:18-24` documents it as Azure.
- Secrets are Azure Key Vault only: `secretproviderclass.yaml:9-14` hard-codes `provider: azure` and Key Vault parameters; `Chart.yaml` describes the chart as "for AKS".
- Existing optional blocks name Azure services (`scan`, `deployApply`, `writeTargets`, `search.provider` azure, `values.yaml:69-120`) and the NetworkPolicy comments name Entra and Azure Monitor (`values.yaml:161-175`); compose has only Microsoft emulators (`docker-compose.yml:36-84`).
- Earlier waves changed the same files: PRP-58 (role switches, store switch), PRP-67 (`probes.*`, `NS_PROBE_*`, `deployment.yaml` env), PRP-84 (`autoscaling`, `workers.pools`, `hpa.yaml`, `keda-scaledobject.yaml`, `pdb.yaml`). They must keep rendering byte-identically.

## Acceptance criteria
- [ ] Governance-core worker roles: the chart renders the roles the governance core adds (at least `policy_eval`, `notifications`, `connector_runner`, `alerting` and `attestation`, plus any role PRP-115 and PRP-118 to PRP-126 add; the list is read from `services/workers/neurosphere_workers/runtime/roles.py` at execution) for every platform values file with workers idle unless `workers.roles` lists them, and the content-capture settings render only where the platform's key-wrap provider (PRP-94) and content bucket (PRP-92) exist, otherwise capture is rendered disabled with the reason.
- [ ] Given the existing value sets (`infra/helm/ci/values-ci.yaml`, `values-government.yaml`, the PRP-84 autoscale values and any value set PRP-58 or PRP-67 added), When `helm template` runs before and after this PRP with `platform` unset or `azure`, Then the rendered manifests are byte-identical to goldens captured from `main` at the start of item 1. The test asserts equality of the full output, not of selected fields.
- [ ] Given `platform` is `aws`, `gcp` or `kubernetes` and `env.NS_CLOUD=government`, Then the chart fails with a message naming the rule; `government` with `azure` renders as today; an unknown platform value fails; the chart renders `NS_PLATFORM` from the value (default `azure` keeps today's output because no env line is added for it, or the goldens are re-captured only if the owner approves a diff).
- [ ] Given `platform: aws`, Then the service account carries the EKS role annotation and the pods have a projected service-account token; given `gcp`, the GKE service-account annotation; given `kubernetes`, no cloud identity annotation. None of these renders an Azure annotation, label or Key Vault parameter. Role ARN and service-account email values are identifiers from the platform-outputs document, never keys.
- [ ] Given `secretProviderClass.provider` is `aws`, `gcp` or `vault`, Then the SecretProviderClass renders that provider's parameters; given `secrets.existingSecret` names a Kubernetes Secret, Then it is mounted or referenced by name only and the chart creates no `Secret` object. `test_no_secret_objects_or_literals` still passes.
- [ ] Given the `backends` block (document store, event stream, object store, search, identity, model, telemetry), Then each entry renders only the `NS_*` names of PRP-85's registry of platform settings that PRP-88 to PRP-95 implemented, with names and hostnames only (no password, key or connection string with credentials), and an unset block renders nothing.
- [ ] `values-aws.yaml`, `values-gcp.yaml` and `values-onprem.yaml` each render with `helm lint --strict` and `helm template`, contain no Azure host (the existing `test_no_literal_azure_endpoints` pattern extended) and no credential, and NetworkPolicy egress for each is documented by CIDR and port (no FQDN support).
- [ ] A helper (`infra/onprem/` or `scripts/`, see item 3) turns a platform-outputs JSON document, in the schema PRP-85 fixed, into a values overlay; a test proves a sample document yields a rendering with no missing `required` value.
- [ ] The portable compose profile starts the application against the PRP-89 to PRP-93 compose fragments (PostgreSQL, Kafka, object store, Keycloak, secret server) on 127.0.0.1 with no paid call, and the existing emulator profiles and `docker compose config` output for them are unchanged.
- [ ] `infra/onprem/` contains pinned operator and chart values (CloudNativePG, Strimzi, MinIO or the chosen S3-compatible store, Keycloak, OpenTelemetry Collector), an image list with digests covering every image the chart and those values reference, and a mirror script that refuses to run without an explicit target registry argument and writes no credential to disk; a test fails when an image in a rendered manifest is missing from the list.
- [ ] The opt-in `kind` smoke installs the chart with in-cluster dependencies, signs in through Keycloak and walks one ingest-to-catalog path, from a script an operator can run locally and from a `workflow_dispatch` workflow; it is not part of the default CI and its result is reported "ran" or OPEN, never skipped silently.
- [ ] Install and uninstall runbooks for AWS, GCP and on-prem state what is OPEN, that no compliance or availability claim is made, and that Terraform state and values files carry names only.
- PRP exit: touched suites, `tests/unit/infra`, `tests/unit/helm_platforms`, `tests/unit/government_profile`, ruff, `validate_planning.py` pass; PR open with CI green including the `helm` job; kind smoke, real clusters and air-gapped install written OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| D-1 | Hosting axis (program decision D-1) | new `DeploymentTarget` axis beside `NS_CLOUD`; widen the cloud enum | Decided by the owner 2026-11-16: a new `DeploymentTarget` axis (`NS_PLATFORM` = azure, aws, gcp, kubernetes; default azure) beside the existing `NS_CLOUD` boundary class; `government` is valid only with azure; canonical IDs are unchanged (they keep the `commercial:` first segment on AWS, GCP and on-prem). Recorded in the PRP-85 multicloud-hosting ADR |
| D-2 | Backend strategy (program decision D-2) | a native service adapter per cloud; one portable backend set | Decided by the owner 2026-11-16: one portable backend set (PostgreSQL, Kafka API, S3 API plus native GCS, generic OIDC, OTLP, OpenAI-compatible/Bedrock/Vertex model adapters) running on each cloud's managed service or in-cluster, not a native service adapter per cloud (no DynamoDB, Firestore or Pub/Sub adapters). Recorded in the PRP-85 multicloud-hosting ADR |
| 3 | Azure rendering | refactor templates freely; keep output identical | Identical for existing value sets, proven by goldens (acceptance 1); new template logic is additive and guarded by `platform` |
| 4 | Where `platform` defaults | required; default azure | ASSUMPTION: default `azure`, so existing deployments need no change; the `NS_CLOUD` required rule is unchanged |
| 5 | Pod identity token | keep `automountServiceAccountToken` tied to Azure flag; per platform | Per platform: Azure flag unchanged; EKS and GKE mount the projected token; plain Kubernetes mounts it only when `serviceAccount.automountToken` is set (default false) |
| 6 | Compose profile shape | edit `docker-compose.yml`; separate file | ASSUMPTION: a new `infra/compose/portable/app.yml` that includes the per-backend fragments PRP-89 and PRP-92 to PRP-94 created, started through new Makefile targets; `docker-compose.yml` gets only edits proven necessary (its fixed project name `neurosphere` must not collide). Verify first that Compose `include` composes fragments that declare their own project names; otherwise merge with `-f` flags in the Makefile |
| 7 | On-prem dependency set | operators; plain manifests | ASSUMPTION: CloudNativePG (PostgreSQL), Strimzi (Kafka), the S3-compatible store chosen under owner decision D-5 in PRP-85 (MinIO or SeaweedFS, as PRP-92 recorded), Keycloak, OpenTelemetry Collector; the Vault/OpenBao secret provider only if D-8 kept the Vault reader. Chart versions and digests are verified from the registries at execution; nothing from memory |
| 8 | Image list format | prose; machine-readable | Machine-readable file `infra/onprem/images.yaml` (name, tag, digest, source, licence note) consumed by the mirror script and the test |
| 9 | Mirror tool | `skopeo`; `crane`; `docker` | Decided at execution after checking licences and availability; the script only calls it, never vendors it; if PRP-87 did not already pin a tool, the ADR-0002 row is reported as a follow-up (no W38 ownership of ADR-0002 here; PRP-97 holds the only W38 ADR-0002 edit) |
| 10 | kind runner capacity | always on in CI; opt-in | Opt-in `workflow_dispatch` only; GitHub runner capacity for it is UNVERIFIED. It holds the compose lane (one compose user at a time) |
| 11 | Telemetry in the chart | Azure Monitor string; Collector | Platform values point `NS_TELEMETRY_EXPORTER=otlp` at an in-cluster or platform Collector using the reference configs from PRP-95 |
| 12 | Azure-only optional blocks (`scan`, `deployApply`, `writeTargets`, `mcp.apimFront`) on other platforms | render anyway; fail | Fail with a clear message when enabled with a non-azure platform (capability reason `platform_not_supported`); disabled by default so existing values are unaffected |

## Context manifest

### Files to read first
- `infra/helm/templates/deployment.yaml` (all 276 lines or more after PRP-58, PRP-67, PRP-84 edits) - guard, env blocks, volumes, identity label; read in full before editing.
- `infra/helm/templates/{serviceaccount,secretproviderclass,networkpolicy,ingress,service,_helpers}.yaml|.tpl` and any template PRP-84 added (`hpa`, `keda-scaledobject`, `pdb`).
- `infra/helm/values.yaml`, `values-government.yaml`, `ci/values-ci.yaml` and every `ci/values-*.yaml` PRP-84 added.
- `tests/unit/infra/test_helm_render.py` - render helpers, `AZURE_HOST`, the secret-literal and extension-point tests.
- `tests/unit/government_profile/` - proves `values-government.yaml` names nothing but Government hosts.
- `.github/workflows/ci.yml:262-278` - the `helm` job (`helm lint --strict`, `helm template`).
- `docker-compose.yml` (header, `name: neurosphere`, profiles `app`, `otel`, `docs`) and `Makefile` targets `dev-up`, `stack-up`, `stack-down`.
- `infra/compose/portable/*.yml` and `scripts/portable/**` as created by PRP-89 and PRP-92 to PRP-94.
- `docs/deploy/hosted-demo.md` - tone and structure of an existing deploy doc.
- `PRPs/backlog/PRP-84-ingest-throughput-and-autoscaling.md`, `PRP-67-hosted-environment-hardening.md`, `PRP-58-hosted-data-path-and-environment-hardening.md` - what each changed in the chart.

### Interfaces consumed
- PRP-85: `NS_PLATFORM`, `DeploymentTarget`, the platform-outputs document schema (`neurosphere_core.platform.outputs`, `outputs.schema.json`), the ADR that records D-1 and D-2, and the registry of platform settings in its "Interfaces provided" (setting, owner PRP, meaning), which this PRP consumes by reference.
- PRP-88 to PRP-95: the implementations of those registry rows (kind selectors, PostgreSQL connection, Kafka bootstrap and topics, object-store endpoints, OIDC issuer, JWKS URI and audiences, secret-reader allowlists, workload identity, model hosts, telemetry exporter, analytics backend), the compose fragments, and `infra/observability/collector/{aws,gcp,onprem}.yaml` (PRP-95). This PRP renders exactly the registry names; it invents none. It renders only settings that exist in the merged code (a row whose owner cut it under its `## Cut line` renders nothing and is listed in the completion note) and stops and reports otherwise.
- PRP-58 and PRP-67: the Helm values they added (worker role switches, store switch, `probes.*`, `probes.required`) and `NS_PROBE_*` rendering; PRP-67's generic probe names for non-Azure backends if PRP-87 changed them.
- PRP-84: `autoscaling.*`, `workers.pools`, `podDisruptionBudget.enabled`, templates `hpa.yaml`, `keda-scaledobject.yaml`, `pdb.yaml`, `ci/values-autoscale.yaml`. KEDA's Event Hubs trigger is Azure; a Kafka lag trigger for non-Azure platforms is a verify-first item (see Gotchas).
- PRP-63: image and chart publication (registry layout, tags, digests) used by the image list.

### Interfaces provided
- Chart values: `platform` (azure|aws|gcp|kubernetes), `serviceAccount.identity.{aws.roleArn,gcp.serviceAccountEmail}`, `serviceAccount.automountToken`, `secretProviderClass.provider` and `secrets.existingSecret`, the `backends.*` block, `platform` guards on Azure-only blocks.
- Files: `infra/helm/values-aws.yaml`, `values-gcp.yaml`, `values-onprem.yaml`, `infra/helm/ci/values-{aws,gcp,onprem}.yaml`; `infra/onprem/{README.md,images.yaml,operators/**,mirror-images.sh,smoke/**}`; `infra/compose/portable/app.yml`; Makefile targets `portable-up`, `portable-down`, `kind-smoke`.
- Docs: `docs/deploy/{aws,gcp,onprem}.md`. Workflow `.github/workflows/onprem-kind-smoke.yml` (`workflow_dispatch`).
- A values-overlay generator from the platform-outputs document, consumed by PRP-97's examples and PRP-98's live-gate scripts.

### Patterns to match
- Conditional env blocks and `fail` guards: `deployment.yaml:60-110`; required-value messages: `serviceaccount.yaml:10`.
- Render tests that shell out to Helm and skip or fail by the shared rule: `tests/unit/infra/test_helm_render.py:30-60` (`skip_or_fail`).
- Values file as overrides with a placeholder registry: `values-government.yaml:1-20`; CI placeholder rules: `ci/values-ci.yaml` ("invalid" TLD).
- Opt-in compose profile with comments naming the exact command: `docker-compose.yml:335-360`.

### Gotchas
- Goldens are captured from `main` before any template edit (item 1) and committed; a diff in them is a defect unless the owner approved it. Capture them for every value set present when this PRP starts, not the list in this file.
- `automountServiceAccountToken` is tied to the Azure flag (`deployment.yaml:29`); IRSA and GKE Workload Identity need the token (acceptance 3). Do not flip it for Azure.
- `test_no_literal_azure_endpoints` scans every chart yaml except `values-government.yaml`; platform comments must not name Azure hosts, and the new files need the same kind of check for AWS and Google hosts only where a value would hold one (names stay in comments as words, not URLs).
- KEDA's `ScaledObject` from PRP-84 targets Event Hubs lag. For non-Azure platforms either render a Kafka trigger (verify the KEDA Kafka scaler fields from its documentation first) or fail with a clear message when `autoscaling.enabled` is set on a platform without a trigger; never render an Azure trigger on another platform.
- `docker-compose.yml` has a fixed project name `neurosphere` and one compose lane: the kind smoke and the portable profile cannot run beside another compose session.
- Helm is Helm 4 (`helm version --short | grep '^v4'`); the helm tests fail rather than skip in CI.
- Do not write digests from memory: resolve them from the registry at execution and record the date; if the network is unavailable leave the digest field empty and make the mirror script refuse an empty digest.
- No `.env` or credential is read or written; sample platform-outputs documents are synthetic with placeholder ids.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - infra/onprem/**
  - infra/compose/portable/app.yml
  - tests/unit/helm_platforms/**
  - tests/unit/infra/**
  - docs/deploy/aws.md
  - docs/deploy/gcp.md
  - docs/deploy/onprem.md
  - .github/workflows/onprem-kind-smoke.yml
tier1:
  - infra/helm/**
  - docker-compose.yml
  - Makefile
tier2_appends:
  - mkdocs.yml
must_not_touch:
  - infra/bicep/**
  - infra/demo/**
  - infra/appservice/**
  - infra/terraform/**
  - packages/contracts/**
  - pyproject.toml
  - uv.lock
  - infra/compose/portable/postgres.yml
  - infra/compose/portable/kafka.yml
  - infra/compose/portable/objectstore.yml
  - infra/compose/portable/keycloak.yml
  - infra/compose/portable/secrets.yml
```

## Implementation blueprint

### Item 1 - Goldens and the platform axis
- Deliverable: before touching any template, render and commit goldens for every existing value set to `tests/unit/helm_platforms/goldens/`; add `platform` (default `azure`), the `NS_PLATFORM` render, the guard "government requires azure", and the Azure-only block guards; the golden test compares full output.
- Owned files: `infra/helm/templates/deployment.yaml` (guard and env only), `infra/helm/values.yaml` (new keys), `tests/unit/helm_platforms/{conftest,test_goldens,test_platform_guard}.py`, `tests/unit/infra/test_helm_render.py` (additive cases only).
- Must NOT touch: probes, pools and autoscaling logic from PRP-67 and PRP-84, `values-government.yaml`.
- Depends on: none.
- Acceptance criteria: criteria 1 and 2, plus the Azure-only guard (clarification 12).
- Tests: the byte-identity test must fail when a character of an Azure render changes (prove with a temporary edit in the working tree, then revert).
- Pattern references: `test_helm_render.py` render helpers.

### Item 2 - Per-platform identity and secrets
- Deliverable: `serviceAccount.identity` blocks, projected-token handling, `secretProviderClass.provider` parameterisation (azure unchanged; aws, gcp, vault with provider parameters verified from each provider's documentation at execution, UNVERIFIED in the design), and `secrets.existingSecret`.
- Owned files: `infra/helm/templates/{serviceaccount,secretproviderclass}.yaml`, the identity and mount parts of `deployment.yaml`, `values.yaml` keys, `tests/unit/helm_platforms/test_identity_and_secrets.py`.
- Depends on: item 1.
- Acceptance criteria: criteria 3 and 4.
- Tests: render per platform; assert no Azure annotation or label outside `azure`; assert no `kind: Secret` in any render.

### Item 3 - Backends block, platform values files, outputs overlay
- Deliverable: the `backends.*` block rendered into the settings of PRP-85's registry of platform settings (implemented by PRP-88 to PRP-95), `values-aws.yaml`, `values-gcp.yaml`, `values-onprem.yaml`, matching `ci/values-*.yaml`, per-platform egress notes in `networkPolicy` comments, a generator that maps the PRP-85 platform-outputs document to a values overlay.
- Owned files: `infra/helm/templates/deployment.yaml` (backends env block), `infra/helm/values*.yaml`, `infra/helm/ci/values-{aws,gcp,onprem}.yaml`, `infra/onprem/outputs_to_values.py` (new), tests `tests/unit/helm_platforms/test_backends_and_values.py`.
- Depends on: item 2.
- Acceptance criteria: criteria 5, 6 and 7.
- Tests: lint strict and template for each new values file; a secret-shape scan over rendered output; sample outputs document round trip.
- Pattern references: `values-government.yaml`, the optional env blocks in `deployment.yaml`.

### Item 4 - Portable compose profile  [P]
- Deliverable: `infra/compose/portable/app.yml` and Makefile targets `portable-up` and `portable-down`; the profile runs api, workers and frontend against the existing per-backend fragments; documented port map (127.0.0.1 only).
- Owned files: `infra/compose/portable/app.yml` (new), `Makefile` (additive targets), `docker-compose.yml` only if the verify-first step requires it.
- Must NOT touch: the per-backend fragments, the Azure emulator profiles.
- Depends on: item 3 for names.
- Acceptance criteria: criterion 8; `docker compose config` for the existing profiles unchanged.
- Tests: `tests/unit/compose/` additive case if a pattern exists there (read first); otherwise `tests/unit/helm_platforms/test_portable_compose.py` using `docker compose config`, skipped with a reason when Docker is absent.

### Item 5 - On-prem reference and air-gap bundle  [P]
- Deliverable: `infra/onprem/` operator and chart values (resource sizing as notes, not claims), `images.yaml` with digests resolved at execution, `mirror-images.sh` (target registry argument required, no credential written), offline install notes (chart archive, image mirror, CRDs, ordering), `README.md`.
- Owned files: `infra/onprem/**` (except item 3's generator and item 6's smoke directory).
- Depends on: item 3 for the image set.
- Acceptance criteria: criterion 9.
- Tests: `tests/unit/helm_platforms/test_image_list.py` (every image in the renders for the three non-Azure value sets and in the operator values is listed with a digest; the script refuses empty digests; shell script passes `shellcheck` where installed).

### Item 6 - kind install smoke (opt-in)  [P]
- Deliverable: `infra/onprem/smoke/` script (create cluster, load or pull images, install dependencies and chart, Keycloak sign-in, one ingest-to-catalog check, teardown), Makefile target `kind-smoke`, and the `workflow_dispatch` workflow. Evidence layout under `docs/evidence/` is PRP-98's; this item prints a result file path only.
- Owned files: `infra/onprem/smoke/**`, `.github/workflows/onprem-kind-smoke.yml`, `Makefile` target.
- Depends on: items 3 and 5. It is the only item that needs the compose lane or a local cluster; run it last, alone.
- Acceptance criteria: criterion 10; local run result reported honestly ("ran, passed" or "did not run: reason").
- Tests: static tests of the script's refusals (no cluster context outside `kind-*`, no real kubeconfig use) in `tests/unit/helm_platforms/test_kind_smoke_static.py`.

### Item 7 - Deploy documentation  [P]
- Deliverable: `docs/deploy/{aws,gcp,onprem}.md` (prerequisites, values, install, upgrade, uninstall, what is disabled and why, OPEN list); `mkdocs.yml` nav lines (Tier 2 additive).
- Owned files: the three docs, `mkdocs.yml` (additive).
- Depends on: item 3.
- Acceptance criteria: criterion 11; docs build and nav allowlist tests pass (`tests/docs/test_nav_allowlist.py`).

### Item 8 - Integration and close-out
- Deliverable: rebase, regenerate Tier-3 files, changelog fragment `changelog.d/PRP-96-helm-for-four-platforms-and-on-prem-reference.md`, completion note, list of new `NS_*` and values keys for the operator.
- Owned files: this PRP file, Tier-3 files per reference section 2.
- Depends on: items 1 to 7.
- Acceptance criteria: validation gates pass; CI green including the `helm` job.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q tests/unit/infra tests/unit/helm_platforms tests/unit/government_profile tests/unit/compose tests/docs/test_nav_allowlist.py
helm version --short
helm lint --strict infra/helm -f infra/helm/ci/values-ci.yaml
helm lint --strict infra/helm -f infra/helm/ci/values-aws.yaml
helm lint --strict infra/helm -f infra/helm/ci/values-gcp.yaml
helm lint --strict infra/helm -f infra/helm/ci/values-onprem.yaml
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Local, opt-in, not CI: `make portable-up` and `make kind-smoke` (one compose or cluster session at a time).

## Migration and rollback
No data migration. Existing Azure releases upgrade with unchanged values and render identical manifests (acceptance 1). The new keys default to today's behaviour; rollback is reverting the chart change or not setting `platform`. A release moved between platforms is a new install, not an upgrade; data migration from a Cosmos deployment is OPEN and not scoped.

## Live and open gates
OPEN and operator-only (`NS_LIVE_APPROVED=1`, PRP-64 for installs on real AWS and GCP clusters, PRP-66 for operations sign-off): install on EKS and GKE, install on a customer-like on-prem cluster, an air-gapped install from the offline bundle, KEDA Kafka scaling, Secrets Store CSI provider parameters on AWS and GCP, load at stated targets. The `kind` smoke is local and opt-in; if it did not run, the completion note says so. No availability or compliance claim is made for any platform.

## NOT building
Azure Bicep or AKS cluster IaC; Terraform (PRP-97); conformance matrix, DR and live-gate scripts (PRP-98); a service mesh or ingress controller choice beyond values; an operator for the chart; OpenSearch or Pub/Sub wiring; Government-class boundaries outside Azure; HA tuning claims for PostgreSQL or Kafka.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (D-1 and D-2 were decided by the owner 2026-11-16; rows 4, 6, 7, 9 and 10 are ASSUMPTIONS for plan approval; row 7 depends on owner decisions D-5 and D-8, and D-6 and D-10 in PRP-85 also apply)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | holds the compose lane |
| 7 | todo | | |
| 8 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issue numbers:
- Product check (can an operator use it without editing files):
