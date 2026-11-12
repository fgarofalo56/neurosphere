---
name: PRP-20-government-verification-and-sovereign-deployment
status: active
priority: P1
order: 14
started: 2026-11-12
pr: 97
branch: prp-20-round2
review: required
created: 2026-10-08
model: sonnet
phase: 4
ns: NS-07, NS-08
depends_on: [PRP-08-deployment-intelligence-and-iac, PRP-12-threat-model-and-security-baseline, PRP-13-release-versioning-and-container-publishing]
wave: W7
absorbs: P4.1 + P4.2, G02
orchestrator_model: sonnet
implementer_model: sonnet
---

# PRP-20: Government verification and sovereign deployment

## Goal
Ship the Azure Government deployment profile (parameters, endpoints, audiences, private DNS, egress allowlist), a per-dependency evidence register with a responsibility matrix, static and compose-level tests proving no Commercial endpoint appears in or is reachable from the Government profile, and the gated AKS and App Service profile scripts. It is for the platform owner, the customer security team and the authorizing official, who need dated first-party evidence of what exists where and who is responsible, without any authorization claim. It lands in W7 because it consumes the Bicep and Helm modules (PRP-08), the security baseline (PRP-12) and the release images (PRP-13). **No Government subscription exists (decision D7), so item 4 and the in-cluster half of item 3 are OPEN by construction.** The PRP still ships the profile, the static tests and the evidence register.

> At deployment choose Commercial or Government, approved region(s), AKS enterprise or App Service smaller profile, and Fabric/Synapse/Azure Databricks analytics backend where validated. Show unavailable options disabled with reasons; never route Government telemetry to Commercial to fill a gap. (NS-07)

> NeuroSphere is not FedRAMP authorized and cannot grant an agency ATO. Azure Government, GCC/GCC High and DoD impact levels are not interchangeable. Agency authorizing officials determine ATO; inherited controls do not automatically authorize this application. No certification deadline promise. (NS-08)

> Service availability, feature GA and authorization are distinct verification items. (NS-08)

## Acceptance criteria
- [ ] Item 1: Given the register at `docs/evidence/G02/register.yaml`, When the register test runs, Then every dependency row has a first-party source URL and an ISO date, availability, GA/preview and authorization are separate fields, and no row's authorization field says "authorized". `docs/compliance/responsibility-matrix.md` exists and states "not FedRAMP authorized; the authorizing official decides".
- [ ] Item 2: Given the Government parameters and `infra/helm/values-government.yaml`, When the static test scans them, Then no Azure Commercial endpoint (for example `login.microsoftonline.com`, `*.documents.azure.com`, `*.servicebus.windows.net`, `*.search.windows.net`, `management.azure.com`) appears, and the Government sovereign hosts are used.
- [ ] Item 3: Given the rendered Government network policy and egress allowlist, When the egress test runs offline, Then every Commercial host in the deny corpus is absent from the allowlist; in the egress-blocked compose network the same hosts fail to resolve or connect. The in-cluster proof is recorded OPEN.
- [ ] Item 4: Given no `NS_LIVE_APPROVED=1`, When either profile script is invoked, Then it refuses with a non-zero exit and writes nothing. With approval but no Government subscription configured it also refuses. Both live gates are recorded OPEN.
- [ ] PRP exit: items 1-3 green under `verify-gates -Mode full`; the G02 row text states exactly what remains OPEN; no document or test output claims authorization, ATO or parity.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required; opus | sonnet, review required (D6) |
| 2 | Government subscription | assume one; none | None exists (D7). Items 1, 2 and the static/compose parts of 3 ship. Item 4 and the in-cluster half of item 3 stay OPEN and are never reported as skipped green tests |
| 3 | Live approval | CI; operator | Operator sets `NS_LIVE_APPROVED=1` per run; CI never runs `scripts/gates/*`. A Government run additionally needs an operator-provided Government subscription reference in the environment (variable name only in docs; no value in any file) |
| 4 | Emulators | claim Government behaviour from compose; label | Compose (D8) is used only for the egress-blocked network test. It proves nothing about Government services or authorization |
| 5 | Meaning of "Government" | any sovereign cloud; Azure Government only | The profile targets the Azure Government cloud (usgov endpoints). GCC, GCC High and DoD are separate evidence rows and never aliases; Fabric in GCC High is GA in US Gov Virginia and Texas, GCC and DoD availability is unverified, and the profile claims none of them |
| 6 | Default regions | pick one; list | Parameters expose an allowed-region set drawn from the evidence (usgovvirginia, usgovarizona; usgovtexas flagged Fabric-only because AI Search semantic ranker and agentic retrieval are not in Texas). The customer selects; the PRP does not silently choose (PRD section 4) |
| 7 | Register format | markdown; YAML plus markdown | `docs/evidence/G02/register.yaml` is the source; a generated markdown view is optional. Authorization field enum: `not_verified`, `audit_scope_listed`, `assessment_in_progress`, `customer_determines`. There is no "authorized" value |
| 8 | Rows without existing evidence (Cosmos, Storage, Key Vault, APIM, AKS, App Service, Monitor, Entra) | guess; retrieve | The implementer retrieves first-party pages at implementation time and records the retrieval date. If a feature cannot be verified, the row says `not_verified` with the page checked. No invented availability |
| 9 | Where the static profile test lives | item 3; item 2 | Item 2 owns `tests/unit/government_profile/`; item 3 owns `tests/security/egress/`. Both run offline |
| 10 | Commercial deny corpus | ad hoc; list | A committed list of Commercial host patterns in `tests/security/egress/` (item 3). Item 2's static test carries its own pattern list so ownership stays disjoint |
| 11 | Evidence from live scripts | any path; carve-out | Item 1 owns `docs/evidence/G02/` except files named `profile-aks-*.md` and `profile-appservice-*.md`, which item 4's scripts write at run time |
| 12 | G02 row | no edit; item 1 edits | Item 1 owns the G02 row of `docs/RESEARCH-AND-GATES.md` only. It stays OPEN (the customer's authorizing official owns closure) |
| 13 | Compliance statement | per PRP; shared | Every file under `docs/compliance/` states "not FedRAMP authorized; the authorizing official decides". PRP-23 item 3 enforces it across the directory, so the responsibility matrix must already comply |

## Context manifest

### Files that matter
- `PRP.md` - sections 1-3 (delivery contract, stack and boundaries, contracts first).
- `docs/PRD.md` - NS-07 and NS-08 text, section 4 release gates.
- `docs/ARCHITECTURE.md` - deployment and boundary diagrams.
- `docs/RESEARCH-AND-GATES.md` - findings retrieved 2026-10-06 and 2026-10-08; rows G01, G02, G12.
- `docs/adr/0002-stack-pins.md` - Helm 4.3, Bicep 0.48, azure-ai-projects 2.8 (Government needs 2.0 or later).
- `docs/DECISIONS-LOG.md` - D6, D7, D8.
- `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.claude/hooks/config.ps1`, `.env.example`, `scripts/validate_planning.py`.
- Created by PRP-08: `infra/bicep/modules/`, `infra/bicep/params/government/`, `infra/helm/`, `infra/appservice/`, `infra/scripts/`, `packages/core/neurosphere_core/deploy/`.
- Created by PRP-02: capability matrix under `packages/core/neurosphere_core/capabilities/` (register rows cross-reference matrix row ids).
- Created by PRP-12: `infra/bicep/modules/network/`, `infra/helm/templates/networkpolicy.yaml`, `docs/security/threat-model.md`.
- Created by PRP-13: published image references consumed by the Government Helm values.
- Created by PRP-03: the egress-blocked compose network used by item 3.
- Created by PRP-05: `neurosphere_core.cloud` (Commercial and Government endpoint resolution), `neurosphere_core.errors`.

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`; FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py`; async Azure SDK clients from `packages/core/neurosphere_core/clients`; error taxonomy exceptions from `neurosphere_core.errors` (`capability_unavailable` for disabled options).
- The Government profile resolves `.azure.us` and `.usgovcloudapi.net` hosts through `neurosphere_core.cloud`; tests assert against that resolver where possible rather than hard-coded strings.
- Tests beside packages plus cross-package suites in `tests/`; `pytest.mark.live` and `pytest.mark.integration` markers are declared in root `pyproject.toml`.
- TS strict with `@fluentui/react-components`, Vitest + Testing Library, Playwright under `frontend/tests/e2e` apply to other PRPs; this PRP touches no frontend code.

### Conventions
- ruff config in root pyproject (line 100, py312, S rules on), pyright standard, conventional commits, owned-file discipline.
- Evidence under `docs/evidence/G02/`; live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1`.
- Forward slashes only in commands.

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
- PRP-specific: Fabric in GCC High reached GA on 2026-10-01 in US Gov Virginia and US Gov Texas only; customer-managed keys, workspace identity and Fabric IQ items are unsupported there and the FedRAMP High assessment is in progress. GCC and DoD are unverified. Availability is not authorization.
- PRP-specific: Foundry in Government lists prompt agents, AI Search, MCP servers and function calling; workflows are preview; hosted agents, web search, Bing grounding, Fabric tool and agent-to-agent are unavailable. The general Foundry region page and the Government roadmap conflict with the feature-specific page; record the conflict, do not choose the favorable one.
- PRP-specific: Azure Resource Graph is in the Government audit scope (portal.azure.us, management.usgovcloudapi.net); the PRP-08 scan must use those hosts under the Government profile.
- PRP-specific: Event Hubs data geo-replication is GA on Premium and Dedicated only and Government support is unverified; do not mark it available in a Government profile.
- PRP-specific: "listed in audit scope" is not "authorized for this workload". The register must never convert one into the other, and the responsibility matrix lists NeuroSphere's own controls as customer-assessed.
- PRP-specific: private endpoints need configuration and testing on both sides of Event Hubs geo-DR; the Government private DNS zone list must use Government zone names, not Commercial ones.

### External references
- Fabric in GCC High: https://learn.microsoft.com/fabric/enterprise/us-government-community-cloud-high and https://www.microsoft.com/en-us/microsoft-cloud/blog/us-government/2026/09/02/microsoft-fabric-in-gcc-high-building-the-data-foundation-for-ai/ (retrieved 2026-10-08).
- Azure services in FedRAMP and DoD audit scope (Synapse, Databricks, Resource Graph): https://learn.microsoft.com/azure/azure-government/compliance/azure-services-in-fedramp-auditscope (updated 2026-09-21, retrieved 2026-10-08).
- Azure AI Search regional support: https://learn.microsoft.com/azure/search/search-region-support (observed 2026-10-01).
- Foundry models in Azure Government: https://learn.microsoft.com/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-gov (2026-09-01) and agent features https://learn.microsoft.com/azure/foundry/agents/concepts/azure-government (retrieved 2026-10-06 and 2026-10-08).
- Foundry platform Government page: https://learn.microsoft.com/azure/foundry/concepts/foundry-azure-government (2026-10-06); conflicting sources https://learn.microsoft.com/azure/foundry/reference/region-support and https://learn.microsoft.com/azure/azure-government/documentation-government-product-roadmap (2026-10-06).
- Event Hubs data geo-replication: https://learn.microsoft.com/azure/event-hubs/geo-replication (2026-07-11); metadata geo-DR: https://learn.microsoft.com/azure/event-hubs/event-hubs-geo-dr (2026-10-06).
- Version pins: docs/adr/0002-stack-pins.md (observed 2026-10-08).

## Implementation blueprint

### Item 1 - evidence-register  [P]
- Deliverable: per-dependency register of feature, region, SKU, availability, GA/preview, authorization-boundary status and source (previews and SaaS flagged), plus an inheritance and responsibility matrix (Microsoft, customer, NeuroSphere) and a register validator test.
- Owned files (may edit): `docs/evidence/G02/` (except `profile-aks-*.md` and `profile-appservice-*.md`), `docs/compliance/responsibility-matrix.md`, `docs/RESEARCH-AND-GATES.md` (G02 row only), `tests/unit/evidence_register/`.
- Must NOT touch: `infra/bicep/params/government/`, `infra/helm/values-government.yaml`, `tests/security/egress/`, `scripts/gates/`, other files under `docs/compliance/` (PRP-23), root `pyproject.toml`, `docker-compose.yml`, any other row of `docs/RESEARCH-AND-GATES.md`.
- Depends on: none.
- Acceptance criteria:
  - Every row has `source_url` and `retrieved_on` (ISO date); a row missing either fails the test.
  - Availability, GA/preview and authorization are separate fields; the authorization enum has no "authorized" value (test).
  - Preview and SaaS dependencies are flagged; the Fabric rows reflect GCC High GA in US Gov Virginia and Texas with GCC and DoD `not_verified`.
  - The responsibility matrix states "not FedRAMP authorized; the authorizing official decides".
- Pattern references: capability matrix rows from PRP-02 (link row ids, do not duplicate truth).
- Tests to write: `tests/unit/evidence_register/test_register_schema.py`, `tests/unit/evidence_register/test_matrix_statement.py`.

### Item 2 - government-profile  [P]
- Deliverable: Government parameter files, Helm values, endpoints, audiences, private DNS zones and egress allowlist for the Azure Government cloud.
- Owned files (may edit): `infra/bicep/params/government/` (created by PRP-08, handed off here), `infra/helm/values-government.yaml`, `tests/unit/government_profile/`.
- Must NOT touch: `infra/bicep/modules/` (PRP-08, PRP-12), `infra/bicep/params/commercial/`, `infra/helm/templates/`, `tests/security/egress/`, `docs/evidence/G02/`, root `pyproject.toml`, `docker-compose.yml`.
- Depends on: none.
- Acceptance criteria:
  - Static test: no Azure Commercial endpoint pattern appears in any Government parameter or values file.
  - Parameters use `login.microsoftonline.us`, `*.documents.azure.us`, `*.servicebus.usgovcloudapi.net`, `*.search.azure.us`, `management.usgovcloudapi.net`; audiences are Government-cloud values.
  - Options the matrix marks unavailable (for example Fabric outside Virginia/Texas, Event Hubs data geo-replication) are disabled with a reason in the parameters, not omitted silently.
  - `helm lint` and `helm template` pass with `values-government.yaml`; `az bicep build` passes for the Government parameters' target templates.
- Pattern references: PRP-08 module parameter shape; `capability_unavailable` reasons from PRP-02.
- Tests to write: `tests/unit/government_profile/test_no_commercial_endpoints.py`, `tests/unit/government_profile/test_sovereign_hosts.py`.

### Item 3 - no-commercial-egress-test
- Deliverable: a test suite asserting a Government deployment cannot reach Commercial endpoints: static over rendered network policy and egress allowlist, plus a compose test on the egress-blocked network.
- Owned files (may edit): `tests/security/egress/`.
- Must NOT touch: `infra/helm/values-government.yaml`, `infra/helm/templates/networkpolicy.yaml` (PRP-12), `infra/bicep/`, `docker-compose.yml`, `scripts/gates/`.
- Depends on: Item 2.
- Acceptance criteria:
  - The test fails if any Commercial host pattern in the committed deny corpus is present in the rendered Government egress allowlist or private DNS zone list.
  - In the PRP-03 egress-blocked compose network, name resolution or connection to each corpus host fails (`pytest.mark.integration`).
  - The report labels the result "static and compose only; in-cluster proof OPEN".
- Pattern references: PRP-12 network-policy default-deny design.
- Tests to write: `tests/security/egress/test_allowlist_no_commercial.py`, `tests/security/egress/test_compose_egress_blocked.py`.

### Item 4 - profile-tests  [P]
- Deliverable: gated AKS and App Service profile deploy/smoke scripts with drift and uninstall-safety checks.
- Owned files (may edit): `scripts/gates/g02_profile_aks.py`, `scripts/gates/g02_profile_appservice.py`, `tests/unit/gates/test_g02_profile_refuses.py`.
- Must NOT touch: `scripts/gates/g03_live.py`, `scripts/gates/g01_deploy_smoke.py`, `docs/evidence/G02/register.yaml`, `infra/`, `docs/RESEARCH-AND-GATES.md`.
- Depends on: Item 2.
- Acceptance criteria:
  - Both scripts exit non-zero and write nothing without `NS_LIVE_APPROVED=1` (unit test) and without a configured Government subscription reference.
  - On an approved run, evidence is written to `docs/evidence/G02/profile-aks-<date>.md` and `profile-appservice-<date>.md` with no credential values.
  - The uninstall check shows shared resources untouched (dry-run output asserted).
  - No Government subscription exists today, so this item stays OPEN and is recorded as such.
- Pattern references: `g03_live.py` refusal pattern from PRP-02; `g01_deploy_smoke.py` evidence format from PRP-08.
- Tests to write: `tests/unit/gates/test_g02_profile_refuses.py`.

### Round 2: audit gap closure (items 5-9, added 2026-11-12)
Reopened by the 2026-11-04 audit (section at the end). Rechecked 2026-11-12 against main 8d4fd85:
- Fixed or overstated since the audit:
  - The deploy planner is mounted (`services/api/neurosphere_api/routers.py` `_register_deploy_plan`). Disabled-with-reason at runtime comes from the capability matrix.
  - Tests in `tests/unit/government_profile/test_sovereign_hosts.py` already tie `sovereign-profile.yaml` to the matrix (`test_capability_rows_referenced_exist`) and to `neurosphere_core.cloud` (`test_endpoints_equal_cloud_resolver`). The YAML is the reviewable IaC record, and the matrix is the runtime truth.
- Still open:
  - `DeploymentProfile` (`packages/core/neurosphere_core/capabilities/validate.py:103`) accepts any `usgov*`/`usdod*` region for `cloud=government`. A Government plan for `usdodeast` validates, although the profile claims no DoD support and `allowedRegions` lists only usgovvirginia, usgovarizona and usgovtexas.
  - Audiences. Retrieved 2026-11-12:
    - AI Search Government is `https://search.azure.us` (https://learn.microsoft.com/azure/search/search-security-rbac-client-code). `neurosphere_core/search/azure/client.py` already uses it, but the manifest records null.
    - Event Hubs is `https://eventhubs.azure.net/`, "the same for all clouds and tenants" (https://learn.microsoft.com/azure/event-hubs/authorize-access-azure-active-directory).
    - The Cosmos DB Government data-plane audience is still not stated on any first-party page checked, so it stays `not_verified`.
  - #100: helm and az static checks skip when the tool is absent; the CIDR is not tied to the PE subnet; `GOV_SUFFIX` is loose.
  - #98: the compose egress test can pass vacuously and never runs in CI.
  - #99: teardown can skip the resource-group delete on timeout or parse error.
  - #101: CLI paths flow into evidence paths in the g01 gate scripts.
  - NetworkPolicy is CIDR-only, so hostname egress is not enforced in-cluster.

User decisions 2026-11-12:
- Plan approved as below.
- D7 still holds (no Government subscription). Live profile runs and the in-cluster egress proof stay OPEN.
- Hostname (FQDN) egress enforcement is documented as a customer firewall control and recorded OPEN. No new Bicep.

### Item 5 - gov-region-allowlist  [P]
- Deliverable: for `cloud=government`, `DeploymentProfile` accepts only the evidence-backed region set (usgovvirginia, usgovarizona, usgovtexas). Any other `usgov*` region, and every `usdod*` region, is refused with a reason in the `capability_unavailable` style. DoD is a separate profile, not built here. Commercial validation is unchanged.
- Owned files (may edit):
  - `packages/core/neurosphere_core/capabilities/validate.py` (region validation only)
  - the existing tests of `DeploymentProfile` that use now-refused regions
  - new `tests/unit/government_profile/test_region_parity.py`
- Must NOT touch: `infra/`, `docs/`, `tests/unit/government_profile/test_sovereign_hosts.py`, `test_no_commercial_endpoints.py`, contracts.
- Acceptance criteria:
  - `usdodeast` and `usdodcentral` are refused for Government, with a reason that names the supported set.
  - The parity test asserts that the runtime set equals `allowedRegions` in `sovereign-profile.yaml`.
  - Existing deploy plan and capability tests stay green.

### Item 6 - evidence-and-profile-refresh  [P]
- Deliverable:
  - Record the AI Search Government audience as verified and the Event Hubs audience as cross-cloud (both with source URL and retrieved_on 2026-11-12). Record Cosmos as `not_verified`, with the pages checked.
  - Mirror these in `values-government.yaml`.
  - #100 profile half: tie the `egressAllowlist` CIDR to the network module's private-endpoint subnet, and tighten `GOV_SUFFIX` so arbitrary `*.azure.us` typos fail.
  - Responsibility-matrix row: hostname egress enforcement is a customer control (for example Azure Firewall application rules) and is OPEN.
  - Update the G02 row.
- Owned files (may edit): `infra/bicep/params/government/sovereign-profile.yaml`, `infra/helm/values-government.yaml`, `docs/evidence/G02/register.yaml`, `docs/compliance/responsibility-matrix.md`, `docs/RESEARCH-AND-GATES.md` (G02 row only), `tests/unit/government_profile/test_sovereign_hosts.py` (including its `GOV_SUFFIX`), `tests/unit/evidence_register/`. The second `GOV_SUFFIX` copy, in `tests/security/egress/`, belongs to item 7.
- Must NOT touch: `infra/bicep/modules/`, `infra/helm/templates/`, `tests/security/egress/`, `.github/`, `packages/`.
- Acceptance criteria:
  - The audience test asserts the AI Search value equals the constant in `search/azure/client.py`.
  - No document claims authorization.
  - The static no-Commercial scan still passes. `eventhubs.azure.net` is an audience, not an egress host: it must not enter the egress allowlist, and the scanner must not treat it as a reachable host.

### Item 8 - profile-script-paths (#99)  [P]
- Deliverable:
  - Fake-runner unit tests for the approved path of both scripts: success writes evidence with no credential values, drift is detected, and the uninstall dry-run leaves shared resources untouched.
  - The teardown fix from #99: catch `TimeoutExpired`, `JSONDecodeError` and `KeyboardInterrupt`; make the resource-group delete independent of cleanup; set `release_installed` before `helm upgrade --install`. Document that the AKS cluster must be in the NS_GOV_SUBSCRIPTION_ID subscription.
- Owned files (may edit): `scripts/gates/_g02_profile_common.py`, `scripts/gates/g02_profile_aks.py`, `scripts/gates/g02_profile_appservice.py`, new `tests/unit/gates/test_g02_profile_paths.py`.
- Must NOT touch: other `scripts/gates/*`, `tests/unit/gates/test_g02_profile_refuses.py` (it must stay green unchanged), `docs/`.
- Acceptance criteria:
  - The tests never invoke real az, helm or kubectl.
  - A timeout in cleanup still issues the group delete.
  - The refusal tests are unchanged and green.

### Item 9 - g01-path-confinement (#101)  [P]
- Deliverable: CLI-supplied output paths in `g01_analytics_live.py` and `g01_deploy_smoke.py` resolve inside the evidence directory (`resolve()` + `is_relative_to`), or the script refuses. Test fixtures that look like secrets are generated per run.
- Owned files (may edit): `scripts/gates/g01_analytics_live.py`, `scripts/gates/g01_deploy_smoke.py`, `tests/unit/gates/test_g01_*.py`.
- Must NOT touch: `scripts/gates/g02_*`, `scripts/gates/_g02_profile_common.py`, `docs/`.
- Acceptance criteria:
  - A traversal path (`../x`) is refused, and the test asserts that.
  - The Snyk Code scan of the touched files shows no new findings.

### Item 7 - egress-tests-in-ci (#100 CI half, #98) (depends on item 6)
- Deliverable:
  - Under `CI`, a missing helm or az fails instead of skipping. The rendered helm output is asserted non-empty. Tighten the `GOV_SUFFIX` copy in `tests/security/egress/test_allowlist_no_commercial.py`.
  - #98: the compose egress per-host test requires a session-scoped positive-control fixture. An exec failure is distinguished from a blocked connection, and DNS resolution failure is asserted.
  - A CI job installs helm 4 and the az bicep CLI and runs `tests/unit/government_profile`, `tests/unit/infra` and `tests/security/egress -m "not integration"`.
  - A separate CI job runs `-m integration tests/security/egress` against compose (the egress probe only, if feasible).
- Owned files (may edit): `.github/workflows/ci.yml`, `tests/security/egress/`, the skip sites in `tests/unit/government_profile/test_no_commercial_endpoints.py`, `tests/unit/government_profile/test_sovereign_hosts.py` and `tests/unit/infra/test_helm_render.py`.
- Must NOT touch: `infra/`, `docker-compose.yml`, `packages/`, `scripts/`.
- Acceptance criteria:
  - Locally without helm, the tests still skip. With `CI=true` and no helm, they fail.
  - Both new CI jobs are green on the PR.
  - The egress report still reads "static and compose only; in-cluster proof OPEN".

### Round 2 waves
- Wave A: items 5, 6, 8, 9 in parallel (WIP 4).
- Wave B: item 7, after item 6 merges.
- Merge order: 6, 5, 8, 9, 7. Every item gets one review pass (PRP `review: required`).

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
python -m pytest tests/unit/evidence_register tests/unit/government_profile tests/unit/gates/test_g02_profile_refuses.py
python -m pytest tests/security/egress -m "not integration"
docker compose up -d --wait
python -m pytest -m integration tests/security/egress
helm lint infra/helm -f infra/helm/values-government.yaml
helm template neurosphere infra/helm -f infra/helm/values-government.yaml
NS_LIVE_APPROVED=1 python scripts/gates/g02_profile_aks.py    # operator-approved, requires NS_LIVE_APPROVED=1 and a Government subscription; OPEN today
NS_LIVE_APPROVED=1 python scripts/gates/g02_profile_appservice.py    # operator-approved, requires NS_LIVE_APPROVED=1 and a Government subscription; OPEN today
```

## Live and open gates
- G02 (FedRAMP/DoD boundary and agency ATO): stays OPEN. Item 1 narrows the evidence side (dated, per-dependency, separate availability and authorization columns). Closure belongs to the customer's authorizing official; nothing here can close it.
- G01 (service/feature/region/SKU matrix): the register feeds Government rows; Fabric Government is recorded as "GCC High GA in Virginia and Texas; GCC and DoD unverified". No integration evidence exists, so G01 stays OPEN.
- G12 (emulator parity): item 3 records that compose network tests do not reproduce a Government cluster.
- Item 4 and the in-cluster half of item 3 need a Government subscription that does not exist (D7). Record both OPEN in the completion note and in the G02 row.
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Any FedRAMP, DoD IL or ATO claim, certification deadline, or parity statement between Commercial and Government.
- SSP narratives, POA&M, boundary and contingency plans (PRP-23); the threat model (PRP-12).
- Bicep modules and Helm templates themselves (PRP-08, PRP-12); this PRP supplies parameters, values and tests.
- GCC and DoD profiles; classified or air-gapped deployment (outside the baseline).
- A live Government deployment, or any bridge of Government data to Commercial to fill a gap.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Plan deltas (approved 2026-10-22)
- Item 2: `modules/main.bicep` has no endpoint parameters and item 2 may not edit modules, so `main.bicepparam` keeps deriving hosts from `environment()`. Item 2 additionally owns `infra/bicep/params/government/sovereign-profile.yaml`: the host-level manifest (endpoints, audiences, Government private DNS zone names, egress host allowlist, allowed regions, disabled-with-reason options). `values-government.yaml` carries `env.NS_CLOUD=government`, CIDR egress entries and a mirrored `sovereignProfile` block. Tests assert against `neurosphere_core.cloud`.
- Item 3: NetworkPolicy is CIDR-only (PRP-12), so the static test scans the full `helm template` output, the manifest host allowlist and DNS zone list, and the `az bicep build-params` output of the Government parameters.
- Item 4 runs in wave A with items 1 and 2 (it references fixed paths only). Item 3 waits for item 2. Merge order 2, 1, 4, 3.
- Item 2 ownership extended (user-approved 2026-10-22) to the two PRP-08 handoff markers in `tests/unit/infra/test_helm_render.py`: `test_extension_points_left_to_later_prps` now asserts `values-government.yaml` exists, and `test_no_literal_azure_endpoints` excludes that one file (covered by `tests/unit/government_profile/`).

## Completion note (filled at ship)
- Date: 2026-10-22
- Merged commits: PR #97 (merge e00d606). Item 2: 34d2deb, c5b567c, 3ddde6d (merge f2d2aaf). Item 1: 2e84afa (merge 8f5435e). Item 4: b6b79a3 (merge 083d5d2). Item 3: de8c5cc (merge 4990f12). Local `verify-gates -Mode full` PASS (lint, typecheck, 6709 tests, build); CI on PR #97 all green.
- Deviations from blueprint and why:
  - Item 2: `modules/main.bicep` has no endpoint parameters, so `main.bicepparam` still derives hosts from `environment()`. The host-level truth lives in the new `infra/bicep/params/government/sovereign-profile.yaml`, mirrored in `values-government.yaml` under `sovereignProfile`.
  - Item 2 ownership was extended (user-approved) to flip the two PRP-08 handoff markers in `tests/unit/infra/test_helm_render.py`. The orchestrator corrected three audience source citations (commit 3ddde6d).
  - Item 3: NetworkPolicy is CIDR-only, so the static test scans the full `helm template` output, the manifest hosts and DNS zones, and the compiled Bicep params (skipping `$schema`). It also asserts default-deny and RFC1918-only `ipBlock`s.
  - Item 4 ran in wave A rather than after item 2, because it references fixed paths only. It adds a shared `_g02_profile_common.py`. It requires an existing operator AKS cluster (main.bicep creates none). It uses its own run-id-tag dry-run uninstall guard instead of `infra/scripts/uninstall.py`, which is ownership-register based.
  - Item 1: the Foundry agent features (prompt agents, AI Search tool, MCP servers, function calling) are recorded `not_verified` with the source conflict noted, instead of available.
- Descoped items: none.
- Live gates (G02 profile AKS / App Service): OPEN. There is no Government subscription (D7), and neither script was run with approval.
- Also OPEN:
  - The in-cluster half of the item 3 egress proof. The compose half passed 41/41 locally only, because the `integration` marker does not run in CI.
  - G02 agency ATO, which belongs to the customer's authorizing official.
  - The Government data-plane audiences for Cosmos DB, AI Search and Event Hubs. No first-party page checked states them.
  - Fabric availability in GCC and DoD.
  - G01 Government integration evidence.
- Follow-ups: #98 (compose egress positive-control dependency), #99 (G02 profile teardown robustness), #100 (fail rather than skip when helm is absent in CI; CIDR and GOV_SUFFIX tightening), #101 (pre-existing Snyk low findings in the g01 gate scripts).

## Execution state

| Item | Status | Branch | Model | Evidence | Updated |
|------|--------|--------|-------|----------|---------|
| 1 | merged | worktree-agent-a4650021553086e92 | sonnet | 2e84afa, merge 8f5435e; verify ruff/format/pyright clean, evidence_register 44/44, validate_planning PASS, RESEARCH-AND-GATES diff = G02 row only; post-merge 44/44; review APPROVED (3 follow-ups) | 2026-10-22 |
| 2 | merged | worktree-agent-ad2f171f638730ee5 | sonnet | 34d2deb + c5b567c (handoff-marker flip) + 3ddde6d (audience provenance fix), merge f2d2aaf; verify government_profile+infra+network 92/92, helm lint/template ok, bicep build-params ok; post-merge 92/92; review APPROVED (4 follow-ups) | 2026-10-22 |
| 3 | merged | worktree-agent-af3ed6e509f2e314f | sonnet | de8c5cc, merge 4990f12; verify ruff/format/pyright clean, static 57/57, compose integration 41/41 (fresh stack, local only; integration marker does not run in CI); post-merge touched suites 313 passed; snyk 0; review APPROVED (4 follow-ups). In-cluster proof OPEN | 2026-10-22 |
| 4 | merged | worktree-agent-a2d5b5afaff30879b | sonnet | b6b79a3, merge 083d5d2; verify ruff/format/pyright clean, gates 144/144, both scripts refuse exit 2 "OPEN", docs/ untouched; post-merge 144/144; review APPROVED (4 follow-ups) | 2026-10-22 |
| 5 | merged | worktree-agent-af900dd58ab8e81c1 | sonnet | 67ab6e4, merge 5a12345; verify ruff/pyright clean, import-grep suites 172 passed; post-merge touched 232 passed + every usdod-mentioning test 189 passed; review APPROVED (4 follow-ups: copilot gating uncaught ValueError, analytics registry generic reason, UI/mock usdod prefixes, workers deploy test) | 2026-11-12 |
| 6 | merged | worktree-agent-a8302abde93efff18 | sonnet | 6e94eb6, merge fb36944; verify government_profile+evidence_register+infra+egress(non-integration) 205 passed, helm lint/template ok (agent), check_statements PASS, RESEARCH-AND-GATES diff = G02 row only; post-merge 205 passed; review APPROVED (2 follow-ups) | 2026-11-12 |
| 7 | in-progress | worktree (implementer) | sonnet | dispatched after item 6 merge | 2026-11-12 |
| 8 | merged | worktree-agent-af3ae03bb05de1884 | sonnet | c023444, merge 7d690e7; verify ruff/pyright clean, tests/unit/gates 376 passed, refusal tests unchanged, snyk 0 in g02 files; post-merge 376 passed; review APPROVED (3 follow-ups) | 2026-11-12 |
| 9 | merged | worktree-agent-a75575acb0d33361c | sonnet | 285c904, merge 6d01ae3; verify ruff/pyright clean, gates+hosted_demo 421 passed, snyk tests 0; snyk scripts still reports PT lows (reviewer traced every sink: confinement real, Snyk does not model is_relative_to); post-merge 439 passed; review APPROVED (3 follow-ups) | 2026-11-12 |

## Audit 2026-11-04

Reopened after a deep audit (static read by a read-only agent; no tests were run). Gaps, with evidence:

- `infra/bicep/params/government/sovereign-profile.yaml` (disabledOptions ~line 140, allowedRegions, egressHosts) is read by no running code: only tests, the Helm values mirror, comments and docs reference it. Disabled-with-reason at runtime comes from the capability matrix via the deploy planner (`planner.py` `_disabled_item`), whose router mounting was not confirmed in `app.py`.
- No live Government evidence: `docs/evidence/G02/` holds only `register.yaml`; G01 has Commercial smoke files only. Several audiences recorded null/unverified (Cosmos, AI Search, Event Hubs).
- Egress proof is partial: `tests/security/egress/test_compose_egress_blocked.py` is `integration` and not run in CI; Helm/az-bicep static tests `pytest.skip` when the tool is absent (follow-up #100); the NetworkPolicy is CIDR-only so the host allowlist is not enforced per FQDN. Bicep only refuses APIM v2 SKUs in Government (`main.bicep:48`).
- Profile scripts (`g02_profile_aks.py`, `g02_profile_appservice.py`) are tested for refusal only; success, drift and uninstall paths never run live.
