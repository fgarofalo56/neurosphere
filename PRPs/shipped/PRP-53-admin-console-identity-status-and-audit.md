---
name: PRP-53-admin-console-identity-status-and-audit
status: shipped
shipped: 2026-11-16
pr: 309
priority: P0
order: 40
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-06, NS-08, NS-10
depends_on: [PRP-39-identity-admin-api-and-revocation, PRP-40-audit-search-export-and-siem-sink, PRP-44-platform-configuration, PRP-45-system-status-first-run-and-feature-settings]
wave: W17
branch: prp-53-admin-console-core
allow_parallel: true
issues: [246]
---

# PRP-53: Admin console, part 1: identity, domains, system status and audit search

## Goal
Replace the `/workspaces/admin` placeholder with a real admin console for the first half of the operator control plane: users, roles, domain scopes, resource grants with expiry and revocation (PRP-39 API); the domain registry (PRP-44 API); one system-status screen with the first-run checklist (PRP-45 API); and audit search, denial review, SIEM sink status and export (PRP-40 API). It is for the deployment administrator and the security auditor, who today need `sbx_grant_operator.py`, JSON from `/readyz` and a log file (validation doc, "operator-setup finding"). It is frontend only (React 19, Fluent UI v9, mock-API twins, vitest, Playwright, axe, Docker-only visual baselines) and runs in W17 because the four backends it reads ship in W13-W16. Every control is a usability aid: the API decides access on every request, and a 403 renders a forbidden state, never a hidden failure.

Out of scope: producers, connectors, gateway registration, catalog import, price sheets, budgets, models and feature settings, review policy (PRP-57); any backend route, permission or contract change (PRP-37/PRP-65, 39, 40, 44, 45); editing stored feature settings (PRP-57, this PRP only shows source and `restart_required`); the existing chain browser at `/audit` and the kill switch at `/admin/execution-control` (unchanged); lifecycle holds (no UI is planned; PRP-23 ships the API only).

## Why
- `/workspaces/admin` answers `items=[]` and prints "Placeholder: this workspace is built out in later work" (`frontend/src/features/workspaces/WorkspacePage.tsx:70`; lane-d step 1 last row).
- No frontend code reads `/readyz` or any status route (lane-d step 1, "Feature enablement" row); the operator-setup table in `docs/validation/PRODUCT-VALIDATION-2026-11-06.md:25-40` lists role assignment, audit search and feature enablement as "cannot do in the product".
- The audit page is read-only: `frontend/src/features/audit/AuditPage.tsx:253` says "Nothing is enriched, joined or exported here"; PRP-40 adds search, export and the denials chain but no screen.
- Unit F1 of lane-d section 4 scopes this page set and names the hot registries (`appRoutes.ts`, `route-manifest.json`, `workspaceNav.ts`, `tests/mock-api/features/index.ts`, `tests/e2e/a11y/route-samples.ts`, `tests/real-stack/routes.spec.ts`).
- `route-manifest.test.ts` and `routes.a11y.spec.ts` fail a route that has no manifest entry or axe sample (`frontend/tests/e2e/a11y/route-samples.ts:15-17`), so the registries must move in the same PR as the pages.

## Acceptance criteria
- [x] Given an admin, When `/workspaces/admin` opens, Then it still probes `/api/v1/workspaces/admin` (a non-admin sees the existing forbidden state) and shows the console landing: links to the four areas, the first-run checklist summary and the `restart_required` count; the "Placeholder" text is gone and `workspaces.test.tsx` asserts that.
- [x] Identity: `/admin/identity` lists principals (bounded page, cursor); `/admin/identity/principal?principal_id=` shows memberships, role assignments with expiry, grants and revocation state. Assign and remove a role, add and remove a domain membership, put and remove a grant (expiry and reason required) each open `ChangeConfirmDialog` with exact target, ETag/version and diff, send the PRP-39 route, and show the result or the typed error (403, 409 `stale_version`, 422).
- [x] Revoke and lift: the revoke action shows mode (`issued_before` or `until_lifted`) and a required reason; a revoked principal shows a persistent banner with a lift action; both call the PRP-39 revocation route.
- [x] Domains: `/admin/domains` lists the PRP-44 domain registry (display name, classification, residency region, status, control-domain flag) and creates or retires a domain through the confirm dialog; a reserved name (PRP-48 `is_reserved_chain_name`) shows the API's 422 text unchanged.
- [x] System: `/admin/system` shows every composition component with state, required flag and reason code, the first-run checklist (the shipped PRP-45 statuses `complete | missing | error | disabled | not_applicable`, reason, docs anchor) and the six stored-setting keys with source (`stored | env | default`) and `restart_required`; it never renders a configuration value, host or secret (a test feeds a body with such a field and asserts it is not in the DOM).
- [x] Audit: `/admin/audit` filters by domain, operation, kind, outcome, actor pseudonym, correlation id and a required, capped time range; pages with the server cursor; a denials tab (customer-wide) and a SIEM status panel (last success, consecutive failures, last reason code); export offers NDJSON and CSV, is disabled with an explanation when the API answers 403, and shows the row cap and the audit notice the API returns.
- [x] Empty, loading, error and forbidden states exist for every list; "unknown" is shown as unknown, never 0; no pseudonym is joined to a name.
- [x] Mock handlers `frontend/tests/mock-api/features/admin-core.ts` serve every route above (including 403, 409 and 422 cases keyed by fixture ids) and are listed in the registry test.
- [x] Vitest covers each page's states; Playwright `frontend/tests/e2e/admin-core/**` runs the happy path and a forbidden path per area on the mock API; the a11y suite has a sample for every new manifest pattern with zero serious or critical axe violations in light, dark and high-contrast; Docker-only visual baselines exist for the new pages.
- [x] `pnpm --filter @neurosphere/frontend lint`, `typecheck`, `test`, `format` and `test:e2e` pass; `python scripts/validate_planning.py` passes.
- PRP exit: an operator signed in as a deployment administrator can assign a role, revoke a principal, create a domain, read system status and search and export audit records without a script or raw API call, on the mock API; the real-stack run is OPEN until PRP-38's job covers these pages.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Where the audit search lives | Extend `/audit`; new admin page | New `/admin/audit` (ASSIGNMENTS owns `features/admin/audit`); the chain browser and verify at `/audit` stay untouched |
| 2 | How the placeholder is replaced | New route; swap the admin persona's body | Keep `/workspaces/admin` and its probe (PRP-48 gates it); `WorkspacePage` renders the console landing for the Admin persona. Edits `features/workspaces/WorkspacePage.tsx` and its test, which ASSIGNMENTS does not list (reported) |
| 3 | Detail routing | Path param; query param | Query param (`/admin/identity/principal?principal_id=`), the repo convention (`/gateways/detail`) |
| 4 | Domains page without PRP-44 routes at hand | Wait; consume by purpose | Consume by purpose; the first item reads the shipped PRP-44 completion note and `services/api/openapi.json` for exact paths before coding |
| 5 | Editing stored settings | Here; PRP-57 | PRP-57. Here read-only, with a link per key |
| 6 | Visual baselines | Add to `visual.spec.ts` `PAGES`; new spec | ASSUMPTION: append rows to `PAGES` in `frontend/tests/e2e/visual/visual.spec.ts` (one line each, a Tier-2-style append; the file is not in the reference list) so no Playwright config changes |
| 7 | Nav visibility | Hide for non-admin; show all | Show for `Admin` and `Auditor` per page (`roles` hint), cosmetic only |

## Context manifest

### Files to read first
- `frontend/src/features/gateways/{routes.tsx,paths.ts,hooks.ts,GatewaysPage.tsx}` - a feature folder with light route module, path constants, query hooks and a list page on the PageTemplate.
- `frontend/src/features/mcp-admin/{hooks.ts,McpServersPage.tsx}` - an admin list plus mutation hooks (`createMutationHook`) and error rendering.
- `frontend/src/features/governed-change/ChangeConfirmDialog.tsx` - the confirm dialog (target, version, diff, reason, expiry) every write must use.
- `frontend/src/features/workspaces/{WorkspacePage.tsx,personas.ts,ForbiddenState.tsx}` - the placeholder to replace and the forbidden state to reuse.
- `frontend/src/features/audit/{AuditPage.tsx,data.ts,types.ts}` - cursor paging with `useInfiniteQuery`, record drawer.
- `frontend/src/app/{appRoutes.ts,workspaceNav.ts,route-manifest.json,route-manifest.test.ts}` - registries that must move together.
- `frontend/tests/mock-api/features/{index.ts,audit.ts,context.ts,registry.test.ts}` - the mock-handler shape and dispatch.
- `frontend/tests/e2e/a11y/route-samples.ts`, `frontend/tests/e2e/visual/visual.spec.ts`, `frontend/tests/e2e/admin/evaluations-and-control.spec.ts` - samples, baselines, an admin e2e.
- `frontend/src/api/errors.ts` - typed errors (`ForbiddenError`, `StaleVersionError`, `InvalidSchemaError`).
- `services/api/openapi.json` (after PRP-39, 40, 44, 45 merged) and each provider PRP's completion note - the exact routes, query names and models.

### Interfaces consumed
- PRP-39 (`/api/v1/admin/identity`): `GET /principals`, `GET /principals/{principal_id}`, `PUT|DELETE /principals/{principal_id}/role-assignments/{assignment_id}`, `.../domain-memberships/{domain_id}`, `.../grants/{grant_id}`, `POST|GET|DELETE .../revocation`; models `PrincipalAccessSummary`, `RoleAssignmentChange`, `DomainMembershipChange`, `ResourceGrantChange`, `RevocationRequest`, `RevocationStatus` from PRP-37/PRP-65 (`neurosphere_contracts.admin.v1`, TS under `packages/contracts/ts/src/admin/v1/`).
- PRP-40: `GET /api/v1/audit/search`, `/export` (`format=ndjson|csv`, needs `audit.export`), `/denials`, `/siem/status`; models `AuditSearchPage`, `AuditSiemStatus`. Query names are those in the shipped PRP-40 (filters: domain, operation, kind, outcome, actor pseudonym, correlation id, time range, cursor).
- PRP-44 (platform configuration): domain registry create, list, retire routes under `/api/v1/admin/platform`; model `DomainDefinition` {`domain_id`, `display_name`, `classification`, `residency_region`, `status`, `is_control_domain`}. Exact paths UNVERIFIED until PRP-44 ships.
- PRP-45: `GET /api/v1/admin/system/status`, `/checklist`, `/settings`; item ids in `docs/runbooks/system-settings.md`.
- PRP-48: `require_deployment_admin` (403 `deployment_scope_required`) behind the system routes; `/api/v1/workspaces/admin` probe.
- Existing UI: `ChangeConfirmDialog`, `PageTemplate`, `Panel`, `StatusPill`, `ErrorState`, `LoadingState` (`frontend/src/design-system`).

### Interfaces provided
- Routes (all added to `route-manifest.json`): `/admin/identity`, `/admin/identity/principal`, `/admin/domains`, `/admin/system`, `/admin/audit`.
- `frontend/src/features/admin/shared/` (`AdminTabs`, `useEtagMutation`, `adminPaths.ts`, `strings.ts`, and `areas.ts` exporting the `ADMIN_AREAS` array that `AdminTabs` and the console landing render) which PRP-57 imports; PRP-57 may only append entries to `areas.ts`.
- `frontend/tests/mock-api/features/admin-core.ts` exports fixture ids (`ADMIN_PRINCIPAL_ID`, `ADMIN_PRINCIPAL_FORBIDDEN`, ...) reused by PRP-57 specs.
- Light module `frontend/src/features/admin/routes.tsx` exporting `adminCoreRoutes` and `adminCoreNavItems()`.

### Patterns to match
- `frontend/src/features/gateways/routes.tsx:1-16` (routes plus `NavItem[]`); `frontend/src/features/execution-control/routes.tsx:8-15` (`permission` hint on the nav item).
- `frontend/src/features/mcp-admin/hooks.ts:25-50` (query and mutation hooks); `frontend/src/features/audit/data.ts:20-50` (cursor paging, server cursor only).
- `frontend/tests/mock-api/features/audit.ts:1-30` (synthetic ids, persona gate) and `frontend/tests/e2e/admin/evaluations-and-control.spec.ts:1-40` (an admin e2e).
- `frontend/src/app/appRoutes.ts:25-50` ("light route modules only, never a feature index").

### Gotchas
- Fluent dialog tests: query with `hidden: true` (Tabster sets `aria-hidden`).
- The admin shell is hidden for non-admins only cosmetically; test the 403 path by fixture, never by hiding.
- A new `/api/v1/admin/*` GET in the manifest calls list: `services/api/tests/runtime_routes/manifest_calls.py` and `tests/integration/real_stack/test_manifest_routes.py` need one line per new route (Tier 2); the real-stack run needs a seeded principal, so leave those rows tolerant of an empty list.
- Pseudonymous principal ids must not be turned into names; show the id and copy button only.
- Visual baselines are Linux-only: generate with `pnpm --filter @neurosphere/frontend visual:update` in Docker, never on Windows. Unique `NS_E2E_APP_PORT` and `NS_MOCK_API_PORT` per worktree.
- Pre-existing `WorkspacePage` test asserts the Viewer 403 probe: keep it passing.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - frontend/src/features/admin/identity/**
  - frontend/src/features/admin/domains/**
  - frontend/src/features/admin/system/**
  - frontend/src/features/admin/audit/**
  - frontend/src/features/admin/shared/**
  - frontend/src/features/admin/routes.tsx
  - frontend/src/features/workspaces/WorkspacePage.tsx
  - frontend/src/features/workspaces/workspaces.test.tsx
  - frontend/tests/mock-api/features/admin-core.ts
  - frontend/tests/e2e/admin-core/**
tier1: []
tier2_appends:
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/route-manifest.json
  - frontend/src/app/workspaceNav.ts
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - frontend/tests/real-stack/routes.spec.ts
  - frontend/tests/e2e/visual/visual.spec.ts
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
  - mkdocs.yml
must_not_touch:
  - services/api/neurosphere_api/**
  - packages/**
  - frontend/src/features/audit/**
  - frontend/src/features/execution-control/**
  - frontend/src/features/admin/sources/**
  - frontend/src/features/admin/pricing/**
  - frontend/tests/mock-api/server.ts
```

## Implementation blueprint

Parallelization map: item 1 first; item 2 (the single mock file) next; items 3-6 are independent pages in separate folders [P]; item 7 registers routes and owns e2e, a11y and visual; item 8 closes out.

### Item 1 - Shared foundation and console landing
- Deliverable: `admin/shared` (`adminPaths.ts` constants for the four API prefixes, `AdminTabs`, `useEtagMutation` wrapping `createMutationHook` with `If-Match`, typed-error banner, `strings.ts`), `admin/routes.tsx` skeleton, `AdminConsoleHome` (area links, checklist summary, restart count) and the `WorkspacePage` change for the Admin persona. Reads the shipped PRP-39, 40, 44, 45 completion notes and `openapi.json` and records exact paths in `adminPaths.ts` comments.
- Owned files: `frontend/src/features/admin/shared/**`, `frontend/src/features/admin/routes.tsx`, `frontend/src/features/workspaces/{WorkspacePage.tsx,workspaces.test.tsx}`.
- Must NOT touch: other admin folders, backend.
- Depends on: none.
- Acceptance criteria: landing renders with the probe 200 and 403; placeholder text gone; `useEtagMutation` sends `If-Match` and maps 409 to a stale-version message (unit test).
- Tests: `frontend/src/features/admin/shared/shared.test.tsx` (new), `frontend/src/features/workspaces/workspaces.test.tsx`.
- Pattern references: `workspaces/WorkspacePage.tsx:15-70`, `mcp-admin/hooks.ts`.

### Item 2 - Mock handlers
- Deliverable: `admin-core.ts` serving identity, domains, system and audit routes with synthetic data, ETags, a 403 persona, a 409 and a 422 fixture, a revoked principal, an empty list and a 31-row audit set with a cursor; exports fixture ids; `registry.test.ts` list line.
- Owned files: `frontend/tests/mock-api/features/admin-core.ts`, `frontend/tests/mock-api/features/index.ts` (append one import and one list entry).
- Must NOT touch: `server.ts`, other mock modules.
- Depends on: item 1 (paths).
- Acceptance criteria: handler answers each route once per method; unknown paths return false; pseudonyms and hashes are visibly synthetic.
- Tests: `frontend/tests/mock-api/features/registry.test.ts`, `frontend/tests/mock-api/features/admin-core.test.ts` (new).
- Pattern references: `tests/mock-api/features/audit.ts`.

### Item 3 - Identity pages  [P]
- Deliverable: `PrincipalsPage`, `PrincipalDetailPage`, role, membership and grant editors, revoke and lift flow, hooks and types.
- Owned files: `frontend/src/features/admin/identity/**`.
- Must NOT touch: other admin folders, `ChangeConfirmDialog`.
- Depends on: items 1, 2.
- Acceptance criteria: the identity criteria above; expiry required for grants; 409 shows reload guidance; an expired assignment is labelled expired.
- Tests: `frontend/src/features/admin/identity/identity.test.tsx` (new).
- Pattern references: `mcp-admin/McpServersPage.tsx`, `governed-change/ChangeConfirmDialog.tsx`.

### Item 4 - Domains page  [P]
- Deliverable: `DomainsPage` (list, create, retire) with the dialog and API error text passthrough.
- Owned files: `frontend/src/features/admin/domains/**`.
- Must NOT touch: other admin folders.
- Depends on: items 1, 2.
- Acceptance criteria: domains criterion above; control domain is badged and cannot be retired from the UI (the control is disabled with the API's reason on hover; the API still decides).
- Tests: `frontend/src/features/admin/domains/domains.test.tsx` (new).
- Pattern references: `gateways/GatewaysPage.tsx`.

### Item 5 - System status and checklist page  [P]
- Deliverable: `SystemPage` with component table, checklist, settings summary, empty and forbidden states.
- Owned files: `frontend/src/features/admin/system/**`.
- Must NOT touch: other admin folders.
- Depends on: items 1, 2.
- Acceptance criteria: system criterion above, including the no-value-in-DOM test.
- Tests: `frontend/src/features/admin/system/system.test.tsx` (new).
- Pattern references: `design-system` `HealthIndicator`, `StatusPill`.

### Item 6 - Audit search and export page  [P]
- Deliverable: `AdminAuditPage` (filters, results, denials tab, SIEM panel, export), hooks with server cursor.
- Owned files: `frontend/src/features/admin/audit/**`.
- Must NOT touch: `frontend/src/features/audit/**`.
- Depends on: items 1, 2.
- Acceptance criteria: audit criterion above; export link carries only filters and format, never a token in the URL (download through the API client with the bearer header).
- Tests: `frontend/src/features/admin/audit/admin-audit.test.tsx` (new).
- Pattern references: `audit/data.ts`, `audit/AuditPage.tsx`.

### Item 7 - Registration, e2e, a11y and visual
- Deliverable: Tier-2 lines (routes, manifest entries, nav items, route samples, real-stack route rows, `manifest_calls.py` and real-stack manifest rows), Playwright specs, visual `PAGES` rows and Docker-generated baselines.
- Owned files: `frontend/tests/e2e/admin-core/**` and the Tier-2 appends listed in Ownership.
- Must NOT touch: existing lines in the registries.
- Depends on: items 3-6.
- Acceptance criteria: `route-manifest.test.ts`, `routes.a11y.spec.ts`, `routes-keyboard.a11y.spec.ts` and the real-stack manifest test pass; e2e covers assign role, revoke, create domain, status view and audit export on the mock API.
- Tests: `frontend/tests/e2e/admin-core/identity.spec.ts`, `domains.spec.ts`, `system.spec.ts`, `audit.spec.ts` (new).
- Pattern references: `tests/e2e/admin/evaluations-and-control.spec.ts`, `tests/e2e/a11y/route-samples.ts:130-145`.

### Item 8 - Integration and close-out
- Deliverable: rebase, `python scripts/prp_status.py --write`, `PRPs/INDEX.md` regeneration, mkdocs nav line if a doc page is added, CHANGELOG entry, completion note with the operator product check (can an operator do this without a script?) and OPEN list.
- Owned files: this PRP file, `CHANGELOG.md`.
- Depends on: item 7.

## Validation gates
```bash
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend format
NS_E2E_APP_PORT=5271 NS_MOCK_API_PORT=5272 pnpm --filter @neurosphere/frontend test:e2e
uv run pytest -q services/api/tests/runtime_routes tests/docs
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Visual baselines: `pnpm --filter @neurosphere/frontend visual:update` in the pinned Docker image, then `visual:check`.

## Migration and rollback
No data or schema migration: the console only calls existing APIs. Roll back by reverting the PR; the routes and nav entries disappear together and `/workspaces/admin` returns to its prior body. A deployment where PRP-39, 40, 44 or 45 routes are absent shows the error state per page, not a crash.

## Live and open gates
No live gate. The real-stack Playwright walk of these pages is OPEN until PRP-38's job exists; run `frontend/playwright.real-stack.config.ts` headed against the composed stack only with an operator and report the result. Hosted verification is part of PRP-58 and PRP-64.

## NOT building
Producers, connectors, gateway registration, catalog import, pricing, budgets, feature-setting edits and review policy (PRP-57); any backend change; lifecycle hold UI; a client-side permission engine; role, domain or user names resolved from pseudonyms.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (row 6 is flagged ASSUMPTION; PRP-44 route paths are confirmed in item 1)

## Execution state

| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-53-admin-console-core | merged in PR 309 |
| 2 | merged | prp-53-admin-console-core | merged in PR 309 |
| 3 | merged | prp-53-admin-console-core | merged in PR 309 |
| 4 | merged | prp-53-admin-console-core | merged in PR 309 |
| 5 | merged | prp-53-admin-console-core | merged in PR 309 |
| 6 | merged | prp-53-admin-console-core | merged in PR 309 |
| 7 | merged | prp-53-admin-console-core | merged in PR 309 |
| 8 | merged | prp-53-admin-console-core | close-out: changelog fragment, completion note, Tier-3 regeneration |

## Completion note (filled at ship)
- Date, PR number, merge commit: 2026-11-16, PR 309, merge commit recorded by the squash merge.
- Deviations: `frontend/tests/e2e/demo-audit.spec.ts` and `frontend/tests/mock-api/features/registry.test.ts` are not in the Ownership block; both received small appends the new routes require. The spec listed checklist statuses as done|todo|blocked; the UI follows the shipped PRP-45 contract (complete|missing|error|disabled|not_applicable) and the acceptance wording is corrected. No `serial-after` items existed in this PRP.
- Descoped items: none.
- OPEN gates: the real-stack Playwright walk of the admin pages is OPEN (needs PRP-38's job and an operator run; `NS_LIVE_APPROVED` not set). The real-stack manifest rows in `services/api/tests/runtime_routes/manifest_calls.py` carry no `non_empty` requirement, so an empty list is tolerated by design, but this was not exercised against a composed stack. Audit denials and SIEM status are not in the manifest calls (they need control-domain audit.read). The 20 visual baselines were generated in Docker earlier in this PR and not regenerated at close-out.
- Env vars for the operator: none (no new NS_* variables).
- Follow-up issues filed: none filed by this close-out; PRP-57 owns producers, connectors, pricing and feature-setting edits.
- Operator product check (can an operator use this without editing files or calling raw APIs?): on the mock API yes (assign role, revoke, create domain, system status, audit search and export through the UI). Against a real stack it is unverified until the real-stack walk runs.
- Local evidence at close-out: frontend lint, typecheck and format clean; vitest 98 files / 1155 tests passed; Playwright admin-core and a11y suites 587 passed (one /mcp-admin keyboard sweep timeout under load passed on rerun); runtime_routes, tests/docs and openapi drift 131 passed.
