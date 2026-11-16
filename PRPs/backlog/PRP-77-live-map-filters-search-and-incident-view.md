---
name: PRP-77-live-map-filters-search-and-incident-view
status: backlog
priority: P0
order: 68
review: required
created: 2026-11-16
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 7
ns: NS-05
depends_on: [PRP-74-live-map-topology-backend]
wave: W22
branch: prp-77-live-map-filters-search-incident
allow_parallel: true
issues: []
---

# PRP-77: Live map filters, search and incident view

## Goal
Make the live map usable for the two people the original PRD wrote it for. The architect narrows the map by node type, tag, environment, cloud provider and health and finds any node by name from a search box that jumps to it. The SRE selects a failing service (or a node that just turned failing) and sees every agent that depends on it highlighted, with the highlight kept current as telemetry and topology change. New nodes and edges appear without a reload because the client refetches when the server pushes a topology change. The accessible table gets the same filters, the same search and the same impact list, so nothing is mouse-only. The PRD's interaction-latency figure is measured here and the number is recorded with the hardware named. It is for the SRE, the architect and the keyboard and screen-reader user, and it runs in W22 on the PRP-74 routes.

Out of scope: every server route, node field, push message and the whole-graph search (PRP-74); the 50k-node browser target, which stays cluster-first and bounded by design (see clarification 1); the headed re-measure of frame rate and latency on operator hardware (PRP-66, which reads the evidence file this PRP defines); per-edge traffic overlays (no server field exists); the catalog entity page and its impact table (`frontend/src/features/catalog/**`, PRP-73 and PRP-76 own it); the copilot (PRP-78).

## Why
- Original PRD 5d (`git show 9fbf5f4c:docs/PRD.md`): "As an SRE, I want to see, during an incident, every downstream agent affected by a failing service, highlighted live." Today hover highlights one hop only (`frontend/src/features/map/renderer.ts:176-183`) and the map never calls an impact route; the SRE has to leave the map and read a depth-2 table (gap analysis 5d).
- Original 5d: "As an architect, I want to filter the map by environment (prod/staging) or cloud provider" and "Supports filtering/search by node type, tag, environment, health status." The toolbar holds only the table link, the reduce-motion switch, fit view and counts (`frontend/src/features/map/MapPage.tsx:347-371`); there is no filter and no search on the map or the table (`frontend/src/features/map-table/MapTablePage.tsx`).
- Original 5d: "Map updates within 5s of a graph-affecting telemetry event (push via WebSocket/SignalR)." The client applies a delta only to nodes it already holds and never refetches (`frontend/src/features/map/mapGraph.ts:391-398`), so a new agent or edge needs a reload even after PRP-74 pushes it. The delta also replaces a node's whole metrics object, so a delta that carries `context_size: null` blanks a known value (PRP-49 completion note).
- Original 5d: "Handles graphs of at least 50k nodes / 250k edges with acceptable pan/zoom performance (<200ms interaction latency)." Cut by v1.2: `docs/PRD.md` NS-05 "never download the full enterprise graph to a browser" (line 25) and "Browser target <=2k visible nodes at >=30fps on documented hardware, not 1M nodes rendered at once" (line 51). Gap analysis section 5 item 1 restates it: the server searches the whole graph (PRP-74), the browser stays at 2000 nodes, and interaction latency is measured and reported for that supported count. No interaction-latency measurement exists today; the only evidence is frame rate, 2000 nodes and 4000 edges, mean 38.6-41.8 fps and p5 24-30 fps on an RTX 5090 (`docs/evidence/G07/map/fps-run1..3.json`, `frontend/tests/e2e/map-perf.spec.ts`).
- NS-05 requires "text/table alternative, reduced motion, keyboard navigation and non-color status indicators" (`docs/PRD.md:26`): every new control and the impact highlight need a table and a text form, not color alone.

## Acceptance criteria
- [ ] Given the map, When the user sets node type, tag, environment, cloud or health in the filter bar, Then the viewport is refetched with the PRP-74 query parameters, counts and clusters reflect only matching nodes, the filters are in the URL (shareable, back button works), and a "N filters applied, clear all" control is present; an invalid tag is rejected in the field before a request.
- [ ] Given the search box, When the user types at least 2 characters, Then results come from the server search route (debounced, in-flight request cancelled on the next keystroke), are announced to screen readers (result count in a polite live region), are operable by keyboard (combobox: arrow keys, Enter, Escape), and show kind, environment and health as text; a result for a person shows the pseudonym only.
- [ ] Given a search result, When selected, Then the neighbourhood route is fetched, merged into the graph without exceeding the 2000-node client cap, the camera centres on the node, the node is selected and its panel opens; a result already on screen just selects and centres; the table view focuses the matching row.
- [ ] Given a selected node, When the user presses "Show impact" (or the keyboard shortcut documented in the panel), Then the impact route is called with a depth control 1 to 5 (default 2), every dependent node and edge on screen is highlighted and everything else is dimmed, the panel lists affected nodes by depth as text with their health, and nodes not currently on screen are listed with a "show on map" action; clearing restores the previous view.
- [ ] Given incident view is on for a node and a live delta turns it, or a node on its dependents list, to `failing`, Then the impact is recomputed (debounced 2 s) and the highlight and list update without user action, an aria-live polite message says how many dependents are affected, and a node that newly turns `failing` while selected starts the impact view automatically.
- [ ] Given a `topology` message for the subscribed domain, When `refetch` is true, Then the viewport (and every open cluster section) is refetched once per burst (debounced, not once per message), the camera and selection do not reset, and an existing node keeps its position; a new agent from the PRP-71 demo world appears within 5 s of the server message without a reload.
- [ ] Given a delta that omits a metric (null), Then the client keeps the last known value; given the model delta ids now match viewport ids (PRP-74), Then a model node's metrics update live. Both are asserted in `mapGraphDelta.test.ts`.
- [ ] Service, tool and MCP server nodes have their own shape and text label (non-color), and the legend explains them; an error-rate size option and a "recent errors" line in the node panel use the server facets; every status is conveyed by text or shape as well as color.
- [ ] Given the table view, Then it offers the same filters and search (same URL state), columns for kind, environment, cloud, health and error rate, an impact toggle that adds a depth column and filters to affected rows, and works by keyboard alone (existing `map-table-keyboard.spec.ts` still passes).
- [ ] Interaction latency: `map-latency.spec.ts` renders the 2000-node fixture and measures, over at least 30 samples each, the time from input event to the next painted frame for pan, wheel zoom, node hover, node click and "Show impact" highlight; it writes `docs/evidence/G07/map/interaction-latency.json` with p50, p95, max, sample counts, browser, headless or headed, GL renderer string, OS, CPU and RAM. The target 200 ms (p95) is asserted only with `NS_MAP_LATENCY_ENFORCE=1`; the committed file states the hardware and says whether the target held on it. No claim about 50k nodes is made anywhere.
- [ ] No new control is mouse-only; the axe sample for `/map` and `/map/table` passes with the filter bar open and the impact view on; reduced-motion keeps highlights without animation.
- PRP exit: `pnpm` typecheck, lint, unit and the touched Playwright specs pass; the recorded latency file is committed; PR open with CI green; visual baselines regenerated through the Docker flow (Tier 3).

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | The 50k-node criterion | Lift the 2000-node client cap; keep it and search server-side | Keep. The client never holds more than `NODE_BUDGET` (2000); search and filter go to the server (PRP-74). The latency number is reported for 2000 nodes only. Gap analysis section 5 item 1 |
| 2 | Where filter state lives | Component state; URL search params | URL search params, shared by map and table, so a filtered view can be shared and survives reload |
| 3 | Filter options | Hard-coded; from server counts | Node type, environment, cloud and health options come from the PRP-74 search `counts` for the domain; tags are a validated free-text token (the PRP-70 tag pattern) because no tag list route exists |
| 4 | "Downstream" for the highlight | Edges out; dependents | Dependents (what relies on the failing node), as PRP-73 and PRP-74 define it; panel text says "Depends on this node" |
| 5 | When incident view starts by itself | Always for any failing node; selected node only | ASSUMPTION: only for the selected node or a node the user pinned, so the map never jumps under the user. A banner offers "Show impact" for any other node that turns failing |
| 6 | Jump to a node that is not on screen | Page the cluster; neighbourhood route | Neighbourhood route (PRP-74), merged under the node cap; if the merge would exceed the cap the farthest unselected leaf nodes of the previous view are dropped and the response `truncated` is shown |
| 7 | Latency method | Browser performance API only; input-to-paint with double rAF | Input event to the second `requestAnimationFrame` after dispatch, via Playwright, same fake-gateway harness as `map-perf.spec.ts`; the number is hardware-specific, recorded always, asserted only when enforced |
| 8 | New node kinds in old clients | Break; tolerate | The client treats an unknown kind as a generic node with its label, so a server one release ahead never blanks the map |
| 9 | Mock API location | Edit `server.ts`; new feature module | New `frontend/tests/mock-api/features/map-topology.ts` registered in `features/index.ts` (other lanes list `server.ts` as must-not-touch); it answers search, neighbourhood, impact and a viewport with facets for one new fixture domain and passes every other request through |

## Context manifest

### Files to read first
- `frontend/src/features/map/MapPage.tsx` - state, toolbar (`:347-371`), expansion, live updates, node panel wiring.
- `frontend/src/features/map/mapGraph.ts` - `parseNode`, `upsertNodes`, `applyDelta` (`:391-398`), `METRICS_ONLY_KINDS`, caps.
- `frontend/src/features/map/renderer.ts` - node and edge reducers, hover dimming (`:61-183`) to reuse for impact.
- `frontend/src/features/map/realtime.ts` - `ServerMessage` switch (`:80-210`); add `topology`.
- `frontend/src/features/map/hooks.ts`, `types.ts`, `strings.ts`, `Legend.tsx`, `NodePanel.tsx`, `appearance.ts` - hooks, wire types (hand-mirrored), labels, legend, panel, shapes.
- `frontend/src/features/map-table/MapTablePage.tsx`, `MapGrid.tsx`, `hooks.ts`, `strings.ts` - the table alternative.
- `frontend/tests/e2e/map-perf.spec.ts` - fake gateway, fixture domain, hardware recording; `frontend/tests/mock-api/server.ts:861-1040` map fixtures (read only).
- `frontend/tests/mock-api/features/context.ts` and `index.ts` - how a feature mock registers.
- `PRPs/backlog/PRP-74-live-map-topology-backend.md` ("Interfaces provided") and `PRPs/shipped/PRP-18-live-map-and-session-replay.md`, `PRP-49-per-agent-aggregates-and-map-metrics.md` completion notes.
- `frontend/src/features/catalog/explorerHooks.ts:155-164` - `useImpact` (reference only; the map uses the map impact route).

### Interfaces consumed
- PRP-74 (shipped by the time this runs): `GET /api/v1/map/domains/{domain_id}/viewport` with `node_type`, `tag`, `environment`, `cloud`, `health` parameters; `GET .../search` (`SearchResponse`: `matches`, `counts`, `truncated`, `truncation_reason`, `coverage`); `GET .../neighborhood/{node_id}`; `POST .../impact` (`ImpactResponse` with `levels`); `ViewportNode.facets`; node kinds `service`, `tool`, `mcp_server`; the realtime message `type: "topology"`.
- PRP-70: `MapNodeFacets` and `MapTopologyChange` shapes (TypeScript exports of `@neurosphere/contracts`, names as in PRP-70 "Interfaces provided"; used for the facet and change types, with the map response wrappers hand-written in `types.ts` like today).
- PRP-71: the `demo-world` incident (failing service, downstream agents) for the real-stack check.
- Shipped: `useApiClient`, `createQueryHook`, the Fluent UI v9 components and `useUiStyle`, `STRINGS` pattern, `ConfigContext` for the realtime URL.

### Interfaces provided
- Frontend modules `frontend/src/features/map/filters/` (`useMapFilters` URL hook, `FilterBar`), `search/` (`useMapSearch`, `SearchBox`), `impact/` (`useImpact` for the map route, `ImpactPanel`, `impactState`), shared by map and map-table.
- Test ids for later specs: `map-filter-bar`, `map-search`, `map-search-result`, `show-impact`, `impact-list`, `impact-banner`.
- Evidence file `docs/evidence/G07/map/interaction-latency.json` (schema documented in the runbook) that PRP-66 re-measures on operator hardware.
- Mock module `frontend/tests/mock-api/features/map-topology.ts` and a fixture domain constant `DOMAIN_MAP_INCIDENT`.

### Patterns to match
- Realtime message switch and reconnect: `realtime.ts:80-210`.
- Dimming reducer state: `renderer.ts:111-133,166-183`.
- Feature mock module and its unit test: `frontend/tests/mock-api/features/admin-sources.ts`, `admin-sources.test.ts`.
- Playwright specs with fake gateway and recorded hardware: `frontend/tests/e2e/map-perf.spec.ts`; keyboard spec: `map-table-keyboard.spec.ts`.
- Accessible combobox in this codebase: grep `Combobox` under `frontend/src/features/` and reuse the Fluent pattern already used there.

### Gotchas
- Fluent dialog and popover tests flake on Tabster `aria-hidden`; query with `hidden: true` in unit tests (memory: frontend test gotchas).
- `MapGraph.upsertNodes` assumes cluster and member attributes from the viewport; a node merged from the neighbourhood route must keep its `cluster_id` or the cluster counts drift. Test both paths.
- Sigma crashes jsdom through the map index; unit tests use the existing `map.test.tsx` mocks, and real rendering is covered by Playwright only.
- Headless Chromium uses a software GL renderer (SwiftShader), so recorded latency in CI is not product evidence; the file says `headless` and the renderer string. Never commit a number without its hardware.
- Playwright `reuseExistingServer` crosses worktrees: set unique `NS_E2E_APP_PORT` and `NS_MOCK_API_PORT` for this lane.
- Visual baselines come from the Docker flow only; do not commit locally generated screenshots.
- `pnpm` through MSYS: do not set `MSYS_NO_PATHCONV` for pnpm commands.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - frontend/src/features/map/**
  - frontend/src/features/map-table/**
  - frontend/tests/mock-api/features/map-topology.ts
  - frontend/tests/mock-api/features/map-topology.test.ts
  - frontend/tests/e2e/map-perf.spec.ts
  - frontend/tests/e2e/map-latency.spec.ts
  - frontend/tests/e2e/map-live/**
  - frontend/tests/e2e/map-table-keyboard.spec.ts
  - docs/evidence/G07/map/interaction-latency.json
  - docs/runbooks/live-map.md
tier1: []
tier2_appends:
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - frontend/tests/real-stack/routes.spec.ts
  - mkdocs.yml
must_not_touch:
  - packages/contracts/**
  - services/**
  - packages/core/**
  - frontend/src/features/catalog/**
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/workspaceNav.ts
  - frontend/tests/mock-api/server.ts
```

## Implementation blueprint

Parallelization: item 1 first. Items 2 and 3 edit different new directories but both touch `MapPage.tsx` wiring, so they are sequenced; item 5 (table) can run beside item 4 only after 2 and 3. No item is marked parallel.

### Item 1 - Wire types, delta correctness, new kinds and live refetch
- Deliverable: `types.ts` (new kinds, `facets`, search, neighbourhood, impact and topology types, `error_rate` size metric); `parseNode` tolerant of unknown kinds and facets; `applyDelta` keeps the last known non-null metric values; shapes, labels and legend entries for service, tool and MCP server (non-color); `realtime.ts` handles `topology` and exposes `onTopology`; `MapPage` refetches the top level and open clusters once per burst, preserving camera, selection and positions; node panel "recent errors" and facet lines.
- Owned files: `frontend/src/features/map/{types,mapGraph,realtime,appearance,strings,Legend,NodePanel,MapPage,hooks}.ts*`, `mapGraphDelta.test.ts`, `map.test.tsx`.
- Must NOT touch: `frontend/src/features/catalog/**`, `server.ts`.
- Depends on: PRP-74 shipped.
- Acceptance criteria: delta, topology, unknown-kind, new-kind and error-metric criteria; the existing map unit tests pass.
- Tests: `pnpm --filter @neurosphere/frontend exec vitest run src/features/map`.
- Pattern references: `mapGraph.ts:391-398`, `realtime.ts:80-210`.

### Item 2 - Filter bar and shared URL state
- Deliverable: `map/filters/` with `useMapFilters` (URL params, validation, clear all), `FilterBar` (Fluent controls, counts from search `counts`, labelled, keyboard-operable), the viewport hook sends filter parameters and keys its cache by them; the table reads the same hook.
- Owned files: `frontend/src/features/map/filters/**`, `map/hooks.ts`, `map/MapPage.tsx` (toolbar slot), tests beside the new files.
- Must NOT touch: `map-table/**` yet.
- Depends on: item 1.
- Acceptance criteria: filter criterion; invalid tag blocked; filters survive reload and back button.
- Tests: `frontend/src/features/map/filters/filters.test.tsx`.
- Pattern references: `map-table/hooks.ts`, the toolbar in `MapPage.tsx:347-371`.

### Item 3 - Search with jump-to-node
- Deliverable: `map/search/` with `useMapSearch` (debounce, abort previous), `SearchBox` combobox, result row text, neighbourhood fetch and merge under the 2000 cap, camera centre and select, announcements.
- Owned files: `frontend/src/features/map/search/**`, `mapGraph.ts` merge helper (item 1 owns the file; this item adds one method only after item 1 merged), `MapCanvas.tsx` camera method.
- Depends on: items 1 and 2.
- Acceptance criteria: search criteria and jump criterion; cap respected; pseudonym only for people.
- Tests: `frontend/src/features/map/search/search.test.tsx`, `mapGraphMerge.test.ts`.
- Pattern references: `MapCanvas.tsx` camera handle, `mapGraph.ts` `upsertNodes`.

### Item 4 - Incident view (impact highlight, live)
- Deliverable: `map/impact/` with the map-route impact hook, `impactState` (affected node and edge sets, per-depth lists), renderer reducer extension reusing the hover dim state, `ImpactPanel` text list with "show on map", depth control, auto-start for the selected node that turns `failing`, banner for other failing nodes, debounced recompute on delta and topology, aria-live messages, reduced-motion safe.
- Owned files: `frontend/src/features/map/impact/**`, `renderer.ts`, `NodePanel.tsx` (button slot), `strings.ts`.
- Depends on: items 1 and 2 (3 not required).
- Acceptance criteria: impact and incident criteria; highlight is not color-only (ring plus text list).
- Tests: `frontend/src/features/map/impact/impact.test.tsx`, `impactState.test.ts`.
- Pattern references: `renderer.ts:111-133,166-183`.

### Item 5 - Table alternative parity
- Deliverable: filters, search and the impact toggle in `MapTablePage`; columns kind, environment, cloud, health, error rate, and depth when impact is on; row focus on a search result; strings.
- Owned files: `frontend/src/features/map-table/**`.
- Depends on: items 2, 3 and 4.
- Acceptance criteria: table criterion; `map-table-keyboard.spec.ts` unchanged and green.
- Tests: `frontend/src/features/map-table/map-table.test.tsx` (extended), `frontend/tests/e2e/map-table-keyboard.spec.ts`.
- Pattern references: existing `MapGrid.tsx` keyboard handling.

### Item 6 - Mock API, e2e and accessibility
- Deliverable: `map-topology.ts` mock (search, neighbourhood, impact, a viewport with facets for `DOMAIN_MAP_INCIDENT`, incident health flip on a control hook) with its unit test; e2e specs in `frontend/tests/e2e/map-live/` (filter, search jump, incident highlight with a live health flip, topology push via the fake gateway, table parity); a11y samples updated.
- Owned files: `frontend/tests/mock-api/features/map-topology.ts`, `map-topology.test.ts`, `frontend/tests/e2e/map-live/**`.
- Tier-2: `features/index.ts`, `a11y/route-samples.ts`.
- Depends on: items 1-5.
- Acceptance criteria: e2e covers each user story; axe passes with the bar and impact open; no flaky waits (use web-first assertions).
- Tests: `pnpm --filter @neurosphere/frontend exec playwright test tests/e2e/map-live` with unique ports.
- Pattern references: `map-perf.spec.ts` fake gateway, `admin-sources.test.ts`.

### Item 7 - Interaction-latency measurement
- Deliverable: `map-latency.spec.ts` (pan, zoom, hover, click, impact highlight; at least 30 samples each; input to second rAF), a writer that adds hardware and renderer metadata to `docs/evidence/G07/map/interaction-latency.json`, an enforce switch `NS_MAP_LATENCY_ENFORCE=1` (p95 <= 200 ms), a headed switch like `NS_MAP_PERF_HEADED`; one real run on this machine committed with its hardware, whatever the number; `map-perf.spec.ts` untouched except sharing helpers.
- Owned files: `frontend/tests/e2e/map-latency.spec.ts`, `frontend/tests/e2e/map-perf.spec.ts` (helper extraction only), `docs/evidence/G07/map/interaction-latency.json`.
- Depends on: items 1-4.
- Acceptance criteria: latency criterion; the file says plainly if the target did not hold or ran headless.
- Tests: the spec itself.
- Pattern references: `map-perf.spec.ts` (hardware capture, fps window).

### Item 8 - Integration and close-out
- Deliverable: Tier-2 lines; runbook section in `docs/runbooks/live-map.md` (PRP-74 created it): filters, search, incident view, the latency file schema and how PRP-66 re-measures; regenerate Tier-3 (visual baselines through Docker, `PRPs/INDEX.md`, status table); changelog fragment under `changelog.d/`; completion note with the recorded latency and hardware.
- Owned files: Tier-2 lines, the runbook, this PRP file, Tier-3 per reference section 6.
- Depends on: items 1-7.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend exec vitest run src/features/map src/features/map-table tests/mock-api
NS_E2E_APP_PORT=5287 NS_MOCK_API_PORT=5288 pnpm --filter @neurosphere/frontend exec playwright test tests/e2e/map-live tests/e2e/map-table-keyboard.spec.ts tests/e2e/map-reduced-motion.spec.ts tests/e2e/a11y
NS_E2E_APP_PORT=5287 NS_MOCK_API_PORT=5288 pnpm --filter @neurosphere/frontend exec playwright test tests/e2e/map-latency.spec.ts
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Real-stack check (local, emulators, not CI): `make demo-up` (PRP-71), open `/map`, filter to production, search a service, run impact on the failing service, confirm the downstream agents highlight and a newly registered agent appears without reload.

## Migration and rollback
None: no stored data, no setting. URL params are additive. Rollback: revert the PR; the map returns to the PRP-18 behaviour (the server routes of PRP-74 stay in place and are harmless). The latency evidence file is a committed artifact and stays as history.

## Live and open gates
Nothing here needs `NS_LIVE_APPROVED=1`. OPEN and handed to PRP-66 (G07): the headed re-measure of frame rate and interaction latency on operator hardware, and a latency run against a real hosted API. The committed number is from this session's hardware and must be reported as exactly that; the 200 ms figure is reported as met or not met on that hardware only, never as a 50k-node result.

## NOT building
A 50k-node browser rendering mode or a raised client cap; client-side search over a downloaded graph; per-edge traffic overlays; a saved-views feature; the entity page changes (PRP-73, PRP-76); the copilot "show me on the map" tool (PRP-78); any server change; any claim that the map meets the original 50k-node criterion.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (row 5 is an ASSUMPTION; the PRP-74 route shapes in "Interfaces consumed" now match PRP-74 "Interfaces provided" exactly)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | types, delta fix, new kinds, topology refetch |
| 2 | todo | | filter bar, URL state |
| 3 | todo | | search and jump-to-node |
| 4 | todo | | incident view |
| 5 | todo | | table parity |
| 6 | todo | | mock API, e2e, a11y |
| 7 | todo | | interaction-latency measurement and evidence |
| 8 | todo | | Tier-2, runbook, Tier-3, close-out |

## Completion note (filled at ship)
- Date, PR, merge commit:
- Deviations from the blueprint and why:
- Descoped items:
- OPEN gates (headed and hosted re-measure via PRP-66):
- Env vars for the operator (`NS_MAP_LATENCY_ENFORCE`, `NS_MAP_PERF_HEADED`):
- Recorded interaction latency (p95 per interaction) and hardware:
- Follow-up issue numbers:
- Product check (can an SRE find the failing service and see its dependents highlighted without leaving the map?):
