---
name: prp-16-agent-evaluation-and-quality
status: backlog
review: required
created: 2026-10-08
model: sonnet
phase: 2
ns: NS-03
depends_on: PRP-04, PRP-07, PRP-10
wave: W6
absorbs: P2.4
---

# PRP-16: Agent evaluation and quality

## Goal
Ship the quality-evaluation half of NS-03: versioned benchmark datasets, rubrics and judge-model registry; a budgeted sampling worker that evaluates redacted archive data inside the selected boundary; human-label calibration with drift alerts; and a quality API and UI showing trends, coverage and missing labels. It is for agent owners, stewards and auditors who need evidence-based quality, not thumbs-up counts. It lands in W6 because it needs the UI shell (PRP-04), the redacted archive and ledger (PRP-07) and the catalog identities (PRP-10). Recommendations (rules, duplicates, projections) belong to PRP-15.

> Add offline benchmark and sampled online evaluation for task success, groundedness, safety, tool correctness, feedback and drift. Version datasets/rubrics/judge models; calibrate LLM-as-judge against human labels and report uncertainty, bias and sampling coverage. Quality is not inferred solely from thumbs-up or absence of errors. Evaluate approved/redacted data inside the selected boundary; enforce evaluator token/cost budgets.

> Model swaps require capability/context/tool compatibility, quality regression tests and cost comparison, then staged rollout/canary and rollback.

## Acceptance criteria
- [ ] Item 1: Every `EvaluationResult` references a dataset version, rubric version and judge-config version; a result missing any of the three is rejected by schema.
- [ ] Item 2: Given an item classified restricted, When sampling selects it, Then it is never sent to a judge not approved for that classification (test); a run stops when its token or cost budget is exhausted and records `budget_exhausted`.
- [ ] Item 3: Calibration output reports agreement with human labels, uncertainty, bias and sampling coverage; a drift alert fires on a seeded drift fixture.
- [ ] Item 4: Trends, coverage and missing-label views render; the pilot-set grounded-answer rate is shown with a confidence interval and the target of at least 90% is labelled a pilot-set target, not a guarantee.
- [ ] No test or CI job makes a paid judge call; judge behavior in CI comes from recorded fixtures.
- [ ] PRP exit: items 1-4 green under `verify-gates -Mode full`; reviewer confirms restricted-content and budget tests are not mocked away.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required; opus | sonnet, review required (D6) |
| 2 | Live gates | live judge run per PRP; fixtures only | Fixtures only in CI. A live judge run is optional, operator-approved with `NS_LIVE_APPROVED=1`, and not required for merge (D7); if skipped it is recorded OPEN |
| 3 | Emulator | live services; compose emulators | Local work uses Docker Compose emulators and Azurite for the archive (D8). Emulator evidence is bounded feasibility only |
| 4 | Judge calls in CI | recorded; live | Recorded fixtures (request hash to canned response). No paid model calls in CI |
| 5 | What data judges may see | raw; redacted; approved only | Redacted archive data only, and only for judges approved for the item's classification and boundary. Restricted content never goes to unapproved judges. Redaction runs before any external transmission |
| 6 | Government boundary | any judge; matrix-gated | Judge endpoints are chosen from the capability matrix; a Government deployment never uses a Commercial judge. Unavailable judge options are disabled with reason |
| 7 | Evaluator budgets | unlimited; per-run and per-domain | Token and cost budgets per run and per domain, enforced before each judge call; exhaustion stops the run and is reported, never silently truncated |
| 8 | 90% grounded-answer rate | guarantee; target | Pilot-set target with a confidence interval (method documented in the item 3 module). The UI never presents it as a guarantee or a product SLA |
| 9 | Quality signal | feedback only; multi-signal | Task success, groundedness, safety, tool correctness, feedback and drift are separate metrics; thumbs-up or absence of errors is never the sole signal |
| 10 | Model-swap regression | build here; PRP-17 | This PRP supplies quality-regression results consumed by the swap flow; the swap executor is PRP-17 |
| 11 | Human labels source | build labeling tool; ingest | Ingest labels through the HITL review interface (PRP-17 supplies the queue); this PRP defines label use and calibration stats only |
| 12 | Sampling strategy | uniform; stratified | Stratified by domain, agent and classification, with sampling coverage reported per stratum |

## Context manifest

### Files that matter
- `PRP.md` - sections 1-3 (delivery contract, scope, contracts).
- `docs/PRD.md` - NS-03 text; planning targets and load-test notes (evaluator overhead).
- `docs/ARCHITECTURE.md` - ingestion, archive and analytics diagrams.
- `docs/RESEARCH-AND-GATES.md` - G01, G05, G06, G12 rows; Foundry models in Azure Government note.
- `docs/adr/0002-stack-pins.md` - frontend and Python pins.
- `docs/DECISIONS-LOG.md` - D6, D7, D8, D11.
- `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.env.example`, `.claude/hooks/config.ps1`, `scripts/validate_planning.py`.
- Created by PRP-01: `packages/contracts/schemas/evaluation/` (`EvaluationResult`), `.../scope/`, `.../query/`.
- Created by PRP-03: `sandbox/` generator (traces, seeded quality anomalies).
- Created by PRP-04: `frontend/src/design-system/`, `frontend/src/api/`, `frontend/src/features/workspaces/`.
- Created by PRP-05: `neurosphere_core.errors`, `.../scope/`, `.../clients/`, worker runtime base.
- Created by PRP-06: `neurosphere_core.auth.scope`, `neurosphere_api.authz`, `neurosphere_core.audit`.
- Created by PRP-07: redacted archive under `services/workers/neurosphere_workers/archive/`, cost ledger `neurosphere_core.ledger`.
- Created by PRP-10: catalog repository and graph query in `neurosphere_core.catalog`.

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`, generated from `packages/contracts`; do not hand-edit generated files.
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py` (here `evaluation/`).
- Async Azure SDK clients from `packages/core/neurosphere_core/clients`; error taxonomy exceptions from `neurosphere_core.errors`.
- Judge access behind a protocol in `neurosphere_core.evaluation`, with a recorded-fixture implementation for tests.
- Tests beside packages plus cross-package suites in `tests/`; `pytest.mark.live` and `pytest.mark.integration` markers (declared in root `pyproject.toml`).
- TypeScript strict with `@fluentui/react-components`; Vitest + Testing Library; Playwright under `frontend/tests/e2e`.

### Conventions
- ruff config in root `pyproject.toml` (line 100, py312, S rules on); pyright standard; conventional commits; owned-file discipline.
- Evidence under `docs/evidence/<gate>/`; live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1`.
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
- PRP-specific: restricted-classified content must never reach an unapproved judge. Check classification and judge approval before the call, not after; a failed check skips the item and records why.
- PRP-specific: LLM-as-judge is biased and noisy. Never display a judge score without the judge-config version, calibration state and uncertainty.
- PRP-specific: budget enforcement happens before the call. A run that overshoots because the check came after the call is a defect.
- PRP-specific: the 90% grounded-answer figure is a pilot-set target with a confidence interval, not a guarantee. Small pilot sets give wide intervals; show them.
- PRP-specific: prompt and response bodies are off by default (PRP-07). Evaluation can only use data the archive actually holds; if bodies were not opted in, report coverage as limited, never fabricate.
- PRP-specific: dataset or rubric edits create a new version. Results tied to an old version stay valid and queryable; never mutate in place.

### External references
- Foundry models and Agent Service in Azure Government: docs/RESEARCH-AND-GATES.md "Infrastructure and tooling" (observed 2026-10-08 per the register); use only through the capability matrix.
- Azure AI Search regional support (retrieval for grounding checks, Government gaps): https://learn.microsoft.com/azure/search/search-region-support (observed 2026-10-01).
- Pins for React, Fluent UI, Vitest, Playwright: docs/adr/0002-stack-pins.md (observed 2026-10-08).
- Emulator limits relevant to local evaluation storage: https://learn.microsoft.com/azure/cosmos-db/emulator-linux (GA June 2026).

## Implementation blueprint

### Item 1 - datasets-and-rubrics  [P]
- Deliverable: versioned benchmark datasets, rubrics and a judge/model configuration registry, with sandbox benchmark data.
- Owned files (may edit): `packages/core/neurosphere_core/evaluation/registry/`, `sandbox/evaluation/`.
- Must NOT touch: `packages/core/neurosphere_core/evaluation/calibration/`, `services/workers/neurosphere_workers/evaluation/`, `services/api/neurosphere_api/evaluation/`, `frontend/src/features/quality/`, `packages/contracts/`, root `pyproject.toml`, `docker-compose.yml`, `docs/RESEARCH-AND-GATES.md`.
- Depends on: none.
- Acceptance criteria:
  - Every result references dataset, rubric and judge-config versions; edits create new versions and never mutate old ones.
  - Registry records which classifications and boundaries each judge is approved for.
  - Sandbox datasets validate against PRP-01 evaluation schemas and cover task success, groundedness, safety and tool correctness.
- Pattern references: Pydantic forbid-extra; contract-generated models.
- Tests to write: `packages/core/tests/evaluation/test_registry_versions.py`, `packages/core/tests/evaluation/test_judge_approval.py`.

### Item 2 - sampling-worker
- Deliverable: sampled online evaluation from the redacted archive with budget enforcement and a restricted-classification guard, using recorded fixtures in CI.
- Owned files (may edit): `services/workers/neurosphere_workers/evaluation/`, `scripts/gates/g16_judge_live.py`, `docs/evidence/G16/`.
- Must NOT touch: `packages/core/neurosphere_core/evaluation/registry/`, `packages/core/neurosphere_core/evaluation/calibration/`, `services/workers/neurosphere_workers/archive/`, `services/workers/neurosphere_workers/runtime/`, `services/api/`, root `pyproject.toml`, `docker-compose.yml`.
- Depends on: Item 1.
- Acceptance criteria:
  - A restricted-classified item is never sent to an unapproved judge (test asserts zero calls to the judge double).
  - Run stops when the token or cost budget is exhausted and reports `budget_exhausted` with coverage achieved.
  - Sampling is stratified and per-stratum coverage is recorded; replaying the same seed yields the same sample.
- Pattern references: worker runtime base and checkpoint interface from PRP-05; redaction before external transmission.
- Tests to write: `services/workers/tests/evaluation/test_restricted_guard.py`, `services/workers/tests/evaluation/test_budget.py`, `services/workers/tests/evaluation/test_sampling_coverage.py`.

### Item 3 - calibration-and-drift  [P]
- Deliverable: human-label ingestion, calibration statistics (agreement, bias, uncertainty), sampling coverage and drift alerts.
- Owned files (may edit): `packages/core/neurosphere_core/evaluation/calibration/`.
- Must NOT touch: `packages/core/neurosphere_core/evaluation/registry/`, `services/workers/neurosphere_workers/evaluation/`, `services/api/neurosphere_api/evaluation/`, `packages/contracts/`, root `pyproject.toml`.
- Depends on: Item 1.
- Acceptance criteria:
  - Output includes agreement with human labels, uncertainty interval, bias estimate and sampling coverage.
  - A seeded drift fixture triggers a drift alert; a stable fixture does not.
  - Confidence interval method is documented in the module docstring and tested against a known case.
- Pattern references: pure functions over typed inputs; no I/O in the statistics module.
- Tests to write: `packages/core/tests/evaluation/test_calibration.py`, `packages/core/tests/evaluation/test_drift.py`.

### Item 4 - quality-api-ui
- Deliverable: scoped API and UI for quality trends, coverage and missing labels, with grounded-answer rate and its confidence interval.
- Owned files (may edit): `services/api/neurosphere_api/evaluation/`, `frontend/src/features/quality/`.
- Must NOT touch: `packages/core/neurosphere_core/evaluation/`, `services/workers/`, `frontend/src/features/dashboards/`, `frontend/src/design-system/`, `frontend/src/api/` (consume only), root `pyproject.toml`.
- Depends on: Items 2, 3.
- Acceptance criteria:
  - Pilot-set grounded-answer rate renders with a confidence interval and the label "pilot-set target: at least 90%"; no wording implies a guarantee.
  - Unknown or uncovered metrics render as "unknown", never 0; missing-label counts are visible.
  - Cross-domain evaluation results are never returned for a scoped caller (negative test); routes use `require(permission)`.
- Pattern references: router per module; `IdentityScope` on every query; Fluent UI v9 components.
- Tests to write: `services/api/tests/evaluation/test_quality_api.py`, `frontend/src/features/quality/quality.test.tsx`, `frontend/tests/e2e/quality.spec.ts`.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
docker compose up -d --wait
python -m pytest packages/core/tests/evaluation services/workers/tests/evaluation services/api/tests/evaluation
python -m pytest -m integration tests/integration/evaluation
pnpm --filter frontend test
pnpm --filter frontend exec playwright test frontend/tests/e2e/quality.spec.ts
```
Optional live judge run (not required for merge): operator-approved, requires NS_LIVE_APPROVED=1, run as `NS_LIVE_APPROVED=1 python scripts/gates/g16_judge_live.py`.

## Live and open gates
- G01 (service/feature/region matrix): judge endpoint availability per cloud is read from the matrix; no evidence closes G01 here.
- G06 (privacy/retention/legal hold): evaluation reads only approved, redacted archive data; classification handling informs G06, which stays OPEN until PRP-23.
- G12 (emulator parity): record where archive and storage emulators differ from live behavior.
- G05 (model swap compatibility): this PRP supplies quality-regression inputs; G05 stays OPEN until PRP-17 live verification.
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Recommendation rules, duplicate detection and cost projection (PRP-15).
- The review queue, HITL workflow and label capture UI (PRP-17); this PRP ingests labels via its interface.
- Model-swap execution, canary and rollback (PRP-17).
- A labeling product, or any automatic action triggered by a judge score.
- Agent/tool selection as a recommendation capability (optional per NS-03, deferred).
- Schema changes to PRP-01 contracts; request them through PRP-01.

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
- Optional live judge run: date, operator approval, evidence path (or OPEN):
- Follow-ups:
