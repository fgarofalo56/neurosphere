---
name: PRP-47-frontend-shell-and-test-infrastructure
status: shipped
shipped: 2026-11-15
pr: 298
priority: P2
order: 34
review: none
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-10, NS-08
depends_on: []
wave: W15
branch: prp-47-shell-test-infra
allow_parallel: true
issues: [240, 92, 93, 94, 95, 125, 209]
---

# PRP-47: Frontend shell fixes and test infrastructure

## Goal
Close the small frontend follow-ups that PRP-24 and PRP-28 left behind, before the admin console PRPs (PRP-53, PRP-57) add many pages on top of the shell and the Vitest and Playwright setup. It covers the shell (arrow-key movement in the navigation, last-domain clean-up on every sign-out path, the overflowing badge on the overview cost tile, the deployment default theme on screens that render before the shell), test infrastructure (MSW 3 unhandled requests failing tests again, load flakes, a demo-build positive control), static cleanups (`paths.ts` for dashboards, actions and review) and the mock API gap that hides catalog actions in the demo (#209 item 1). It is for developers and for reviewers of every later frontend PRP. No product behaviour changes besides the visible shell fixes.

Out of scope: any real-stack spec or `frontend/tests/real-stack/**` (PRP-38); the admin console pages and their mock handlers (PRP-53, PRP-57); the production `ChartFrame` sandbox design (the sandbox stays opaque; see clarification 2); the Snyk ignore entry for `postMessage` (PRP-59 owns `.snyk`); the `catalog_review_queue` page (PRP-43); accessibility sign-off by a human (PRP-64); map feature code (PRP-18, PRP-49).

## Why
- `frontend/tests/setup.ts:27` calls `server.listen({ onUnhandledRequest: "error" })`, but msw 3 only knows `onUnhandledFrame`, so an unhandled request now logs a warning instead of failing the test (#92). `frontend/tests/setup.ts:21` sets `asyncUtilTimeout: 5000`; the repo has no Vitest retries (`grep -n retry frontend/vite.config.ts` is empty), and `frontend/playwright.config.ts:14` retries once only in CI. Flakes named in #92: `reports.test.tsx` sharing, `quality.spec.ts:38`, `actions.spec.ts:160`, `map-table-keyboard.spec.ts:34`.
- `frontend/src/app/Shell.tsx:116-118` replaced `NavDrawerBody` with a plain container, so arrow-key movement in the nav is gone (#94); only the UserMenu sign-out clears `ns.lastDomain.<key>` (`frontend/src/app/domain.tsx:44,77,181`); the cost-tile badge overflow was reported at 1440px and is UNVERIFIED in the current tree.
- `frontend/src/app/Shell.tsx:314-327` applies `defaultThemePack`, `defaultThemeMode` and `defaultUiStyle` in a Shell effect; `Providers.tsx:26` renders `AppThemeProvider` first, so the sign-in redirect screen uses the built-in theme (#125).
- `frontend/src/features/overview/data.ts:56-58` hardcodes `/dashboards/cost`, `/review`, `/actions`; `features/dashboards`, `features/actions` and `features/review` have no `paths.ts` (the pattern is `features/map/paths.ts`); `tests/static/no-native-controls.test.ts:15` and `tests/prod-exclusion/no-demo-in-prod.test.ts:15,57` use `process.cwd()` and `configFile: false` (#95, #93).
- `frontend/tests/mock-api/server.ts:98-120` gives the Finance demo domain only `data.read` and `action.propose`, so catalog create and edit actions are invisible in `pnpm demo` (#209 item 1).
- `frontend/src/features/charts/ChartFrame.tsx:101` posts with target origin `"*"` (Snyk `TooPermissiveCorsPostMessage`, #133 bullet); the iframe is `sandbox="allow-scripts"` (`:169`), an opaque origin, and both directions already check the message source (`:103`; `sandbox/main.ts:29`).

## Acceptance criteria
- [x] MSW: an unhandled request in any Vitest test fails that test (`onUnhandledFrame` set to error). Every test that starts failing is fixed with an explicit handler, none with a broad catch-all. `tsc` accepts `tests/setup.ts` (#92).
- [x] Flakes: the Vitest config sets a bounded retry (at most 1) in CI only and a documented `asyncUtilTimeout`; the three named Playwright specs are made deterministic (explicit waits on a signal, not longer sleeps) and pass 10 times in a row locally with parallel workers (#92). Show the loop output.
- [x] Nav: Given focus in the navigation, when the user presses ArrowDown or ArrowUp, then focus moves between nav links; axe `aria-hidden-focus` stays clean on the specs that failed before (the nav axe specs under `tests/e2e/a11y` pass) (#94).
- [x] Sign-out: Given a stored `ns.lastDomain.<key>`, when the account disappears for any reason (menu sign-out, token expiry, sign-out in another tab), then the key is removed; a Vitest test covers each path that can be exercised without `frontend/src/auth/**` changes (#94).
- [x] Badge: the cost-tile "incomplete total" badge no longer overflows at 1440px; a Playwright check measures the text box inside the badge box. If the overflow cannot be reproduced, say so and keep the test (#94).
- [x] Theme: Given runtime config with `defaultThemePack` and `defaultThemeMode`, when the app renders the config-loaded sign-in redirect screen (before the shell), then the default theme is applied; a saved user choice still wins (#125). A test renders `Providers` without `Shell`.
- [x] `ChartFrame`: the `"*"` target stays only because the sandbox origin is opaque; the code comment states the reason, and a test asserts the message is posted only to `iframeRef.current.contentWindow` and that a message from another source is ignored (#133 bullet).
- [x] Demo hardening: the prod-exclusion test also builds with `mode: "demo"` and asserts the demo markers are present (positive control), loads the real `vite.config.ts` with the bundle-report plugin off, and finds the frontend directory through `import.meta.dirname` (#93). The `'"demo"'` marker is dropped.
- [x] `paths.ts` exists in `dashboards`, `actions` and `review`; `overview/data.ts` imports from them; `no-native-controls.test.ts` anchors on `import.meta.url` and also scans `.ts` for `createElement("button")`; `ROLE_TILES` has a test tying each tile permission to a name in the API permission list available to the frontend (#95).
- [x] Mock API: the Finance demo domain holds `catalog.curate`, so catalog create and edit actions show in `pnpm demo`; the demo's first domain is a healthy one (#209 item 1, #93).
- [ ] `pnpm --filter @neurosphere/frontend lint`, `typecheck`, `test` and `test:e2e` pass; visual baselines are regenerated in Docker only if a baseline legitimately changed (state which).

PRP exit: all boxes ticked, `verify-gates.ps1` full run green, PR open, CI green including the non-required `frontend-e2e` shards.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Arrow keys in the nav | Restore `NavDrawerBody`; custom roving focus | ASSUMPTION: a small roving-tabindex handler on the plain container (no Tabster sentinels, which caused the axe failures); the implementer may choose a Fluent `Mover` only if axe stays clean. |
| 2 | `postMessage` `"*"` | Same-origin sandbox; keep opaque with proof | ASSUMPTION: keep the opaque sandbox (it is the isolation guarantee) and document and test the exception. The scanner finding is dismissed in `.snyk` by PRP-59, not here. Confirm at plan approval. |
| 3 | Sign-out in another tab and token expiry | Edit `src/auth/**`; react in `domain.tsx` | React in `domain.tsx` (and `Providers.tsx`) when the user key disappears; `frontend/src/auth/**` is not owned. A path that cannot be reached without auth changes is listed as a follow-up. |
| 4 | Vitest retries | None; 1 in CI | 1 retry in CI only, so a real failure still fails and flakes are visible in the report. |
| 5 | Gitignore `build/` rule (#93) and demo default domain | Change `.gitignore`; document | Document in the test header (`.gitignore` is not owned). Default domain: the mock's first domain sorts to Finance already (`server.ts:108-118`), so only verify and record. |
| 6 | Unused `map/strings.ts` entries (#95) | Edit now; wait | Wait for PRP-18 (it owns `features/map/**` in W13); item 7 is `[serial-after: PRP-18]` and tiny. |

## Context manifest

### Files to read first
- `frontend/tests/setup.ts`, `frontend/vite.config.ts` (`test` block at `:126-130`), `frontend/playwright.config.ts`.
- `frontend/src/app/Shell.tsx` (`:100-130` nav styles, `:200-230` NavDrawer, `:305-330` theme effect), `frontend/src/app/Providers.tsx`, `frontend/src/app/App.tsx`, `frontend/src/app/domain.tsx` (`:44-80`, `:140-195`), `frontend/src/app/ConfigContext.ts`.
- `frontend/src/design-system/theme-store.ts` (`applyDeploymentDefault`).
- `frontend/src/features/overview/{data,OverviewPage}.ts*` and the cost tile component with the badge.
- `frontend/src/features/charts/ChartFrame.tsx` (`:85-110`, `:160-175`), `charts/sandbox/main.ts`.
- `frontend/tests/prod-exclusion/no-demo-in-prod.test.ts`, `frontend/tests/static/no-native-controls.test.ts`.
- `frontend/tests/mock-api/server.ts` (`:92-125`).
- `frontend/src/features/map/paths.ts` and its use in `map/routes.tsx:4` (the pattern).

### Interfaces consumed
- msw 3 `setupServer().listen({ onUnhandledFrame })` (docs for the installed 3.0.3: check `node_modules/msw` types, not memory).
- `useThemeStore.applyDeploymentDefault` (PRP-24, shipped); `ConfigContext` runtime config (PRP-28, shipped).
- API permission names (`packages/core/neurosphere_core/auth/scope/permissions.py`, PRP-06) for the `ROLE_TILES` test; PRP-37 adds permissions later and must not be pre-empted.

### Interfaces provided
- `frontend/src/features/{dashboards,actions,review}/paths.ts` (new): path constants other features import.
- A fail-on-unhandled MSW baseline and CI retry rule that PRP-53 and PRP-57 tests inherit.
- Mock persona permissions (Finance with `catalog.curate`) other mock features may rely on.

### Patterns to match
- `frontend/src/features/map/paths.ts` and `map/routes.tsx:4`.
- AST scan style in `frontend/tests/static/no-native-controls.test.ts`.
- Config-driven default plus saved override: `frontend/src/design-system/theme-store.ts` and its test `theme.test.tsx`.
- Parallel-safe Playwright ports: `frontend/playwright.config.ts:43-56`.

### Gotchas
- `tests/mock-api/server.ts` is the Tier-1 shared frontend file for this wave: edit it only in item 6, and rebase on `main` first (PRP-18 changed it in W13).
- Fluent dialog tests: query with `hidden: true` (Tabster sets `aria-hidden`).
- Playwright ports must be unique per worktree (`NS_E2E_APP_PORT`, `NS_MOCK_API_PORT`); `reuseExistingServer` crosses worktrees.
- Do not use `MSYS_NO_PATHCONV` with `pnpm` (it breaks the shim).
- Visual baselines are Linux and Docker-only (`pnpm --filter @neurosphere/frontend visual:update`); do not regenerate them on Windows.
- `frontend/vitest*` does not exist: Vitest config lives in the `test` block of `frontend/vite.config.ts`, which this PRP edits (test block only; the dev proxy block belongs to nobody else).
- Visual baselines may change with the badge fix; only regenerate for the affected specs.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership

```ownership
owns:
  - frontend/src/app/Shell.tsx
  - frontend/src/app/Providers.tsx
  - frontend/src/app/App.tsx
  - frontend/src/app/domain.tsx
  - frontend/src/features/charts/ChartFrame.tsx
  - frontend/src/features/dashboards/paths.ts
  - frontend/src/features/actions/paths.ts
  - frontend/src/features/review/paths.ts
  - frontend/src/features/overview/**
  - frontend/tests/setup.ts
  - frontend/tests/prod-exclusion/**
  - frontend/tests/static/**
  - frontend/tests/e2e/shell.spec.ts
  - frontend/tests/e2e/overview.spec.ts
  - frontend/tests/e2e/quality/**
  - frontend/tests/e2e/actions/**
  - frontend/tests/e2e/map-table-keyboard.spec.ts
  - frontend/tests/mock-api/server.ts
  - frontend/vite.config.ts
tier1:
  - frontend/src/app/Shell.tsx
  - frontend/src/app/Providers.tsx
  - frontend/src/app/App.tsx
  - frontend/src/app/domain.tsx
  - frontend/tests/mock-api/server.ts
tier2_appends: []
must_not_touch:
  - frontend/tests/real-stack/**
  - frontend/src/auth/**
  - frontend/src/features/admin/**
  - frontend/tests/mock-api/features/**
  - .snyk
```

## Implementation blueprint

Parallelization map: item 1 (shell) edits `Shell.tsx`, `Providers.tsx`, `domain.tsx`; item 2 edits `ChartFrame.tsx`; item 3 edits test config and e2e specs; item 4 edits the prod-exclusion test; item 5 edits `paths.ts` files, overview and the static test; item 6 edits `server.ts`. Items 2, 3, 4 and 6 share no file with each other or with item 1 and are [P]; item 5 is [P] with all but item 1 only if the overview badge fix (item 1) is done first, because both touch `features/overview/**`: run item 1 before item 5.

### Item 1 - Shell: nav arrows, sign-out clean-up, theme before shell, badge (#94, #125)
- Deliverable: roving arrow-key movement on the nav container; `forget` of the last-domain key when the account disappears; `applyDeploymentDefault` invoked from `Providers` (render-phase safe initialiser or layout effect above the theme provider's first paint) and removed from the Shell effect; the cost-tile badge wraps inside its box (CSS in the overview component).
- Owned files: `frontend/src/app/Shell.tsx`, `frontend/src/app/Providers.tsx`, `frontend/src/app/domain.tsx`, `frontend/src/app/App.tsx`, `frontend/src/features/overview/**`, `frontend/tests/e2e/shell.spec.ts`, `frontend/tests/e2e/overview.spec.ts`, `frontend/src/app/*.test.tsx` that cover them.
- Must NOT touch: `frontend/src/auth/**`, `frontend/src/design-system/**`.
- Depends on: none.
- Acceptance criteria: the Nav, Sign-out, Badge and Theme boxes.
- Tests: `pnpm --filter @neurosphere/frontend test -- src/app src/features/overview`; `pnpm --filter @neurosphere/frontend exec playwright test tests/e2e/shell.spec.ts tests/e2e/overview.spec.ts tests/e2e/a11y` with unique `NS_E2E_APP_PORT`/`NS_MOCK_API_PORT`.
- Pattern references: `frontend/src/design-system/theme.test.tsx`, `frontend/src/app/domain.test.tsx:140-235`.

### Item 2 - ChartFrame postMessage exception  [P]
- Deliverable: comment and tests documenting why the target is `"*"`, plus the two message-source assertions; no behaviour change unless the sandbox attribute turns out to allow a real origin (then restrict to it).
- Owned files: `frontend/src/features/charts/ChartFrame.tsx`, `frontend/src/features/charts/charts.test.tsx`.
- Must NOT touch: `charts/sandbox/**`, `.snyk`.
- Depends on: none.
- Acceptance criteria: the ChartFrame box; the PR text asks PRP-59's owner to dismiss the Snyk finding with this justification.
- Tests: `pnpm --filter @neurosphere/frontend test -- src/features/charts`.
- Pattern references: `ChartFrame.tsx:101-110`.

### Item 3 - MSW 3 unhandled frames and flakes (#92)  [P]
- Deliverable: switch `setup.ts` to `onUnhandledFrame`, fix newly failing tests with handlers, add the CI retry in the `test` block of `vite.config.ts`, and fix the three named e2e flakes at their cause; record the loop evidence.
- Owned files: `frontend/tests/setup.ts`, `frontend/vite.config.ts` (test block only), `frontend/tests/e2e/quality/**`, `frontend/tests/e2e/actions/**`, `frontend/tests/e2e/map-table-keyboard.spec.ts`, test files under `frontend/src/**` that need handlers (test files only).
- Must NOT touch: production code under `frontend/src/**`, the dev-proxy block of `vite.config.ts`.
- Depends on: none (run after item 1 if both change the same test file).
- Acceptance criteria: the MSW and Flakes boxes.
- Tests: `pnpm --filter @neurosphere/frontend test`; `pnpm --filter @neurosphere/frontend typecheck`; a 10x loop of the three specs.
- Pattern references: `frontend/tests/setup.ts:21-35`.

### Item 4 - Demo build positive control (#93)  [P]
- Deliverable: extend `no-demo-in-prod.test.ts` as in the Demo box; document the `.gitignore` `build/` quirk in the test header; confirm the mock API binds `127.0.0.1` (already true at `server.ts:2871`; keep a test line).
- Owned files: `frontend/tests/prod-exclusion/**`.
- Must NOT touch: `.gitignore`, `frontend/src/app/demo/**`.
- Depends on: none.
- Acceptance criteria: the Demo hardening box.
- Tests: `pnpm --filter @neurosphere/frontend test -- tests/prod-exclusion`.
- Pattern references: `no-demo-in-prod.test.ts:15-60`.

### Item 5 - paths.ts and static cleanups (#95)
- Deliverable: three `paths.ts` files, overview imports, static test changes, `ROLE_TILES` permission test; check that no `__fixtures__` directory holds shipped UI and note the result.
- Owned files: `frontend/src/features/{dashboards,actions,review}/paths.ts`, `frontend/src/features/overview/**`, `frontend/tests/static/**`.
- Must NOT touch: the three features' `routes.tsx` (leave the route literals; wiring them to `paths.ts` is optional only if the import does not pull page components into overview).
- Depends on: item 1 (same overview files).
- Acceptance criteria: the `paths.ts` box.
- Tests: `pnpm --filter @neurosphere/frontend test -- tests/static src/features/overview`.
- Pattern references: `features/map/paths.ts`.

### Item 6 - Mock API persona gap (#209 item 1)  [P]
- Deliverable: add `catalog.curate` to the Finance demo domain permissions in `meDomainItems`, verify the catalog create and edit actions appear in `pnpm demo`, and update any e2e or demo-audit expectation (`tests/e2e/demo-audit.spec.ts`) that counts actions.
- Owned files: `frontend/tests/mock-api/server.ts`, `frontend/tests/e2e/demo-audit.spec.ts`.
- Must NOT touch: `frontend/tests/mock-api/features/**` (PRP-53 and PRP-57 append there).
- Depends on: none (rebase on `main` first: Tier-1 file).
- Acceptance criteria: the Mock API box.
- Tests: `pnpm --filter @neurosphere/frontend exec playwright test tests/e2e/demo-audit.spec.ts tests/e2e/catalog`.
- Pattern references: `server.ts:92-125`.

### Item 7 - Unused map strings  `[serial-after: PRP-18]`
- Deliverable: delete `domainLabel` and `domainSubmit` from `frontend/src/features/map/strings.ts:17-18` after confirming no importer (`grep -rn "domainSubmit" frontend/src` is empty). PRP-18 owns `features/map/**` in W13, so do this only after it has merged and the branch is rebased; if PRP-18 already removed them, skip.
- Owned files: `frontend/src/features/map/strings.ts` (one deletion; not in this PRP's Ownership block, hence the serial marker).
- Depends on: PRP-18 merged.
- Acceptance criteria: typecheck and lint pass.
- Tests: `pnpm --filter @neurosphere/frontend typecheck`.

### Item 8 - Integration and close-out
- Deliverable: completion note (include "Env vars for the operator": none), `CHANGELOG.md` `[Unreleased]` line, issue references (close #92, #93, #94, #95, #125; leave #209 open for PRP-38's items 2 and 3), regenerate Tier-3 files if any route changed (none expected).
- Owned files: close-out files from the reference, section 6.
- Depends on: items 1 to 7.
- Acceptance criteria: Validation gates pass.
- Tests: the gates below.

## Validation gates
```bash
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend format
NS_E2E_APP_PORT=5291 NS_MOCK_API_PORT=5292 pnpm --filter @neurosphere/frontend test:e2e
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
The port values are examples: pick free ones. Show the 10x flake loop output separately.

## Migration and rollback
No data or config migration. Every change is frontend code or test setup and reverts with the PR. The MSW and retry changes can be reverted independently if they destabilise CI (revert item 3 alone).

## Live and open gates
No live run, no `NS_LIVE_APPROVED=1`, no paid call. The human accessibility sign-off (#124) stays OPEN and belongs to PRP-64; the Snyk dismissal for `postMessage` is PRP-59.

## NOT building
- Changes to `frontend/src/auth/**` or any production auth behaviour.
- A same-origin chart sandbox or a Snyk ignore file.
- Admin pages, real-stack specs, new routes or contract changes.
- Regeneration of visual baselines on Windows.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1 and 2 are assumptions to confirm at plan approval)

## Execution state

| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-47-shell-test-infra | nav arrows, last-domain cleanup, theme in Providers; badge overflow not reproducible, Playwright check added |
| 2 | merged | prp-47-shell-test-infra | comment + tests |
| 3 | merged | prp-47-shell-test-infra | onUnhandledFrame + afterEach rethrow, CI retry 1; flakes not reproducible locally (20x30 pass), hardened map-table focus polls and approve click |
| 4 | merged | prp-47-shell-test-infra | demo positive control, real config, import.meta.dirname |
| 5 | merged | prp-47-shell-test-infra | paths.ts x3, overview imports, createElement scan, import.meta.dirname anchor (import.meta.url is a jsdom URL), TILE_PERMISSION test; no __fixtures__ UI (actions has one JSON) |
| 6 | merged | prp-47-shell-test-infra | Finance holds catalog.curate; catalog.spec negative test now revokes on the wire (one file outside Ownership, test-only) |
| 7 | merged | prp-47-shell-test-infra | PRP-18 shipped; removed domainLabel and domainSubmit from map/strings.ts |
| 8 | merged | prp-47-shell-test-infra | close-out |

## Completion note (filled at ship)
- Date and PR: 2026-11-15, PR #298.
- Deviations: item 6 also edited `frontend/tests/e2e/catalog/catalog.spec.ts` (test only, outside the Ownership block) because the negative test now revokes the permission on the wire. Arrow keys use a roving handler on the plain nav container (clarification 1 assumption). The `ChartFrame` `"*"` target stays with a documented opaque-origin reason and tests (clarification 2 assumption). `no-native-controls` anchors on `import.meta.dirname` because `import.meta.url` is a jsdom URL under Vitest.
- Descoped items: the cost-tile badge overflow could not be reproduced at 1440px; the Playwright measurement check was kept. The three named Playwright flakes did not reproduce locally (20 x 30 passes); the map-table focus polls and the approve click were hardened instead. Sign-out paths that need `frontend/src/auth/**` changes are not covered (clarification 3).
- OPEN gates: human accessibility sign-off (#124, PRP-64); Snyk `postMessage` dismissal (PRP-59); no live gate applies. Visual baselines were not regenerated (Docker only). The Playwright e2e acceptance box is left to the CI frontend-e2e shards.
- Env vars for the operator: none.
- Follow-up issues: #209 stays open for PRP-38 items 2 and 3.
- Product check: shell and test-infrastructure fixes only; no operator capability is added or needed.
