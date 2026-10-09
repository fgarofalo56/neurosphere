---
name: prp-23-ato-evidence-and-data-lifecycle
status: backlog
review: required
created: 2026-10-08
model: sonnet
phase: 4
ns: NS-08
depends_on: PRP-12, PRP-20, PRP-21
wave: W8
absorbs: P4.5, G06
---

# PRP-23: ATO evidence and data lifecycle

## Goal
Ship the data lifecycle engine (retention, pseudonymization, deletion, export, legal hold, with written conflict rules and immutable audit) and the ATO accelerator documents: NIST 800-53 Rev 5 control narratives, SSP sections, a POA&M template, boundary and data-flow diagrams, incident/contingency/change/continuous-monitoring plans, and a script that assembles an evidence inventory idempotently. It is for the customer security team, records officers and the authorizing official. It supports their decision; it does not make it. It lands in W8 because it indexes evidence from the threat model and scans (PRP-12), the Government register (PRP-20) and the DR measurements (PRP-21). **Every document produced here states "not FedRAMP authorized; the authorizing official decides".**

> ATO accelerator includes boundary/data-flow diagrams, SSP/control narratives, inheritance/responsibility matrix, POA&M, evidence inventory, scan outputs, configuration baselines, continuous monitoring and change/incident/contingency plans. Map to applicable NIST 800-53 Rev 5 and agency requirements; track FedRAMP/DoD scope separately. (NS-08)

> NeuroSphere is not FedRAMP authorized and cannot grant an agency ATO. Azure Government, GCC/GCC High and DoD impact levels are not interchangeable. Agency authorizing officials determine ATO; inherited controls do not automatically authorize this application. No certification deadline promise. (NS-08)

> Configurable retention, pseudonymization, deletion/export, legal holds and immutable audit retention with documented conflict rules. (PRD section 3)

## Acceptance criteria
- [ ] Item 1: Given an object under legal hold, When a deletion or retention expiry targets it, Then deletion is blocked and the attempt is audited; given any audit record or audit container, When any lifecycle action targets it, Then the engine refuses (test), and with no policy configured nothing is deleted.
- [ ] Item 2: Given the control narrative set, When the mapping test runs, Then every control entry cites at least one implementing PRP and one evidence path that exists (or is explicitly marked `planned` or `customer`), and no entry uses the words "compliant" or "authorized" about NeuroSphere.
- [ ] Item 3: Given unchanged inputs, When `scripts/compliance/` runs twice, Then `docs/evidence/inventory.md` and the package manifest are byte-identical; files matching credential-shaped paths are never collected.
- [ ] Item 4: Given the plans under `docs/compliance/plans/`, When the statement check runs, Then every document under `docs/compliance/` contains "not FedRAMP authorized; the authorizing official decides".
- [ ] PRP exit: items 1-4 green under `verify-gates -Mode full`; G06 and G02 recorded OPEN with the customer inputs still required; no document claims authorization, ATO, parity or a certification date.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required; opus | sonnet, review required (D6) |
| 2 | Control baseline | pick Low/Moderate/High; leave to customer | Not selected here. The mapping covers the control families the platform plausibly implements or inherits (AC, AU, CA, CM, CP, IA, IR, PL, RA, SA, SC, SI, SR and related) and records baseline selection as a customer/agency input. FedRAMP and DoD scope are tracked in a separate section of the SSP scope file, never merged into the NIST mapping |
| 3 | Control status vocabulary | compliant/non-compliant; neutral | `designed`, `implemented_tested`, `inherited`, `customer`, `planned`, `not_applicable`. No "compliant" or "authorized" value. Inheritance cites the PRP-20 responsibility matrix and states inherited controls do not automatically authorize this application |
| 4 | Conflict precedence | ad hoc; written order | Highest first: (1) audit immutability, (2) legal hold, (3) minimum retention period, (4) subject deletion or pseudonymization request, (5) maximum retention expiry. A lower rule never overrides a higher one; a deferred request is queued and audited, and executes when the blocking rule lifts |
| 5 | Audit and deletion | allow with approval; never | Audit is never deleted by the engine. Audit records carry pseudonymous principals; the pseudonym mapping store is separate and is subject to deletion unless under hold, so erasure of a person is achieved by mapping destruction, not audit deletion |
| 6 | Default policy | built-in defaults; none | No built-in retention values. Missing or invalid policy fails closed: nothing is deleted, prompt/response bodies are not retained, and the engine reports the policy as unset. Retention periods come from the customer's records policy (G06) |
| 7 | Deletion verification | trust the API; read back | Every deletion is verified by reading back the target; a failed verification marks the job `failed` and raises an audit record. No pretend deletes |
| 8 | Export | any scope; scoped | Export is filtered by the caller's `IdentityScope` and the request's lawful basis; held data may be exported only to authorized custodians, and exports are audited |
| 9 | Evidence package location | commit the package; index only | `docs/evidence/inventory.md` (committed index with path, sha256, source date, status) plus a package archive written to `temp/compliance-package/` (gitignored). The generation timestamp is not written into the index so reruns are identical |
| 10 | Diagrams | claim rendered; render | Boundary and data-flow diagrams are Mermaid in markdown; they are rendered with the pinned `@mermaid-js/mermaid-cli` and the SVGs committed before any document says they are rendered |
| 11 | Disclaimer enforcement | by convention; by test | `scripts/compliance/check_statements.py` plus `tests/compliance/` fail if any `docs/compliance/**/*.md` lacks the sentence. This includes the PRP-20 responsibility matrix |
| 12 | Customer-specific inputs | assume; record | Classification, payload opt-in, retention periods, legal hold process, authorizing official and agency baseline are recorded as required customer inputs in the SSP scope file with status OPEN. They are not guessed |

## Context manifest

### Files that matter
- `PRP.md` - sections 1-3.
- `docs/PRD.md` - NS-08 text, section 3 retention and DR, section 4 release gates.
- `docs/ARCHITECTURE.md` - the five diagrams, trust boundaries.
- `docs/RESEARCH-AND-GATES.md` - G02, G06, G07; Government findings.
- `docs/adr/0002-stack-pins.md` - pins used by the scripts (Python 3.12, Node 24, pnpm 11).
- `docs/DECISIONS-LOG.md` - D6, D7, D8.
- `SECURITY.md`, `.gitleaks.toml`, `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.claude/hooks/config.ps1`, `.env.example`, `scripts/validate_planning.py` (credential-shaped path regex to reuse, not copy).
- Created by PRP-06: `neurosphere_core.audit` (hash-chained, append-only), `neurosphere_core.auth.scope`.
- Created by PRP-07: redacted archive, quarantine container, cost ledger.
- Created by PRP-10: catalog repository (a lifecycle target).
- Created by PRP-12: `docs/security/threat-model.md`, `.github/workflows/security.yml` outputs (SBOM, scans), `docs/security/runbooks/`.
- Created by PRP-13: `docs/release/dod-checklist.md`, migrations tooling.
- Created by PRP-20: `docs/evidence/G02/register.yaml`, `docs/compliance/responsibility-matrix.md`.
- Created by PRP-21: `docs/ops/dr-runbook.md`, `docs/evidence/G07/`.

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`; FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py`; async Azure SDK clients from `packages/core/neurosphere_core/clients`; error taxonomy exceptions from `neurosphere_core.errors`.
- Lifecycle targets are protocol implementations (catalog, archive, ledger, conversations) so each store keeps its own adapter; the engine never reaches into a store's internals.
- Tests beside packages plus cross-package suites in `tests/`; `pytest.mark.integration` for compose-backed targets.
- Documents are markdown with a fixed header block (scope, status vocabulary, statement).

### Conventions
- ruff line 100, py312, S rules on; pyright standard; conventional commits; owned-file discipline.
- Evidence under `docs/evidence/`; any live script under `scripts/gates/` refuses without `NS_LIVE_APPROVED=1`. This PRP has none.
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
- PRP-specific: legal hold wins over deletion and over retention expiry. Audit is never deleted. A deletion request that is blocked is queued and audited, never silently dropped and never forced.
- PRP-specific: pseudonymization is not deletion. Pseudonymized data that can be re-identified through a retained mapping is still personal data; the engine reports which of the two actually happened.
- PRP-specific: "inherited" controls do not automatically authorize this application, and a service in a FedRAMP or DoD audit scope listing is not an authorization of this workload.
- PRP-specific: the evidence script reads scan and test outputs; it must never read `.env`, credential-shaped paths or secret stores, and must never copy a value that looks like a credential into the package. Failures are listed, not skipped.
- PRP-specific: Mermaid diagrams are not "produced" until rendered; the plan documents link rendered SVGs or say "not rendered".
- PRP-specific: no certification date, authorization date or compliance percentage may appear in any document.

### External references
- NIST SP 800-53 Rev 5 control catalog: https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final (agency baseline selection is a customer input; verify the current revision at implementation time).
- Azure services in FedRAMP and DoD audit scope: https://learn.microsoft.com/azure/azure-government/compliance/azure-services-in-fedramp-auditscope (updated 2026-09-21, retrieved 2026-10-08).
- Fabric in GCC High (FedRAMP High assessment in progress): https://learn.microsoft.com/fabric/enterprise/us-government-community-cloud-high (retrieved 2026-10-08).
- Event Hubs metadata geo-DR and data geo-replication (contingency plan inputs): https://learn.microsoft.com/azure/event-hubs/event-hubs-geo-dr (retrieved 2026-10-06) and https://learn.microsoft.com/azure/event-hubs/geo-replication (2026-07-11).
- Gitleaks and secret-scan layers: SECURITY.md in this repository; gitleaks 8.30.1 per docs/adr/0002-stack-pins.md (observed 2026-10-08).

## Implementation blueprint

### Item 1 - retention-policy-engine  [P]
- Deliverable: lifecycle engine with retention, pseudonymization, deletion, export and legal hold, the written conflict rules, target protocols with catalog/archive/ledger/conversation adapters, and a worker that executes scheduled and requested jobs with read-back verification.
- Owned files (may edit): `packages/core/neurosphere_core/lifecycle/`, `services/workers/neurosphere_workers/lifecycle/`.
- Must NOT touch: `packages/core/neurosphere_core/audit/` and `services/api/neurosphere_api/audit/` (PRP-06), `packages/core/neurosphere_core/catalog/` (PRP-10), `packages/core/neurosphere_core/ledger/` (PRP-07), `docs/compliance/`, `scripts/compliance/`, root `pyproject.toml`, `docker-compose.yml`.
- Depends on: none.
- Acceptance criteria:
  - Legal hold blocks deletion and retention expiry; the blocked request is queued and audited.
  - The engine refuses any action targeting the audit container or an audit record (test); audit is never deleted.
  - With no policy configured, nothing is deleted and prompt/response bodies are not retained.
  - Every deletion is verified by read-back; a failed verification yields `failed` plus an audit record.
- Pattern references: `IdentityScope` on export; error taxonomy; worker runtime base from PRP-05; audit writer interface from PRP-06 (consume, do not modify).
- Tests to write: `packages/core/tests/lifecycle/test_conflict_rules.py`, `packages/core/tests/lifecycle/test_audit_immutable.py`, `packages/core/tests/lifecycle/test_no_policy_fails_closed.py`, `services/workers/tests/lifecycle/test_job_verification.py`, `tests/integration/lifecycle/test_targets_compose.py` (`pytest.mark.integration`).

### Item 2 - control-narratives  [P]
- Deliverable: NIST 800-53 Rev 5 mapping, SSP narratives per control family, SSP scope file (customer inputs, FedRAMP/DoD scope tracked separately) and POA&M template.
- Owned files (may edit): `docs/compliance/ssp/`, `docs/compliance/poam.md`, `tests/compliance/test_control_mapping.py`.
- Must NOT touch: `docs/compliance/responsibility-matrix.md` (PRP-20), `docs/compliance/plans/` (item 4), `docs/evidence/` (items 3 and PRP-20/21), `scripts/compliance/`, `packages/core/`.
- Depends on: none.
- Acceptance criteria:
  - Each control entry has a status from the fixed vocabulary, an implementing PRP id and an evidence path; entries with `planned` or `customer` say so and name the owner.
  - The mapping test fails on a missing evidence path for any `implemented_tested` entry, and on the words "compliant" or "authorized" applied to NeuroSphere.
  - The POA&M template has columns for weakness, control, milestone, owner, scheduled completion and status; no pre-filled completion dates.
  - The SSP scope file lists the customer inputs from clarification 12 as OPEN.
- Pattern references: PRP-20 responsibility matrix (link, do not copy); PRP-12 threat model.
- Tests to write: `tests/compliance/test_control_mapping.py`.

### Item 3 - evidence-inventory-automation  [P]
- Deliverable: script that collects scan outputs, test evidence and configuration baselines into an indexed inventory and a package archive, plus the statement checker.
- Owned files (may edit): `scripts/compliance/`, `docs/evidence/inventory.md`, `tests/compliance/` (except `test_control_mapping.py`).
- Must NOT touch: `docs/evidence/G02/`, `docs/evidence/G03/`, `docs/evidence/G07/`, `docs/compliance/`, `.github/workflows/`, `scripts/gates/`, `scripts/validate_planning.py`.
- Depends on: none.
- Acceptance criteria:
  - Two runs on unchanged inputs produce byte-identical `docs/evidence/inventory.md` and package manifest (test).
  - Credential-shaped paths and `.env*` files are never collected; a planted fixture file proves it.
  - Missing expected evidence is listed as `missing` in the inventory, never skipped silently.
  - `check_statements.py` fails when any `docs/compliance/**/*.md` lacks the required sentence.
- Pattern references: credential-shaped path regex in `scripts/validate_planning.py`; scan output locations from PRP-12.
- Tests to write: `tests/compliance/test_inventory_idempotent.py`, `tests/compliance/test_no_credential_collection.py`, `tests/compliance/test_statements.py`.

### Item 4 - boundary-and-contingency  [P]
- Deliverable: boundary and data-flow diagrams (rendered), incident response, contingency, change management and continuous monitoring plans.
- Owned files (may edit): `docs/compliance/plans/`.
- Must NOT touch: `docs/compliance/ssp/`, `docs/compliance/poam.md`, `docs/compliance/responsibility-matrix.md`, `docs/ops/dr-runbook.md` (PRP-21), `docs/security/` (PRP-12), `docs/ARCHITECTURE.md`.
- Depends on: none.
- Acceptance criteria:
  - Every document states "not FedRAMP authorized; the authorizing official decides".
  - Contingency plan references measured DR results from `docs/evidence/G07/dr/` and the Event Hubs metadata-DR caveat; it does not restate RTO/RPO targets as guarantees.
  - Diagrams are rendered SVGs committed beside the sources, or the plan says "not rendered".
  - Government and Commercial boundaries are drawn separately; no data flow crosses between them.
- Pattern references: `docs/ARCHITECTURE.md` boundary diagrams; PRP-12 incident response and rotation runbooks (link).
- Tests to write: covered by item 3 `tests/compliance/test_statements.py`; diagram render check `tests/compliance/test_plan_diagrams_rendered.py` is owned by item 3.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
python -m pytest packages/core/tests/lifecycle services/workers/tests/lifecycle tests/compliance
docker compose up -d --wait
python -m pytest -m integration tests/integration/lifecycle
python scripts/compliance/collect_evidence.py
python scripts/compliance/collect_evidence.py
python scripts/compliance/check_statements.py
git diff --exit-code docs/evidence/inventory.md
```
The two collection runs followed by `git diff --exit-code` after staging the first output prove idempotency.

## Live and open gates
- G06 (privacy/retention/legal hold): stays OPEN. The engine ships policy-driven with fail-closed defaults, but approved classification, payload opt-in, retention periods and the legal hold process are customer inputs not yet provided.
- G02 (FedRAMP/DoD boundary and agency ATO): stays OPEN; this PRP provides the accelerator documents only. Closure belongs to the authorizing official.
- G07 (workload/SLO/DR): the contingency plan cites measurements but does not close the gate.
- No live Azure item in this PRP.
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Any authorization, ATO, FedRAMP or DoD IL claim, certification date, or compliance score.
- The responsibility matrix and evidence register (PRP-20); the threat model and runbooks (PRP-12); DR scripts and runbook (PRP-21).
- A 3PAO assessment package, agency-specific baseline selection, or control testing by an assessor.
- A records management product, eDiscovery, or legal hold workflow UI; the engine honors holds set through its interface.
- Automatic deletion of audit data, under any rule.

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
- Customer inputs still OPEN (G06, G02):
- Reviewer verdict (conflict rules, disclaimer enforcement):
- Follow-ups:
