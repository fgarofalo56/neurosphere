---
name: prp-21-scale-federation-finops-and-dr
status: backlog
review: none
created: 2026-10-08
model: sonnet
phase: 4
ns: NS-07, NS-08
depends_on: PRP-07, PRP-11, PRP-13, PRP-14
wave: W7
absorbs: P4.3 + P4.4, G07
---

# PRP-21: Scale, federation, FinOps and DR

## Goal
Ship the load-test profiles (pilot, enterprise, stress), per-domain admission control, authorized cross-cell federation summaries, a cost forecast with real-cost evidence hooks, and per-store backup/restore plus a failover/failback runbook. It is for SRE, FinOps and domain owners who need measured, not asserted, behaviour under skew and noisy neighbors. It lands in W7 because it needs ingestion and the ledger (PRP-07), analytics adapters (PRP-11), release images (PRP-13) and the dashboards/aggregates path (PRP-14). **Every number in the PRD scale and DR sections is a provisional planning target to be measured; nothing here may publish a target as a guarantee.**

> Planning targets, to be measured rather than guaranteed: regional core API availability 99.9%; dashboard p95 <=2s on bounded 90-day aggregates; catalog p95 <=500ms on indexed scoped queries; map freshness p95 <=10s after normalized ingestion. (PRD section 3)

> Scale profiles: pilot 1k agents/1k events per second; enterprise 100k agents/10k sustained events per second; stress 1M entities/10M relationships and 50k sustained/150k burst events per second subject to partition/cost validation. (PRD section 3)

> Federate domain/region cells with scope-filtered summaries; data remains in approved boundaries. ... Per-domain quotas/admission control protect noisy neighbors. (PRD section 3)

> RTO <=4h/RPO <=15min are provisional profile targets requiring measured end-to-end evidence. Metadata-only Event Hubs geo-DR is insufficient for event-data RPO. (PRD section 3)

## Acceptance criteria
- [ ] Item 1: Given the pilot profile (1k events per second, 1k agents) against the compose stack, When the suite runs, Then it produces an evidence JSON with the measured rates, p95 values and error counts and reports pass/fail against the profile thresholds. Enterprise and stress profiles are defined, parametrized by target, and run only by the operator at a sized environment.
- [ ] Item 2: Given one domain exceeding its quota, When the limiter is under load, Then that domain is throttled with `rate_limited` and a retry hint while other domains stay within their configured limits (unit and simulated-load test).
- [ ] Item 3: Given a federated summary request, When cells respond, Then the merged summary contains no identity, count or cost contribution outside the caller's `IdentityScope`, and no cell in one cloud contributes to a summary served in another cloud.
- [ ] Item 4: Given a month of sandbox cost records, When the forecast runs, Then forecast and actual are reported side by side with the price version id, estimated and invoiced are separate, and unknown inputs yield `unknown`, never 0.
- [ ] Item 5: Given the compose stack, When the restore drill runs, Then each store is restored from backup, verification queries match, and measured restore time and recovery point gap are published in `docs/ops/dr-runbook.md` with the method and the label "compose, not representative of production".
- [ ] PRP exit: items 1-5 green under `verify-gates -Mode full`; G07 row updated to state what was measured, where, and what remains OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required; opus | sonnet, review none (D6, master index). Reviewer attention goes to items 3 (scope leak) only if the author flags it |
| 2 | Load tool | k6; locust | locust (Python, MIT, managed with the existing toolchain). k6 is AGPL-3.0 and would need ADR-0002 approval under the non-permissive rule. Pins live in `tests/load/profiles/requirements.txt`; record the licence in the profile README and raise a follow-up for ADR-0002 |
| 3 | Where profiles run | CI; operator | Pilot against compose (CI-capable, no paid calls). Enterprise and stress need sized environments and quota/cost approval: operator-run, never CI (D7); recorded OPEN until run |
| 4 | Emulator limits | treat emulator numbers as capacity | Event Hubs emulator (one namespace, ten hubs, no persistence, SAS only) and Cosmos vNext (no RU accounting) mean compose results are "bounded feasibility" only (G12) |
| 5 | Admission wiring | edit ingest edge and query service now; library first | Item 2 delivers `neurosphere_core.admission` (limiter, quota config, ASGI middleware factory). Wiring into `services/api/neurosphere_api/ingest/` (PRP-07) and the query services is outside this PRP's ownership; it is recorded as a follow-up needing approval from those owners |
| 6 | Quota source | hard-coded; config | Per-domain quota config loaded from a policy document; absent config means a conservative default limit and a logged warning, never unlimited |
| 7 | Federation boundary | cross-cloud allowed; same cloud only | A summary is composed only from cells in the same cloud and the same approved boundary. Government cells never contribute to Commercial summaries or the reverse |
| 8 | Federation mechanism | raw data pull; scoped aggregate summary | Each cell computes a scope-filtered aggregate locally; only aggregates travel. The requester's `IdentityScope` is derived server-side in each cell, not passed as a trusted caller field |
| 9 | Forecast model | ML; simple trend | A simple, explainable trend model over ledger aggregates with an uncertainty band and price version citation. Not a savings claim; unknown inputs stay unknown |
| 10 | RTO/RPO publication | publish targets; publish measurements | Publish measurements with method, date and environment. Targets (RTO 4h, RPO 15min) appear only as "provisional target" next to the measured value |
| 11 | Event data RPO | metadata geo-DR; data geo-replication; replay | Metadata geo-DR copies neither payloads nor RBAC and is insufficient for event-data RPO. Data geo-replication is GA on Premium and Dedicated only, Government support unverified. The runbook documents replay from the redacted archive and source producers as the compose-testable path, and lists geo-replication as an option requiring a live test |
| 12 | Evidence paths | single; split | Item 1: `docs/evidence/G07/load/`; item 4: `docs/evidence/G07/finops/`; item 5: `docs/evidence/G07/dr/`. Item 5 also owns the G07 row of `docs/RESEARCH-AND-GATES.md` |

## Context manifest

### Files that matter
- `PRP.md` - sections 1-3.
- `docs/PRD.md` - section 3 (scale, federation, retention, DR) and NS-07/NS-08 text.
- `docs/ARCHITECTURE.md` - ingestion, projection and deployment diagrams.
- `docs/RESEARCH-AND-GATES.md` - G07, G12; Event Hubs geo-DR and geo-replication findings (2026-07-11 and 2026-10-06).
- `docs/adr/0002-stack-pins.md` - azure-eventhub 5.15, azure-cosmos 4.17, Helm 4.3.
- `docs/DECISIONS-LOG.md` - D6, D7, D8, D9.
- `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.claude/hooks/config.ps1`, `.env.example`, `scripts/validate_planning.py`.
- Created by PRP-03: compose stack, sandbox generator (`sandbox/`), `scripts/sandbox/` seed and replay CLI.
- Created by PRP-05: `neurosphere_core.errors`, `.../scope/`, `.../paging/`, `.../clients/`, SLO doc `docs/ops/slo.md`.
- Created by PRP-07: ingest edge, normalizer, quarantine and replay CLI (`scripts/replay/`), redacted archive, cost ledger and outbox.
- Created by PRP-11: analytics adapter protocols and fixture adapter.
- Created by PRP-13: Dockerfiles, migration tooling (`packages/core/neurosphere_core/migrations/`).
- Created by PRP-14: hot aggregates worker and dashboards API; PRP-18 owns `tests/load/map_freshness/` and `docs/evidence/G07/map/` (do not write there).

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`; FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py`; async Azure SDK clients from `packages/core/neurosphere_core/clients`; error taxonomy exceptions from `neurosphere_core.errors` (`rate_limited` for throttling).
- Every federated and finops query takes an `IdentityScope`; no caller-supplied `domain_id` is trusted.
- Tests beside packages plus cross-package suites in `tests/`; `pytest.mark.integration` for compose, `pytest.mark.live` for real Azure; load profiles under `tests/load/`.
- Evidence JSON plus markdown, labelled with environment and method.

### Conventions
- ruff line 100, py312, S rules on; pyright standard; conventional commits; owned-file discipline.
- Evidence under `docs/evidence/G07/<area>/`; no live script is added by this PRP, enterprise and stress runs use the profile definitions directly at a target the operator names.
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
- PRP-specific: scale numbers are targets. The enterprise and stress rows say "subject to partition/cost validation"; a green pilot run on compose must not be reported as evidence for 10k or 50k events per second.
- PRP-specific: Event Hubs emulator is one namespace with ten hubs and no persistence; partition and consumer-group scale cannot be inferred from it.
- PRP-specific: noisy-neighbor and hot-key tests must include skew (one domain at a large multiple of the median) and permission-heavy multi-domain users, per PRD section 3 load test scope.
- PRP-specific: a restore drill proves a restore, not a failover. Failover/failback of Event Hubs requires checkpoint store, key and DNS checks on both sides and, for private endpoints, configuration on both sides.
- PRP-specific: Foundry does not provide automatic application disaster recovery or failover; the runbook must not imply the model endpoint fails over with the platform.
- PRP-specific: a forecast that cannot cite its price version, or mixes estimated with invoiced, is rejected by schema.

### External references
- Event Hubs data geo-replication (GA on Premium and Dedicated): https://learn.microsoft.com/azure/event-hubs/geo-replication (2026-07-11).
- Event Hubs metadata geo-DR (no payloads, no Entra RBAC; private endpoints both sides): https://learn.microsoft.com/azure/event-hubs/event-hubs-geo-dr (retrieved 2026-10-06).
- Foundry high availability (no automatic application DR): https://learn.microsoft.com/azure/foundry/how-to/high-availability-resiliency (retrieved 2026-10-06).
- Event Hubs emulator limits: https://learn.microsoft.com/azure/event-hubs/overview-emulator (2026-08-26).
- Cosmos DB vNext Linux emulator limits: https://learn.microsoft.com/azure/cosmos-db/emulator-linux (GA June 2026).
- Version pins: docs/adr/0002-stack-pins.md (observed 2026-10-08).

## Implementation blueprint

### Item 1 - load-suites  [P]
- Deliverable: locust suites for pilot, enterprise and stress profiles with hot keys, noisy neighbor and fan-out scenarios, evidence JSON writer.
- Owned files (may edit): `tests/load/profiles/`, `docs/evidence/G07/load/`.
- Must NOT touch: `tests/load/graph_benchmark/` (PRP-02), `tests/load/catalog_latency/` (PRP-10), `tests/load/map_freshness/` (PRP-18), `docs/evidence/G07/map/`, `docs/evidence/G07/finops/`, `docs/evidence/G07/dr/`, `packages/core/neurosphere_core/admission/`, root `pyproject.toml`, `docker-compose.yml`.
- Depends on: none.
- Acceptance criteria:
  - Pilot profile (1k events per second, 1k agents) completes against compose and writes evidence JSON with measured rate, p95, error count, environment label.
  - Enterprise and stress profiles are defined from the PRD numbers, parametrized by target host and duration, and refuse to start without an explicit target (no default to any cloud).
  - Skew scenario drives one domain at a configurable multiple of the median; permission-heavy multi-domain users included.
- Pattern references: sandbox generator from PRP-03; ingest edge contract from PRP-07.
- Tests to write: `tests/load/profiles/test_profiles_definition.py` (profile parameters match PRD numbers; no default target), `tests/load/profiles/test_pilot_compose.py` (`pytest.mark.integration`).

### Item 2 - admission-control  [P]
- Deliverable: `neurosphere_core.admission` with per-domain quota config, token-bucket limiter, backpressure signals, and an ASGI middleware factory usable by the ingest edge and query service.
- Owned files (may edit): `packages/core/neurosphere_core/admission/`.
- Must NOT touch: `services/api/neurosphere_api/ingest/` (PRP-07), `services/api/neurosphere_api/dashboards/` (PRP-14), `tests/load/profiles/`, `packages/core/neurosphere_core/errors/`, root `pyproject.toml`.
- Depends on: none.
- Acceptance criteria:
  - Noisy domain gets `rate_limited` with a retry hint; other domains remain within limits in a simulated-load test.
  - Missing quota config yields a conservative default and a logged warning, never unlimited.
  - Limiter keys include the derived domain from `IdentityScope`, not a caller field (test with a spoofed header).
- Pattern references: error taxonomy `rate_limited` (retryable flag); `IdentityScope` from PRP-05/PRP-06.
- Tests to write: `packages/core/tests/admission/test_limiter.py`, `packages/core/tests/admission/test_noisy_neighbor.py`.

### Item 3 - federation-summaries  [P]
- Deliverable: worker that computes scope-filtered per-cell aggregates and an API that merges authorized summaries across cells within one cloud boundary.
- Owned files (may edit): `services/workers/neurosphere_workers/federation/`, `services/api/neurosphere_api/federation/`.
- Must NOT touch: `services/workers/neurosphere_workers/aggregates/` (PRP-14), `services/api/neurosphere_api/dashboards/` (PRP-14), `packages/core/neurosphere_core/admission/`, `packages/core/neurosphere_core/auth/`, root `pyproject.toml`.
- Depends on: none.
- Acceptance criteria:
  - Summary excludes unauthorized identities, counts and costs (negative test with two domains and a restricted principal).
  - A cell outside the caller's cloud boundary is refused with `capability_unavailable`; no cross-cloud merge path exists (test).
  - Cache keys include a hash of the scope; revoked principals get 403 within the configured TTL.
- Pattern references: `require(permission)` from `neurosphere_api.authz`; worker runtime base from PRP-05.
- Tests to write: `services/workers/tests/federation/test_cell_summary.py`, `services/api/tests/federation/test_federation_scope.py`.

### Item 4 - finops-forecast  [P]
- Deliverable: forecast service over ledger aggregates and the evidence hooks that record forecast versus actual cost.
- Owned files (may edit): `services/api/neurosphere_api/finops/`, `docs/evidence/G07/finops/`.
- Must NOT touch: `packages/core/neurosphere_core/ledger/` (PRP-07), `packages/core/neurosphere_core/pricing/` (PRP-15), `services/api/neurosphere_api/dashboards/`, `docs/evidence/G07/load/`, `docs/evidence/G07/dr/`.
- Depends on: none.
- Acceptance criteria:
  - Forecast response carries price version id, estimated and invoiced as separate series, and an uncertainty band.
  - Unknown inputs return `unknown`, never 0; a forecast missing a price version is rejected by the response model.
  - Evidence hook writes forecast-versus-actual rows to `docs/evidence/G07/finops/` with environment label and no savings claim.
- Pattern references: cost record schema from PRP-01; pricing snapshot usage from PRP-15 (read-only).
- Tests to write: `services/api/tests/finops/test_forecast.py`, `services/api/tests/finops/test_unknown_not_zero.py`.

### Item 5 - backup-restore-and-failover  [P]
- Deliverable: per-store backup and restore scripts (Cosmos documents, blob archive, quarantine container, search index rebuild, checkpoint store), failover/failback runbook with checkpoint, key and DNS checks, and a restore drill harness that records measurements.
- Owned files (may edit): `infra/dr/`, `docs/ops/dr-runbook.md`, `docs/evidence/G07/dr/`, `tests/integration/dr/`, `docs/RESEARCH-AND-GATES.md` (G07 row only).
- Must NOT touch: `infra/bicep/`, `infra/helm/`, `infra/compose/` (PRP-03), `docker-compose.yml`, `scripts/replay/` (PRP-07), other rows of `docs/RESEARCH-AND-GATES.md`.
- Depends on: none.
- Acceptance criteria:
  - Restore drill on compose restores every store and verification queries match; measured restore time and recovery point gap are written to `docs/evidence/G07/dr/` with method and the label "compose, not representative of production".
  - Runbook states the Event Hubs metadata-DR caveat (no payloads, no RBAC), covers data geo-replication as a Premium/Dedicated-only option with Government unverified, and includes encryption-key retention and checkpoint-store checks.
  - RTO 4h and RPO 15min appear only as "provisional target" beside measured values.
- Pattern references: replay CLI and quarantine design from PRP-07; migrations runner from PRP-13.
- Tests to write: `tests/integration/dr/test_restore_compose.py` (`pytest.mark.integration`), `tests/integration/dr/test_runbook_caveats.py` (asserts required caveat strings exist).

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
python -m pytest packages/core/tests/admission services/api/tests/federation services/api/tests/finops services/workers/tests/federation
python -m pytest tests/load/profiles/test_profiles_definition.py
docker compose up -d --wait
python -m pytest -m integration tests/load/profiles/test_pilot_compose.py tests/integration/dr
```
Enterprise and stress profile runs are operator-run against a sized environment the operator names; they are not CI steps and no script in this PRP starts them implicitly.

## Live and open gates
- G07 (workload/SLO/DR): stays OPEN. This PRP supplies pilot evidence on compose (bounded feasibility, G12) and measured restore on compose; enterprise and stress profiles, real Event Hubs failover/failback and data geo-replication remain OPEN until an operator runs them in a sized environment.
- G12 (emulator parity): record rate ceilings and persistence limits of the emulators observed during the pilot run.
- G01: Event Hubs data geo-replication availability in Government is unverified; no evidence closes it here.
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Production-sized load runs, capacity guarantees, SLA or SLO commitments.
- Wiring admission control into the ingest edge and query service (follow-up with the PRP-07 and PRP-14 owners).
- Automatic model-endpoint failover (Foundry does not provide it).
- Multi-customer SaaS federation; cross-cloud federation of any kind.
- Savings claims or ML cost forecasting; recommendations (PRP-15).
- Government DR profiles (PRP-20 evidence applies).

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
- Measured values (pilot rate and p95, restore time, recovery point gap) with environment label:
- Enterprise/stress/failover runs: date and operator approval, or OPEN:
- Follow-ups (admission wiring, ADR-0002 locust licence row):
