---
name: prp-17-action-executor-and-hitl
status: backlog
review: required
created: 2026-10-08
model: opus
phase: 3
ns: NS-04, NS-06
depends_on: PRP-04, PRP-06, PRP-09, PRP-10
wave: W6
absorbs: P3.2, P3.4, G05
---

# PRP-17: Action executor and human-in-the-loop workflow

## Goal
Ship the single durable action plane and the HITL workflow around it: an intent store and state machine, an executor worker that rechecks permission and target version at execution time, a maker-checker approval workflow with SLA timers and notification interfaces, the shared action and review-queue API, a Foundry model-swap write connector, and the reviewer and confirmation UI. It is for stewards, reviewers and agent owners who change real systems. It is Opus work with required review because it is the highest-risk code path (authorization, idempotency, rollback). It lands in W6 after identity (PRP-06), the write-connector interface (PRP-09) and the catalog (PRP-10). The copilot (PRP-19) and MCP (PRP-22) later reuse this executor unchanged.

> Route low-confidence relationships, disputed evaluations, recommendation reviews and policy exceptions to scoped reviewers. Persistent states: pending, assigned, approved, rejected, expired, escalated, executed and failed; SLA timers, reassignment, notifications and immutable decisions. Separate insight review from maker-checker approval of executable changes; prohibit self-approval where configured.

> The same action API serves copilot, recommendation buttons, REST and MCP. Recheck current resource permission and policy at execution; bind confirmation to target/version/diff and expiry. Idempotent execution, approvals, dry-run, audit before/after, canary, rollback and emergency disable are mandatory. External systems need a supported write connector and delegated credentials; unsupported actions are advisory, not catalog-only pretend changes.

Binding contract from PRP.md section 3:

> Action states: drafted -> validated -> awaiting_confirmation -> awaiting_approval -> executing -> succeeded/failed/rolled_back/expired. Intent contains actor, target/version, proposed diff, prerequisite results, evidence, confirmation hash/expiry and idempotency key. Execution rechecks permission/current target and delegates to a supported connector. Durable audit and safe recovery are part of the contract.

## Acceptance criteria
- [ ] Item 1: A duplicate request with the same idempotency key cannot double-execute; an expired confirmation is rejected; only allowlisted state transitions succeed.
- [ ] Item 2: Given a permission revoked after approval, When the executor runs, Then execution is blocked and audited; a failed verification triggers rollback and the rollback test passes; the emergency disable flag stops all execution.
- [ ] Item 3: A maker cannot approve their own change when policy forbids; an SLA breach escalates; decisions are immutable (update/delete rejected).
- [ ] Item 4: Draft, validate, confirm, approve and status endpoints and the review queue API all call the one executor; policy store outage returns 503.
- [ ] Item 5: A supported Foundry target is changed and verified in the operator-approved live gate; against a read-only or unsupported target the action is advisory and no state is changed anywhere.
- [ ] Item 6: A button action and the equivalent REST call produce an identical intent hash; confirmation dialog shows exact target, version, diff and expiry.
- [ ] PRP exit: items 1-6 green under `verify-gates -Mode full`; reviewer verifies no code path changes catalog metadata as a stand-in for a real change; G05 live status recorded.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet; opus | opus, review required (D6): authorization and irreversible-change risk |
| 2 | One executor or per-surface | per surface; one | One durable executor for button, chat, REST and MCP. All surfaces build an `ActionIntent` and compute the same intent hash over actor-independent fields (target, version, diff, prerequisites) plus expiry bucket; surfaces differ only in `source` metadata |
| 3 | Live gate | mock only; operator-approved live | Foundry swap live verification is operator-approved (D7) with `NS_LIVE_APPROVED=1` against the Commercial subscription. Without it G05 stays OPEN and the connector runs in advisory mode |
| 4 | Read-only connectors | execute anyway; advisory | Advisory: the intent can be drafted and reviewed but never executes, and nothing is changed in the catalog to simulate a change |
| 5 | Maker-checker | always; policy-configured | Policy-configured per action type; when self-approval is forbidden the maker cannot approve, and a second distinct approver with the right scope is required. Insight review (NS-04 reviewer queue) is separate from maker-checker approval of executable changes |
| 6 | Notifications | build full delivery; interface | A `Notifier` interface with stubbed email and Teams adapters that record sends to the audit log. Real delivery is out of scope |
| 7 | Timers | cron; durable timers | Durable timers in `hitl_timers` worker for assignment, SLA, escalation, reassignment and expiry; restart-safe from stored deadlines |
| 8 | Confirmation binding | token only; hash of diff | Confirmation hash binds target, version, diff and expiry; a changed target version invalidates it (`stale_version`) |
| 9 | Decision immutability | editable; append-only | Decisions are append-only with hash-chained audit via PRP-06 audit store; corrections are new records |
| 10 | Canary and rollback | optional; mandatory | Mandatory per NS-06: dry-run, canary, verify, rollback and emergency disable on every executable connector path |
| 11 | Government | assume parity; matrix-gated | Connector availability read from the capability matrix; Foundry write support in Government is unverified, so the action is disabled with reason there |
| 12 | Credentials | stored; delegated | Delegated credentials via vault reference or on-behalf-of; the executor never holds user secrets in intent records or logs |
| 13 | HITL queues for other PRPs | build per PRP; shared | One shared review queue API consumed by catalog conflicts (PRP-10), disputed evaluations (PRP-16), recommendation reviews (PRP-15) |

## Context manifest

### Files that matter
- `PRP.md` - section 3 (action states and intent fields, quoted above), sections 1-2.
- `docs/PRD.md` - NS-04 and NS-06 text; NS-03 model-swap sentence.
- `docs/ARCHITECTURE.md` - action plane and worker diagrams.
- `docs/RESEARCH-AND-GATES.md` - G05, G12, G01 rows; Foundry Government notes.
- `docs/adr/0002-stack-pins.md` - Python and frontend pins.
- `docs/DECISIONS-LOG.md` - D6, D7, D8, D11.
- `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.env.example`, `.claude/hooks/config.ps1`, `scripts/validate_planning.py`.
- Created by PRP-01: `packages/contracts/schemas/actions/` (`ActionIntent`, state enum, `ApprovalDecision`), `.../audit/`, `.../errors/`.
- Created by PRP-04: `frontend/src/design-system/`, `frontend/src/api/`, `frontend/src/auth/`.
- Created by PRP-05: `neurosphere_core.errors`, worker runtime base (graceful shutdown, checkpoints), `neurosphere_core.clients`.
- Created by PRP-06: `neurosphere_core.auth.scope`, `neurosphere_api.authz` (`require(permission)`), `neurosphere_core.audit`, `neurosphere_core.auth.revocation`.
- Created by PRP-09: `connectors/sdk-python/neurosphere_connector/write/` (`WriteConnector`: dry-run, apply, verify, rollback, advisory flag).
- Created by PRP-10: catalog repository, curation review-queue interface, `neurosphere_api.catalog.curation`.

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`, generated from `packages/contracts`.
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py` (`actions/`, `hitl/`).
- Async Azure SDK clients from `packages/core/neurosphere_core/clients`; error taxonomy exceptions from `neurosphere_core.errors` (`stale_version`, `forbidden`, `dependency_transient`, `capability_unavailable`).
- State machine as an explicit allowlist table; invalid transitions raise, they are never coerced.
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
- PRP-specific: the intent hash must not include the surface (button, chat, REST, MCP) or the actor session, or the same logical change hashes differently per surface. PRP-19 and PRP-22 tests assert equality against this PRP's hash.
- PRP-specific: recheck permission and target version at execution time, not only at confirmation. Approval is not a standing grant: revocation (PRP-06) between approval and execution must block.
- PRP-specific: idempotency keys are scoped per actor and intent; a retry after a crash in `executing` must resume through verify, not re-apply. Safe recovery means a restarted worker reads the stored state and never repeats a non-idempotent apply.
- PRP-specific: never change catalog metadata to represent a model swap. The only success evidence is verification against the target system through the connector.
- PRP-specific: a read-only connector reports `advisory=true`; the API must refuse `confirm` and `approve` transitions for advisory intents with `capability_unavailable`.
- PRP-specific: self-approval prohibition compares authenticated principal ids, not display names or session ids. Pseudonymized ids are still compared on the real principal server-side.
- PRP-specific: Foundry deployment-swap API behavior and Government availability are unverified. Do not invent request shapes; use only documented operations and record the exact API version used in the evidence file.
- PRP-specific: notification adapters are stubs. A recorded send is not proof of delivery; never mark an escalation as notified-and-read.

### External references
- Foundry models and Agent Service in Azure Government: docs/RESEARCH-AND-GATES.md "Infrastructure and tooling" (observed 2026-10-08 per the register).
- Cosmos DB hierarchical partition keys (intent store partitioning): https://learn.microsoft.com/azure/cosmos-db/hierarchical-partition-keys (observed 2026-04-27).
- Cosmos DB vNext Linux emulator limits (no sprocs or triggers, so no transactional batch logic outside documented APIs): https://learn.microsoft.com/azure/cosmos-db/emulator-linux (GA June 2026).
- MCP authorization and versioning (future consumer of this executor): https://modelcontextprotocol.io/specification/versioning (spec 2026-07-28, per docs/adr/0002-stack-pins.md).
- Stack pins: docs/adr/0002-stack-pins.md (observed 2026-10-08).

## Implementation blueprint

### Item 1 - action-state-machine  [P]
- Deliverable: durable intent store, allowlisted state machine (drafted to expired), idempotency key handling, and confirmation hash bound to diff, version and expiry.
- Owned files (may edit): `packages/core/neurosphere_core/actions/`.
- Must NOT touch: `packages/core/neurosphere_core/hitl/`, `services/workers/neurosphere_workers/actions/`, `services/api/neurosphere_api/actions/`, `packages/contracts/`, root `pyproject.toml`, `docker-compose.yml`, `docs/RESEARCH-AND-GATES.md`.
- Depends on: none.
- Acceptance criteria:
  - Duplicate request with the same idempotency key returns the original intent and cannot double-execute.
  - Expired confirmation is rejected; a changed target version invalidates the confirmation with `stale_version`.
  - Transitions outside the PRP.md section 3 allowlist raise; the intent hash is identical across `source` values.
- Pattern references: generated `ActionIntent`; errors taxonomy; ETag concurrency.
- Tests to write: `packages/core/tests/actions/test_state_machine.py`, `packages/core/tests/actions/test_intent_hash.py`, `packages/core/tests/actions/test_idempotency.py`.

### Item 2 - executor-worker
- Deliverable: executor that rechecks permission and target version, delegates to a connector, runs canary, verify and rollback, and honors an emergency disable flag.
- Owned files (may edit): `services/workers/neurosphere_workers/actions/`.
- Must NOT touch: `packages/core/neurosphere_core/actions/`, `services/workers/neurosphere_workers/hitl_timers/`, `services/workers/neurosphere_workers/runtime/`, `connectors/`, `services/api/`, root `pyproject.toml`.
- Depends on: Item 1.
- Acceptance criteria:
  - Permission revoked after approval blocks execution and writes a denied audit record.
  - Failed verify triggers rollback; rollback test passes; emergency disable stops execution without data loss.
  - Worker crash during `executing` resumes via verify and never re-applies (fault-injection test).
  - Audit records written before and after each apply.
- Pattern references: worker runtime base and checkpoint interface (PRP-05); `WriteConnector` protocol (PRP-09); revocation (PRP-06).
- Tests to write: `services/workers/tests/actions/test_recheck.py`, `services/workers/tests/actions/test_rollback.py`, `services/workers/tests/actions/test_crash_recovery.py`, `services/workers/tests/actions/test_emergency_disable.py`.

### Item 3 - hitl-workflow  [P]
- Deliverable: HITL domain logic and timers for assignment, SLA, escalation, reassignment and expiry; maker-checker; self-approval prohibition; immutable decisions; `Notifier` interface with stubbed email and Teams adapters.
- Owned files (may edit): `services/workers/neurosphere_workers/hitl_timers/`, `packages/core/neurosphere_core/hitl/`.
- Must NOT touch: `packages/core/neurosphere_core/actions/`, `services/workers/neurosphere_workers/actions/`, `services/api/neurosphere_api/hitl/`, `packages/contracts/`, root `pyproject.toml`.
- Depends on: none.
- Acceptance criteria:
  - Maker cannot approve their own change when policy forbids (compared on real principal id).
  - SLA breach escalates; timers survive a worker restart.
  - Decision update or delete is rejected; corrections are new records.
  - Stub adapters record sends to audit and perform no network calls.
- Pattern references: audit store (PRP-06); worker runtime base.
- Tests to write: `packages/core/tests/hitl/test_maker_checker.py`, `services/workers/tests/hitl_timers/test_sla_escalation.py`, `services/workers/tests/hitl_timers/test_restart_timers.py`.

### Item 4 - action-and-hitl-api
- Deliverable: shared action API (draft, validate, confirm, approve, status) and review queue API.
- Owned files (may edit): `services/api/neurosphere_api/actions/`, `services/api/neurosphere_api/hitl/`.
- Must NOT touch: `packages/core/neurosphere_core/actions/`, `packages/core/neurosphere_core/hitl/`, `services/api/neurosphere_api/catalog/`, `services/api/neurosphere_api/authz/`, root `pyproject.toml`.
- Depends on: Items 1, 3.
- Acceptance criteria:
  - Every route builds an `ActionIntent` and enters the single executor path; a test asserts no alternative execution path exists.
  - Advisory intents refuse `confirm` and `approve` with `capability_unavailable`.
  - Policy store outage returns 503; insufficient scope returns 403; review queue is scope-filtered.
- Pattern references: router per module; `require(permission)`; pagination models (PRP-05).
- Tests to write: `services/api/tests/actions/test_action_api.py`, `services/api/tests/hitl/test_review_queue.py`, `tests/security/actions/test_single_executor_path.py`.

### Item 5 - foundry-model-swap-connector  [P]
- Deliverable: write connector implementing the PRP-09 `WriteConnector` protocol for a Foundry deployment swap; advisory mode when the target is read-only or unsupported.
- Owned files (may edit): `connectors/reference/foundry-actions/`, `scripts/gates/g05_foundry_swap_live.py`, `docs/evidence/G05/`.
- Must NOT touch: `connectors/sdk-python/`, `connectors/reference/foundry/`, `services/workers/neurosphere_workers/actions/`, `docs/RESEARCH-AND-GATES.md` (G05 row update goes in the completion note, not this item).
- Depends on: none.
- Acceptance criteria:
  - Dry-run, apply, verify and rollback implemented; compatibility checks (capability, context, tools) precede apply.
  - Against a read-only credential the connector reports `advisory=true` and performs zero writes.
  - Operator-approved live gate changes a supported target and verifies it; evidence recorded under `docs/evidence/G05/`; script refuses without `NS_LIVE_APPROVED=1`.
- Pattern references: `WriteConnector` protocol; credentials as vault references.
- Tests to write: `connectors/reference/foundry-actions/tests/test_swap_connector.py`, `connectors/reference/foundry-actions/tests/test_advisory_mode.py`, `tests/unit/gates/test_g05_live_refuses.py`.

### Item 6 - review-and-action-ui
- Deliverable: reviewer queue, diff and confirmation dialog with expiry countdown, and action status views.
- Owned files (may edit): `frontend/src/features/actions/`, `frontend/src/features/review/`.
- Must NOT touch: `frontend/src/api/`, `frontend/src/design-system/`, `frontend/src/features/workspaces/`, `services/api/`, root `pyproject.toml`.
- Depends on: Item 4.
- Acceptance criteria:
  - Button action and REST call produce an identical intent hash (e2e test compares).
  - Dialog shows exact target, version, diff and expiry; expired or stale confirmation cannot be submitted.
  - Hidden controls are not relied on: a Viewer deep link to approve receives API 403 and a clear message.
  - Advisory actions show "advisory only" and no execute control; axe clean.
- Pattern references: Fluent UI v9; typed API client from PRP-04; error taxonomy mapping.
- Tests to write: `frontend/src/features/actions/actions.test.tsx`, `frontend/src/features/review/review.test.tsx`, `frontend/tests/e2e/actions.spec.ts`.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
docker compose up -d --wait
python -m pytest packages/core/tests/actions packages/core/tests/hitl services/workers/tests/actions services/workers/tests/hitl_timers services/api/tests/actions services/api/tests/hitl
python -m pytest -m integration tests/integration/actions
python -m pytest tests/security/actions
python -m pytest connectors/reference/foundry-actions/tests
pnpm --filter frontend test
pnpm --filter frontend exec playwright test frontend/tests/e2e/actions.spec.ts
NS_LIVE_APPROVED=1 python scripts/gates/g05_foundry_swap_live.py    # operator-approved, requires NS_LIVE_APPROVED=1
```

## Live and open gates
- G05 (model swap compatibility): item 5 live run, if approved, supplies evidence of a changed and verified supported target plus compatibility, regression, canary and rollback results; this NARROWS G05 for the tested target only. Without it G05 stays OPEN and production action execution is blocked per the register.
- G12 (emulator parity): record behavior of the intent store on the Cosmos emulator versus live (no sprocs or triggers, no RU accounting).
- G01: Foundry write support in Government is unverified; no evidence closes it here.
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Copilot-driven action drafting (PRP-19) and MCP action tools (PRP-22); they call this executor.
- Real email or Teams delivery; only stubbed adapters.
- Write connectors other than Foundry swap; GitOps, APIM and other connectors are later work.
- Automatic merging of duplicate agents (NS-03 forbids it).
- Recommendation generation (PRP-15) and evaluation scoring (PRP-16); they only enqueue reviews.
- Contract changes to `ActionIntent` or the state enum; request them through PRP-01.

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
- G05 live run: date, operator approval, evidence path (or OPEN):
- Follow-ups:
