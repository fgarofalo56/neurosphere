---
name: prp-12-threat-model-and-security-baseline
status: backlog
review: required
created: 2026-10-08
model: opus
phase: 1
ns: NS-08
depends_on: PRP-05, PRP-06, PRP-08
wave: W5
absorbs: new
---

# PRP-12: Threat model and security baseline

## Goal
Ship the security foundations that NS-08 says are "foundational, not final-phase additions": a STRIDE threat model per trust boundary of the component flow in `docs/ARCHITECTURE.md` section 1, supply-chain scanning (SBOM plus image scanning) in its own workflow, default-deny network policy in Bicep and Helm, a shared prompt-injection and overscope test corpus that PRP-19 (copilot) and PRP-22 (MCP) must pass, and secrets/rotation/incident-response runbooks. Audience: security reviewers, the PRP-20/PRP-23 compliance work that cites this model, and every implementer who needs a deny-by-default test target. It lands in wave W5 because the identity layer (PRP-06), runtime (PRP-05) and IaC (PRP-08) now exist to be threatened and hardened; later PRPs consume the corpus and the network modules.

> NS-08: "Private networking/default-deny egress, approved endpoints, threat modeling, prompt-injection isolation, supply-chain scanning, secret rotation and incident response are foundational, not final-phase additions."

> NS-08: "Server-side ABAC/RBAC for APIs, queries, exports, search indexes, copilot, tools and push channels. Fail closed on authorization errors; secure cache keys and federation summaries."

## Acceptance criteria
- [ ] Item 1: every boundary in ARCHITECTURE section 1 (User to Entra, UI to APIM, APIM to API authz, API to Cosmos, API to analytics adapter, orchestrator to model endpoint, tools to action service, action service to write connectors, audit) has STRIDE threats, mitigations and an owning PRP in `docs/security/threat-model.md`.
- [ ] Item 1: abuse cases for prompt injection, confused deputy and SSRF each have a data-flow diagram under `docs/security/dfd/` and a linked corpus or test path.
- [ ] Item 2: Given a container image with a High CVE, When `security.yml` runs, Then the workflow fails; an SBOM artifact (syft) is uploaded per image; `ci.yml` is unchanged.
- [ ] Item 3: Given the `az bicep build` and what-if outputs, Then no resource other than APIM has public ingress, and the Helm NetworkPolicy renders default-deny egress with an explicit allowlist.
- [ ] Item 4: `tests/security/injection/` holds at least 50 cases, each with an expected `abstain` or `deny` outcome, and a harness callable with an adapter fixture by PRP-19 and PRP-22.
- [ ] Item 5: gitleaks reports no secret literal in the repo; rotation runbook and incident response plan exist and reference Key Vault references only.
- [ ] PRP exit: `verify-gates -Mode full` and `python scripts/validate_planning.py` pass; the High-CVE failure and a default-deny render are shown with real output, not asserted.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Model for this PRP | sonnet; opus | Opus (decision D6: risk concentrated in contracts, authz, actions, MCP; threat modeling is cross-cutting security reasoning). Review: required, one pass |
| 2 | Repo visibility and pushes | public; private | Private (D1). Pushes still treated as publication; no secrets or PII in any committed corpus case |
| 3 | Where do scans live | edit ci.yml; new workflow | New `.github/workflows/security.yml`. `ci.yml` already runs pip-audit and pnpm audit; this PRP must not edit it. `security.yml` adds SBOM and image scanning and makes audit findings at High or above blocking in its own jobs |
| 4 | Scanner selection | Trivy only; Grype only; both | syft for SBOM, Trivy and Grype both run on images; either failing on High fails the job. Versions pinned in the workflow and recorded in ADR-0002 appendix by PRP-00 mechanisms |
| 5 | Corpus ownership | per-consumer copies; shared | Shared corpus in `tests/security/injection/`, consumed by PRP-19 and PRP-22. Consumers add cases only via PR to this path; they never fork it |
| 6 | Corpus content policy | real attack payloads from the wild; synthetic | Synthetic, hand-written cases; no real customer data, no credentials, no PII |
| 7 | Live items | include a live scan against Azure | None. Everything runs locally or in CI. `what-if` uses recorded fixtures unless the operator runs it with `NS_LIVE_APPROVED=1` |
| 8 | Government vs Commercial network modules | one param set; per-cloud | One module set with per-cloud params under `infra/bicep/params/`; Government is gated, not banned; PRP-20 owns the Government profile content |
| 9 | Threat model format | tool-generated; markdown + Mermaid | Markdown tables plus Mermaid DFDs; Mermaid must parse (renderer from PRP-00 item 3) |
| 10 | Severity gate | block on Medium; block on High | Block on High and Critical; Medium/Low become follow-up issues |
| 11 | Emulators | assert RBAC in emulator | Event Hubs emulator lacks Entra: producer identity is enforced at the ingest edge, so threat rows for that boundary state the emulator limit (G12) |

## Context manifest

### Files that matter
- `PRP.md` sections 1-3 (binding preamble: delivery contract, stack, contracts-first, IdentityScope rules).
- `docs/PRD.md` NS-08 and NS-09 (security, injection, SSRF, confused deputy).
- `docs/ARCHITECTURE.md` section 1 (trust-boundary flow), sections 3-5 (action, deployment, federation flows).
- `docs/RESEARCH-AND-GATES.md` (G02, G08, G12 rows; MCP and Vega CSP findings).
- `docs/adr/0002-stack-pins.md` (tool and action versions to pin).
- `pyproject.toml` (ruff S rules, pytest markers), `docker-compose.yml`, `infra/compose/eventhubs.config.json`.
- `.claude/hooks/config.ps1` (gate configuration), `.env.example` (placeholders only), `scripts/validate_planning.py`.
- `.github/workflows/ci.yml` (read only here; already runs pip-audit and pnpm audit), `.github/workflows/secret-scan.yml`, `.gitleaks.toml`, `SECURITY.md`.
- Created by PRP-06: `packages/core/neurosphere_core/auth/`, `services/api/neurosphere_api/authz/`, audit store. Created by PRP-08: `infra/bicep/modules/`, `infra/helm/`. Created by PRP-05: `services/api/neurosphere_api/`.

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")` for corpus case schema (case id, category, input, expected outcome, scope fixture).
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py`; the harness calls routers through the app factory, never by importing handlers.
- Async Azure SDK clients from `packages/core/neurosphere_core/clients`; error taxonomy exceptions from `neurosphere_core.errors` (`forbidden`, `unauthorized`, `capability_unavailable`).
- Tests beside packages, cross-package suites in `tests/`; `pytest.mark.live` and `pytest.mark.integration` markers declared in root `pyproject.toml`.
- Frontend rules (TS strict, `@fluentui/react-components`, Vitest + Testing Library, Playwright under `frontend/tests/e2e`) apply only if a corpus case needs a UI assertion; none are planned here.

### Conventions
- ruff configured in root `pyproject.toml` (line 100, py312, S rules on); pyright standard; conventional commits (`feat(security): ...`).
- Owned-file discipline: edit only the paths in your item; shared files (root `pyproject.toml`, `docker-compose.yml`, `docs/RESEARCH-AND-GATES.md`) are off limits unless the item owns a row.
- Evidence under `docs/evidence/<gate>/`; live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1`.
- No `|| true` in any workflow; `validate_planning.py` fails on it.

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
- PRP-specific: this PRP must not edit `.github/workflows/ci.yml`; a second Dependabot or audit step there would collide with PRP-00 items 3 and 4, which own one job and one step.
- PRP-specific: the corpus is shared. A case that only makes sense for MCP belongs in `tests/security/mcp/` (PRP-22), not here; keep the shared set transport-neutral.
- PRP-specific: threat-model rows must name an owning PRP that exists in the master index; do not invent PRP ids.
- PRP-specific: Trivy/Grype database downloads are network calls in CI; pin action versions and never use `continue-on-error`.
- PRP-specific: corpus cases containing injection strings are test data; make sure gitleaks and CodeQL do not misread fake keys (use obvious placeholders like `FAKE-KEY-DO-NOT-USE`).

### External references
- OWASP Top 10 for LLM Applications (prompt injection, excessive agency), https://genai.owasp.org/llm-top-10/ (retrieve on implementation date; not observed in ADR-0002).
- MCP authorization and security best practices (confused deputy, token passthrough, SSRF), https://modelcontextprotocol.io/specification/versioning, observed 2026-10-08 in `docs/RESEARCH-AND-GATES.md`.
- Event Hubs geo-DR does not copy payloads or RBAC, https://learn.microsoft.com/azure/event-hubs/event-hubs-geo-dr, observed 2026-10-06.
- Vega CSP guidance (`vega-interpreter`), https://vega.github.io/vega/usage/#csp, observed 2026-10-08.
- gitleaks 8.30.1 pinned in `docs/adr/0002-stack-pins.md`, observed 2026-10-08.
- Helm 4 pin and Helm 3 end of security fixes 2027-02-10, https://helm.sh/blog/helm-v3-end-of-life/, observed 2026-10-08.

## Implementation blueprint

### Item 1 — threat-model  [P]
- Deliverable: STRIDE analysis per trust boundary of ARCHITECTURE section 1, data-flow diagrams, abuse cases (prompt injection, confused deputy, SSRF).
- Owned files (may edit): `docs/security/threat-model.md`, `docs/security/dfd/`.
- Must NOT touch: `.github/workflows/`, `infra/`, `tests/security/injection/`, `docs/security/runbooks/`, root `pyproject.toml`, `docker-compose.yml`, `docs/RESEARCH-AND-GATES.md`.
- Depends on: none.
- Acceptance criteria:
  - Each boundary has a table of S/T/R/I/D/E threats, each with mitigation and owning PRP id.
  - Three abuse-case DFDs parse with the PRP-00 Mermaid renderer.
  - Document states "not FedRAMP authorized" and does not claim ATO.
- Pattern references: ARCHITECTURE sections 1, 3, 5; NS-08, NS-09.
- Tests to write: none (documentation item). The document embeds a boundary checklist that the reviewer compares against ARCHITECTURE section 1; Mermaid parse is covered by the PRP-00 render gate.

### Item 2 — supply-chain-scans  [P]
- Deliverable: `security.yml` with syft SBOM per image, Trivy and Grype image scans, pip-audit and pnpm audit gated on High, SBOM upload as artifact.
- Owned files (may edit): `.github/workflows/security.yml`.
- Must NOT touch: `.github/workflows/ci.yml`, `.github/workflows/codeql.yml`, `.github/workflows/secret-scan.yml`, `services/*/Dockerfile` (PRP-13), root `pyproject.toml`.
- Depends on: none.
- Acceptance criteria:
  - A planted High-CVE test image (local fixture, not committed) makes the job exit non-zero; evidence pasted in completion note.
  - No `|| true` and no `continue-on-error`; `validate_planning.py` passes.
  - Until PRP-13 Dockerfiles exist, the image jobs skip with an explicit "no image yet" notice that fails once a Dockerfile exists but the build is absent.
- Pattern references: existing `ci.yml` job layout (read only); ADR-0002 action versions.
- Tests to write: workflow lint via `actionlint` run in the gate; no Python tests.

### Item 3 — network-policy  [P]
- Deliverable: Bicep network module (private endpoints, NSG/egress allowlist, APIM as only public ingress) and Helm NetworkPolicy with default-deny egress and allowlist values.
- Owned files (may edit): `infra/bicep/modules/network/`, `infra/helm/templates/networkpolicy.yaml`, `tests/security/network/`.
- Must NOT touch: `infra/bicep/modules/` siblings other than `network/` (PRP-08), `infra/bicep/params/government/` (PRP-20), `infra/helm/values-government.yaml`, `.github/workflows/`.
- Depends on: none.
- Acceptance criteria:
  - `az bicep build` passes; what-if (fixture) shows no public ingress except APIM.
  - `helm lint` and `helm template` render a default-deny policy plus allowlist entries sourced from values.
  - No hardcoded `.com` Azure endpoint in the allowlist; endpoints come from per-cloud params.
- Pattern references: ARCHITECTURE section 4 (sovereign profiles); gotcha on Government endpoints.
- Tests to write: `tests/security/network/test_networkpolicy_render.py` (renders the chart, asserts deny-all egress).

### Item 4 — injection-corpus  [P]
- Deliverable: shared corpus and harness: at least 50 synthetic cases covering direct and indirect injection, overscope retrieval, `domain_id` smuggling, tool-manifest poisoning, data exfiltration via chart plan, SSRF URLs; harness takes an adapter callable and reports pass/fail per case.
- Owned files (may edit): `tests/security/injection/`.
- Must NOT touch: `tests/security/mcp/` (PRP-22), `tests/security/authz/` (PRP-06), `tests/security/egress/` (PRP-20), `packages/core/`, `services/`.
- Depends on: none.
- Acceptance criteria:
  - At least 50 cases, each with an expected `abstain` or `deny` and a category tag; schema validated by a Pydantic v2 `extra="forbid"` model.
  - Harness runs offline against a stub adapter; stub that obeys injections fails the suite (negative control).
  - Documented extension rule: PRP-19 and PRP-22 add cases by PR, never fork.
- Pattern references: Pydantic strict models; markers `pytest.mark.integration` only where an app fixture is needed.
- Tests to write: `tests/security/injection/test_corpus_schema.py`, `tests/security/injection/test_harness_negative_control.py`.

### Item 5 — secrets-and-rotation  [P]
- Deliverable: runbooks for Key Vault references, secret rotation, credential-leak response, incident response plan, and a pre-push checklist aligned to `.githooks/`.
- Owned files (may edit): `docs/security/runbooks/`.
- Must NOT touch: `.gitleaks.toml`, `.githooks/`, `SECURITY.md`, `.env.example`, `docs/security/threat-model.md`.
- Depends on: none.
- Acceptance criteria:
  - gitleaks full-history scan reports zero findings on the branch.
  - Rotation runbook names no secret value and cites vault references only.
  - Incident plan includes the rule: rotate the credential first, then clean history.
- Pattern references: user rule on pushing secrets; `SECURITY.md`.
- Tests to write: none beyond the gitleaks run; add the command to the gate list.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
- `python -m pytest tests/security/injection -q`
- `python -m pytest tests/security/network -q`
- `helm lint infra/helm` then `helm template neurosphere infra/helm`
- `az bicep build --file infra/bicep/modules/network/main.bicep` (path as created by item 3)
- `actionlint .github/workflows/security.yml`
- `gitleaks detect --redact --no-banner` (history scan, binary pinned in ADR-0002)
- Optional `scripts/gates/` what-if against a real subscription is **operator-approved, requires NS_LIVE_APPROVED=1**; not required for merge.

## Live and open gates
- G02 (FedRAMP/DoD boundary): this PRP supplies the threat model that PRP-20 and PRP-23 cite; it does not narrow or close G02.
- G08 (dependency versions and licences): SBOM and scanner pins add evidence; status stays NARROWED until PRP-22 MCP tests land.
- G12 (emulator parity): threat rows record the Event Hubs emulator lack of Entra and Cosmos emulator limits; no live run is planned.
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Runtime authorization code, policy store or audit store (PRP-06).
- MCP-specific confused-deputy tests (PRP-22) and copilot orchestrator behavior (PRP-19); only the shared corpus is built here.
- Government network profile contents and egress test (PRP-20).
- Control narratives, SSP, POA&M (PRP-23).
- Dockerfiles (PRP-13) and Bicep modules other than `network/` (PRP-08).
- Any edit to `.github/workflows/ci.yml`.
- Penetration testing or paid scanning services.

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
- Open gates recorded (ids and where):
- Follow-ups:
