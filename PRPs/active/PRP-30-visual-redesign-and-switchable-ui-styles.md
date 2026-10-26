---
name: prp-30-visual-redesign-and-switchable-ui-styles
status: active
started: 2026-10-26
branch: prp-30-visual-redesign
review: required
priority: P0
created: 2026-10-24
model: sonnet
phase: 5
ns: NS-08, NS-10
depends_on: PRP-24, PRP-28
wave: W9
absorbs: new
---

# PRP-30: Visual redesign and switchable UI styles

## Goal
Give NeuroSphere a visual identity and a polished UI that people can switch between, without changing what any page does or what the API allows. The operator's verdict on 2026-10-24 after running `pnpm demo` was "the ui looks like shit". This PRP ships:
- A **style layer** in `frontend/src/design-system/` with two styles, switchable at runtime from the user menu:
  - **Ops console**: dark-first, dense but polished, KPI cards with sparklines, real charts, colour-coded health, branded header, rich topology map.
  - **Enterprise Fluent**: light-first, a familiar enterprise-portal feel, cards, proper charts, conservative branding.

  A style controls layout density, component treatment and chart theme. PRP-24's light/dark/high-contrast modes and theme packs still apply under both styles.
- **Mockups first.** High-fidelity static mockups of home, the cost dashboard and the map in both styles are rendered to PNG. The operator approves them at a hard checkpoint before any page is restyled.
- A **NeuroSphere logo and wordmark** (original SVG, created in-repo), plus a polished header, navigation and page template.
- **Real charts** on the dashboards, built from in-house declarative SVG primitives:
  - time axes with formatted dates, and tooltips;
  - one chart per currency, never summed;
  - estimated and invoiced visibly distinct;
  - unknown values drawn as gaps, never as 0;
  - the accessible data table kept.
- **Every page in `route-manifest.json` restyled**, in feature lanes: KPI cards, badges that wrap, health colours, empty/loading/error states, and timestamps shown as relative time with the absolute time available.
- **A map visual upgrade.**
- **Demo first-impression fixes**:
  - land on a populated domain;
  - every page has data in demo mode;
  - the demo banner no longer covers "Open assistant".
- **Visual regression baselines** per style and mode on key pages, and PRP-24's axe suite extended to styles × modes × packs at 0 serious/critical.

PRP-31 (new UI surfaces) depends on this PRP. It consumes the primitives and page template exported here; this PRP adds no new pages or nav entries.

Evidence, captured 2026-10-24 against `pnpm demo` at 1440x900 (screenshots in `temp/shots/prp30/`, not committed):
- The default Viewer lands on domain "Analytics (batch down)". On a first visit the home Map coverage and Recent reports tiles show "not loaded / You do not have access to this data". The mock lists that domain first (`frontend/tests/mock-api/server.ts:91-95`) and the shell picks `domains[0]` (`frontend/src/app/domain.tsx:193`).
- Home is three plain cards on white. The logo slot is an empty dashed box (`frontend/src/design-system/LogoSlot.tsx:4-14`). The Viewer sees three tiles and a large empty area.
- On the home cost tile, the "incomplete total (partial sum of known parts)" badge overflows its pill and overlaps the next row. Fluent `Badge` has a fixed height and does not wrap.
- The cost dashboard looks like a debug view:
  - Each chart is one 320x80 polyline with no axes (`frontend/src/features/dashboards/components.tsx:122-136`).
  - Timestamps are raw ISO strings.
  - Freshness is a bare `<dl>` (`components.tsx:75-92`).
  - Every table row repeats the badges.
- The fixed "Open assistant" button (`frontend/src/features/copilot/CopilotDock.tsx:22-28`, `bottom: spacingVerticalL`, z-index 1000) sits under the fixed bottom demo banner (`frontend/src/app/demo/DemoBanner.tsx:11`, z-index 2147483000).
- The map shows 7 nodes. Only 2 have labels, the layout leaves large empty space, and the health colours are hard-coded hex values in the feature (`frontend/src/features/map/appearance.ts:33-40`).

## Acceptance criteria
- [ ] Item 1: a style registry exports exactly two styles, `ops-console` and `enterprise-fluent`. Each style is presentation data:
  - density/spacing scale, typography adjustments and component treatment (radius, elevation, borders, header treatment);
  - a chart theme per mode (categorical palette, estimated/invoiced treatments, grid, unknown-gap marker);
  - a health palette per mode;
  - a `preferredMode`.

  Composition is mode × pack × style:
  - The pack keeps the brand ramp and logos.
  - The style may override only an allowlisted set of neutral surface, stroke, shadow and radius tokens, and only if every PRP-24 guarded contrast pair still passes. Otherwise the overrides are dropped.
  - In high-contrast, style colour overrides never apply.
  - Unit tests cover every style × mode × pack.
- [ ] Item 1: the style choice persists in the existing `ns.theme` record as an optional `styleId`, validated on read like `packId`. A stored record without `styleId` stays byte-identical until the user picks a style (test).

  Precedence:
  - Style: user choice > deployment default > built-in default `enterprise-fluent`.
  - Mode: user choice > deployment default > the chosen style's `preferredMode`.

  No style module imports `frontend/src/api/` or `frontend/src/auth/` (boundary test).
- [ ] Item 2: the brand and component primitives are exported from `frontend/src/design-system`:
  - an original NeuroSphere mark and wordmark (inline JSX SVG, token colours, no hex outside `tokens/`), plus `frontend/public/brand/neurosphere-mark.svg` and `frontend/public/favicon.svg`;
  - `KpiCard` (value, label, optional sparkline slot, delta and status), `StatusPill` (wraps long text, never overflows its container), `HealthIndicator` (colour plus icon plus text, never colour alone);
  - `EmptyState`, `LoadingState` (skeleton) and `ErrorState`;
  - `Timestamp`: relative text, the absolute value in the accessible name and on hover, raw ISO in `datetime`, and day-grain values formatted in UTC;
  - `DataTable` (a style-density Fluent `Table` wrapper);
  - `PageTemplate` v2, with additive props only (`kpis`, `layout`).

  The format helpers render unknown as "unknown", never 0, and format each currency separately.
- [ ] Item 3: the chart primitives in `frontend/src/design-system/charts/` are `TimeSeriesChart` (line/area), `Sparkline`, `BarChart` and `ChartLegend`. They are declarative typed props rendered as React SVG: no new dependency, no `dangerouslySetInnerHTML`, no eval, no LLM-supplied code.
  - `TimeSeriesChart` throws a typed error in tests and renders an `ErrorState` if given series with different units or currencies.
  - Estimated series are dashed with a lighter fill; invoiced are solid. The legend and table say so in words.
  - Unknown points are gaps with a marker, never 0. Incomplete points use a hollow marker.
  - Axes use formatted dates and numbers. A pointer tooltip shows the value, basis and date.
  - The chart has `role="img"` with a generated summary `aria-label`.
  - Motion runs only under `prefers-reduced-motion: no-preference`.
  - It renders in jsdom.
- [ ] Item 4: 12 mockup PNGs are rendered by `frontend/scripts/render-mockups.mjs` into `docs/design/prp-30/mockups/`: {home, cost dashboard, map} × {ops-console, enterprise-fluent} × {light, dark}.
  - They are built from the item 1-3 primitives with static fixture data.
  - They are served only from demo-mode code: no router route, `route-manifest.json` unchanged, and the prod-exclusion test extended to the mockup marker.
- [ ] **Mockup approval checkpoint**: the operator has approved the mockups, or approved them after one rework round, and confirmed the default style, recorded in Execution state, before any wave D item starts.
- [ ] Item 5: the shell renders the logo and wordmark. "NeuroSphere" stays real text and the shell `h1`/banner pins hold (`frontend/src/app/shell.test.tsx:84-90`).
  - The user menu gains a "UI style" radio group beside "Theme mode" and "Theme pack".
  - Runtime config accepts an optional `defaultUiStyle`, and the deployment default applies like `defaultThemePack`.
  - The recorded-request comparison test (`frontend/src/app/theme-requests.test.tsx`) proves the request set is identical across both styles.
  - The demo banner is an in-flow strip, not a fixed overlay. In demo mode and with the sandbox banner on, the "Open assistant" button is not covered (an e2e `elementFromPoint` check at its centre returns the button).
- [ ] Item 5: in the mock, "Finance" sorts first among the readable domains (the analytics-down fixture is renamed so the mock still sorts by `display_name`, as the real API does), so a first visit lands on a populated domain.
  - `pnpm demo` starts the mock with `NS_MOCK_PROFILE=demo`. That profile adds richer fixtures (a 30-day cost series per currency and kind, a 20-40 node topology, and more recommendations, reports, review items and intents), so every route in `route-manifest.json` shows data, not an empty or access-denied state, on a first visit (Playwright demo audit).
  - The demo persona is `Steward`.
  - The e2e profile is unchanged apart from the rename, and the full e2e suite stays green.
- [ ] Items 6-9: every page in `route-manifest.json` uses `PageTemplate` and the item 2/3 primitives.
  - Health is shown as colour + icon + text.
  - Every list or data view has explicit empty, loading and error states.
  - Timestamps use `Timestamp`, and no raw ISO strings are visible.
  - No `Badge` holds text longer than 24 characters (a `StatusPill` is used instead).
  - Behaviour, data calls, accessible names that specs pin, and PRP-17 confirmation semantics are unchanged.
  - The static no-native-controls test stays green.
- [ ] Item 6: home shows KPI cards: cost per currency for the last 7 days with a sparkline (one `days=7` call; never summed across currencies), review, awaiting, map coverage and reports, still at most 7 API calls. The cost dashboard shows:
  - a KPI strip (per-series totals, freshness as `Timestamp`, analytics state);
  - one `TimeSeriesChart` per currency, with estimated and invoiced in the same currency drawn together but distinct;
  - a restyled data table.
- [ ] Item 9: the map applies the style's canvas theme (background, label colour and font, provenance edge colours, health halo) and a deterministic, better-spaced layout with zoom-to-fit, so all node labels in the demo fixture are legible at 1440x900.
  - Hover highlights neighbours.
  - The legend and node panel are styled cards.
  - Reduced motion, keyboard behaviour and the table alternative are unchanged.
  - sigma still never reaches jsdom.
- [ ] Item 10: Playwright visual baselines (Linux, committed) cover 2 styles × {light, dark} × {home, cost dashboard, map, map table, recommendations, actions}, plus high-contrast home in both styles: 26 shots. Settings:
  - `maxDiffPixelRatio: 0.01`, `threshold: 0.2`;
  - fixed clock, `timezoneId: "UTC"` and `locale: "en-US"`;
  - animations disabled and the map canvas masked.
- [ ] Item 10: axe (with the documented tabster exclusion only) reports 0 serious or critical issues:
  - `themes.a11y.spec.ts`: 2 styles × 3 modes × 2 packs over the theme-matrix routes plus `/map`;
  - `routes.a11y.spec.ts`: every route in `route-manifest.json` × 2 styles × 3 modes.

  The keyboard pre-check stays green. A layout spec asserts that no `StatusPill` overflows its parent on home and the cost dashboard in either style.
- [ ] PRP exit:
  - all items green under `verify-gates -Mode full`;
  - full Vitest and Playwright suites green, and the CI frontend job inside its 25-minute cap;
  - licences PASS with no new dependency;
  - the demo-never-ships test green;
  - the reviewer confirms that styles are presentation only (no request, permission or route difference) and that the mockup approval is recorded.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | What to build | restyle only; one new style; two switchable styles plus mockups | Two switchable styles (Ops console, Enterprise Fluent), with a mockup step first (operator decision 2026-10-24) |
| 2 | Mockup gate | mockups optional; mockups reviewed in PR; hard checkpoint between waves | Hard checkpoint after wave C. No wave D work until the operator approves, with at most one rework round inside items 1-4's owned files. The approval and the chosen default style are recorded in Execution state |
| 3 | Mockup medium | Figma or external tool; Storybook; demo-only React pages rendered by Playwright | Demo-only React pages built from the real item 1-3 primitives, rendered to PNG by Playwright. What is approved is the code that ships, not a drawing. The map mockup is a hand-placed static SVG of the intended look, because WebGL is non-deterministic headless |
| 4 | Default style | Ops console; Enterprise Fluent | `enterprise-fluent` (light-first). Agency adopters expect a conservative enterprise look, it matches PRP-24's light default and a11y baseline, and Ops console stays one click away. Re-confirmed at the checkpoint |
| 5 | How style, mode and pack compose | style replaces theme; style as a fourth independent axis | Independent axes. The mode picks the base token set; the pack gives the brand ramp and logos; the style gives density, component treatment, chart theme, health palette and allowlisted neutral-surface overrides with a contrast guard. High-contrast ignores style colours. Precedence is in the acceptance criteria |
| 6 | Persistence | new storage key; extend `ns.theme`; server-side | Optional `styleId` in the existing `ns.theme` record. Local storage only (PRP-24 clarification 10). No server-side per-user store |
| 7 | Charting engine | vega via the PRP-19 sandbox iframe; vega in the main bundle; new library; in-house SVG primitives | In-house declarative SVG primitives, with no new dependency. The sandbox bans `config` (`frontend/src/features/charts/protocol.ts:15-35`), so it cannot be styled. One iframe per series is heavy. Vega in the main bundle crashes jsdom (PRP-18 lesson). App-authored typed props are not LLM-generated code. The PRP-19 sandbox stays for copilot and report charts, unchanged apart from its outer frame |
| 8 | Timestamps | absolute only; relative with absolute | Relative text, with the absolute value in the accessible name and tooltip, and raw ISO in `datetime`. Day-grain values are formatted in UTC so billing days never shift. Dense tables use absolute formatted dates |
| 9 | Wrong default domain on first visit | change shell default logic; fix fixtures | Fix fixtures. The real API sorts by `display_name` (PRP-28 wire contract), so the mock renames the analytics-down fixture and keeps sorting. Product logic is unchanged |
| 10 | Populating the demo | enrich `DOMAIN_OK` in place; new demo domain; demo fixture profile | `NS_MOCK_PROFILE=demo` profile set by `pnpm demo`. The e2e fixtures that specs pin (counts, unknown points, "0" invoiced) stay byte-identical |
| 11 | Demo persona | Viewer; Steward; multi-role | `Steward`. The stub token carries one role (`frontend/tests/e2e-support/stubMsal.ts:11-12`), and Steward sees every overview tile and the review queue. e2e keeps `Viewer` |
| 12 | Demo banner vs assistant launcher | raise launcher; z-index juggling; in-flow banner | The banner becomes an in-flow strip at the top, like `SandboxBanner`. No fixed element besides the copilot dock remains, and an e2e check proves the launcher is not covered |
| 13 | Logo | leave the slot empty; external brand asset; original in-repo SVG | Original abstract mark (a sphere of linked nodes) plus a text wordmark, drawn in-repo. Inline JSX using tokens and `currentColor`; static copies in `frontend/public/brand/`. No Microsoft or partner marks. An agency pack logo, if set, shows beside it in `LogoSlot`. An empty `LogoSlot` no longer renders a dashed box in the header |
| 14 | Visual regression | none; pixel baselines everywhere; key pages on Linux | 26 Linux baselines (see acceptance), committed, updated with the official Playwright Docker image matching `@playwright/test`. The `visual` project runs only on Linux or with `NS_VISUAL=1`, and CI on ubuntu is authoritative. Tolerance `maxDiffPixelRatio 0.01`, `threshold 0.2`; map canvas masked (SwiftShader) |
| 15 | a11y matrix size vs CI time | default style only; full matrix | Full style dimension: themes 72 tests, routes 156 tests. If the CI frontend job goes past 20 minutes, item 10 shards Playwright across two jobs in `.github/workflows/ci.yml` (frontend job only); the cap is never raised past 25 |
| 16 | Health colours | per feature; design tokens | Tokens per style × mode in `frontend/src/design-system/tokens/`, at least 3:1 against the surface (WCAG 1.4.11) and always with icon and text. `map/appearance.ts` `HEALTH_COLOUR` moves to these tokens |
| 17 | Item split | one lane per page; PRP-28 feature-folder lanes | PRP-28 lane split by feature folder, extended for the folders added since (overview, mcp-admin, sandbox, charts). Shared foundations come first; lanes never edit `design-system/**` |
| 18 | Review | none; required | `review: required`. Cross-cutting, with an a11y regression risk and a demo-never-ships boundary |

### Decisions to confirm at plan approval
- D-a, default style `enterprise-fluent` (clarification 4). The alternative is `ops-console` as the default for demo mode only.
- D-b, precedence and the high-contrast rule (clarification 5), especially: picking a style switches the mode to its `preferredMode` only if the user never chose a mode explicitly.
- D-c, in-house SVG charts with no new dependency (clarification 7). If the operator prefers a library, it must pass `python scripts/licenses_report.py --check` and get operator approval before item 3.
- D-d, the demo fixture profile and the `Steward` demo persona (clarifications 10, 11).
- D-e, home cost KPI changes from "last day" to "last 7 days" with a sparkline (item 6): one call, same bound.
- D-f, visual tolerance, Linux-only baselines and the Docker update path (clarification 14).
- D-g, a11y matrix size and the sharding fallback in `ci.yml` (clarification 15).
- D-h, the logo concept (clarification 13). The mockups show it; the operator can reject it at the checkpoint.
- D-i, file claims at the PRP-29 boundary: this PRP edits `frontend/index.html` (favicon `<link>` only), `frontend/scripts/demo.mjs` (passes `NS_MOCK_PROFILE` only) and `frontend/package.json` (scripts only). None of these is in PRP-29's declared set; confirm when the two plans are approved together.

## Context manifest

### Files that matter
- `PRPs/shipped/PRP-24-themes-sandbox-mode-and-accessibility.md` (theme packs, modes, sandbox banner, a11y suite, D6/D7 contrast and tabster decisions). `PRPs/shipped/PRP-28-ui-shell-and-usability.md` (shell, lanes, pinned names, demo mode).
- The design-system today:
  - `frontend/src/design-system/AppThemeProvider.tsx`:
    - `:16-24`: global link rule scoped by `LINK_SCOPE_CLASS`.
    - `:31-46`: `FluentProvider` with `data-theme` and `data-theme-pack`. The style hooks in here.
  - `frontend/src/design-system/theme-store.ts`:
    - `:7`: `THEME_STORAGE_KEY = "ns.theme"`.
    - `:29-57`: read/validate/write.
    - `:78-101`: the zustand store and `applyDeploymentDefault`.
  - `frontend/src/design-system/themes/`:
    - `resolve.ts:13-23`: pack × mode, with the HC guard via `meetsContrast`.
    - `types.ts:36-42`: `ThemePack`.
    - `packs.ts:11-32`.
    - `logo.ts:3-8`: SVG is deliberately excluded from agency uploads. The product mark here is first-party code, not an upload path.
    - `contrast.ts`: `TEXT_PAIRS`, `UI_PAIRS`, `HC_MIN`.
  - `frontend/src/design-system/tokens/`:
    - `brand.ts:8-36`: ramp and HC palette.
    - `themes.ts:5-70`: modes and HC token set.
    - `typography.ts:13-50`.
  - `frontend/src/design-system/tokens.test.ts:9-23`: hex literals are allowed only under `design-system/tokens/`, and the test covers `themes/` too.
  - `frontend/src/design-system/page/PageTemplate.tsx:47-80` and `PageHeader.tsx:55-57`: the single `h1`. `PageToolbar.tsx:26-33`: a labelled `group`.
  - `frontend/src/design-system/LogoSlot.tsx:4-29`: the dashed empty box.
  - `frontend/src/design-system/index.ts:1-33`: the public exports.
- Shell:
  - `frontend/src/app/Shell.tsx`:
    - `:28`: `PRODUCT_NAME`.
    - `:31`: `NAV_WIDTH`.
    - `:34-90`: styles.
    - `:157-195`: the nav (plain div body, see Gotchas).
    - `:198-208`: `HeaderLogo`.
    - `:233-239`: deployment theme default.
    - `:268-277`: header.
    - `:278`: `SandboxBanner`.
    - `:293-296`: `CopilotDock` mount.
  - `frontend/src/app/UserMenu.tsx:47-88`: the mode and pack radio groups, where the style group joins them. `frontend/src/app/navigation.ts:4-11`: `NAV_GROUPS`.
  - `frontend/src/app/config.ts:16-18,62-81`: `defaultThemePack` and `defaultThemeMode` parsing, the pattern for `defaultUiStyle`.
  - `frontend/src/app/main.tsx:15-27`: the demo branch (stub sign-in, `withDemoBanner`).
  - `frontend/src/app/demo/index.tsx:34-55`: `demoConfig`, `withDemoBanner`. `frontend/src/app/demo/DemoBanner.tsx:5-22`: fixed bottom overlay.
  - `frontend/src/app/route-manifest.json` (26 routes) and `route-manifest.test.ts`: the registered routes must equal the manifest.
  - `frontend/src/app/domain.tsx:193`: default `domains[0]`. `frontend/src/app/theme-requests.test.tsx`: the recorded-request invariance test.
- Features:
  - `frontend/src/features/copilot/CopilotDock.tsx:22-34`: fixed launcher and panel positions.
  - Dashboards:
    - `dashboards/components.tsx`:
      - `:17-47`: `MetricText`.
      - `:49-61`: `KindBadge` (HC tint fix, A11Y-003; keep the contrast).
      - `:75-92`: `LagIndicator`.
      - `:122-136`: `SeriesChart` polyline.
      - `:138-196`: `SeriesBlock` and table.
    - `dashboards/types.ts:14-53`: `MetricValue`, `Series` (per-series `currency`, `kind`), `Freshness`.
  - `overview/OverviewPage.tsx:99-125`: the cost tile imports `KindBadge` and `MetricText` from dashboards; the badge overflow is here. `overview/data.ts:29-38`: tiles per role.
  - `charts/protocol.ts:15-45` (banned keys including `config`, allowed marks), `charts/sandbox/render.ts` (vega-interpreter, deny loader) and `charts/ChartFrame.tsx:17,143-150` (iframe `sandbox="allow-scripts"`). Only the frame container is restyled.
  - Map:
    - `map/appearance.ts:33-40`: `HEALTH_COLOUR` hex.
    - `map/mapGraph.ts:69-81`: deterministic island/phyllotaxis layout.
    - `map/renderer.ts:95-99`: sigma node attributes.
    - `map/index.ts` vs `map/paths.ts`: the import rule.
  - `workspaces/ForbiddenState.tsx`, imported by five features.
- Mock and test support:
  - `frontend/tests/mock-api/server.ts`:
    - `:27,56-57`: fake token prefix; one role per token.
    - `:78-95`: `meDomainItems` (analytics-down first).
    - `:158-162`: `DOMAIN_OK`, `DOMAIN_ANALYTICS_DOWN`, `DOMAIN_FORBIDDEN`.
    - `:200-280`: dashboard series fixtures (3 points).
    - `:759`: `DOMAIN_MAP_PERF`.
    - `:1239`: `DOMAIN_VIEWER`.
    - `:1973`: `createMockApi`.
    - `:2097`: `/me/domains` handler.
    - `:2170-2171`: env ports.
  - `frontend/tests/e2e-support/stubMsal.ts:11-24`: `STUB_ROLES`, `STUB_TOKEN`, `createStubMsalInstance`.
  - `frontend/scripts/demo.mjs:10-17`: demo ports 5180/5181 (`NS_DEMO_APP_PORT`/`NS_DEMO_API_PORT`).
- Tests that pin markup:
  - `frontend/tests/e2e/a11y/`:
    - `themes.a11y.spec.ts:22-48`: the stored record must `toEqual({packId, themeName})` exactly.
    - `axe-support.ts:28-30` (`MODES`, `PACKS`, `TABSTER_SENTINEL`) and `:63-77` (`seedPreferences`).
    - `route-samples.ts:150-156` (`THEME_MATRIX_PATTERNS`).
    - `routes.a11y.spec.ts`, `routes-keyboard.a11y.spec.ts`, `keyboard-flows.a11y.spec.ts`, `aria-tree.a11y.spec.ts`.
  - `frontend/tests/e2e/dashboards/dashboards.spec.ts`:
    - `:22-23`: `series-block` filtered by heading.
    - `:47-65`: `kind-badge`, `price-version-badge`, `metric-value` "unknown"/"0", `incomplete-marker`.
    - `:72`: `watermark` text equals the raw ISO fixture.
    - `:73`: `lag` "120 s".
    - `:173-175`: nav names.
  - `frontend/tests/e2e/overview.spec.ts:25-26` (`tile-cost`, `cost-row`). `frontend/src/app/shell.test.tsx:84-90` (headings `["NeuroSphere"]`, banner text). `frontend/tests/static/no-native-controls.test.ts:16,26-28` (scans `src/features` and `src/app`, with its allowlist).
  - `frontend/tests/prod-exclusion/no-demo-in-prod.test.ts`: demo markers absent from the production build.
- `frontend/playwright.config.ts`:
  - `:3-4`: ports.
  - `:20`: one chromium project.
  - `:21-34`: webServers with `reuseExistingServer: !isCi`.
- `.github/workflows/ci.yml:48-50` (frontend job, ubuntu, `timeout-minutes: 25`), `:83-86` (Playwright install and `test:e2e`). The last frontend job ran about 10 min (run 40119413809). PR #90 ran 14m49s.
- `frontend/package.json:16-30`: runtime deps. `@fluentui/react-components`, `sigma`, `graphology`, `vega*` and `zustand` are already present. No charting library beyond vega.

### Patterns to match
- Theme packs as typed presentation data, with an HC contrast guard that drops unsafe overrides: `themes/resolve.ts:13-23`. Styles follow the same shape (`styles/types.ts`, `styles/registry.ts`, `styles/resolve.ts`).
- Store validation and best-effort write: `theme-store.ts:34-57`. `applyDeploymentDefault` where the user's choice wins: `:92-100`.
- Boundary test, theme code never imports api/auth: `themes/no-api-import.test.ts`.
- PRP-28 placeholder hookup: the foundation item creates empty subfolder `index.ts` files and the root re-exports once, so later items never edit `design-system/index.ts`.
- Feature folder shape: `routes.tsx`, path-only `paths.ts`, light `index.ts` (`map/paths.ts`, `reports/paths.ts`).
- Demo-only dead code: dynamic import behind `import.meta.env.MODE === "demo"` (`main.tsx:15-27`), proven absent by `tests/prod-exclusion/`.
- Axe in Playwright with the tabster exclusion only: `tests/e2e/a11y/axe-support.ts:21-28`.
- Data-honesty rules from PRP-14 and PRP-28: unknown never 0, never sum across currencies, estimated and invoiced always distinct, "N+" for paged lists.

### Conventions
- TypeScript 6.0.x strict, `@fluentui/react-components` 9.74.x, React 19, Vitest + Testing Library + MSW, Playwright 1.64. **No new dependencies.** Any exception needs `python scripts/licenses_report.py --check` plus operator approval first. pnpm only.
- Colours as hex live only in `frontend/src/design-system/tokens/`. Components use Fluent `tokens.*` or style tokens from the registry.
- Theme, pack and style are presentation (NS-10). They never feed an access decision, add or remove a request, or hide a route as a control.
- Playwright: unique `NS_E2E_APP_PORT`/`NS_MOCK_API_PORT` per worktree. Demo runs use unique `NS_DEMO_APP_PORT`/`NS_DEMO_API_PORT` per worktree.
- No em-dashes in docs. Forward slashes in commands. Temp files in `temp/`. Python is `python`. Conventional commits. Owned-file discipline.
- Snyk code scan on new first-party code (`snyk_code_scan`), with 0 new issues as merge evidence (PRP-24 precedent).
- No Microsoft logos, badges or "powered by" marks. Style B is "Enterprise Fluent", a Fluent-component style, not an imitation of any Microsoft product's trade dress, and no affiliation is implied (PRP-24 clarification 9).

### Gotchas
- **Heavy imports (PRP-18).** The shell, nav, mockups and design-system must import feature `paths.ts`/`routes.tsx`, never `index.ts`, or sigma (WebGL) and vega reach jsdom and crash unrelated tests. Chart primitives must not import vega.
- **Pinned names and text.**
  - Keep: the `navigation` landmark "Primary" and every nav link name; the shell heading list `["NeuroSphere"]`; and every `data-testid` the specs query.
  - The wordmark is an SVG mark plus a real text node, never text inside the SVG.
  - Lanes keep `getByLabel` exact names (`actions.spec.ts:50-53`).
- **Timestamp text pins.** `dashboards.spec.ts:72` expects the `watermark` text to equal the raw ISO fixture. When a lane switches to `Timestamp`, it updates the assertion to the `datetime` attribute in its owned spec. The value must stay the same ISO string.
- **Stored theme record.** `themes.a11y.spec.ts:31-32` asserts `toEqual({packId, themeName})` exactly. The store must not write `styleId` unless the user picks a style. Item 10 extends the spec to seed and assert `styleId`.
- **Hex rule.** `tokens.test.ts:9-23` fails on any hex outside `design-system/tokens/` (and on `themes/`). Style palettes, chart palettes and health palettes go in `tokens/`. The inline SVG logo uses `currentColor` and tokens. `frontend/public/brand/*.svg` is outside the scan and may hold literal colours.
- **Fluent `Badge`** has a fixed height and does not wrap. Long text overflows it, as on the home cost tile. Use `StatusPill` for anything over 24 characters.
- **Tabster and the nav.** The axe exclusion is `[data-tabster-dummy]` only (A11Y-012). Do not reintroduce `NavDrawerBody`, which was replaced for `aria-hidden-focus` (#94).
- **High-contrast** always starts from the PRP-24 HC set. Style colour overrides never apply there; density and layout still do. The chart theme and health palette have HC variants built from `highContrastPalette`.
- **Chart sandbox.** The PRP-19 protocol bans `config`, `params`, `signals`, `expr` and `url`. Do not route dashboards through the iframe, and do not change `protocol.ts` or `sandbox/**`: two Snyk `postMessage` findings there are accepted by design.
- **Route manifest.** Any new router route must be in `route-manifest.json`, and then it must pass axe in every mode. The mockups must therefore render outside the router (demo `withDemoBanner` path switch), not as a route.
- **Prod exclusion.** The mockups and `NS_MOCK_PROFILE` code live only in demo or test code. Extend `no-demo-in-prod.test.ts` with a mockup marker string.
- **Static native-controls test** scans `src/app` too, so the mockups use Fluent controls (or none).
- **Shared modules.**
  - `ForbiddenState` (workspaces) is imported by five features: lane 7 owns it, the others import only.
  - Overview imports `KindBadge`/`MetricText` from dashboards: same lane (6).
  - Copilot imports `SaveReportDialog`/`buildSaveReportRequest` from reports: lane 8 keeps their props.
- **Mock server** is one file of about 2,200 lines. Only item 5 edits it. Lanes needing new e2e fixtures ask the orchestrator, which sequences an additive follow-up. Never edit it in parallel.
- **Stub token carries one role** (`stubMsal.ts:12`, `STUB_TOKEN` uses `STUB_ROLES[0]`), and the mock derives the role from it (`server.ts:56-57`). The demo persona is a single role.
- **Map and WebGL.** Headless fps is SwiftShader: `map-perf` records it and never fails on it. Mask the canvas in pixel baselines. `reuseExistingServer` crosses worktrees, so use unique ports per lane.
- **Visual baselines are platform-specific** (fonts, antialiasing). Generate them only on Linux via the Docker image whose tag matches `@playwright/test`. Fix the clock (relative times), timezone and locale, or every run differs.
- **Day-grain dates in local time** shift by a day west of UTC. Format day-grain values in UTC.
- **CI time.** The frontend job cap is 25 min and recent runs took 10-15 min. The a11y matrix roughly doubles. Keep new specs lean, use shared fixtures, and shard if needed (clarification 15).
- **Demo ports.** `pnpm demo` defaults to 5180/5181 and lanes collide. Set `NS_DEMO_APP_PORT`/`NS_DEMO_API_PORT` per worktree.
- **CodeQL rules that fail PRs**: `js/bad-tag-filter` (no regex HTML parsing), plus gitleaks: split credential-shaped literals in tests. Put these in every brief.
- **Licence gate.** `python scripts/licenses_report.py --check` must stay PASS. Transitive d3 modules under vega are not importable directly under pnpm and must not be added as direct deps.

### External references
- Fluent UI v9 theming and tokens: https://react.fluentui.dev/?path=/docs/concepts-developer-theming--docs (9.74.x, pinned in `docs/adr/0002-stack-pins.md`).
- Playwright visual comparisons (`toHaveScreenshot`, `maxDiffPixelRatio`, `mask`, `animations`): https://playwright.dev/docs/test-snapshots. Playwright Docker image: https://playwright.dev/docs/docker. Clock API: https://playwright.dev/docs/clock.
- `Intl.RelativeTimeFormat` / `Intl.DateTimeFormat` / `Intl.NumberFormat` (currency): https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl.
- WCAG 2.2: 1.4.1 Use of Color, 1.4.3 Contrast (Minimum), 1.4.11 Non-text Contrast, 2.3.3 Animation from Interactions: https://www.w3.org/TR/WCAG22/.

### Style contract (items 2-10 code against it)
- `UiStyleId = "ops-console" | "enterprise-fluent"`. `useUiStyle()` returns `{ id, density: "compact" | "comfortable", chart: ChartTheme, health: HealthPalette, treatment: ComponentTreatment }` for the active style and mode. The provider root carries `data-ui-style`.
- `ChartTheme`: `categorical[]`, `estimated` / `invoiced` stroke, dash and fill, `grid`, `axis`, `unknownGap`, `incompleteMarker`, `tooltip` surface, with all colours as token values.
- `HealthPalette`: `ok`, `degraded`, `failing`, `unknown`, each `{ fg, bg, icon }`, at least 3:1 against the surface.
- Store: `styleId`, `setStyle(id)`, `applyDeploymentDefault({ packId?, themeName?, styleId? })`.
- Exports for PRP-31: `PageTemplate` v2, `KpiCard`, `StatusPill`, `HealthIndicator`, `EmptyState`, `LoadingState`, `ErrorState`, `Timestamp`, `DataTable`, `TimeSeriesChart`, `Sparkline`, `BarChart`, `ChartLegend`, `NeuroSphereMark`, `useUiStyle`. Signatures are frozen at the checkpoint; later changes are additive only.

## Implementation blueprint

### Item 1 - style-foundation
- Deliverable:
  - The style registry, resolver and context per the style contract.
  - Style, chart and health tokens in `tokens/`.
  - The store extension (`styleId`, `setStyle`, deployment default, preferred-mode rule).
  - `AppThemeProvider` composing mode × pack × style, with `data-ui-style` on the root.
  - Placeholder `index.ts` files for `components/`, `charts/`, `brand/` and `format/`, re-exported once from `design-system/index.ts`, so items 2 and 3 never edit the root index.
  - A short `frontend/src/design-system/styles/README.md` on the composition rules, matching `themes/README.md`.
- Owned files (may edit): `frontend/src/design-system/styles/**` (new), `frontend/src/design-system/tokens/**`, `frontend/src/design-system/theme-store.ts`, `frontend/src/design-system/AppThemeProvider.tsx`, `frontend/src/design-system/index.ts`, `frontend/src/design-system/theme.test.tsx`, `frontend/src/design-system/tokens.test.ts`, placeholder `frontend/src/design-system/{components,charts,brand,format}/index.ts` (new, empty exports).
- Must NOT touch: `frontend/src/design-system/themes/**` (PRP-24 packs; import only), `frontend/src/design-system/page/**`, `frontend/src/app/**`, `frontend/src/features/**`, `frontend/tests/**`, `frontend/src/api/**`, `frontend/src/auth/**`, `frontend/package.json`.
- Depends on: none.
- Acceptance criteria:
  - Every style × mode × pack resolves to a theme where all `TEXT_PAIRS`/`UI_PAIRS` pass; unsafe style overrides are dropped (test with a deliberately failing override).
  - HC ignores style colours.
  - Persistence and precedence as in the PRP acceptance criteria. A record without `styleId` is not rewritten.
  - Health palettes are at least 3:1 against `colorNeutralBackground1` in every style × mode.
  - The boundary test shows no api/auth import from `styles/`.
  - The hex rule stays green.
- Pattern references: `themes/resolve.ts:13-23`, `themes/contrast.ts`, `theme-store.ts:29-101`, `AppThemeProvider.tsx:31-46`, `themes/no-api-import.test.ts`.
- Tests to write: `frontend/src/design-system/styles/styles.test.ts`, `frontend/src/design-system/styles/no-api-import.test.ts`, extended `frontend/src/design-system/theme.test.tsx` (store and provider).

### Item 2 - brand-and-component-primitives  [P]
- Deliverable:
  - The NeuroSphere mark and wordmark (`brand/`).
  - The static `frontend/public/brand/neurosphere-mark.svg` and `frontend/public/favicon.svg`, plus the favicon `<link>` in `frontend/index.html`.
  - In `components/`: `KpiCard`, `StatusPill`, `HealthIndicator`, `EmptyState`, `LoadingState`, `ErrorState`, `Timestamp`, `DataTable`.
  - Format helpers in `format/`: number, currency per currency, duration, relative and absolute time, UTC day.
  - `PageTemplate` v2 (additive `kpis` and `layout` props, style density), all reading `useUiStyle()`.
- Owned files (may edit): `frontend/src/design-system/brand/**`, `frontend/src/design-system/components/**`, `frontend/src/design-system/format/**`, `frontend/src/design-system/page/**`, `frontend/public/brand/**` (new), `frontend/public/favicon.svg` (new), `frontend/index.html` (favicon link only).
- Must NOT touch: `frontend/public/config.json` (PRP-29), `frontend/vite.config.ts` (PRP-29), `frontend/src/design-system/{styles,tokens,charts,themes}/**`, `frontend/src/design-system/index.ts`, `frontend/src/app/**`, `frontend/src/features/**`.
- Depends on: Item 1.
- Acceptance criteria:
  - `StatusPill` wraps (no fixed height, `overflow-wrap: anywhere`), and its accessible name equals its text.
  - `HealthIndicator` always renders an icon plus text.
  - `Timestamp`:
    - renders `<time dateTime=ISO>`, with relative text and the absolute value in the accessible name;
    - formats day-grain values in UTC;
    - handles null as "unknown".
  - The format helpers never turn null into 0 and never combine currencies (type signature takes one currency).
  - `PageTemplate` v2 keeps every v1 prop and the single `h1`.
  - The mark is inline JSX (no `dangerouslySetInnerHTML`) and has `aria-hidden`, because the wordmark text carries the name.
  - Axe (vitest-axe) is clean on every primitive in light, dark and HC.
- Pattern references: `page/PageTemplate.tsx:47-80`, `LogoSlot.tsx`, `dashboards/components.tsx:17-61` (data-honesty rules), `tokens/typography.ts`.
- Tests to write: `frontend/src/design-system/components/components.test.tsx`, `frontend/src/design-system/format/format.test.ts`, `frontend/src/design-system/brand/brand.test.tsx`, new `frontend/src/design-system/page/page.test.tsx`.

### Item 3 - chart-primitives  [P]
- Deliverable: `TimeSeriesChart` (line/area, multi-series in one unit and currency), `Sparkline`, `BarChart` and `ChartLegend` as React SVG, plus scale and tick math (nice ticks, time ticks by grain) and a pointer tooltip. They consume `useUiStyle().chart` and render the estimated/invoiced, unknown-gap and incomplete-marker treatments.
- Owned files (may edit): `frontend/src/design-system/charts/**`.
- Must NOT touch: `frontend/src/features/charts/**` (PRP-19 sandbox), the rest of `frontend/src/design-system/**`, `frontend/package.json`, `pnpm-lock.yaml`.
- Depends on: Item 1.
- Acceptance criteria:
  - Mixed units or currencies raise `MixedSeriesError` (test) and render `ErrorState` in production.
  - Unknown points break the line and draw a gap marker. Nothing plots as 0 (test on path data).
  - Estimated is dashed and invoiced is solid, and the legend labels say "estimated"/"invoiced" in words.
  - `role="img"` with a generated summary (series, range, min, max, latest, unknown count).
  - Tooltip content is formatted by `format/` helpers.
  - No vega or sigma import (static test), and renders in jsdom.
  - Motion only under `prefers-reduced-motion: no-preference`.
  - Scale and tick math unit-tested (empty, single point, all unknown, negative, large values).
- Pattern references: `dashboards/components.tsx:122-136` (what it replaces); `features/charts/ChartTable.tsx` (table alternative shape); `map/motion.ts` (reduced-motion handling).
- Tests to write: `frontend/src/design-system/charts/charts.test.tsx`, `frontend/src/design-system/charts/scale.test.ts`.

### Item 4 - mockups-and-approval-checkpoint
- Deliverable:
  - A demo-only mockup gallery under `frontend/src/app/demo/mockups/`: home, cost dashboard and map for each style, built from the item 1-3 primitives with static fixtures. The map is a hand-placed static SVG of the intended look.
  - Rendering: `withDemoBanner` renders the gallery instead of `App` when the path starts with `/__mockups/`, so no router route exists.
  - `frontend/scripts/render-mockups.mjs`, which starts Vite in demo mode on unique ports and writes the 12 PNGs (1440x900, `timezoneId: "UTC"`, fixed clock) to `docs/design/prp-30/mockups/`.
  - The prod-exclusion marker test.

  The orchestrator then **stops for operator approval**.
- Owned files (may edit): `frontend/src/app/demo/mockups/**` (new), `frontend/src/app/demo/index.tsx`, `frontend/scripts/render-mockups.mjs` (new), `docs/design/prp-30/**` (new), `frontend/tests/prod-exclusion/no-demo-in-prod.test.ts`.
- Must NOT touch: `frontend/src/app/` outside `demo/index.tsx` and `demo/mockups/`, `frontend/src/app/route-manifest.json`, `frontend/src/design-system/**` (defects go back to items 1-3 within the checkpoint rework round), `frontend/src/features/**`, `frontend/tests/mock-api/**`.
- Depends on: Items 1, 2, 3.
- Acceptance criteria:
  - 12 PNGs exist and were viewed by the orchestrator before the hand-off (CLAUDE.md: produce media before claiming it).
  - The production `dist/` contains no mockup marker (test).
  - `route-manifest.test.ts` is unchanged and green.
  - The static native-controls test is green.
  - The PR or hand-off lists each PNG with what to judge: density, colour, KPI treatment, chart legibility, logo, map look.
- Checkpoint: the Execution state records `mockups approved <date>` (or `rework requested: <notes>` and then approved), the chosen default style, and any primitive signature changes. A rework round edits only items 1-4 owned files. Wave D does not start without that record.
- Pattern references: `app/demo/index.tsx:48-55`, `main.tsx:15-27`, `tests/prod-exclusion/no-demo-in-prod.test.ts`, `temp/ui-shots.mjs` (screenshot loop; the copy must run from `frontend/` so `@playwright/test` resolves).
- Tests to write: extended `frontend/tests/prod-exclusion/no-demo-in-prod.test.ts`, `frontend/src/app/demo/mockups/mockups.test.tsx` (renders each mockup in jsdom, axe clean).

### Item 5 - shell-chrome-demo-and-fixtures  [P]
- Deliverable:
  - Shell: logo and wordmark in the header; style-aware header, nav and density (no new nav entries); an empty `LogoSlot` hidden when the pack has no logo; the agency logo shown beside the mark.
  - User menu: the "UI style" radio group.
  - Runtime config: the `defaultUiStyle` key and its deployment-default wiring.
  - Requests: the recorded-request test extended to styles.
  - Demo:
    - the in-flow `DemoBanner`;
    - copilot dock and panel restyled, with the launcher-occlusion e2e;
    - the mock rename so "Finance" sorts first;
    - the `NS_MOCK_PROFILE=demo` fixture profile;
    - the `Steward` demo persona (`createStubMsalInstance(roles?)`, default `Viewer`);
    - `demo.mjs` passing the profile;
    - a demo route audit spec;
    - a docs note.
- Owned files (may edit):
  - App: `frontend/src/app/Shell.tsx`, `frontend/src/app/UserMenu.tsx`, `frontend/src/app/navigation.ts` (styling and types only, no entries), `frontend/src/app/config.ts`, `frontend/src/app/config.test.ts`, `frontend/src/app/main.tsx` (demo branch only), `frontend/src/app/demo/DemoBanner.tsx`, `frontend/src/app/shell.test.tsx`, `frontend/src/app/theme-requests.test.tsx`, `frontend/src/app/sandbox-shell.test.tsx`.
  - Copilot: `frontend/src/features/copilot/**`.
  - Mock and test support: `frontend/tests/mock-api/**`, `frontend/tests/e2e-support/stubMsal.ts`.
  - Scripts: `frontend/scripts/demo.mjs` (env only).
  - Specs: `frontend/tests/e2e/shell.spec.ts`, `frontend/tests/e2e/smoke.spec.ts`, `frontend/tests/e2e/hidden-route.spec.ts`, `frontend/tests/e2e/copilot.spec.ts`, `frontend/tests/e2e/demo-audit.spec.ts` (new).
  - Docs: `docs/dev/local-setup.md`.
- Must NOT touch: `frontend/src/design-system/**` (consume; defects to the orchestrator), `frontend/src/features/**` except copilot, `frontend/src/app/demo/mockups/**`, `frontend/src/app/demo/index.tsx`, `frontend/src/app/route-manifest.json`, `frontend/tests/e2e/a11y/**`, `frontend/src/api/**`, `frontend/src/auth/**`, `frontend/public/config.json`, `frontend/vite.config.ts`, `frontend/Dockerfile`, `frontend/nginx.conf` (PRP-29).
- Depends on: Item 4 checkpoint approved.
- Acceptance criteria: the item 5 rows of the PRP acceptance criteria, plus:
  - `copilot.spec` stays green with the same "Open assistant" name.
  - The e2e fixture values that specs pin are unchanged; the full e2e suite runs green.
  - The demo audit visits every manifest route (detail routes through links from their list pages) in the demo profile and asserts no `forbidden-state` and no empty state on first load.
  - The prod build has no `NS_MOCK_PROFILE` reference.
- Pattern references: `Shell.tsx:198-208,233-239,268-277`, `UserMenu.tsx:47-88`, `config.ts:62-81`, `server.ts:78-95,2097`, `stubMsal.ts:11-24`, `demo.mjs:10-17`.
- Tests to write: extended `shell.test.tsx`, `config.test.ts`, `theme-requests.test.tsx`, `copilot.spec.ts` (occlusion); new `frontend/tests/e2e/demo-audit.spec.ts`. The audit runs against a second webServer started in demo mode on unique ports, defined inside the spec file via `test.use`/a fixture, never in `playwright.config.ts` (item 10 owns it).

### Item 6 - lane: overview, dashboards and reconciliation  [P]
- Deliverable:
  - Home: KPI cards, with the cost KPI per currency over the last 7 days plus a sparkline, `HealthIndicator` for map coverage, and N+ counts.
  - Cost, latency and coverage dashboards: KPI strip, `TimeSeriesChart` per currency/unit, `Timestamp` freshness, a restyled `DataTable`, and `StatusPill` for incomplete and price-version text.
  - Reconciliation as cards with a coverage `BarChart`.
  - Empty, loading and error states throughout.
- Owned files (may edit): `frontend/src/features/overview/**`, `frontend/src/features/dashboards/**`, `frontend/src/features/reconciliation/**`, `frontend/tests/e2e/overview.spec.ts`, `frontend/tests/e2e/dashboards/**`.
- Must NOT touch: `frontend/src/design-system/**`, `frontend/src/app/**`, other features (import `ForbiddenState`, don't edit), `frontend/tests/mock-api/**`, `frontend/tests/e2e/a11y/**`.
- Depends on: Item 4 checkpoint approved.
- Acceptance criteria:
  - Item 6 and items 6-9 rows of the PRP criteria.
  - Every testid that specs pin keeps its value semantics. The `watermark` assertion moves to `datetime` with the same ISO value.
  - The A11Y-003 HC invoiced contrast is preserved (`invoiced-badge-contrast.test.tsx` green).
  - At most 7 calls on home.
- Pattern references: `dashboards/components.tsx:17-196`, `overview/OverviewPage.tsx:99-125`, `overview/data.ts:29-38`.
- Tests to write: update `dashboards/__tests__/*` and `overview/overview.test.tsx`; add `dashboards/__tests__/chart-honesty.test.tsx` (per currency, never summed, unknown gaps).

### Item 7 - lane: actions, review, workspaces, sandbox and MCP admin  [P]
- Deliverable: restyle with the primitives. Action and intent states use `StatusPill`/`HealthIndicator`; queues use `DataTable` with empty and loading states; the workspace persona pages become card layouts; `ForbiddenState` becomes `ErrorState`-styled with the same text; `SandboxBanner` is styled per style; the MCP admin list and detail pages are restyled.
- Owned files (may edit): `frontend/src/features/actions/**`, `frontend/src/features/review/**`, `frontend/src/features/workspaces/**`, `frontend/src/features/sandbox/**`, `frontend/src/features/mcp-admin/**`, `frontend/tests/e2e/actions/**`, `frontend/tests/e2e/mcp-admin.spec.ts`.
- Must NOT touch: as item 6, plus the PRP-17 confirmation semantics (same executor calls, confirmation dialog, intent hash, focus restore from A11Y-013) and the PRP-24 sandbox banner role and name.
- Depends on: Item 4 checkpoint approved.
- Acceptance criteria: items 6-9 rows. `actions.spec.ts` passes unchanged, including the exact `getByLabel` names at `:50-53`. The sandbox banner keeps its role and accessible name. `forbidden.test.tsx` is green.
- Pattern references: `actions/ActionWorkflow.tsx`, `review/ReviewQueuePage.tsx`, `workspaces/ForbiddenState.tsx`, `sandbox/SandboxBanner.tsx`.
- Tests to write: update the existing feature tests; add one empty/loading/error state test per feature.

### Item 8 - lane: quality, recommendations, reports and chart frame  [P]
- Deliverable: restyle quality (score `KpiCard`s, `BarChart` for distributions), recommendations (cards with impact, confidence and advisory `StatusPill`) and reports (list as cards or `DataTable`, view with styled sections). Restyle the `ChartFrame` outer container and `ChartTable` to the style. The sandbox protocol and render code are not changed.
- Owned files (may edit): `frontend/src/features/quality/**`, `frontend/src/features/recommendations/**`, `frontend/src/features/reports/**`, `frontend/src/features/charts/ChartFrame.tsx`, `frontend/src/features/charts/ChartTable.tsx`, `frontend/src/features/charts/charts.test.tsx`, `frontend/tests/e2e/quality/**`, `frontend/tests/e2e/recommendations/**`, `frontend/tests/e2e/chart-sandbox.spec.ts`.
- Must NOT touch: `frontend/src/features/charts/protocol.ts`, `frontend/src/features/charts/sandbox/**`, `frontend/src/features/charts/harness/**`, `frontend/chart-sandbox.html`, plus the item 6 list. `SaveReportDialog` props and `buildSaveReportRequest` stay unchanged.
- Depends on: Item 4 checkpoint approved.
- Acceptance criteria: items 6-9 rows. The copilot tests still pass against the reports imports. The chart iframe focus indicator from A11Y-014 is kept. The chart-sandbox spec is green.
- Pattern references: `quality/QualityPage.tsx`, `recommendations/RecommendationListPage.tsx`, `reports/ReportsListPage.tsx`, `charts/ChartFrame.tsx:143-150`.
- Tests to write: update the existing feature tests; add `recommendations/__tests__/cards.test.tsx`.

### Item 9 - lane: map, map table and replay  [P]
- Deliverable:
  - Map: a style-aware sigma theme from `useUiStyle()`; `HEALTH_COLOUR` replaced by the health tokens; a better-spaced deterministic layout with zoom-to-fit; legible labels at the demo fixture size; neighbour highlight on hover; legend and node panel as styled cards; and a toolbar built from Fluent controls.
  - Map table and replay restyled with `DataTable`, `Timestamp` and `HealthIndicator`.
- Owned files (may edit): `frontend/src/features/map/**`, `frontend/src/features/map-table/**`, `frontend/src/features/replay/**`, `frontend/tests/e2e/map-perf.spec.ts`, `frontend/tests/e2e/map-reduced-motion.spec.ts`, `frontend/tests/e2e/map-table-keyboard.spec.ts`.
- Must NOT touch: as item 6. Keep `paths.ts` path-only; no new dependency (no layout library).
- Depends on: Item 4 checkpoint approved.
- Acceptance criteria:
  - Item 9 and items 6-9 rows.
  - Layout stays deterministic: the same input gives the same positions (test).
  - The `map-reduced-motion`, `map-table-keyboard` and `map-perf` specs pass.
  - The MapGrid treegrid allowlist entry is unchanged.
  - No sigma import reaches jsdom through the shell or design-system.
- Pattern references: `map/appearance.ts:33-40`, `map/mapGraph.ts:69-81`, `map/renderer.ts:95-99`, `map/motion.ts`, `map-table/MapGrid.tsx`.
- Tests to write: update `map/map.test.tsx` (appearance from tokens, deterministic layout, spacing bounds); update the replay and map-table tests.

### Item 10 - visual-regression-and-a11y-matrix
- Deliverable:
  - A `visual` Playwright project: Linux or `NS_VISUAL=1` only, `snapshotPathTemplate` without a platform suffix, a fixed clock, UTC and en-US, and the canvas mask. It takes the 26 baselines.
  - `frontend/scripts/update-visual-baselines.mjs`, which runs the Playwright Docker image matching `@playwright/test` with `--update-snapshots`.
  - Scripts `test:visual` and `visual:update`.
  - The a11y suite extended with the style dimension (`axe-support.ts` `STYLES`, `seedPreferences` with `styleId`, the themes and routes specs).
  - The `StatusPill` overflow layout spec.
  - A new dated axe results JSON and remediation-log entries.
  - CI sharding only if the frontend job exceeds 20 minutes.
- Owned files (may edit): `frontend/tests/e2e/a11y/**`, `frontend/tests/e2e/visual/**` (new; baselines under `frontend/tests/e2e/visual/__screenshots__/`), `frontend/playwright.config.ts`, `frontend/scripts/update-visual-baselines.mjs` (new), `frontend/package.json` (scripts only), `.github/workflows/ci.yml` (frontend job only, sharding fallback), `docs/accessibility/**` (new dated results and log entries only; checklist sign-off fields stay blank).
- Must NOT touch: `frontend/src/**` (product defects found here are fixed forward by a sequenced item that owns exactly the offending files, under the PRP-24 D5 pattern, after operator sign-off of the file list), `frontend/tests/mock-api/**`, `pnpm-lock.yaml`.
- Depends on: Items 5, 6, 7, 8, 9.
- Acceptance criteria:
  - The item 10 rows of the PRP criteria.
  - The baselines were generated in Docker and committed.
  - Two consecutive CI runs pass with no visual diff.
  - The frontend job time is recorded in the completion note, with sharding applied if it went past 20 minutes.
  - The keyboard pre-check (`routes-keyboard`, `keyboard-flows`, `aria-tree`) is green in the default style.
- Pattern references: `tests/e2e/a11y/themes.a11y.spec.ts:22-48`, `axe-support.ts:28-77`, `route-samples.ts:150-156`, `playwright.config.ts:20-34`.
- Tests to write: `frontend/tests/e2e/visual/visual.spec.ts`, `frontend/tests/e2e/visual/layout.spec.ts`, extended `themes.a11y.spec.ts` and `routes.a11y.spec.ts`.

### Waves
- A = item 1.
- B = items 2 and 3 [P]. They own disjoint `design-system` subfolders; item 1 already re-exported their placeholder indexes.
- C = item 4, then the **MOCKUP APPROVAL CHECKPOINT** (operator; hard stop; at most one rework round inside items 1-4 owned files; the default style is confirmed here).
- D = items 5, 6, 7 and 8 [P] (WIP 4). Their owned files are disjoint: app/copilot/mock, overview/dashboards/reconciliation, actions/review/workspaces/sandbox/mcp-admin, quality/recommendations/reports/chart frame.
- E = item 9 (map lane). It is independent of wave D's files and is held only by the WIP limit.
- F = item 10 (needs the final look of every page).

No shared file is edited in parallel:
- `design-system/index.ts` is item 1 only.
- `tests/mock-api/server.ts` is item 5 only.
- `playwright.config.ts` and `tests/e2e/a11y/**` are item 10 only.
- `app/demo/index.tsx` is item 4 (wave C), and item 5 owns only `DemoBanner.tsx`.

Merge one at a time, running the touched suites after each.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend exec vitest run
pnpm --filter @neurosphere/frontend exec vitest run src/design-system tests/prod-exclusion
pnpm --filter @neurosphere/frontend build
NS_E2E_APP_PORT=<unique> NS_MOCK_API_PORT=<unique> pnpm --filter @neurosphere/frontend exec playwright test
NS_E2E_APP_PORT=<unique> NS_MOCK_API_PORT=<unique> pnpm --filter @neurosphere/frontend exec playwright test tests/e2e/a11y
NS_E2E_APP_PORT=<unique> NS_MOCK_API_PORT=<unique> pnpm --filter @neurosphere/frontend exec playwright test tests/e2e/demo-audit.spec.ts
pnpm --filter @neurosphere/frontend run visual:update    # item 10 only; Docker, Linux baselines
pnpm --filter @neurosphere/frontend run test:visual      # Linux or NS_VISUAL=1
node frontend/scripts/render-mockups.mjs                 # item 4; writes docs/design/prp-30/mockups/*.png
python scripts/licenses_report.py --check
NS_DEMO_APP_PORT=<unique> NS_DEMO_API_PORT=<unique> pnpm demo   # manual: open the printed URL, check landing domain, every page populated, launcher visible, style switch; then stop it
```
Snyk code scan on new first-party code before each merge (0 new issues). There is no live gate: this PRP makes no cloud calls and needs no `NS_LIVE_APPROVED`.

## Live and open gates
- **Mockup approval (operator gate, this PRP).** Wave D is blocked until it is recorded in Execution state. If it is not given, the PRP stays active at wave C. It is never treated as passed by default.
- G09 (accessibility) stays OPEN and owned by the PRP-24 evidence trail. This PRP keeps axe at 0 serious or critical across styles × modes × packs and re-runs the automated pre-check. The human keyboard and screen-reader checklists remain unsigned (an agent never signs them). The tester runbook must now cover both styles; item 10 notes this in `docs/accessibility/` without signing.
- Visual baselines are authoritative on Linux CI only. A Windows run that skips the `visual` project is reported as "not run locally", never as passed.
- No other gate is touched.

## NOT building
- New pages or nav entries: catalog browser, audit log, finops/forecast, federation, deploy scan/plan (PRP-31, which consumes this PRP's primitives).
- Runtime wiring, services, workers, compose, `frontend/vite.config.ts`, `frontend/nginx.conf`, `frontend/Dockerfile`, `frontend/public/config.json`, `frontend/src/api/**`, `frontend/src/auth/**` (PRP-29). Infra (PRP-32).
- Styling of LLM-proposed charts inside the PRP-19 sandbox iframe, and any change to its protocol or render code.
- New npm dependencies (charting, layout or icon libraries) unless the operator approves a licence-checked exception.
- A server-side per-user style store, per-domain styles, or agency-authored styles. Agency SVG logo uploads stay excluded (PRP-24).
- New aggregate API endpoints for KPIs (cards use existing bounded endpoints; "N+" for paged lists).
- Marketing screenshots, deck or video (PRP-26 and PRP-27 consume the restyled UI later). Docs site (PRP-25).
- Localization beyond `Intl` formatting with the browser locale. Mobile-specific layouts beyond the existing compact nav.
- Signing G09 checklists, VPAT or conformance claims.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (open confirmations listed under "Decisions to confirm at plan approval")

## Execution state

Plan approved 2026-10-26. Decisions confirmed: D-a default `enterprise-fluent`; D-c in-house SVG charts; D-b, D-d to D-h accepted as written; D-i moot (PRP-29 shipped).

| Item | Status | Branch | Model | Evidence | Updated |
|------|--------|--------|-------|----------|---------|
| 1 style-foundation | merged | worktree-agent-ada44407b6067d976 | sonnet | e4e5663: typecheck/lint clean, vitest 649/649, build OK, Snyk 0; review APPROVED; on integration design-system+theme-requests 179 passed; merge ae9550e | 2026-10-26 |
| 2 brand-and-component-primitives | merged | worktree-agent-abfe8d48212d2230b | sonnet | 5361ad0: typecheck/lint clean, vitest 679/679, build OK, Snyk 0; review APPROVED; merge 42d3e57 | 2026-10-26 |
| 3 chart-primitives | merged | worktree-agent-ad516ea5d3efa1e6d | sonnet | bcea132: typecheck/lint clean, vitest 686/687 (reports sharing flake, 3/3 isolated), build OK, Snyk 0; review APPROVED; merge 929abae; on integration typecheck/lint/build OK, vitest 717/717 x7 after 2 contention flakes (reports.test sharing, follow-up to item 8) | 2026-10-26 |
| 4 mockups-and-approval-checkpoint | merged | worktree-agent-abf5489aec670eb83 | sonnet | c20a4d3: typecheck/lint clean, vitest 734/734, build OK, Snyk 0 (demo + script), manifest unchanged, 12 PNGs viewed by orchestrator; review APPROVED; merge d0101bc; on integration touched suites 338 passed | 2026-10-26 |
| CHECKPOINT mockup approval | merged | | operator | **mockups approved 2026-10-26 after one rework round (R1, merge 282dda1); default style `enterprise-fluent` confirmed; primitive signatures frozen at 282dda1 (additive only after this), incl. R1 additions: ComponentTreatment panelSurface/kpiAccent/numerals/monoNumerals/kpiMaxAcross/liveIndicator, KpiCard accent, DataTable column width/minWidth, Sparkline unit/currency, countKpis/kpiColumns, UiStyleContext/StyleOverrides root exports.** Original rework notes: (1) Ops console not distinct enough from Enterprise Fluent, (2) orphan 6th KPI card on a 5-col grid, (3) Ops console uppercases sentences and status pills, (4) cost area charts too heavy, estimated/invoiced overlap, (5) home table Item column wraps, flat delta glyph. Default style confirmed `enterprise-fluent`. Rework item R1 dispatched | 2026-10-26 |
| R1 mockup-rework (items 1-4 owned files) | merged | worktree-agent-a4a702f5d9c694dc6 | sonnet | caf6dcd: scope = items 1-4 files only; typecheck/lint clean, vitest 750/750 x2, build OK, Snyk 0 new (4 pre-existing in untouched auth test + chart sandbox); 12 PNGs re-rendered and viewed by orchestrator; review APPROVED; merge 282dda1; on integration touched suites 354 passed | 2026-10-26 |
| 5 shell-chrome-demo-and-fixtures | in-progress | worktree-agent-a363d72dd2daaf9ac | sonnet | 7d6b64d: typecheck/lint/build OK, vitest targeted 262/262, e2e shell/smoke/hidden/copilot/demo-audit 17/17 (lane: full 337/337), prod dist no demo markers. **PRP delta signed off 2026-10-26:** lane relaxed demo mock authz (Steward into MCP admin, any persona workspace) to meet "every route shows data"; operator chose faithful mock: revert relaxations, demo-audit expects forbidden-state on an explicit allowlist (admin-only and other-persona routes). 5b 3900f2d reverted both relaxations, EXPECTED_FORBIDDEN = /mcp-admin, /mcp-admin/server, /workspaces/{admin,analyst,auditor,viewer}; lane full Playwright 339/339; Snyk 0 new (3 tests/ findings identical fingerprints on integration baseline); review APPROVED (5+5b); merge 9bc52dc | 2026-10-26 |
| 6 lane-overview-dashboards-reconciliation | merged | worktree-agent-acdafa8e5f17673cc | sonnet | 11073d1: home 6 calls (days=7 one call); typecheck/lint/build OK, vitest targeted 516/516, e2e overview+dashboards 19/19 (lane: 259 incl a11y), Snyk 0 new; watermark asserts normalised datetime (same instant, reviewer OK); review APPROVED; merge 23795a4; post-merge 402 passed | 2026-10-26 |
| 7 lane-actions-review-workspaces-sandbox-mcp | merged | worktree-agent-ac3e01a09b51aa067 | sonnet | 0a9877e: actions e2e unchanged, PRP-17 semantics intact; typecheck/lint/build OK, vitest targeted 270/270, e2e actions+mcp-admin 19/19 (lane: 259 incl a11y), Snyk 0; confirm expiry stays raw ISO (pinned, exact confirmed value); local RowTable/StatePanel stand-ins until F1; review APPROVED; merge f540fad; post-merge 206 passed | 2026-10-26 |
| F1 primitive-fix-forward (StatusPill info contrast, DataTable getRowProps, testId props, legend unclassified) | merged | worktree-agent-a4df5d056169ba155 | sonnet | e6268aa: info tone 4.25 -> 14.54 (default light), all tones >= 4.5:1 across pack x style x mode (61 tests); vitest 709/709 (design-system+app+features), build OK, Snyk 0; review APPROVED (haiku); merge 990cd63; orchestrator hardening 082a078 (runtime data-* filter on getRowProps, DataTableRowProps root export), 396 passed | 2026-10-26 |
| 8 lane-quality-recommendations-reports-chartframe | merged | worktree-agent-aa5acb33df5133af5 | sonnet | 524c3f6: typecheck/lint/build OK, vitest targeted 208/208, e2e quality+recs+chart-sandbox 33/33 (lane: 279 incl a11y), Snyk 0; reports flake root cause = Tabster modalizer aria-hidden on dialog surface in jsdom, fixed with hidden:true (same pattern needed in mcp-admin: F2); review APPROVED; merge 774c954; post-merge 459 passed | 2026-10-26 |
| 9 lane-map-maptable-replay | merged | worktree-agent-a2a6d4c151a08242b | sonnet | 6b93aaa: typecheck/lint/build OK, lane Playwright 251/251, vitest map/map-table/replay+static 159 passed (full suite 4 timeouts in other lanes' dialog tests: F2), Snyk 0; review APPROVED; merge 8feda4f; post-merge 501 passed + map specs/demo-audit 13/13 | 2026-10-26 |
| INT wave-D integration check | merged | prp-30-visual-redesign @ 9bc52dc | orchestrator | before item 9: vitest 866/866, build OK, Playwright 338/339 (actions.spec:120 advisory-note 5s timeout under load; actions e2e rerun 16/16 x2 = flake, watch) | 2026-10-26 |
| F2 dialog-test-hardening + enterprise canvas + primitive stand-ins | merged | worktree-agent-ad93b3914c1d96ffa | sonnet | 8c73c6b/94c2ee5/93c7c7b: hidden:true in actions+mcp-admin dialog tests (vitest 882/882 x3), Enterprise canvas Background2, design-system Panel (additive) replaces 5 duplicates, RowTable/StatePanel folded into DataTable/ErrorState (ErrorState +tone/+action additive), info tone restored; net -270 lines; lane Playwright 339/339; Snyk 0 new; review APPROVED; merge 27b4203; on integration vitest 882/882, a11y 240/240 | 2026-10-26 |
| 10 visual-regression-and-a11y-matrix | merged | worktree-agent-af64bdaea1d0c2ffa | sonnet | aa9195e/9456dd1/4415db6: a11y themes 72 + routes 156 (257 checks, 0 critical/serious/moderate/minor, tabster exclusion only); default Playwright 463 passed (4.5m); 26 Linux baselines via playwright v1.64.0-noble; visual:check 26/26 no diff (agent) + 26/26 (orchestrator, 3rd run); CI: test:e2e pinned --project=chromium + visual:check step in the same image (deviation: frontend job change beyond sharding, needed for pixel determinism); est. CI job 16-17 min (not measured), no sharding; G09 OPEN, sign-offs blank; review APPROVED; merge 239aacd; validate_planning PASS | 2026-10-26 |
| F3 chart-pixel-sizing (charts scaled via viewBox: axis text ~2x at wide containers) | in-progress | (worktree) | sonnet | found by orchestrator viewing baselines; dispatched; regenerates affected baselines | 2026-10-26 |

## Completion note (filled at ship)
- Date:
- Merged commits:
- Mockup approval (date, rework notes, default style chosen):
- Deviations from blueprint and why:
- Descoped items:
- axe results (routes × styles × modes, themes × packs) and keyboard pre-check:
- Visual baselines (count, CI runs without diff) and frontend CI job duration:
- G09 status after this PRP (expected OPEN):
- Follow-ups:
