---
name: prp-08-deployment-intelligence-and-iac
status: backlog
review: required
created: 2026-10-08
model: sonnet
phase: 1
ns: NS-07
depends_on: PRP-02, PRP-05
wave: W4
absorbs: P1.4 reuse/IaC
---

# PRP-08: Deployment intelligence and IaC

## Goal
Ship the deployment path for a customer-hosted NeuroSphere: per-cloud Bicep modules (Commercial and Government parameter sets), a Helm 4 chart for AKS, an App Service profile, a consented and visibility-limited Azure Resource Graph scan, a reuse/create/skip planner, an ownership register with a safe uninstall, and a Fabric provisioning adapter that uses the Fabric REST APIs. It is for platform owners who must decide what to reuse versus create without NeuroSphere ever touching shared enterprise resources. It lands now (wave W4) because PRP-02 supplies the capability matrix that decides which options are enabled, and PRP-05 supplies the API runtime the scan and planner routers mount into.

> At deployment choose Commercial or Government, approved region(s), AKS enterprise or App Service smaller profile, and Fabric/Synapse/Azure Databricks analytics backend where validated. Show unavailable options disabled with reasons; never route Government telemetry to Commercial to fill a gap.

> Read-only, consented Azure Resource Graph scan across authorized subscriptions and Graph/Foundry discovery where needed identifies APIM, model endpoints, Key Vault, monitoring, Event Hubs, storage and analytics workspaces. Tenant scope alone does not grant subscription visibility. Validate SKU, network reachability, quotas, capacity, permissions, residency, lifecycle and enterprise owner consent before reuse.

> Show reuse/create/skip and plan/cost implications; seek confirmation for shared services rather than always creating them. Provision missing approved services with idempotent IaC after plan approval. Never modify/delete shared resources on uninstall; record ownership and dependencies. Fabric capacity/workspace lifecycle uses its supported APIs, not assumed ARM-only provisioning.

## Acceptance criteria
- [ ] Item 1: `az bicep build` succeeds for every module and what-if lint runs in CI for both param sets; a static test finds no hardcoded `.com` Azure endpoint in modules or params.
- [ ] Item 2: `helm lint` and `helm template` pass on Helm 4; AKS and App Service profiles resolve the same image references.
- [ ] Item 3: Given a caller authorized for subscriptions A and B and a tenant containing C, When the scan runs (mock Resource Graph), Then results contain only A and B and the response labels itself visibility-limited.
- [ ] Item 4: Given a discovered shared service without the owner-consent flag, When a plan is built, Then that resource is marked `needs_consent` and not `reuse`; plan JSON validates against `DeploymentManifest`.
- [ ] Item 5: Uninstall dry-run lists shared and reused resources as untouched and only NeuroSphere-created resources as removable.
- [ ] Item 6: Given the matrix says Fabric is unavailable for the selected cloud/region, When the adapter is asked to provision, Then it returns `capability_unavailable` with the reason and calls nothing.
- [ ] Item 7: `scripts/gates/g01_deploy_smoke.py` exits non-zero without `NS_LIVE_APPROVED=1`; with approval it deploys to the Commercial subscription and writes an evidence manifest.
- [ ] PRP exit: items 1-6 green under `verify-gates -Mode full`; item 7 either evidenced or recorded OPEN; `python scripts/validate_planning.py` has no failures attributable to this file.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required; opus | sonnet, review required (D6; master table). One review pass, approve unless blocking |
| 2 | Is live deployment allowed? | live in CI; operator-approved script only; never | Operator-approved only (D7): `scripts/gates/g01_deploy_smoke.py` with `NS_LIVE_APPROVED=1`, Commercial subscription only |
| 3 | Government deployment | build and test live; params and static tests only | Params and static tests only; no Government subscription exists, so Government live evidence stays OPEN (G01, G02) |
| 4 | Local test substrate | live ARG/ARM; mocks and emulators | Mocked Resource Graph and ARM clients in tests; Compose emulators from `docker-compose.yml` for anything stateful (D8) |
| 5 | Terraform | second implementation; none | None. Bicep is the only IaC (PRP.md section 2) |
| 6 | Chart tooling | Helm 3; Helm 4 | Helm 4 (ADR-0002). Helm 3 security fixes end 2027-02-10 |
| 7 | How are per-cloud endpoints expressed? | literals; cloud profile parameters | Parameters per cloud (`params/commercial/`, `params/government/`) using `environment()` suffixes in Bicep; no literal `.com` Azure endpoint anywhere |
| 8 | Fabric provisioning mechanism | ARM only; Fabric REST | Fabric REST for capacity and workspace lifecycle plus ARM only where the capacity resource itself is an ARM resource; adapter is stub-tested, live is out of scope here |
| 9 | Scan scope | tenant-wide; per authorized subscription | Per subscription the caller token can read; zero results from an unauthorized subscription are reported as "not visible", never as "empty" |
| 10 | Consent record storage | audit only; own collection | Consent record is a document in the ownership register plus an audit event via the PRP-06 audit interface (if PRP-06 has not merged, a protocol stub in `neurosphere_core.deploy.register`) |
| 11 | Cost implications in the plan | live pricing call; static estimate | Estimate fields come from a versioned price table input and are labelled `estimated`; no paid or live pricing call in tests, unknown stays `unknown` never 0 |
| 12 | Uninstall of reused resources | delete if empty; never delete | Never delete, never modify. Only resources recorded `created_by=neurosphere` with no foreign dependents are removable |

## Context manifest

### Files that matter
- `PRP.md` - binding preamble sections 1-3 (Bicep primary IaC, Helm 4, Fabric needs a separate adapter).
- `docs/PRD.md` - NS-07 text; NS-08 for managed identity and private networking.
- `docs/ARCHITECTURE.md` - deployment topology and cloud boundary diagrams.
- `docs/RESEARCH-AND-GATES.md` - G01 row and the Fabric GCC High, Resource Graph, Synapse/Databricks findings.
- `docs/adr/0002-stack-pins.md` - Bicep 0.48, Azure CLI 2.91, Helm 4.3, pnpm/Node pins.
- `docs/DECISIONS-LOG.md` - D6, D7, D8, D9.
- `pyproject.toml` - ruff, pyright and pytest markers (`live`, `integration`).
- `docker-compose.yml` and `infra/compose/eventhubs.config.json` - emulator stack the integration tests use.
- `.claude/hooks/config.ps1` - gate configuration read by verify-gates.
- `.env.example` - names of variables only; never read `.env`.
- `scripts/validate_planning.py` - planning validator.
- Created by PRP-02: `packages/core/neurosphere_core/capabilities/` (matrix and `validate_profile()`), `scripts/gates/` conventions.
- Created by PRP-01: `packages/contracts/schemas/deployment/` (`DeploymentManifest`, `CapabilityMatrixEntry`) and generated Python models.
- Created by PRP-05: `neurosphere_core.errors`, `.../cloud/` (Commercial/Government endpoint suffixes), `.../clients/`, `services/api/neurosphere_api/app.py` router registry.
- Created by PRP-06 (soft): audit interface; do not block on it.

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")` for scan results, plan items, register rows.
- One FastAPI router per module: `services/api/neurosphere_api/deploy/scan/router.py` and `.../deploy/plan/router.py`.
- Async Azure SDK clients only via `packages/core/neurosphere_core/clients`; never construct credentials inline.
- Errors raised from `neurosphere_core.errors` (`capability_unavailable`, `forbidden`, `dependency_transient`).
- Tests beside packages; cross-package suites in `tests/`; `pytest.mark.integration` for emulator tests, `pytest.mark.live` for anything touching a real subscription.
- Bicep: one module per resource family, parameters typed and `@description`-annotated, outputs never contain secrets.

### Conventions
- ruff line length 100, py312, S rules on; pyright standard; conventional commits; each item edits only its owned files.
- Evidence under `docs/evidence/G01/`; live scripts under `scripts/gates/` refuse to run without `NS_LIVE_APPROVED=1`.
- Forward slashes in every command.

### Gotchas
- Event Hubs has no DLQ: quarantine is an explicit container + replay CLI; checkpoints advance only after durable accept or quarantine. Metadata geo-DR copies neither payloads nor RBAC.
- `IdentityScope` is derived server-side; caller- or model-supplied `domain_id`/`customer_id` is ignored. Same scope object on REST, search, cache keys, exports, WebSocket, copilot tools, MCP.
- No LLM-generated SQL/Cypher/KQL/JS. Charts are a Vega-Lite subset (no `expr`, signals, external `url` data) rendered with `vega-interpreter` in a sandboxed iframe.
- Government is gated, not banned: disabled-with-reason from the capability matrix; separate endpoints (`login.microsoftonline.us`, `*.documents.azure.us`, `*.servicebus.usgovcloudapi.net`, `*.search.azure.us`). Never route Government data to Commercial.
- Fail closed: policy store outage returns 503. Privileged roles are scoped; no bypass.
- One action executor for button/chat/REST/MCP; same intent hash; permission and target version rechecked at execution; read-only connectors are advisory; no catalog-only pretend swaps.
- Costs: null/unknown never 0; estimated vs invoiced always distinct; projections cite price version. Provider billing freshness is not sub-10s.
- Catalog: raw events outside the graph; locks affect presented lineage not observations; traversals budgeted; ETag mismatch returns `stale_version`. Outbox is the projection baseline, not emulator change feed.
- Emulators: Event Hubs emulator lacks Entra, so producer identity is enforced at the ingest edge; Cosmos vNext emulator has no RU accounting, no sprocs/triggers/UDF, no range/composite/spatial indexes, so G03 emulator evidence is "bounded feasibility" only.
- `scripts/gates/*` refuse without `NS_LIVE_APPROVED=1`; missing live evidence is an open gate, never a skipped green test. No paid model calls in CI.
- No FedRAMP/ATO/parity claims. Availability, GA and authorization are separate matrix columns.
- Secrets via vault references; dev issuer only when `NS_ENV=local`; never read `.env`. Pseudonymize people; prompt/response bodies off by default; redact before archive and before any external transmission (judges, connectors).
- Hidden navigation is not authorization; the API must deny.
- Versions: Python 3.12, Node 24, TypeScript 6.0.x (not 7), Helm 4, MkDocs Material 9.7 (EOL 2026-11-05, evaluate Zensical), sigma 4 + graphology (never @cosmograph, CC-BY-NC), MCP SDK 2.x (spec 2026-07-28). See docs/adr/0002-stack-pins.md.
- CI contains no `|| true`; `scripts/validate_planning.py` fails if it does. Python is `python`, not `python3`.
- PRP-specific: Azure Resource Graph returns only what the caller's identity can read. Tenant root scope does not grant subscription visibility; a missing subscription is "not visible", not "absent".
- PRP-specific: Fabric capacity and workspace lifecycle use Fabric REST. Do not model a Fabric workspace as an ARM resource. Fabric in GCC High is GA only in US Gov Virginia and US Gov Texas; GCC and DoD are unverified.
- PRP-specific: Government Bicep parameters use Government suffixes (`login.microsoftonline.us`, `management.usgovcloudapi.net`). A Commercial default that "also works" in Government is a defect.
- PRP-specific: `what-if` needs a subscription; CI runs `az bicep build` and lint offline, and runs what-if only in the operator-approved live script.
- PRP-specific: uninstall must be incapable of deleting a resource whose register row says `reused` or `shared`; enforce in code, not by convention.

### External references
- Azure Resource Graph overview and scope behavior: https://learn.microsoft.com/azure/governance/resource-graph/overview (Government audit scope observed 2026-09-21 via https://learn.microsoft.com/azure/azure-government/compliance/azure-services-in-fedramp-auditscope).
- Fabric in GCC High (GA 2026-10-01, US Gov Virginia and Texas): https://learn.microsoft.com/fabric/enterprise/us-government-community-cloud-high (observed 2026-10-08).
- Helm 3 end of life and Helm 4: https://helm.sh/blog/helm-v3-end-of-life/ (observed 2026-10-08).
- Bicep releases: https://github.com/Azure/bicep/releases (pin 0.48, observed 2026-10-08).
- Event Hubs geo-DR caveat: https://learn.microsoft.com/azure/event-hubs/event-hubs-geo-dr (retrieved 2026-10-06).
- Foundry in Azure Government: https://learn.microsoft.com/azure/foundry/agents/concepts/azure-government (retrieved 2026-10-06).

## Implementation blueprint

### Item 1 - bicep-core-modules  [P]
- Deliverable: Bicep modules for Cosmos, Event Hubs, Storage, Key Vault, AI Search, Log Analytics and APIM reuse-or-create, each with a `reuse` input that skips creation and returns the existing resource id; per-cloud parameter files.
- Owned files (may edit): `infra/bicep/modules/`, `infra/bicep/params/commercial/`, `infra/bicep/params/government/`.
- Must NOT touch: `infra/helm/`, `infra/appservice/`, `infra/scripts/`, `infra/bicep/modules/network/` (PRP-12), `infra/bicep/params/government/` additions by PRP-20 after merge, `pyproject.toml` root, `docker-compose.yml`, `docs/RESEARCH-AND-GATES.md`.
- Depends on: none.
- Acceptance criteria:
  - `az bicep build` passes for every module; what-if lint step is wired in CI for both param sets without `|| true`.
  - Static test: no literal `.com` Azure endpoint in modules or params; Government params use Government suffixes.
  - A `reuse` input of an existing resource id produces no resource declaration in the what-if plan for that service.
- Pattern references: Bicep rules and Conventions above; cloud suffixes from PRP-05 `cloud/`.
- Tests to write: `tests/unit/infra/test_bicep_endpoints.py`, `tests/unit/infra/test_bicep_build.py`.

### Item 2 - aks-helm-and-appservice  [P]
- Deliverable: Helm 4 chart for api, workers and frontend (values for both clouds delegated to later PRPs); App Service profile Bicep running the same stateless api/workers images.
- Owned files (may edit): `infra/helm/`, `infra/appservice/`.
- Must NOT touch: `infra/bicep/`, `infra/helm/templates/networkpolicy.yaml` (PRP-12) and `infra/helm/values-government.yaml` (PRP-20) beyond leaving the extension points, `infra/scripts/`, root `pyproject.toml`, `docker-compose.yml`.
- Depends on: none.
- Acceptance criteria:
  - `helm lint infra/helm` and `helm template` pass on Helm 4.
  - Image repository and tag come from one values key shared by the AKS chart and the App Service profile.
  - No secret literal in values; credentials are vault references.
- Pattern references: Conventions; ADR-0002 Helm row.
- Tests to write: `tests/unit/infra/test_helm_render.py`.

### Item 3 - resource-scan  [P]
- Deliverable: consented scan service using Azure Resource Graph via `neurosphere_core.clients`, returning discovered APIM, model endpoints, Key Vault, monitoring, Event Hubs, storage and analytics workspaces, per authorized subscription, with a visibility-limited label.
- Owned files (may edit): `services/api/neurosphere_api/deploy/scan/`.
- Must NOT touch: `services/api/neurosphere_api/deploy/plan/`, `packages/core/neurosphere_core/deploy/`, `services/api/neurosphere_api/app.py`, root `pyproject.toml`.
- Depends on: none.
- Acceptance criteria:
  - Mock ARG tests show only caller-authorized subscriptions appear; unauthorized ones are reported "not visible".
  - Scan refuses to start without a recorded consent flag in the request context (403 via `forbidden`).
  - Read-only: no ARM write call exists in the module (static test greps for write verbs).
- Pattern references: FastAPI router per module; async clients; `forbidden` error.
- Tests to write: `services/api/tests/deploy/test_scan.py`.

### Item 4 - reuse-planner
- Deliverable: planner that validates SKU, network reachability, quota, permission, residency and lifecycle for each discovered service and emits a reuse/create/skip plan with estimated cost implications and a consent record.
- Owned files (may edit): `services/api/neurosphere_api/deploy/plan/`.
- Must NOT touch: `services/api/neurosphere_api/deploy/scan/`, `packages/core/neurosphere_core/deploy/register/`, `packages/core/neurosphere_core/deploy/fabric/`, `infra/`.
- Depends on: Item 3.
- Acceptance criteria:
  - Reuse of a shared service requires the owner-consent flag; otherwise item is `needs_consent`.
  - Plan JSON validates against the PRP-01 `DeploymentManifest` schema.
  - Options the capability matrix marks unavailable appear in the plan as disabled with reason; cost fields are `estimated` or `unknown`, never 0.
- Pattern references: `capabilities.validate_profile()` from PRP-02; Pydantic forbid-extra.
- Tests to write: `services/api/tests/deploy/test_plan.py`.

### Item 5 - ownership-register-and-uninstall
- Deliverable: ownership and dependency register (library) and an uninstall script that removes only NeuroSphere-created, dependent-free resources and supports `--dry-run`.
- Owned files (may edit): `infra/scripts/`, `packages/core/neurosphere_core/deploy/register/`.
- Must NOT touch: `services/api/neurosphere_api/deploy/`, `infra/bicep/`, `infra/helm/`, `packages/core/neurosphere_core/deploy/fabric/`.
- Depends on: Item 4.
- Acceptance criteria:
  - Dry-run output lists every `reused`/`shared` resource as untouched.
  - Code path to delete a `reused`/`shared` row does not exist (test asserts the guard raises).
  - Register rows record owner, consent reference, dependents and creating plan id.
- Pattern references: Pydantic forbid-extra; errors taxonomy.
- Tests to write: `packages/core/tests/deploy/test_register.py`, `tests/integration/deploy/test_uninstall_dry_run.py`.

### Item 6 - fabric-provisioning-adapter  [P]
- Deliverable: adapter for Fabric capacity and workspace lifecycle through Fabric REST, behind a protocol so it can be stub-tested; consults the capability matrix before acting.
- Owned files (may edit): `packages/core/neurosphere_core/deploy/fabric/`.
- Must NOT touch: `packages/core/neurosphere_core/deploy/register/`, `packages/core/neurosphere_core/capabilities/`, `services/api/neurosphere_api/deploy/`.
- Depends on: none.
- Acceptance criteria:
  - Matrix says unavailable: returns `capability_unavailable` with the matrix reason and performs zero HTTP calls (stub asserts).
  - No ARM-only code path creates a workspace.
  - Government profile uses the Government Fabric endpoint set and never a Commercial host.
- Pattern references: `cloud/` profile; async clients; errors taxonomy.
- Tests to write: `packages/core/tests/deploy/test_fabric_adapter.py`.

### Item 7 - live-smoke (operator approved)
- Deliverable: Commercial deploy smoke script that applies the Bicep modules to an approved resource group, checks health, writes an evidence manifest, and tears down only what it created.
- Owned files (may edit): `scripts/gates/g01_deploy_smoke.py`, `docs/evidence/G01/`.
- Must NOT touch: `docs/RESEARCH-AND-GATES.md` (the completion note records G01 status; the master index owner updates the register), `infra/`, root `pyproject.toml`.
- Depends on: Items 1-5.
- Acceptance criteria:
  - Exits non-zero with a clear message when `NS_LIVE_APPROVED` is unset.
  - With approval: evidence file lists resources created, what-if summary and teardown result.
  - No credential value appears in the evidence file (grep test).
- Pattern references: `scripts/gates/` conventions from PRP-02.
- Tests to write: `tests/unit/gates/test_g01_refuses_without_approval.py`.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
az bicep build --file infra/bicep/modules/main.bicep
helm lint infra/helm
helm template neurosphere infra/helm
docker compose up -d --wait
python -m pytest -m integration tests/integration/deploy
python -m pytest services/api/tests/deploy packages/core/tests/deploy tests/unit/infra
NS_LIVE_APPROVED=1 python scripts/gates/g01_deploy_smoke.py    # operator-approved, requires NS_LIVE_APPROVED=1
```

## Live and open gates
- G01 (service/feature/region/SKU matrix): item 7 supplies Commercial integration evidence under `docs/evidence/G01/`. Narrows G01 for Commercial only; Government Fabric, Synapse, Databricks and Search profiles stay OPEN.
- G02 (FedRAMP/DoD boundary): touched only by the Government parameter set; no evidence is produced here, remains OPEN (owned by PRP-20).
- G12 (emulator parity): record in the completion note which behaviors the mocked Resource Graph and emulators cannot reproduce (real subscription visibility, quota APIs, Entra RBAC).
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Government live deployment or any Government subscription work (PRP-20; no subscription exists).
- Network policy, private endpoints, default-deny egress (PRP-12 owns `infra/bicep/modules/network/` and `networkpolicy.yaml`).
- Dockerfiles, image publishing, cosign, chart packaging (PRP-13).
- DR and backup scripts (PRP-21).
- Terraform, Neo4j hosting, AWS/GCP/on-prem hosting.
- Analytics query adapters (PRP-11); this PRP only provisions Fabric capacity/workspace.
- Deployment wizard UI (not in the decomposition; planner is API-only here).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Completion note (filled at ship)
- Date:
- Merged commits:
- Deviations from blueprint and why:
- Descoped items:
- Live items run or OPEN (G01, G02, G12):
- Follow-ups:
