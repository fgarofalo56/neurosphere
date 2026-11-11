# Copilot and report loop on the compose emulators (2026-11-11)

Scope: **emulator, bounded feasibility, not a live claim.** The composed API runs in-process
against the compose Cosmos emulator (127.0.0.1:8081, throwaway database) with the REAL authz, data,
planes, action-plane, reports and copilot builders. The model is the real `ApprovedEndpointAdapter`
built through `resolve_adapters` / `create_adapter` for Commercial, centralus, `model_gpt_4_1_mini`,
`Global Standard` (gating enabled it from the capability matrix; nothing stubbed). Its HTTP transport replays
hand-authored provider-format streams (`tests/integration/real_stack/fixtures/copilot_loop/`); the
credential is a static fake. Test: `tests/integration/real_stack/test_copilot_loop.py`
(`pytest.mark.integration`, never runs in CI).

## Steps

| Step | Outcome |
|---|---|
| 1 copilot status | ready ({'state': 'ready', 'reason_code': None}) |
| 2 data question + chart | 3 citations (freshness ['stale']), as_of == Cosmos updated_at, chart.query_spec present, 3 model calls |
| 3 evidence question | recommendation cited via get_evidence, as_of == Cosmos created_at (stale); evaluation evidence NOT seeded (the EvaluationStore protocol has no by-id read) |
| 4 action suggestion | intent 4e048d09.. fetched, state=drafted |
| 5 save as report | report 4c2e71d3.. created; owner run rows=3 |
| 6 share + viewer run | B sees 2 of 3 rows; domain B row filtered out |
| 7 revoke | B's run after unshare -> HTTP 404 |
| 8 no-access callers | C: denied (domain_out_of_scope) and abstain (no_authorized_evidence), no data; D without any grant: HTTP 403 before any turn |
| 9 audit | 9 records on chain synthco.loop-a-1fe82532 |

## Turns (SSE event names in order, wall time of the streamed response)

| Turn | Time | Events |
|---|---|---|
| 2 data question + chart | 172 ms | `context > tool x4 > token > citation x3 > chart > done` |
| 3 evidence question | 125 ms | `context > tool x2 > token > citation > done` |
| 4 action suggestion | 219 ms | `context > tool x2 > token > citation > action_suggestion > done` |
| 8a out-of-scope domain request (C) | 78 ms | `context > tool x2 > denied` |
| 8b empty readable scope (C) | 125 ms | `context > tool x2 > abstain` |

## Counts

- Seeded: 3 agents (2 in domain A, 1 in domain B), 1 recommendation in domain A.
- Audit records read from the Cosmos audit chain: 9 (action.draft/after, action.draft/before, report.run/after, report.run/denied, report.share/after, report.share/before, report.unshare/after, report.unshare/before).
- Whole loop: 1.3 s (seeding and all nine steps; app startup excluded).

## Gaps found

- evaluation_result evidence is not exercised: `StoreEvidenceReader` omits that kind because the shipped `EvaluationStore` protocol has no by-id read (`services/api/neurosphere_api/copilot/evidence.py::_evaluation`).

## NOT exercised

- A live model: the G05/G17 live gate stays OPEN (`NS_LIVE_APPROVED=1` not set; no paid calls).
  Recorded streams prove the adapter, engine, tools and API plumbing, not model quality.
- The Playwright UI (chat panel, report page).
- Azure Government: this is a Commercial row only.
- Real Entra tokens (a stand-in issuer signs them) and real RBAC on a hosted endpoint.
- Emulator limits (G12): no auth, no RU accounting, so latency and throttling are not representative.
