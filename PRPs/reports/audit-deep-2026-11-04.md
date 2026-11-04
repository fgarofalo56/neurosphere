# Deep PRP audit 2026-11-04

Scope: all 35 PRPs, one read-only agent each, acceptance criteria vs code. Static reading only: no agent ran tests or the app, so "met" means the code and a test that asserts it exist, not that they pass or work live. The earlier `audit-2026-11-03.md` was an evidence/process audit and is superseded where they differ.

Result: 20 PRPs reopened to `PRPs/backlog/` (each has an `## Audit 2026-11-04` section with file:line gaps); 15 stay shipped.

## Reopened (priority, order)

| PRP | P/order | Headline gap |
|---|---|---|
| 07 telemetry ingestion + cost ledger | P0/5 | Ingest edge returns 503 in compose and hosted (`NS_INGEST_PRODUCERS_FILE` never set); data only via sandbox seed |
| 06 identity, authz, audit | P0/6 | Denials not audited in the composed app (`denial_recorder` is None); no SIEM export; no push revocation |
| 17 action executor + HITL | P1/1 | Live Foundry swap (G05) never ran; HITL store in-memory only |
| 22 MCP server + client | P1/1 | Server off unless `NS_MCP_RESOURCE_SERVER_URL` set; MCP writes advisory only; weak injection corpus |
| 33 APIM observe | P1/1 | Gateways UI is a 59-line stub; G17 observe OPEN; poll worker opt-in |
| 34 APIM manage | P1/2 | Connector has no production caller; cost-center attribution unmet; manage UI mock-only |
| 16 agent evaluation + quality | P1/3 | Offline benchmark and calibration never run (`run_pipeline` has no caller); only a fixture judge |
| 05 API/worker runtime + self-observability | P1/7 | SLO metrics/traces/export never wired; lifecycle and actions roles inert |
| 08 deployment intelligence + IaC | P1/8 | No UI; scan off by default (`NS_SCAN_ENABLED`); Fabric provisioner unwired |
| 10 catalog + relationships | P1/9 | Search not composed; catalog starts empty (worker only makes edges) |
| 19 copilot + reports | P1/10 | Copilot disabled by default (503); evidence reader empty; save-from-chat not built |
| 25 docs site + assistant | P1/11 | Site has only home + ADRs; assistant is a stub model and deployed nowhere |
| 31 missing UI surfaces | P1/12 | Never run against the real API; deferred pages not built |
| 15 recommendations | P1/13 | Computed from sandbox files only; hosted image lacks the data mounts |
| 20 Government verification | P1/14 | Sovereign profile read by no running code; no live Government evidence |
| 09 connector SDK + reference connectors | P2/4 | OTel/Foundry/billing connectors have no runtime caller; kit never run on a real connector; #46 row loss |
| 11 analytics adapters | P2/15 | No real Fabric/Synapse/Databricks client; nothing selects an adapter |
| 18 live map + replay | P2/16 | Per-node metrics null; 15 s viewport; fps below target at p5; replay never on real storage |
| 21 scale, federation, FinOps, DR | P2/17 | Pilot load run failed every threshold; admission control unwired; single in-process cell |
| 23 ATO evidence + data lifecycle | P2/18 | Lifecycle engine has empty targets and no jobs; no lifecycle API |

## Stayed shipped (small gaps to track)

- 00: `git grep "|| true"` prints 3 annotated lines in workflows; CI proof for the mermaid check is local only; no CI check on carried-forward licence rows.
- 01: additive-only versioning rule is prose, no baseline test; Pydantic does not enforce cross-field rules (82/226 invalid examples accepted); hand-written `frontend/src/features/audit/types.ts`.
- 02: completion note stale on G03 (live evidence exists); most matrix rows are generic `ga_status: unverified`.
- 03: cold-start time unmeasured; devcontainer build never run.
- 04: real MSAL never run against a real tenant; placeholder `config.json` in a plain build.
- 12: threat-model rows stale (cites `packages/core/tests/mcp/test_ssrf.py`; real path `mcp_core/`); same unwired denial recorder as PRP-06.
- 13: docs-assistant image has no publish path; `CHANGELOG.md:262` `TODO(operator)`; GHCR packages public.
- 14: composed, but browser e2e is mock-only; compose e2e OPEN.
- 24: `validateLogo` has no runtime caller; a11y checklists unsigned; G09 waived.
- 26: claims reviewed by an agent only; stale manifest lines.
- 27: MP4 is local-only (gitignored); scenes S03/S05/S06 narrated not drawn.
- 28: `/workspaces/{role}` returns `items=[]`; cost tile uses days=7 not 1.
- 29: write registry empty (#132); lifecycle inert; catalog search has no backend; #104 still open.
- 30: all visual/demo evidence is mock-API; map canvas masked in baselines.
- 32: S10 teardown OPEN (#144); S6 partial; `RESEARCH-AND-GATES.md:46-47` stale.

## Root causes (fixing these clears most reopened gaps)

1. **No real data path.** Ingest edge unconfigured (07), catalog starts empty (10), recommendations read sandbox files (15), no price table. Pages are empty or seed-fed.
2. **Write side inert.** Empty `WriteTargetRegistry` in API and workers (`planes.py:189-195`, `factories.py:427-430`, #132): no model swap, cap change or publication can happen (17, 22, 33, 34).
3. **Features off by default / unconfigured.** MCP server, scan, copilot, ingest, lifecycle, telemetry export (22, 08, 19, 07, 23, 05).
4. **Mock-only end-to-end.** Playwright's only web server is the mock API; no page (31, 14, 18, 19, 30...) has run against the real API.
5. **Search has no backend.** `_NoSearch` in the composed app (10, 31).
6. **Security audit holes.** Denials unaudited, no SIEM, no push revocation (06, 12).
7. **Live gates OPEN.** G05, G17, G04, G02 and others have never run live (need `NS_LIVE_APPROVED=1`).

## Audit method caveats

- Agents read bounded slices; some "no non-test caller" claims were spot-checked by the orchestrator (one was partly wrong and corrected: PRP-22 MCP is composed in `planes.py:355` and `builders/mcp.py:106` but off by default; PRP-16's `run_pipeline` is genuinely uncalled).
- Nothing here was executed. Next step for confidence is to run the real-stack Playwright config against the composed app.

## Suggested fix order

Roots 1 + 2 + 5 as one "runtime composition" effort first (ingest config, write registry, search backend), then 06 audit holes, then UI/real-stack e2e, then the live gates under operator approval.
