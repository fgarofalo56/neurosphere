---
name: PRP-75-find-an-agent-ui-and-recommendation-metrics
status: active
started: 2026-11-21
priority: P0
order: 66
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 7
ns: NS-03, NS-05
depends_on: [PRP-72-agent-and-tool-recommender-backend]
wave: W24
branch: prp-75-find-an-agent-ui
allow_parallel: true
issues: []
---

# PRP-75: "Find an agent" page and recommendation metrics

## Goal
Give a person a place to type a task, see ranked agents and tools with a score, a confidence and a readable explanation (matched tags, graph relationships, telemetry signals), follow links to the entity and the map, and accept or reject each candidate. A small metrics strip shows the acceptance rate, so the original "recommendation acceptance rate" metric is visible instead of invisible, and a metadata-completeness tile appears when PRP-76 provides the endpoint. It is for the operations lead and platform engineer from original feature 5c, on the Quality navigation group, built against the mock API first and then covered on the real stack. It runs in W24 on top of PRP-72 (routes and contract types from PRP-70).

Out of scope: the matcher, feedback store and routes (PRP-72); tags, capabilities and the completeness endpoint (PRP-70 and PRP-76); the copilot tool and any chat entry point (PRP-78); changing the existing detector recommendations pages; live-map overlays (PRP-77); any invocation of the chosen agent.

## Why
- Original PRD 5c, `git show 9fbf5f4c:docs/PRD.md` lines 59-69. Story: "As an operations lead, I want the system to suggest which agent to invoke for 'summarize this support ticket.'" Story: "As a platform engineer, I want recommendations ranked with an explanation (why this agent was suggested)." Criteria: "Returns ranked list of candidate agents with confidence score and explanation referencing graph relationships/telemetry signals." and "Supports feedback loop (accept/reject) that retrains/adjusts ranking." Metric (line 17): "Recommendation acceptance rate (operator picks suggested agent/tool) > 60%". A backend with no screen satisfies none of these for a person.
- v1.2 demoted it: `docs/PRD.md:21` "Agent/tool selection is an optional secondary recommendation capability, not the product's primary purpose." The owner decision of 2026-11-16 restores it as a visible page.
- Today `/recommendations` lists operational findings only; there is no box to type a task into (gap analysis 5c; `frontend/src/features/recommendations/routes.tsx` has two routes, list and detail). The only action is "Route to review" (`RecommendationDetailPage.tsx`).
- The feature-page conventions are in place: `hooks.ts` builds domain-addressed paths with `createQueryHook` and `createMutationHook` and the shared client refuses `domain_id` as a parameter (`hooks.ts:11-24`); pages use `useSelectedDomain`, `PageTemplate`, `EmptyState`, `LoadingState`, `QueryErrorState`.
- Every route needs a manifest entry, an axe sample, a mock handler and a real-stack row or the suites fail (`frontend/tests/e2e/a11y/route-samples.ts` header; `frontend/src/app/route-manifest.test.ts`; `frontend/tests/real-stack/routes.spec.ts:270-274` for the recommendations rows).

## Acceptance criteria
- [ ] Given the mock API and a selected domain, When a user types a task and submits, Then ranked cards render best first, each showing name, kind, `score`, the API-local `confidence` (PRP-72), and an explanation list with one row per `AgentMatchSignal` (`signal`, observed or not (`value` null = unobserved), `weight`, `contribution`), the graph relationship path when present, and links to `/catalog/entity` and the map.
- [ ] Given an unobserved telemetry signal, Then the card says "no telemetry yet" and shows the cold-start label; a card never shows 0 for an unknown value.
- [ ] Given a candidate, When the user clicks Accept or Reject, Then the mutation posts to the feedback route once, the button state reflects the stored decision, the decision can be changed, a failure keeps the previous state and shows the error, and focus stays on the card.
- [ ] Given a response with `truncated` or a `partial_reason`, Then the page says results are partial and shows the reason; given `cold_start` or `signals_unavailable` it names the unobserved signals; given no candidates it shows an empty state that suggests broader wording or a domain filter; given a 403 or 503 it shows the shared error state with the reason code.
- [ ] Given the metrics endpoint answers, Then the strip shows matches, accepts, rejects and acceptance rate (shown as "no feedback yet" when null, never 0 percent); the text states that the rate is an outcome to observe, not a target met. Given the PRP-76 completeness endpoint is absent (404 or capability_unavailable), Then the completeness tile shows "not available" and nothing else breaks.
- [ ] Given the page, Then it is keyboard operable end to end, passes axe in light, dark and high-contrast themes, announces result count and partial state in a live region, and the explanation is available as text (not color alone).
- [ ] The route `/recommendations/find` is in `route-manifest.json`, the Quality nav group, the a11y route samples, the mock-api handler registry and the real-stack route list; the existing recommendations list and detail routes are unchanged.
- [ ] Real-stack coverage: against the composed local stack with seeded tagged agents (PRP-71), a task returns at least one candidate and accepting it persists across reload; if no tagged seed exists the spec reports the gap rather than skipping silently.
- [ ] No task text is written to the URL, local storage, logs or analytics; the form state lives in component memory only.
- PRP exit: `pnpm` typecheck, lint, unit, e2e (mock-api) and a11y specs pass; visual baselines for the new page are produced by the Docker flow; PR open with CI green.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where it lives | New top-level route; under recommendations | `/recommendations/find` under the recommendations feature, nav label "Find an agent" in the Quality group next to Recommendations. |
| 2 | Domain handling | Own selector; shared selector | Shared `useSelectedDomain`; the match is always for the selected path domain (PRP-70 `AgentMatchRequest` has no domain filter, PRP-72 adds none), so there is no "search other domains" control. |
| 3 | Completeness tile | Require PRP-76; optional | ASSUMPTION: optional. PRP-76 runs in the same wave and may not be merged; the tile degrades to "not available" and is wired by a typed hook that treats 404 and `capability_unavailable` as absent. |
| 4 | Task text persistence | URL param; memory only | Memory only (privacy; task text can name internal systems). A reload clears the form; the last result is not restored. |
| 5 | Feedback optimism | Optimistic; confirmed | Confirmed: the button changes after the 202, because feedback adjusts shared ranking and a silent failure would mislead. |
| 6 | Hosted deployment | Here; PRP-82 | PRP-82 (hosted profile everything on) deploys it; this PRP ships mock and local real-stack coverage only. |

## Context manifest

### Files to read first
- `frontend/src/features/recommendations/RecommendationListPage.tsx` - page layout, form, `useSelectedDomain`, empty and error states.
- `frontend/src/features/recommendations/hooks.ts` - path builders and the query and mutation hook factories (no `domain_id` parameter).
- `frontend/src/features/recommendations/routes.tsx` and `index.ts` - route objects and nav items to extend.
- `frontend/src/features/recommendations/components.tsx`, `strings.ts`, `types.ts` - shared pieces and string table.
- `frontend/src/features/recommendations/__tests__/fixtures.tsx`, `list.test.tsx`, `pages.a11y.test.tsx` - test construction to copy.
- `frontend/src/app/appRoutes.ts`, `workspaceNav.ts`, `route-manifest.json` and `route-manifest.test.ts` - registries and the check that enforces them.
- `frontend/tests/mock-api/features/index.ts`, `context.ts` and `finops.ts` - feature mock handlers; `frontend/tests/mock-api/server.ts:439-640` for the existing recommendation mock.
- `frontend/tests/e2e/recommendations/recommendations.spec.ts`, `frontend/tests/e2e/a11y/route-samples.ts`, `frontend/tests/real-stack/routes.spec.ts:250-290`.
- PRP-72 "Interfaces provided" and PRP-70 "Interfaces provided" for the response shape.

### Interfaces consumed
- PRP-72: `POST /api/v1/recommendations/domains/{domain}/match`, `POST .../match/feedback`, `GET .../match/metrics`; permission `data.read`; response fields `truncated`, `partial_reason` (`limit`|`timeout_ms`), `cold_start`, `signals_unavailable`; error code `capability_unavailable`; candidate `confidence` and the metrics response are PRP-72 API-local models (`match_models.py`, in `openapi.json`), not PRP-70 contracts.
- PRP-70 TypeScript exports: `AgentMatchRequest`, `AgentMatchResponse`, `AgentMatchCandidate`, `AgentMatchSignal`, `AgentMatchFeedbackRequest` (decision `accepted`|`rejected`, `reason_code`); metrics and `confidence` come from PRP-72's OpenAPI (the frontend mirrors them in `types.ts`; names follow PRP-70 and are checked by the existing contract-sync test if one covers frontend types, otherwise by the mock handler's validation).
- PRP-76 (optional, same wave): a metadata-completeness endpoint; consumed through one hook that tolerates its absence.
- Shipped: `useSelectedDomain`, the shared API client, `PageTemplate`, `QueryErrorState`, catalog entity route `/catalog/entity` and the map route.

### Interfaces provided
- Route `/recommendations/find`; nav item "Find an agent".
- Components `FindAgentPage`, `MatchCandidateCard`, `ExplanationList`, `MatchMetricsStrip` exported from `frontend/src/features/recommendations/match`.
- Hooks `useAgentMatch` (mutation, since it posts text), `useMatchFeedback`, `useMatchMetrics`.
- Mock module `frontend/tests/mock-api/features/agent-match.ts` with exported fixture constants (task text, candidate ids) that later specs can import.
- Test ids `match-task-input`, `match-submit`, `match-candidate`, `match-accept`, `match-reject`, `match-metrics`.

### Patterns to match
- Page with form and result grid: `RecommendationListPage.tsx:30-60`.
- Mutation hook with typed vars: `hooks.ts:63-69` `useRouteToReview`.
- Feature mock registered by a single import line: `frontend/tests/mock-api/features/index.ts:14-30`.
- Route sample and ready selector: `frontend/tests/e2e/a11y/route-samples.ts:30-60`.
- Live region and focus handling after a mutation: the review route action in `RecommendationDetailPage.tsx`.

### Gotchas
- `/recommendations/find` sits under the existing `recommendations` prefix; the router and any nav active-state logic must not treat it as the detail route (`recommendations/detail`). Check `route-manifest.test.ts` ordering.
- The mock dispatch order matters: add the new handler before any handler that answers `/api/v1/recommendations/**` broadly, or the old `recommendationHandler` in `server.ts` will swallow `/match` (it matches `^/api/v1/recommendations/domains/([^/]+)(/.*)?$`). Put the match paths ahead of it through the feature registry, not by editing `server.ts`.
- Fluent dialog tests need `hidden: true` role queries (Tabster aria-hidden); visual baselines are Docker-only, do not commit locally generated ones.
- `MSYS_NO_PATHCONV` breaks the pnpm shim on this machine; run frontend commands without it.
- Headless fps and WebGL do not matter here, but axe runs per theme: the explanation list must not rely on color for observed versus unobserved.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - frontend/src/features/recommendations/match/**
  - frontend/tests/mock-api/features/agent-match.ts
  - frontend/tests/mock-api/features/agent-match.test.ts
  - frontend/tests/e2e/agent-match/**
  - docs/runbooks/agent-match-ui.md
tier1: []
tier2_appends:
  - frontend/src/features/recommendations/routes.tsx
  - frontend/src/features/recommendations/index.ts
  - frontend/src/app/route-manifest.json
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - frontend/tests/real-stack/routes.spec.ts
  - mkdocs.yml
must_not_touch:
  - frontend/src/features/recommendations/RecommendationListPage.tsx
  - frontend/src/features/recommendations/RecommendationDetailPage.tsx
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/workspaceNav.ts
  - frontend/tests/mock-api/server.ts
  - packages/contracts/**
  - services/**
  - frontend/tests/e2e/visual/__screenshots__/**
```

## Implementation blueprint

Parallelization: items 1 and 2 [P] (typed hooks and the mock share no file). Item 3 needs 1; item 4 needs 3; item 5 needs 2 and 4; item 6 last.

### Item 1 - Types, hooks and strings  [P]
- Deliverable: `match/types.ts` (request, candidate, signal explanation, feedback, metrics, mirroring PRP-70), `match/hooks.ts` (`useAgentMatch`, `useMatchFeedback`, `useMatchMetrics`, `useMatchCompleteness` that returns `absent` on 404 or `capability_unavailable`), `match/strings.ts`. Paths are built with `encodeURIComponent` on the domain; no `domain_id` or `customer_id` is ever a parameter.
- Owned files: `frontend/src/features/recommendations/match/{types,hooks,strings}.ts`, `match/__tests__/hooks.test.ts`.
- Must NOT touch: the existing `hooks.ts`.
- Depends on: PRP-72 merged.
- Acceptance criteria: hooks refuse scope claims as parameters (same guard as the shared client); `absent` handling covered; strings table has no hard-coded text in components.
- Tests: `match/__tests__/hooks.test.ts`.
- Pattern references: `recommendations/hooks.ts`.

### Item 2 - Mock API module  [P]
- Deliverable: `agent-match.ts` handler answering the three routes with deterministic fixtures: a cold-start candidate, a telemetry-rich one, a graph-proximity one, a partial response variant triggered by a fixed task text, a 403 for the viewer persona and a 404 for the completeness path; feedback is stored in module memory per principal so accept then reload shows the decision; one registration line in `features/index.ts` placed before the generic recommendations handler.
- Owned files: `frontend/tests/mock-api/features/agent-match.ts`, `agent-match.test.ts`, `features/index.ts` (one import and one list line).
- Must NOT touch: `frontend/tests/mock-api/server.ts`.
- Depends on: PRP-70 merged.
- Acceptance criteria: fixtures validate against the PRP-70 schema in the test; unknown or out-of-domain ids give 403; the registry test (`registry.test.ts`) still passes.
- Tests: `frontend/tests/mock-api/features/agent-match.test.ts`, `registry.test.ts`.
- Pattern references: `features/finops.ts`, `features/admin-sources.test.ts`.

### Item 3 - Page and components
- Deliverable: `FindAgentPage` (form, submit, live-region status, result list, empty, partial and error states), `MatchCandidateCard`, `ExplanationList` (signal table with text labels for observed state), accept and reject controls with confirmed state, `MatchMetricsStrip` and the completeness tile; component unit tests including the a11y test.
- Owned files: `match/{FindAgentPage,MatchCandidateCard,ExplanationList,MatchMetricsStrip}.tsx`, `match/index.ts`, `match/__tests__/*.test.tsx`.
- Must NOT touch: shared design-system files.
- Depends on: item 1.
- Acceptance criteria: criteria 1-6 and 9 at component level; no raw task text in `localStorage`, URL or `console` (asserted); focus returns to the card after feedback.
- Tests: `match/__tests__/page.test.tsx`, `card.test.tsx`, `metrics.test.tsx`, `pages.a11y.test.tsx`.
- Pattern references: `RecommendationListPage.tsx`, `RecommendationCard.tsx`, `__tests__/pages.a11y.test.tsx`.

### Item 4 - Route, nav and manifest
- Deliverable: route `recommendations/find` and nav item added in `recommendations/routes.tsx` and exported from `index.ts` (they flow into `appRoutes.ts` and `workspaceNav.ts` through the existing spreads, so those files are not edited); `route-manifest.json` regenerated with `/recommendations/find`.
- Owned files: `frontend/src/features/recommendations/routes.tsx`, `index.ts` (Tier-2 lines), `frontend/src/app/route-manifest.json`.
- Must NOT touch: `appRoutes.ts`, `workspaceNav.ts`.
- Depends on: item 3.
- Acceptance criteria: `route-manifest.test.ts` passes; the nav shows "Find an agent" once under Quality; the detail route still resolves.
- Tests: `frontend/src/app/route-manifest.test.ts`, the shell e2e spec.
- Pattern references: other features' `routes.tsx`.

### Item 5 - e2e, a11y and real-stack coverage
- Deliverable: `frontend/tests/e2e/agent-match/agent-match.spec.ts` (mock API: submit, explanation, accept, reject, partial, error, completeness absent), the a11y sample row, the real-stack row (type a task against the local stack, expect a candidate, accept, reload, expect persisted decision; reports "no tagged seed" as a failure with a clear message), and a visual spec entry list for the Docker baseline flow (baselines are produced by the Docker job, not committed here).
- Owned files: `frontend/tests/e2e/agent-match/**`, `route-samples.ts` and `real-stack/routes.spec.ts` (Tier-2 lines).
- Must NOT touch: `frontend/tests/e2e/visual/__screenshots__/**`.
- Depends on: items 2 and 4.
- Acceptance criteria: mock-api e2e and a11y pass in all three themes; the real-stack row is registered and passes on the local stack when PRP-71 and PRP-72 are present; use unique `NS_E2E_APP_PORT` and `NS_MOCK_API_PORT` values when running next to other worktrees.
- Tests: `pnpm` e2e project for `agent-match`, `routes.a11y.spec.ts`, `routes.spec.ts` (real-stack, local only).
- Pattern references: `frontend/tests/e2e/recommendations/recommendations.spec.ts`.

### Item 6 - Integration and close-out
- Deliverable: rebase, Tier-2 lines, short runbook `docs/runbooks/agent-match-ui.md` (what the explanation means, what the acceptance rate is and is not), changelog fragment under `changelog.d/`, regenerated Tier-3 files per reference section 2 (visual baselines come from the Docker job), completion note with screenshots of the page on mock and real stack and the product check.
- Owned files: Tier-2 lines, the runbook, this PRP file.
- Depends on: items 1-5.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
pnpm --dir frontend typecheck
pnpm --dir frontend lint
pnpm --dir frontend test -- src/features/recommendations src/app/route-manifest.test.ts tests/mock-api
pnpm --dir frontend exec playwright test tests/e2e/agent-match tests/e2e/recommendations tests/e2e/a11y/routes.a11y.spec.ts
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Local real-stack check (not CI): bring the stack up, run `playwright.real-stack.config.ts` for the new row with unique ports.

## Migration and rollback
No data or schema change; the page only calls PRP-72 routes. Rollback: revert the PR, or remove the route object and nav item (the manifest test then requires removing the manifest line). When the backend reports `capability_unavailable` the page shows the shared error state and nothing else is affected.

## Live and open gates
No live call. Open: hosted deployment and the signed-in hosted smoke of this page (PRP-82, operator-attended), the acceptance-rate outcome (observed, never claimed), and an accessibility sign-off by a person (parked project-wide).

## NOT building
Chat entry point; automatic invocation or deployment of the chosen agent; editing weights in the UI; saved searches or history of past tasks; export of results; changes to existing recommendation pages; embedding or semantic controls.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (row 3 is an ASSUMPTION; PRP-70 and PRP-72 names are provisional until they merge)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | worktree-agent-a948ce11391fd9979 | sonnet; 03b65e28, merge 5944ae3b; vitest recommendations+mock-api 87 passed, typecheck+lint clean; 2026-11-21 |
| 2 | merged | worktree-agent-a6e9aeaedbba3f785 | sonnet; 816023f2, merge e62fe667; vitest tests/mock-api 44 passed; 2026-11-21 |
| 3 | merged | worktree-agent-acc66c8d695642f74 | sonnet; fbf8a506, merge cabf7263; vitest 203 passed, typecheck+lint clean; 2026-11-21 |
| 4 | merged | worktree-agent-acc66c8d695642f74 | sonnet; fbf8a506, merge cabf7263; pytest runtime_routes+docs+marketing 257 passed; shell.test.tsx nav list also updated; 2026-11-21 |
| 5 | merged | worktree-agent-ae17bd52611bf486b | sonnet; ac3e3ec8, merge d0476e9f; playwright agent-match+recommendations+shell+full a11y 445 passed; real-stack browser (CI mode) 64 passed after orchestrator fix (domain loop, task text, stand-in NS_SEARCH_PROVIDER=fixture); 4 Docker baselines 8fcd326d; 2026-11-21 |
| 6 | verifying | prp-75-find-an-agent-ui | runbook+changelog+mkdocs 7a3575cf; review APPROVE (no blockers), rounding follow-up c99c7ca1; PR and CI pending; 2026-11-21 |

Plan deltas approved 2026-11-21: (a) the real match response is PRP-72 `AgentMatchView` `{match, assessments[], confidence_note}`, and confidence and cold_start join from `assessments` by `entity_id`; (b) "persists across reload" is checked through the metrics strip's accept count, because no route reads a stored decision back; (c) ownership extension: `frontend/tests/mock-api/features/registry.test.ts` (item 2), `services/api/tests/runtime_routes/manifest_calls.py`, `services/api/tests/runtime_routes/test_manifest_routes_serve.py`, `tests/integration/real_stack/test_manifest_routes.py` (count 57 to 58, item 4), `frontend/tests/e2e/shell.spec.ts`, `frontend/tests/e2e/visual/visual.spec.ts` plus 4 Docker-generated baselines under `__screenshots__` (item 5).

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can a person use it): type a task on the local stack, read the explanation, accept a candidate, reload:
