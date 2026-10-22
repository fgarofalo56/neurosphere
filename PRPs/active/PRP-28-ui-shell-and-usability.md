---
name: prp-28-ui-shell-and-usability
status: active
started: 2026-10-22
branch: prp-28-ui-shell-and-usability
review: required
priority: P1
created: 2026-10-22
model: sonnet
phase: 5
ns: NS-08, NS-10
depends_on: PRP-04, PRP-06, PRP-14, PRP-17, PRP-18, PRP-19
wave: W8
absorbs: new
---

# PRP-28: UI shell and usability

## Goal
Turn the frontend from a set of working but bare feature pages into a usable product shell. Analysts, stewards, agent owners and evaluators should be able to open NeuroSphere and find their way without knowing a domain id. It ships five things:
- A Fluent UI v9 app shell: header, grouped permission-aware side navigation and a shared page template.
- A domain switcher fed by a new server endpoint that lists the caller's readable domains, carried across pages.
- A role-aware overview home page with summary tiles.
- Fluent controls in place of native form elements on every existing page.
- A one-command local demo (`pnpm demo`) that runs the UI against the mock API with stubbed sign-in.

It also implements the real `GET /api/v1/workspaces/{role}`, which today only the mock serves. It lands before PRP-24, because PRP-24's accessibility audit and theme packs should audit and brand the finished shell, not the current one.

Evidence for the gap, captured 2026-10-22 against the mock API (screenshots in `temp/shots/`, not committed):
- The navigation is a raw bulleted list.
- Browser-default inputs, selects and buttons appear on every page.
- Every data page is empty until the user types an exact id such as `commercial:e2e:sandbox:domain:finance` into a text box.
- The home page is a title and one line.
- Running the UI locally points it at `http://localhost:8000` through `frontend/public/config.json`. Nothing is running there, so every data call fails unless the Playwright config swap is reproduced by hand.

## Acceptance criteria
- [ ] Item 1: `GET /api/v1/me/domains` returns exactly the domains in which the server-derived `IdentityScope` holds `data.read`, as `{items: [{domain_id, display_name, display_name_source: catalog|derived, cloud, permissions[]}]}`.
  - Domains of another customer or cloud are never returned (test).
  - A caller with no readable domain gets 403 (`require(data.read)`).
  - The route inventory test stays green, and caller-supplied `domain_id`/`customer_id` query or body values are ignored.
- [ ] Item 1: `GET /api/v1/workspaces/{role}` decides access from server-derived roles with an explicit mapping (`viewer`, `analyst`, `steward`->`domain_steward`, `admin`, `auditor`->`security_auditor`).
  - Unknown role -> 404; role not held -> 403 `forbidden`; held -> 200.
  - The 200 body has the shape the frontend workspaces feature and the mock already use (additive only).
  - `frontend/tests/e2e/hidden-route.spec.ts` semantics hold against the real API in a test.
- [ ] Item 2: every route renders inside one shell:
  - A header with the product name, `LogoSlot` and a user menu showing the role, plus sign out.
  - A side navigation with groups Overview / Cost & usage / Agents / Quality / Governance / Reports, keeping the `navigation` landmark named "Primary" and the existing link names ("Cost dashboard", "Reconciliation", "Actions", "Review", "Quality", "Recommendations", "Reports", "Map", "Map table", "Trace replay", "Workspace").
  - A skip link to `main`, and a page template (`PageHeader` + toolbar + content).
  - Nav entries the caller cannot use are hidden, while a deep link to a hidden route still gets the API's 403 (hidden-route spec green).
- [ ] Item 2: the domain switcher shows the `/me/domains` list (display name, with id fallback labelled "name unavailable").
  - Selecting one updates `?domain_id=` on the current page and on every nav link.
  - The last selection is stored in `localStorage` as the domain id only, under `ns.lastDomain.<pseudonymous user key>`. It is cleared on sign-out and restored only if still in the list; otherwise the first readable domain is used.
  - A 403 from `/me/domains` shows "No domains are assigned to you".
  - No token or other data is written to `localStorage` (test).
- [ ] Items 4-7: no feature page renders its own domain text box any more.
  - A static test finds 0 native `<input>`, `<select>`, `<button>` and `<textarea>` in non-test `.tsx` under `frontend/src/features/**` and `frontend/src/app/**`, except an explicit allowlist (the PRP-18 treegrid in `map-table/MapGrid.tsx`, and anything listed with a reason in the test).
  - Every feature page uses the page template.
  - Existing accessible names that specs query (for example the labels in `frontend/tests/e2e/actions/actions.spec.ts:50-53`) are unchanged.
- [ ] Item 8: the home page shows tiles for the selected domain:
  - **Cost total:** from `GET /api/v1/dashboards/domains/{d}/cost?days=1`, per currency, never summed across currencies, with estimated/incomplete badges.
  - **Pending review:** from `.../review/domains/{d}/items?state=pending`.
  - **Awaiting confirmation or approval:** from `.../actions/domains/{d}/intents` for those two states.
  - **Map coverage:** from `.../map/domains/{d}/viewport?node_budget=1`.
  - **Recent reports:** from `.../reports/domains/{d}/reports`.

  Each tile:
  - links into its feature with `domain_id`;
  - shows "N+" when a list is paged (no endpoint returns totals), and "unknown" or "not loaded" instead of 0 when data is missing;
  - shows its own error state without breaking the others.

  The page makes at most 7 bounded API calls.
- [ ] Item 3: `pnpm demo` from the repo root starts the mock API and the app in a `demo` Vite mode wired to the mock with stub sign-in, and prints the URL.
  - A persistent "Demo data, mock API" banner shows on every page.
  - A test over a production `vite build` output finds no demo banner string, no stub sign-in module and no `demo` mode branch.
  - A test asserts `frontend/Dockerfile`, `frontend/nginx.conf` and `infra/helm/**` carry no demo flag.
  - `docs/dev/local-setup.md` documents it.
  - The CI frontend job `timeout-minutes` is raised from 15 to 25, with the reason noted in the workflow.
- [ ] Axe (with the documented Fluent tabster-dummy exclusion) reports 0 violations on the shell, the home page and every feature page in Playwright. Keyboard: the skip link, nav, domain switcher and user menu are operable.
- [ ] PRP exit: all items green under `verify-gates -Mode full`; the full frontend Vitest and Playwright suites green; reviewer confirms that `/me/domains` and `/workspaces/{role}` derive scope server-side only, and that demo mode cannot ship.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Relationship to PRP-24 | separate PRP first; fold into PRP-24; separate and parallel | Separate PRP-28 first; PRP-24 gains `depends_on: PRP-28` so its audit and theme packs land on the finished shell |
| 2 | Order | P1 next (before PRP-20); wave order; P2 after PRP-20 | `priority: P1`, next ahead of PRP-20 |
| 3 | Domain list source | new `GET /api/v1/me/domains`; token claims; static config | New server endpoint from the server-derived `IdentityScope`, plus the mock |
| 4 | Carrying the domain | URL + remember last; global store only | `?domain_id=` stays the source of truth; the shell injects it into nav links; last-used remembered |
| 5 | Home page | role-aware tiles; static launcher; reuse workspace page | Role-aware summary tiles from existing bounded endpoints; unknown never 0 |
| 6 | Navigation | grouped + permission-aware; grouped show-all; flat | Grouped and permission-aware; hidden is not authorization, the API still denies |
| 7 | Demo mode | `pnpm demo` dev-only; plus compose profile; docs only | `pnpm demo`, dev-only, banner, tested never to ship |
| 8 | Restyle depth | shell + Fluent controls everywhere; shell + new pages; full overhaul | Shell, page template and Fluent controls on every page; feature behaviour and data logic untouched; custom visual identity stays PRP-24 |
| 9 | Workspaces endpoint | out of scope; implement here | Implement the real `GET /api/v1/workspaces/{role}` here |
| 10 | Review | required; none | `review: required` (new scope-sensitive endpoints; stub sign-in must never reach production) |
| 11 | Last-domain storage vs PRP-04 rule C8 ("sessionStorage only; no localStorage", written for tokens) | localStorage id only; sessionStorage; no persistence | `localStorage`, domain id only, keyed by a pseudonymous user key, cleared on sign-out. C8 is clarified as governing tokens and auth state; this PRP adds that note to `frontend/src/auth/msal.ts` |
| 12 | `/me/domains` for a caller with no readable domain | `require(data.read)` -> 403; authenticated-only 200 [] | `require(data.read)` -> 403; no authz-model or route-inventory change; the UI explains it |
| 13 | Domain display names | catalog name with id fallback; label parsed from id | Catalog `display_name` read server-side under the caller's scope; fallback to a readable label derived from the id, flagged `display_name_source: derived` |
| 14 | Workspaces access | server roles + explicit map; permission-based | Server-derived roles with an explicit frontend-to-backend role map; 403 on mismatch |

## Context manifest

### Files that matter
- `frontend/src/app/App.tsx:40-69`: config load, router and provider nesting.
- `frontend/src/app/main.tsx:22-42`: `e2e` stub import gated on `MODE`; flat `appRoutes` list.
- `frontend/src/app/routes.tsx`:
  - `:6-9`: `NavItem {to,label}`, flat, with no group or permission field.
  - `:20`: `DEFAULT_NAV`.
  - `:22-29`: `HomePage`.
  - `:40-84`: `makeLayout` (raw logo div `:50`, `nav aria-label="Primary"` `:52`, inline-styled links `:56-65`, `main#main-content` `:72`, `CopilotDock` mount `:78-80`).
- `frontend/src/app/workspaceNav.ts:2-39`: nav built from feature **index** imports. These pull in heavy modules; see Gotchas.
- `frontend/src/app/Providers.tsx:25-29` (theme > auth > query). `frontend/src/app/config.ts:6-12,35,68-106` (`AppConfig`, `devDefaults` gated on `env.DEV`, `loadConfig` fetching `/config.json` no-store).
- `frontend/public/config.json`: `apiBaseUrl` `http://localhost:8000`, the local trap.
- `frontend/src/design-system/AppThemeProvider.tsx:14` (`FluentProvider` applied); `LogoSlot.tsx`; `ThemeGallery.tsx` (mounted nowhere); `index.ts:5`. There is no global CSS and no `PageHeader` component.
- `frontend/src/auth/msal.ts:20-21` (`sessionStorage`, C8 comment); `frontend/src/auth/useRoles.ts:14-18`; `frontend/src/auth/roles.ts:8` (frontend role names).
- `frontend/src/api/client.ts:46,65,94`: `FORBIDDEN_SCOPE_KEYS = {domain_id, customer_id}` enforced on query and body. Domain goes in the path, never the query.
- `frontend/src/features/workspaces/personas.ts:3,12-50`: `WORKSPACE_PROBE_BASE`, `probePath`, personas. Also `ForbiddenState`, which five features import.
- Pages reading `domain_id`, each with its own text box + Apply form:
  - `dashboards/DashboardPage.tsx:73,92-119`
  - `reconciliation/ReconciliationPage.tsx:190,237-240`
  - `reports/ReportsListPage.tsx:79,102-108`
  - `quality/QualityPage.tsx:153,173-176`
  - `review/ReviewQueuePage.tsx:107,130-149`
  - `actions/ActionsPage.tsx:107,129-139,194`
  - `recommendations/RecommendationListPage.tsx:91,121-133`
  - `map/MapPage.tsx:380-397` (`DomainForm`)
- Pages reading `domain_id` with only a "domain required" message: `map-table/MapTablePage.tsx:306`, `replay/ReplayPage.tsx:111`, `recommendations/RecommendationDetailPage.tsx:136`, `reports/ReportViewPage.tsx:89`, `review/ReviewItemPage.tsx:220`, `actions/ProposeSwapPage.tsx:18`, `copilot/requestContext.ts:82`.
- Native controls: 57 in non-test `.tsx` (21 button, 15 input, 9 select, 11 table, 1 textarea). The heaviest are actions, quality, recommendations, review, reports, dashboards, and `ReviewItemPage.tsx:137` (textarea). Copilot, charts and workspaces have none.
- `frontend/tests/mock-api/server.ts`:
  - `:25-28`: ports, token prefix, `WORKSPACE_PATH`.
  - `:61-70`: `mockPublicConfig`.
  - `:80,84`: `DOMAIN_OK`, `DOMAIN_FORBIDDEN`.
  - `:1895-2052`: `createMockApi`, the CORS echo `:1901-1909`, the handler chain, and the workspace stub `:2033-2052`.
  - No `/me/domains` handler exists yet.
- `frontend/tests/e2e-support/fixtures.ts:8-15` (`/config.json` interception); `frontend/tests/e2e-support/stubMsal.ts:11-12,37`; `frontend/playwright.config.ts:3-4,21-34` (ports and the two webServers).
- `frontend/Dockerfile` (plain `vite build`), `frontend/nginx.conf:31-35` (`/config.json` no-cache, deploy-time mount), `infra/helm/values.yaml:101-104`, `infra/helm/templates/deployment.yaml`.
- `services/api/neurosphere_api/routers.py:16-40,106-109,166-185`: registry, hook pattern, `REGISTERED` tuple.
- `services/api/neurosphere_api/reconciliation/router.py:28-72`: template read-only router (`PREFIX`, `require(...)`, `build_router`, `register`). `health/router.py:45-68`: minimal shape.
- `services/api/neurosphere_api/authz/dependencies.py`:
  - `:118-122`: `current_scope`, authentication only; not enough for the route inventory.
  - `:164-209`: `require`. With no resource it means "holds anywhere" (`:175-177`).
- `services/api/neurosphere_api/authz/routes.py:1-12` and `test_route_inventory.py`: every non-public route must declare a permission.
- `packages/core/neurosphere_core/scope/identity_scope.py:19`. `packages/core/neurosphere_core/auth/scope/permissions.py`:
  - `:51-57`: backend roles.
  - `:59-72`: permissions.
  - `:135-148`: `domains_with_permission`.
  - `:151-186`: `permits`.
- Catalog `display_name`: `packages/contracts/python/neurosphere_contracts/catalog/v1/domain.py:64`. The catalog router lives at `/catalog`, outside `/api/v1` (`services/api/neurosphere_api/catalog/router.py:93,150-165`). Read names through the catalog repository server-side, not over HTTP.
- `services/api/neurosphere_api/openapi_export.py:17`; `services/api/tests/test_openapi_drift.py:6-10`.
- Overview tile sources:
  - `services/api/neurosphere_api/dashboards/router.py:98-99`; `dashboards/models.py:47-51,79-86,100-113`.
  - `hitl/router.py:66-79`; `hitl/models.py:88-92`.
  - `actions/router.py:54-63,117-128`; `actions/models.py:156-160`.
  - `map/router.py:46,65-100`; `map/models.py:31,66-70`.
  - `reports/router.py:80-105`; `reports/models.py:112,119-123`.
- `docs/PRD.md:46` (role workspaces); `PRPs/shipped/PRP-04-frontend-shell-design-system-auth.md:49` (C8).
- `.github/workflows/ci.yml:46-49`: frontend job `timeout-minutes: 15`. It ran about 10.5 min on PR #87 and was cancelled at the limit on a slow runner for PR #88.

### Patterns to match
- Router per module with `PREFIX`, `build_router`, `register(registry)`, `require(Permission.X, resource=domain_from_path(...))`: `services/api/neurosphere_api/reconciliation/router.py:28-72`.
- Pydantic v2 response models with `ConfigDict(extra="forbid")`: `services/api/neurosphere_api/hitl/models.py:49`.
- Feature folder shape: `routes.tsx` (`*Routes`, `*NavItems`), a path-only `paths.ts`, and a light `index.ts`. See `frontend/src/features/map/paths.ts:1` and `reports/paths.ts:2-4`.
- Item 7-style hookup (PRP-18/19): `routers.py` hooks, regenerate `openapi.json`, mock API handlers, and placeholder feature index exports so later items never edit shared app files.
- Axe in Playwright: `frontend/tests/helpers/axe.ts:15-18`. Tabster exclusion: `frontend/tests/e2e/copilot.spec.ts:8-12`.

### Conventions
- TypeScript 6.0.x strict, `@fluentui/react-components` 9.74.x. `NavDrawer`, `NavItem`, `NavCategory`, `NavSectionHeader`, `Hamburger`, `Field`, `Input`, `Select`, `Textarea`, `Table`, `Toolbar`, `Card` and `Combobox` are already exported. `@fluentui/react-nav` is transitive and MIT (`docs/licenses.md:227`). **No new dependencies.**
- Vitest + Testing Library + MSW (`frontend/tests/setup.ts`, `onUnhandledRequest: "error"`, `asyncUtilTimeout` 5 s). Playwright with unique `NS_E2E_APP_PORT`/`NS_MOCK_API_PORT` per worktree.
- API test package names must be unique across `packages/*/tests` and `services/*/tests`: use `services/api/tests/me_api/` and `services/api/tests/workspaces_api/`.
- Python `python` (never `python3`); ruff (line 100, py312, S rules); pyright standard; conventional commits; owned-file discipline.

### Gotchas
- **Heavy imports (PRP-18 lesson).** The shell and nav must import route constants from each feature's `paths.ts`/`routes.tsx`, never from feature `index.ts`, or sigma (WebGL) and vega reach jsdom and crash unrelated tests. `workspaceNav.ts` violates this today; fix it in item 2.
- **Specs that pin nav markup.** These query `getByRole("navigation", {name: "Primary"})` plus link names:
  - `frontend/tests/e2e/dashboards/dashboards.spec.ts:173-175`
  - `actions/actions.spec.ts:250-252`
  - `quality/quality.spec.ts:125-126`
  - `recommendations/recommendations.spec.ts:198-199`
  - `frontend/src/app/routes.test.tsx:15-17,34`

  Keep the landmark name and link names; grouping adds headers, not renames.
- **Accessible names.** Fluent `Field` labels must keep the exact accessible names the specs use. `actions.spec.ts:50-53` uses `getByLabel` exact.
- **Scope keys.** `ApiClient` forbids `domain_id`/`customer_id` in query and body. `/me/domains` takes no parameters; tile calls put the domain in the path.
- **Role names.** Frontend roles `Steward`/`Auditor` differ from backend `domain_steward`/`security_auditor`; the map must be explicit and tested.
- **Zero domains.** `require` with no resource means "holds anywhere", so a zero-domain caller gets 403 (decided). The UI must handle it.
- **No totals.** List endpoints return no totals. Tiles show "N+" from one page, never an invented exact count.
- **Mixed currencies.** Cost totals with mixed currencies must not be summed (`dashboards/models.py`: per-series `currency`).
- **Demo mode.** It must be dead code in production. Gate on `import.meta.env.MODE === "demo"` with a dynamic import (as `main.tsx:22-24` does for `e2e`), and prove absence by grepping the production `dist/`.
- **CodeQL rules that fail PRs.** `js/bad-tag-filter` (no regex HTML parsing), `py/side-effect-in-assert`, `py/uninitialized-local-variable` (match captures), `py/overwritten-inherited-attribute`, plus a gitleaks rule: split every credential-shaped literal in tests. Put these in every brief.
- **CI time.** The frontend job is near its 15-minute cap; item 3 raises it to 25. Keep new Playwright specs lean (one spec per lane, shared fixtures).
- **Copilot.** `copilot/requestContext.ts` reads `domain_id` from the URL. It keeps working unchanged, because the URL stays the source of truth.

### External references
- Fluent UI v9 Nav (`NavDrawer`, `NavCategory`, `NavSectionHeader`): https://react.fluentui.dev/?path=/docs/components-nav-preview--docs (component set present in `@fluentui/react-components` 9.74.9 `dist/index.d.ts` 681-737, 3389).
- Fluent UI v9 `Field`/`Input`/`Select`/`Textarea`: https://react.fluentui.dev/?path=/docs/components-field--docs.
- Vite modes and `import.meta.env.MODE`: https://vite.dev/guide/env-and-mode.html#modes.

### Wire contract (items 1, 2, 8 code against it)
- `GET /api/v1/me/domains` -> 200 `{items: [{domain_id, display_name, display_name_source: "catalog"|"derived", cloud: "commercial"|"government", permissions: [string]}]}`, sorted by `display_name`. 403 `forbidden` when the caller holds `data.read` nowhere. 401 unauthenticated. There are no query parameters.
- `GET /api/v1/workspaces/{role}`, where `role` is one of `viewer|analyst|steward|admin|auditor` (frontend names; mapped server-side). Unknown role -> 404. Role not held -> 403 `forbidden`. Held -> 200 with the shape the mock returns today (`{workspace, items}`, `frontend/tests/mock-api/server.ts:2033-2052`) and the workspaces feature types. Items 1 and 2 may add fields but must not rename or remove any.
- The mock API (item 2) implements both endpoints with these shapes. The stub caller reads `DOMAIN_OK` (and any other readable fixture domains); `DOMAIN_FORBIDDEN` is never listed.

## Implementation blueprint

### Item 1 - me-and-workspaces-api  [P]
- Deliverable: `GET /api/v1/me/domains` and `GET /api/v1/workspaces/{role}` per the wire contract, registered in the app, with `openapi.json` regenerated.
- Owned files (may edit): `services/api/neurosphere_api/me/**` (new), `services/api/neurosphere_api/workspaces/**` (new), `services/api/neurosphere_api/routers.py` (two hook lines), `services/api/openapi.json` (regenerated), `services/api/tests/me_api/**`, `services/api/tests/workspaces_api/**`.
- Must NOT touch: `services/api/neurosphere_api/authz/**`, `packages/core/neurosphere_core/auth/**` (PRP-06; no new permission constants or route-inventory model changes), `packages/contracts/**`, `frontend/**`.
- Depends on: none.
- Acceptance criteria:
  - `/me/domains` returns only `data.read` domains of the derived scope. There is a cross-customer and cross-cloud negative test.
  - Display names come from the catalog repository under the caller's scope, with a derived fallback labelled `derived`.
  - Zero domains -> 403. The route inventory test stays green.
  - `/workspaces/{role}` uses the explicit role map: 404 unknown, 403 not held, 200 shape matching the mock.
  - `test_openapi_drift` green after regeneration. Report whether the diff is purely additive (the PRP-15/18/19 component-rename precedent).
- Pattern references: `reconciliation/router.py:28-72`; `authz/dependencies.py:164-209`; `permissions.py:135-186`; `routers.py:106-109,166-185`.
- Tests to write: `services/api/tests/me_api/test_me_domains.py`, `services/api/tests/workspaces_api/test_workspaces.py`.

### Item 2 - app-shell-domain-switcher-and-mock  [P]
- Deliverable: the Fluent app shell, the page template, the domain switcher and its state, the grouped permission-aware nav, and the mock API handlers. Also:
  - a placeholder `frontend/src/features/overview/index.ts` (`overviewRoutes`, with `OverviewPage` rendering the current home text), wired as the home route, so item 8 never edits `frontend/src/app/`;
  - the C8 clarification comment in `frontend/src/auth/msal.ts`.
- Owned files (may edit): `frontend/src/app/**`, `frontend/src/design-system/page/**` (new: `PageHeader`, `PageTemplate`, `PageToolbar`), `frontend/src/design-system/index.ts` (exports only), `frontend/src/features/workspaces/**`, `frontend/src/features/overview/index.ts`, `frontend/src/features/overview/paths.ts` (placeholders), `frontend/src/auth/msal.ts` (comment only), `frontend/tests/mock-api/**`, `frontend/tests/e2e/shell.spec.ts` (new), `frontend/tests/e2e/smoke.spec.ts`, `frontend/tests/e2e/hidden-route.spec.ts`.
- Must NOT touch: every other `frontend/src/features/*/**` (lanes 4-7 own them), `frontend/src/api/**`, `frontend/package.json`, `pnpm-lock.yaml`, `frontend/vite.config.ts`, `services/**`.
- Depends on: none. It codes against the wire contract via the mock.
- Acceptance criteria:
  - Shell: header (product name, `LogoSlot`, user menu with role and sign out), skip link, grouped `NavDrawer` with the six groups.
  - The `navigation` landmark is named "Primary" and every existing link name is preserved. Specs pinning nav markup stay green unchanged.
  - Nav hides entries by role/permission; `hidden-route.spec.ts` stays green.
  - The domain switcher (`Combobox` or `Dropdown`) is fed by `/me/domains`. It writes `?domain_id=` and injects it into nav links.
  - Last domain is stored in `localStorage` (id only, keyed by a pseudonymous user key), cleared on sign-out, and falls back when unreadable. A test asserts nothing else is written.
  - A 403 shows "No domains are assigned to you".
  - Exports `useSelectedDomain()` (reads the URL, returns `{domainId, domains, setDomain}`) and the page template for lanes 4-8.
  - The shell and nav import only `paths.ts`/`routes.tsx` from features, never `index.ts`.
  - `CopilotDock` stays mounted once.
- Pattern references: `routes.tsx:40-84`; `workspaceNav.ts:21-39`; `map/paths.ts:1`; mock handler chain `server.ts:1995-2052`.
- Tests to write: `frontend/src/app/shell.test.tsx`, `frontend/src/app/domain.test.tsx`, `frontend/tests/e2e/shell.spec.ts` (nav groups, switcher, skip link, axe).

### Item 3 - local-demo-mode-and-ci-headroom
- Deliverable: `pnpm demo` (root and frontend) that starts the mock API and Vite in `demo` mode with stub sign-in and config pointing at the mock, plus a persistent "Demo data, mock API" banner; the production-exclusion tests; docs; and the CI timeout headroom.
- Owned files (may edit): `package.json` (root `demo` script), `frontend/package.json` (scripts only, no dependencies), `scripts/demo.mjs` (or `frontend/scripts/demo.mjs`), `frontend/src/app/main.tsx` (the `demo` MODE branch only, beside the existing `e2e` one), `frontend/src/app/demo/**` (new: banner, demo config), `frontend/tests/build/no-demo-in-prod.test.ts` (or equivalent, runnable in CI), `docs/dev/local-setup.md`, `.github/workflows/ci.yml` (frontend job `timeout-minutes` 15 -> 25 only).
- Must NOT touch: `frontend/Dockerfile`, `frontend/nginx.conf`, `infra/**` (read-only for the assertion test), `frontend/public/config.json` (the deployment default stays), other `frontend/src/**`.
- Depends on: Item 2 (owns `frontend/src/app/` until it merges).
- Acceptance criteria:
  - `pnpm demo` starts both servers on fixed ports (overridable by env), waits for health, and prints `http://127.0.0.1:<port>`. Visiting it shows the shell with data and the banner on every page.
  - A production build's `dist/` contains no banner text, no stub module and no `demo` branch (test).
  - Dockerfile, nginx and Helm carry no demo flag (test).
  - Docs updated; CI timeout raised with a comment.
- Pattern references: `main.tsx:22-24` (`e2e` dynamic import); `playwright.config.ts:21-34`; `tests/e2e-support/stubMsal.ts`.

### Item 4 - lane: dashboards and reconciliation  [P]
- Deliverable: these pages use the page template and `useSelectedDomain()`, the per-page domain forms are removed, and native controls are replaced with Fluent (`Field`/`Input`/`Select`/`Button`/`Table`). Behaviour and data logic are unchanged.
- Owned files (may edit): `frontend/src/features/dashboards/**`, `frontend/src/features/reconciliation/**`, `frontend/tests/e2e/dashboards/**`.
- Must NOT touch: `frontend/src/app/**`, `frontend/src/design-system/**`, `frontend/src/features/workspaces/**` (import `ForbiddenState`, don't edit), other features, `frontend/tests/mock-api/**`.
- Depends on: Item 2.
- Acceptance criteria: 0 native input/select/button/textarea in owned non-test `.tsx`; the domain text box is gone and the switcher drives the page; existing unit and e2e specs pass with the same accessible names; axe clean on both pages.
- Pattern references: `DashboardPage.tsx:73,92-119`; `ReconciliationPage.tsx:190,237-240`; item 2's `PageTemplate` and `useSelectedDomain`.

### Item 5 - lane: actions and review  [P]
- Deliverable: as item 4, for actions (`ActionsPage`, `ActionDetail`, `ProposeSwapPage`, `ActionWorkflow`) and review (`ReviewQueuePage`, `ReviewItemPage`, including its textarea). PRP-17 behaviour is unchanged: same executor calls, same confirmation dialog, same intent hash.
- Owned files (may edit): `frontend/src/features/actions/**`, `frontend/src/features/review/**`, `frontend/tests/e2e/actions/**`.
- Must NOT touch: as item 4, plus the PRP-17 confirmation semantics.
- Depends on: Item 2.
- Acceptance criteria: as item 4. `actions.spec.ts` passes unchanged, including the exact `getByLabel` names at `:50-53`.
- Pattern references: `ActionsPage.tsx:55-194`; `ProposeSwapPage.tsx:18,59-77`; `ReviewQueuePage.tsx:54-149`; `ReviewItemPage.tsx:137,220`.

### Item 6 - lane: quality, recommendations and reports  [P]
- Deliverable: as item 4, for quality, recommendations (list + detail) and reports (list + view + dialogs).
- Owned files (may edit): `frontend/src/features/quality/**`, `frontend/src/features/recommendations/**`, `frontend/src/features/reports/**`, `frontend/tests/e2e/quality/**`, `frontend/tests/e2e/recommendations/**`.
- Must NOT touch: as item 4. Keep `SaveReportDialog`'s public props and `buildSaveReportRequest` unchanged (copilot imports them).
- Depends on: Item 2.
- Acceptance criteria: as item 4; copilot's reports imports still compile and copilot tests pass.
- Pattern references: `QualityPage.tsx:21-176`; `RecommendationListPage.tsx:42-133`; `ReportsListPage.tsx:37-108`.

### Item 7 - lane: map, map table and replay  [P]
- Deliverable: as item 4, for map (`MapPage` `DomainForm` removed, `Legend` select), map-table and replay. The PRP-18 treegrid stays a native accessible table, allowlisted in the static test with its reason.
- Owned files (may edit): `frontend/src/features/map/**`, `frontend/src/features/map-table/**`, `frontend/src/features/replay/**`, `frontend/tests/e2e/map-*.spec.ts`.
- Must NOT touch: as item 4. Keep `paths.ts` path-only; keep reduced-motion and keyboard behaviour.
- Depends on: Item 2.
- Acceptance criteria: as item 4; `map-reduced-motion`, `map-table-keyboard` and `map-perf` specs pass; no sigma import reaches jsdom through the shell.
- Pattern references: `MapPage.tsx:380-397`; `Legend.tsx:70`; `MapTablePage.tsx:104,249,306`; `MapGrid.tsx:285`; `ReplayPage.tsx:101,111`.

### Item 8 - overview home page
- Deliverable: `frontend/src/features/overview/**` replaces the item 2 placeholder (same export names) with the role-aware tile page per the acceptance criteria, plus the static no-native-controls test covering `frontend/src/features/**` and `frontend/src/app/**`.
- Owned files (may edit): `frontend/src/features/overview/**`, `frontend/tests/e2e/overview.spec.ts`, `frontend/tests/static/no-native-controls.test.ts` (or under `frontend/src/` if Vitest includes it), `frontend/tests/mock-api/**` (tile fixtures only, if the existing ones are insufficient; additive).
- Must NOT touch: `frontend/src/app/**`, other features, `services/**`.
- Depends on: Items 1, 2, and 4-7 (the static test must pass on the restyled tree).
- Acceptance criteria:
  - Tiles per the acceptance criteria: per-currency cost with badges, "N+" for paged lists, "unknown" and "not loaded" never shown as 0, an independent error state per tile, at most 7 API calls, each tile linking with `domain_id`.
  - Axe clean.
  - The static test is green with only the documented allowlist.
- Pattern references: tile sources in "Files that matter"; `dashboards/components.tsx` badges.

### Waves
- A = items 1 and 2 [P].
- B = items 4, 5, 6 and 7 [P] (WIP 4).
- C = items 3 and 8 [P] (they share no files).

Items 1 and 2 own `routers.py`/`openapi.json` and `frontend/src/app/`/the mock respectively, so no shared file is edited in parallel.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
uv run pytest -q services/api/tests/me_api services/api/tests/workspaces_api services/api/tests/authz services/api/tests/test_app.py services/api/tests/test_openapi_drift.py
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend exec vitest run
pnpm --filter @neurosphere/frontend build
NS_E2E_APP_PORT=<unique> NS_MOCK_API_PORT=<unique> pnpm --filter @neurosphere/frontend exec playwright test
python scripts/licenses_report.py --check
pnpm demo   # manual: open the printed URL, confirm shell, switcher, tiles and banner, then stop it
```
No live gate: this PRP makes no cloud calls and needs no `NS_LIVE_APPROVED`.

## Live and open gates
- G09 (accessibility) stays owned by PRP-24. This PRP keeps axe at 0 on its pages but records no human screen-reader or keyboard evidence.
- No other gate is touched.

## NOT building
- Theme packs, agency logos, the theme switcher UI, sandbox mode and the accessibility audit (PRP-24).
- A custom visual identity or data-viz restyling (PRP-24 tokens first).
- Exact counts or new aggregate endpoints for tiles ("N+" from existing pages).
- Changes to authorization, permissions or the route inventory model (PRP-06).
- A production bootstrap of `app.state` for copilot, reports or map (still open from PRP-18/19). The local demo uses the mock API.
- Changes to `frontend/public/config.json` or the deploy-time config mount.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed

## Execution state

| Item | Status | Branch | Model | Evidence | Updated |
|------|--------|--------|-------|----------|---------|
| 1 | merged | worktree-agent-ad5aa5f746e8881fc | sonnet | 75867cc, merge 1b99def; verify 195 passed targeted (pre+post merge), ruff/format clean; impl 831 api passed, pyright 0; review APPROVED (5 non-blocking follow-ups) | 2026-10-22 |
| 2 | merged | worktree-agent-a5c2e30dee17dc54b | sonnet | 0a9125e, merge 1409e46; verify typecheck/lint clean, vitest 412/412, build ok, playwright 86/87 (quality.spec:38 flake, 30/30 on repeat-each=3); post-merge vitest 412/412 + shell/hidden-route/smoke 7/7; review APPROVED (4 non-blocking follow-ups) | 2026-10-22 |
| 3 | todo | | sonnet | | 2026-10-22 |
| 4 | in-progress | (agent worktree) | sonnet | dispatched wave B | 2026-10-22 |
| 5 | in-progress | (agent worktree) | sonnet | dispatched wave B | 2026-10-22 |
| 6 | in-progress | (agent worktree) | sonnet | dispatched wave B | 2026-10-22 |
| 7 | in-progress | (agent worktree) | sonnet | dispatched wave B | 2026-10-22 |
| 8 | todo | | sonnet | | 2026-10-22 |

## Completion note (filled at ship)
- Date:
- Merged commits:
- Deviations from blueprint and why:
- Descoped items:
- Follow-ups:
