---
name: PRP-140-navigation-grouping
status: backlog
priority: P1
order: 140
review: none
created: 2026-11-17
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 9
ns: NS-01
depends_on: []
wave: W18b
branch: prp-140-navigation-grouping
allow_parallel: true
issues: []
---

# PRP-140: Navigation grouping (reviewed groups, a separate Admin group, collapsible sections)

## Goal
Make the side navigation usable at its real size. Today 45 entries sit under six headers and one header, Governance, holds 24 of them, including all eleven admin pages, with nothing to fold. This PRP regroups the entries into nine coherent groups (Admin and Platform split out of Governance, review work split from governance records), and turns each group into a section that opens and closes. The group that holds the current page is always open, the choice of the others is remembered per browser, and the sections work from the keyboard, announce their state to screen readers and look right in both UI styles and in the narrow overlay. It is for every signed-in user, and for the owner who asked to "add grouping to the navigation bar". Later waves add many pages (the plan lists about forty more titles); the nine groups have room for them and a new page stays a one-line change.

Out of scope: any new page, route or permission; changing which role or permission shows an entry (`isNavItemVisible` is untouched); a search box or "favourites" in the nav; an icon-only rail; the identity admin pages and role mapping (PRP-138 owns `frontend/src/features/admin/`); page-level empty states (PRP-139); renaming a route path or an entry label other than the ones in the table below. A tenth group is not added here (see clarification 8).

## Why
- One group is the whole product. `NAV_GROUPS` lists six names (`frontend/src/app/navigation.ts:4-11`) and `buildAppNavItems` puts thirteen feature entries and the eleven admin areas under "Governance" (`frontend/src/app/workspaceNav.ts:71-85`): review, actions, gateways, publication, recertifications, stale agents, relationship review, audit log, compliance evidence, deployment, capabilities, execution control, MCP servers (the 13, from the `*NavItems` functions in each `features/*/routes.tsx`) plus `adminCoreNavItems()` (`workspaceNav.ts:82`), which maps `ADMIN_AREAS` to eleven `Admin: ...` entries (`frontend/src/features/admin/routes.tsx:29-37`, eleven `label:` fields in `frontend/src/features/admin/shared/areas.ts`).
- Real counts with every feature on (workspaces and permission-gated entries all visible): Overview 6 (Home and five persona workspaces, `workspaceNav.ts:47-53`, `features/workspaces/personas.ts`; a seventh, Sandbox, appears while sandbox mode is on, `workspaceNav.ts:95-101`), Cost & usage 6 (three dashboards at `features/dashboards/routes.tsx:13-15,25`, reconciliation, forecast, federation), Agents 4, Quality 3, Governance 24, Reports 1; 44 entries, 45 with Sandbox. Governance is 55 percent of the list. A given user sees fewer (roles and permissions filter at `Shell.tsx:364`), but an Admin sees all of it.
- There is no Admin group. `NavGroup` is the closed union of those six names (`navigation.ts:12`), `inGroup` stamps a group onto a list (`workspaceNav.ts:36-38`), and the admin pages carry only an `Admin: ` prefix in their label (`admin/routes.tsx:33`) to say what they are.
- Sections cannot fold and have no hierarchy beyond header text. `ShellNav` maps each section to a `role="group"` div with a `NavSectionHeader` (`role="presentation"`) followed by every link (`Shell.tsx:234-264`). Nothing stores open or closed state.
- The pieces to build on exist. Navigation focus uses a plain arrow-key handler instead of Tabster because Tabster's `aria-hidden` sentinels fail axe (`Shell.tsx:270-296`, and the comment at `Shell.tsx:124-126`). UI preferences already persist through a zustand `persist` store (`frontend/src/features/sandbox/store.ts:1-33`, key `ns.sandbox-mode`) and a theme store (`frontend/src/design-system/theme-store.ts:9`, key `ns.theme`). The narrow layout is an overlay drawer under 720 px (`Shell.tsx:48,152-168,229-231`). Two UI styles exist, `ops-console` and `enterprise-fluent` (`frontend/src/design-system/styles/registry.ts:9,32`), and the nav already styles per style (`Shell.tsx:226-227,255-257`). `@fluentui/react-nav` 9.4.9 is installed and exports `NavCategory`, `NavCategoryItem`, `NavSubItemGroup` and, on `NavDrawer`, `openCategories` and `onNavCategoryItemToggle` (checked in `node_modules/.pnpm/@fluentui+react-nav@9.4.9*/.../dist/index.d.ts`); its category button sets `aria-expanded` (`useNavCategoryItem.js:81`). Nothing in `frontend/src` uses `NavCategory` or an Accordion yet.
- The mock-up frame carries its own copy of the grouped nav (`frontend/src/app/demo/mockups/MockupFrame.tsx:286-310`, data in `fixtures.ts:11-18`); it is a static demonstration with six sample groups and no state.

## Acceptance criteria
- [ ] Given the full entry list, When it is grouped, Then the groups appear in this order with these counts: Overview 7 (with Sandbox, otherwise 6), Cost & usage 6, Agents 4, Quality 3, Review & curation 5, Governance 4, Reports 1, Platform 4, Admin 11 (45 entries with Sandbox, 44 without); every current entry appears once, none is lost, and every label and route path is unchanged (`Admin: ` prefix kept).
- [ ] Given the signed-in user holds no role or permission for any entry of a group, When the nav renders, Then that group is not rendered at all (no empty header, no empty button); entry visibility is still decided only by `isNavItemVisible` and the API still answers 403 for a deep link to a hidden entry.
- [ ] Given a first visit with no stored choice, When the nav renders, Then Platform and Admin are closed, every other group is open, and the group that holds the current page is open whatever the stored choice.
- [ ] Given a closed group, When the user presses Enter or Space on its header button, Then it opens, `aria-expanded` changes from `false` to `true`, and the links appear; pressing again closes it and the links leave the DOM.
- [ ] Given the current page is in group G, When G was closed and the user navigates there by URL, a link elsewhere, or the browser Back button, Then G opens without a click; the header of G is `aria-disabled="true"` while it holds the current page and a click does nothing.
- [ ] Given the user opens or closes groups and reloads, When the app loads again in the same browser, Then those choices are restored; clearing site data restores the defaults; a stored value with an unknown group name or a wrong type is ignored without an error.
- [ ] Given keyboard use only, Then Tab reaches each header button and each visible link in order, ArrowDown, ArrowUp, Home and End move through the visible headers and links (the existing behaviour, extended to headers), focus is never lost when a group closes (focus stays on its header), and the focus ring is visible in both UI styles.
- [ ] Given a screen reader, Then each header is a `button` with its group name and `aria-expanded`, `aria-controls` pointing at the list it opens (set only while open), the list sits inside a `role="group"` named by the header, the current link keeps `aria-current="page"`, the `Primary` navigation landmark stays unique, and the group headers add no entry to the page heading outline.
- [ ] Given each UI style (`ops-console`, `enterprise-fluent`) and the narrow overlay (under 720 px), Then headers, chevron, open and closed states render without overflow, touch targets are at least 24 by 24 px (WCAG 2.2 SC 2.5.8), contrast passes the repo's axe suite, and choosing a link in the overlay still closes the drawer.
- [ ] Adding a page later is one import line and one spread line in `workspaceNav.ts`, inside the array of the group it belongs to; no edit to `Shell.tsx`; a test fails if an entry is placed under an unknown group.
- [ ] The nav writes to `localStorage` only when the user toggles a group (the shell e2e test asserts that the domain key is the only stored key after a domain change).
- PRP exit: touched frontend suites (unit, component, e2e on the mock API, a11y) and lint, typecheck, format pass; visual baselines regenerated in Docker and committed; `validate_planning.py` passes; PR open with CI green; the proposed group table is confirmed or corrected by the owner and the final table is in the completion note.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Group list and mapping | Keep six and only add Admin; reviewed nine groups | ASSUMPTION: nine groups per the table below. Owner to confirm the names and the placement of the entries marked "moved" |
| 2 | Where the group is assigned | In each feature's `routes.tsx` (the `NavItem.group` field); in `workspaceNav.ts` (today's pattern) | In `workspaceNav.ts`, as today (`inGroup`, `workspaceNav.ts:36-38`). It is a Tier-2 additive file (`PRPs/reference/parallel-build-reference.md:66`), so later PRPs add one line there without a conflict. The feature `routes.tsx` files are not edited and `NavItem.group` stays as it is |
| 3 | Collapsible control | Fluent `NavCategory` (controlled `openCategories`); a plain disclosure button; an Accordion | Try `NavCategory`/`NavCategoryItem` first, time-boxed in item 2. Accept it only if the axe suite shows no `aria-hidden-focus` (the Tabster problem at `Shell.tsx:270-275`), the arrow-key handler still works and links stay real `<a>` elements. Otherwise use the WAI-ARIA disclosure pattern: a Fluent `Button` or `NavSectionHeader`-styled `<button>` with `aria-expanded` and `aria-controls`. Either way the visible behaviour and the acceptance criteria are identical; the completion note records which one shipped |
| 4 | State store | Component state; a new zustand `persist` store; `sessionStorage` | A small zustand `persist` store `useNavGroupStore`, key `ns.nav-groups`, in `frontend/src/app/navGroupStore.ts` next to the shell, copying the sandbox store (`features/sandbox/store.ts:1-33`). It holds only the user's explicit choices `{ [group]: boolean }`, never the derived "current page" opening, and `partialize` keeps that only. Per browser, not per account: it holds no identifier |
| 5 | Closing the group that holds the current page | Allow, then reopen on next navigation; refuse | ASSUMPTION: refuse (header stays focusable with `aria-disabled="true"`, no state change). It satisfies "always open" without a header that appears to do nothing for no reason, and the name of the group stays readable. Owner may prefer allow |
| 6 | Closed group content | Hidden with CSS but in the DOM; removed from the DOM | Removed from the DOM, so closed links are not focusable and the existing `a[href]` arrow-key query needs no filter; `aria-controls` is set only while open |
| 7 | Default open state | All open; all closed; all open except settings groups | ASSUMPTION: all open except Platform and Admin, which are configuration areas most users rarely need. This is a constant (`DEFAULT_CLOSED_GROUPS`) in `navigation.ts` |
| 8 | Room for later waves | Add groups as waves land; fix the nine now | Nine groups now; later pages go under the placement rules below. A wave that truly needs a tenth group adds its name to `NAV_GROUPS` through a `[serial-after: PRP-140]` item, because `navigation.ts` and `Shell.tsx` are this PRP's Tier-1 files in W18b |
| 9 | Narrow layout | Separate state; shared state | Shared. The overlay (`type="overlay"`, `Shell.tsx:229`) renders the same `ShellNav`; no icon rail exists, none is added |
| 10 | Mock-up frame | Match the new groups; leave out | Leave out, explicitly: `MockupFrame.tsx` and `fixtures.ts` are static design samples with their own six sample groups (not the product list) and are owned by the demo mock-ups; this PRP does not edit them, and `mockups.test.tsx` must still pass. A follow-up issue may align the sample names |
| 11 | Per-entry `NavItem.group` for admin entries | Add `Admin: ` prefix removal | Keep labels exactly as they are, including the `Admin: ` prefix. Renaming labels breaks tests, links and docs; dropping the prefix is a follow-up the owner can ask for once the Admin group exists |

### Proposed mapping (ASSUMPTION: owner to confirm)
Counts are with every entry visible. "Moved" marks an entry whose group changes.

| Entry label | Today | New group |
|---|---|---|
| Home | Overview | Overview |
| Viewer, Analyst, Steward, Admin, Auditor (workspaces; each shown only to its role) | Overview | Overview |
| Sandbox (only while sandbox mode is on) | Overview | Overview |
| Cost dashboard, Latency dashboard, Coverage dashboard | Cost & usage | Cost & usage |
| Reconciliation, Forecast, Federation | Cost & usage | Cost & usage |
| Map, Map table, Trace replay, Catalog | Agents | Agents |
| Quality, Recommendations, Evaluation results | Quality | Quality |
| Review | Governance | Review & curation (moved) |
| Actions | Governance | Review & curation (moved) |
| Relationship review | Governance | Review & curation (moved) |
| Recertifications | Governance | Review & curation (moved) |
| Stale agents | Governance | Review & curation (moved) |
| Publication | Governance | Governance |
| Gateways | Governance | Governance |
| Audit log | Governance | Governance |
| Compliance evidence | Governance | Governance |
| Reports | Reports | Reports |
| Deployment | Governance | Platform (moved) |
| Capabilities | Governance | Platform (moved) |
| Execution control | Governance | Platform (moved) |
| MCP servers | Governance | Platform (moved) |
| Admin: Identity, Domains, System, Audit search, Producers, Connectors, Gateways, Catalog import, Pricing, Features, Review policy (eleven, `areas.ts`) | Governance | Admin (moved) |

Totals: Overview 7, Cost & usage 6, Agents 4, Quality 3, Review & curation 5, Governance 4, Reports 1, Platform 4, Admin 11 = 45.

Placement rules for later waves (so adding a page needs no regrouping): finding and exploring agents, tools, services and the map go to Agents; spend, budgets and forecasts to Cost & usage; evaluations, recommendations and quality to Quality; work a person must decide (approvals, queues, exceptions) to Review & curation; policies, violations, interaction records, compliance and audit evidence to Governance; scheduled or generated documents to Reports; deployment, capabilities, execution control and tool servers to Platform; settings that configure the product itself (identity, domains, connectors, sources, pricing, features) to Admin. The plan's later titles fit: the policy, violations and exceptions UI (PRP-106) and the interaction explorer (PRP-104) under Governance, "Find an agent" (PRP-75) and the catalog registration pages (PRP-76) under Agents (`PRPs/EXECUTION-PLAN.md:107,109,117-118`).

## Context manifest

### Files to read first
- `frontend/src/app/navigation.ts:1-80` - `NAV_GROUPS`, `NavItem`, `isNavItemVisible`, `groupNavItems`, `selectedNavTo`.
- `frontend/src/app/workspaceNav.ts:1-102` - the whole grouping table and the sandbox hook; its header comment on light imports.
- `frontend/src/app/Shell.tsx:46-48,150-168,201-296,340-370` - constants, `useCompact`, `ShellNavLink`, `ShellNav`, `useNavArrowKeys`, and where visible items and sections are computed.
- `frontend/src/features/sandbox/store.ts` and `frontend/src/features/sandbox/sandbox.test.tsx:53` - persisted preference pattern and its test.
- `frontend/src/design-system/theme-store.ts:9,51-68` - second persistence example (explicit read and write guarded for bad data).
- `frontend/src/app/shell.test.tsx:54-90,193-245`, `frontend/src/app/nav-keys.test.tsx`, `frontend/src/app/test-support.tsx` - the tests this PRP updates and the harness (`renderShell`, `renderRealNav`).
- `frontend/tests/e2e/shell.spec.ts:19-75`, `frontend/tests/e2e/a11y/aria-tree.a11y.spec.ts:41-75`, `frontend/tests/e2e/a11y/keyboard-flows.a11y.spec.ts:81-110` - the e2e specs that walk the nav (named groups, link lists, aria snapshot, Tab, Enter, `localStorage` having one key at `shell.spec.ts:68`).
- `frontend/tests/e2e/a11y/axe-support.ts:33` (`STYLES`), `frontend/tests/e2e/a11y/themes.a11y.spec.ts`, `frontend/tests/e2e/visual/visual.spec.ts` and `layout.spec.ts`, `frontend/scripts/update-visual-baselines.mjs`.
- `PRPs/reference/parallel-build-reference.md:20-92` - tiers and the visual baseline command.

### Interfaces consumed
- Shipped: `NavItem`, `isNavItemVisible`, `groupNavItems`, `selectedNavTo`, `useAppNavItems`, `useSelectedDomain`, `useUiStyle`, the `Shell` props (`staticItems`, `useNavItems`).
- Not changed: every `features/*/routes.tsx` `*NavItems()` function, `NsRole`, permissions, the API.
- PRP-138 (same wave, merges first) edits pages under `frontend/src/features/admin/`. This PRP does not read or edit them; if PRP-138 adds an admin area to `ADMIN_AREAS`, it shows up under Admin automatically because `adminCoreNavItems()` maps the whole list (`admin/routes.tsx:33`). The count 11 in tests must be derived from `ADMIN_AREAS.length`, not typed in, so a merge of PRP-138 does not break them.
- PRP-139 (same wave, merges last) edits pages and infra; no shared file.

### Interfaces provided
- `navigation.ts`: `NAV_GROUPS` becomes the nine names in display order; `DEFAULT_CLOSED_GROUPS: readonly NavGroup[]` (`["Platform", "Admin"]`); `isGroupOpen(group, { stored, currentGroup }): boolean` (pure: current-page group is open, else the stored choice, else the default); `groupOfPath(sections, selectedTo)` or equivalent returning the group of the selected entry.
- `app/navGroupStore.ts` (new): `useNavGroupStore` (`choices`, `setOpen(group, open)`), `NAV_GROUP_STORAGE_KEY = "ns.nav-groups"`; unknown keys and non-boolean values dropped on read.
- `Shell.tsx`: header button per group, `data-nav-group` attribute on it, the arrow-key handler selector extended to `a[href], button[data-nav-group]`.
- `workspaceNav.ts`: the new group assignment (one array per group).
- Consumers: every later PRP that adds a nav entry (one-line addition in `workspaceNav.ts`).

### Patterns to match
- Persisted UI preference: `features/sandbox/store.ts:1-33` (zustand `persist`, `partialize`), plus the bad-data guard in `design-system/theme-store.ts:51-68`.
- Grouping and visibility as pure functions with tests in `shell.test.tsx:193-245` ("navigation model").
- Per-style classes: `Shell.tsx:136-142,226-227,255-257` (`itemOps` / `itemEnterprise`, `sectionOps`).
- Native-element keyboard first (button for a toggle), as `CopilotDock.tsx:169` uses `aria-expanded`.
- Playwright style loop: `tests/e2e/visual/layout.spec.ts` (`STYLES`, `seedPreferences`, `openSample`).

### Gotchas
- The shell and nav import only light route modules (`paths.ts`, `routes.tsx`), never a feature `index.ts`; those pull in the WebGL map and the chart sandbox and crash jsdom (`workspaceNav.ts:2-3`). The new store and tests import nothing from a feature `index.ts`.
- Fluent dialog and focus-trap queries flake because Tabster sets `aria-hidden` on the rest of the page; use `hidden: true` in Testing Library queries wherever a dialog or the copilot dock is open, and keep nav tests free of open dialogs. Do not put Tabster `Mover` or `NavDrawerBody` back on the nav (axe `aria-hidden-focus`, `Shell.tsx:270-275`).
- Playwright ports are shared across worktrees (`reuseExistingServer`): run with unique `NS_E2E_APP_PORT` and `NS_MOCK_API_PORT` (`frontend/playwright.config.ts:3-4`) or a run attaches to another worktree's server.
- `tests/e2e/shell.spec.ts:68` asserts that exactly one `localStorage` key exists after a domain change. The nav store must write only on a user toggle (and `persist` must not write initial state), or that assertion is updated in the same PR with a reason.
- Existing tests name `role="group"` regions by group name (`shell.test.tsx:64-85`, `shell.spec.ts:31`, `aria-tree.a11y.spec.ts:47-60`). Keep the `role="group"` wrapper with `aria-labelledby` so those queries stay valid; the tests that list six groups or per-group links must be rewritten for the nine.
- A closed group has no links in the DOM, so e2e specs that expect a link in Platform or Admin must open the group first (or sit on that page, which opens it). Use a helper `openGroup(nav, name)`.
- Visual baselines are generated in Docker only (they are Linux); never commit locally generated ones. The 82 images under `frontend/tests/e2e/visual/__screenshots__/` include the nav, so most change.
- The page title `h1` and the group headers: headers are buttons, not headings (`shell.test.tsx:87-91` asserts the only heading is the product name).
- `adminSourcesNavItems()` exists in `admin/sources/routes.tsx:36` but `workspaceNav.ts` does not call it (the eleven areas already include producers, connectors and the rest); do not add it.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - frontend/src/app/navigation.ts
  - frontend/src/app/navGroupStore.ts
  - frontend/src/app/navGroups.test.ts
  - frontend/src/app/nav-groups.test.tsx
  - frontend/src/app/nav-keys.test.tsx
  - frontend/src/app/shell.test.tsx
  - frontend/src/app/sandbox-shell.test.tsx
  - frontend/tests/e2e/shell.spec.ts
  - frontend/tests/e2e/a11y/aria-tree.a11y.spec.ts
  - frontend/tests/e2e/a11y/keyboard-flows.a11y.spec.ts
  - frontend/tests/e2e/visual/__screenshots__/**
tier1:
  - frontend/src/app/Shell.tsx
tier2_appends:
  - frontend/src/app/workspaceNav.ts
  - frontend/tests/e2e/a11y/route-samples.ts
must_not_touch:
  - frontend/src/features/**
  - frontend/src/app/demo/**
  - frontend/src/app/Providers.tsx
  - frontend/src/app/App.tsx
  - frontend/src/app/domain.tsx
  - frontend/tests/mock-api/server.ts
  - services/**
  - packages/**
```
`frontend/src/app/Shell.tsx` is a Tier-1 file (`parallel-build-reference.md:47`); the plan names no owner for it in W18b, so this PRP is its single owner in the wave and PRP-138 and PRP-139 must not edit it. `workspaceNav.ts` is a Tier-2 additive registry (`parallel-build-reference.md:66`), but this PRP changes existing lines in it (it regroups); that is allowed here only because the owner asked for the regrouping and the merge order is 138, 140, 139: PRP-138 merges first, then this PRP rebases onto it and takes any new line PRP-138 added, then PRP-139 rebases on this one. The edit to `workspaceNav.ts` is item 1 and only moves existing spread lines between group arrays; it adds, renames and removes no entry.

## Implementation blueprint

Parallelization: item 1 first; item 2 needs 1; item 3 needs 2. No `[P]` item: all three touch the shell files in sequence.

### Item 1 - Groups, mapping and persisted state (pure code)
- Deliverable: `NAV_GROUPS` set to the nine names in order; `DEFAULT_CLOSED_GROUPS`, `isGroupOpen` and the group-of-selection helper in `navigation.ts`; `buildAppNavItems` regrouped per the table (one `inGroup` call per group; the order of existing spreads inside a group unchanged); `navGroupStore.ts` with the guarded read; unit tests.
- Owned files: `frontend/src/app/navigation.ts`, `frontend/src/app/navGroupStore.ts`, `frontend/src/app/navGroups.test.ts`, `frontend/src/app/workspaceNav.ts` (regroup only).
- Must NOT touch: `Shell.tsx`, any `features/**` file.
- Depends on: nothing.
- Acceptance criteria: the mapping, counts and order criteria; every entry from the old list appears once (a test builds the old flat list of `(to, label)` pairs from a literal and compares); an entry whose group is not in `NAV_GROUPS` fails a test; `isGroupOpen` covers the current-page rule, stored choice, default and bad stored values; the store ignores unknown group names and non-boolean values, writes nothing until `setOpen` is called, and persists across a simulated reload.
- Tests: `frontend/src/app/navGroups.test.ts` (new, pure: grouping, order, empty-group drop, `isGroupOpen`, store read and write, counts derived from `ADMIN_AREAS.length`); the existing "navigation model" block in `shell.test.tsx` stays green.
- Pattern references: `features/sandbox/store.ts:1-33`, `design-system/theme-store.ts:51-68`, `shell.test.tsx:193-245`.

### Item 2 - Collapsible sections in the shell
- Deliverable: `ShellNav` renders, for each section with a group, a `role="group"` wrapper labelled by a header button (chevron, group name, `aria-expanded`, `aria-controls` while open, `data-nav-group`), the links only while open; the header of the current-page group is `aria-disabled="true"`; per-style classes for both UI styles; the same component inside the overlay drawer; arrow-key handler extended to headers; `Shell` passes the stored choices and the selected entry's group. Time-boxed first try of `NavCategory` per clarification 3, with the disclosure-button fallback.
- Owned files: `frontend/src/app/Shell.tsx`, `frontend/src/app/nav-groups.test.tsx`, `frontend/src/app/nav-keys.test.tsx`, `frontend/src/app/shell.test.tsx`, `frontend/src/app/sandbox-shell.test.tsx`.
- Must NOT touch: `features/**`, `demo/**`, `Providers.tsx`, `App.tsx`.
- Depends on: item 1.
- Acceptance criteria: all keyboard, aria, style and overlay criteria above; no new `aria-hidden` focus sentinel; no change to which links are visible for a role or permission; the unit test that lists six groups becomes a nine-group assertion built from `NAV_GROUPS`.
- Tests: `nav-groups.test.tsx` (new component tests: Enter and Space toggle, `aria-expanded`, `aria-controls` only while open, `role="group"` named by the header, current-page group forced open and `aria-disabled`, navigation by `MemoryRouter` opens the group, persisted choice restored, empty group not rendered, focus stays on the header after closing, no heading added, both UI styles via `useThemeStore.getState().setStyle(...)`, the narrow case by a `matchMedia` stub and the link click closing the drawer); `nav-keys.test.tsx` extended for headers; `shell.test.tsx` lines 54-91 rewritten for the nine groups; `sandbox-shell.test.tsx` checks Sandbox sits under Overview. Use `hidden: true` in any query that runs with a dialog or the dock open.
- Pattern references: `Shell.tsx:201-296`, `nav-keys.test.tsx:1-80`, `test-support.tsx` (`renderShell`, `stubResizeObserver`).

### Item 3 - E2E, a11y and visual baselines
- Deliverable: `shell.spec.ts` navigation test lists the nine groups and opens Platform and Admin before asserting their links; the "one localStorage key" assertion kept (or reworded only if item 2 had to write on load); a new case: collapse a group, reload, it stays collapsed, and the group of the current page cannot be collapsed; `aria-tree.a11y.spec.ts` named-groups, aria snapshot and a closed-group snapshot (`button "Admin" [expanded=false]`); `keyboard-flows.a11y.spec.ts` Tab, Enter on a header, Arrow keys across headers; both UI styles through `STYLES`; baselines regenerated in Docker.
- Owned files: `frontend/tests/e2e/shell.spec.ts`, `frontend/tests/e2e/a11y/aria-tree.a11y.spec.ts`, `frontend/tests/e2e/a11y/keyboard-flows.a11y.spec.ts`, `frontend/tests/e2e/visual/__screenshots__/**`.
- Must NOT touch: `tests/mock-api/server.ts`, any feature spec outside the three above unless it breaks for a closed group (then one `openGroup` call, listed in the completion note).
- Depends on: item 2.
- Acceptance criteria: the e2e and a11y projects pass on the mock API with unique ports; `routes.a11y.spec.ts` and `themes.a11y.spec.ts` show no new axe violation in either style; feature specs that click a nav link in Platform or Admin still pass; `pnpm --filter @neurosphere/frontend visual:check` reports no drift after the regenerate.
- Tests: the three spec files plus a grep for other specs that name nav links (`getByRole("navigation", { name: "Primary" })` in `tests/e2e/actions`, `dashboards`, `quality`, `recommendations`); regenerate baselines with `pnpm --filter @neurosphere/frontend visual:update` (needs Docker; run on the operator's machine or a Linux runner, not by hand-editing images).
- Pattern references: `tests/e2e/shell.spec.ts:28-75`, `tests/e2e/a11y/axe-support.ts:33`, `tests/e2e/visual/layout.spec.ts`.

## Validation gates
```bash
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend format
pnpm --filter @neurosphere/frontend test -- src/app
pnpm --filter @neurosphere/frontend test
NS_E2E_APP_PORT=4273 NS_MOCK_API_PORT=4210 pnpm --filter @neurosphere/frontend test:e2e
pnpm --filter @neurosphere/frontend visual:check
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Port numbers are examples: pick values nobody else's worktree uses. Baseline regeneration (Docker required, local emulators not needed): `pnpm --filter @neurosphere/frontend visual:update`, then commit the changed images; do not run it on Windows without Docker.

## Migration and rollback
No data or API change. The only stored value is `ns.nav-groups` in `localStorage`, an object of group names to booleans; an old browser has none and gets the defaults; a later rollback leaves an unused key, harmless. Rollback is a revert of the PR (the regrouped `workspaceNav.ts`, the shell, the store and the regenerated baselines come back together). Because baselines change in the same PR, revert them in the same commit.

## Live and open gates
None run: this is a front-end change tested on the mock API. A look at the hosted app, signed in as an Admin and as a Viewer, to confirm the groups, the folding and the remembered state, happens at the next hosted build and is recorded OPEN until evidenced. The screen reader pass (NVDA or Narrator on the nav) is a manual check that automated axe cannot replace; it is recorded OPEN until a person has done it.

## NOT building
New pages, routes, permissions or labels; an icon rail or a collapsible whole sidebar; nav search or favourites; drag to reorder groups; per-account sync of the open state; edits to the mock-up frame or the demo mock-ups (clarification 10); renaming the `Admin: ` entries; a tenth group; changes to the identity admin pages (PRP-138) or to feature page empty states (PRP-139).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1, 3, 5 and 7 are ASSUMPTIONS for owner confirmation before item 1 starts)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |

## Completion note (filled at ship)
- Date, PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
