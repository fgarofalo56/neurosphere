---
name: prp-04-frontend-shell-design-system-auth
status: backlog
review: none
created: 2026-10-08
model: sonnet
phase: 0/1
ns: NS-08, NS-10
depends_on: PRP-01
wave: W2
absorbs: new
---

# PRP-04: Frontend shell, design system and Entra auth

## Goal

Ship the empty-but-real browser application every later UI PRP builds on: a Vite + React 19 + TypeScript 6 strict shell with routing and an error boundary, a Fluent UI v9 design system with light, dark and high-contrast themes, MSAL sign-in with cloud-specific authority (Commercial and Government selectable by config), a typed API client built on `packages/contracts/ts`, role-named workspace routes, and a test harness (Vitest, Testing Library, Playwright, axe) that runs in CI. It is for the frontend developers of PRP-14, 16, 17, 18, 19, 22 and 24, who need stable seams before features exist. It lands in wave W2 because it needs only the PRP-01 contracts, so it runs parallel to PRP-02 and PRP-03.

> NS-10: "React/TypeScript with Fluent-inspired default, agency theme tokens/logos, light/dark/high-contrast and role workspaces. WCAG 2.2 AA plus Section 508 testing; no implied Microsoft product affiliation or unapproved brand/badge usage. Theme is presentation, never permission enforcement."

> NS-08: "Entra ID with cloud-specific authorities/audiences, managed identities where supported and vault references elsewhere. Roles: Viewer, Analyst/Pro, Domain Steward/Owner, Admin, Security Auditor; custom resource-scoped permissions."

> NS-08: "Server-side ABAC/RBAC for APIs, queries, exports, search indexes, copilot, tools and push channels. Fail closed on authorization errors."

Hidden navigation is not authorization. The shell hides workspaces a user's claims do not suggest, for usability only; the API (PRP-06) is the only enforcement point, and PRP-04 proves this with an e2e test that a hidden route still receives an API 403.

## Acceptance criteria

- [ ] Item 1: `pnpm --filter frontend typecheck` (`tsc --noEmit`, strict) passes; `pnpm --filter frontend build` writes a bundle size report; an injected render error shows the error boundary, not a blank page.
- [ ] Item 2: Given a signed-in session, when the user switches light, dark and high-contrast, then the theme changes with no re-login and no network call; axe reports zero serious or critical contrast violations on the theme gallery route.
- [ ] Item 3: Given cloud config `government`, the MSAL authority host is `login.microsoftonline.us`; given `commercial`, `login.microsoftonline.com`. A request with no token redirects to login. Roles are displayed from claims and never used to grant access.
- [ ] Item 4: 401, 403, 429 and 409 responses map to typed errors (`unauthorized`, `forbidden`, `rate_limited`, `stale_version`) with unit tests; every request carries an `x-correlation-id`.
- [ ] Item 5: Five persona workspaces (Viewer, Analyst, Steward, Admin, Auditor) route and render placeholders; a Playwright test navigates directly to a hidden workspace URL and asserts the mock API returns 403 and the UI shows a forbidden state.
- [ ] Item 6: Playwright smoke passes headless in CI against the mock API; Vitest and axe run in `pnpm --filter frontend test`.
- [ ] PRP exit: `verify-gates.ps1 -Mode full` green; lint, typecheck and test pass with no suppressed failures; no workflow line contains a failure-suppressing shell fallback; `python scripts/validate_planning.py` shows no failure attributable to this file.

## Clarifications (decided)

| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| C1 | TypeScript major | 6.0.x; 7 | **6.0.x.** TS 7 is incompatible with typescript-eslint 8.71 (`<6.1`); ADR-0002 Frontend row "TypeScript". |
| C2 | Node runtime for build and CI | 22; 24 | **Node 24 LTS** (EOL 2028-04-30); ADR-0002 Runtimes row "Node.js". `.node-version` already pins it. |
| C3 | React version | 19.3; 18 | **React 19.3.** Fluent UI v9 (`@fluentui/react-components` 9.74) peers React `<20`; `@azure/msal-react` 5.7 peers React `^19.2.1`, so the floor is 19.2.1 (ADR-0002 rows "React", "@fluentui/react-components", "@azure/msal-browser / msal-react"). |
| C4 | Router | react-router 8; TanStack Router | **react-router 8.4** per ADR-0002 row "@tanstack/react-query / react-router / zustand". |
| C5 | Server-state library | TanStack Query 5; hand-rolled | **TanStack Query 5.104** wraps the typed client; Zustand 5.0 only for UI state (theme, nav). |
| C6 | Who adds npm dependencies | each lane; one integrator commit | **One serialized integrator commit** before lanes start adds anything missing from `frontend/package.json` and `pnpm-lock.yaml` (both PRP-00 files). Lanes never edit them. |
| C7 | Cloud selection at runtime | build-time env; runtime config.json | **Runtime `config.json` fetched at startup** (fields: cloud, tenantId, clientId, apiBaseUrl, apiScope), validated by a hand-written schema check; build-time `VITE_NS_*` only supplies local-dev defaults. One image serves both clouds. |
| C8 | Token storage | localStorage; sessionStorage; memory | **sessionStorage**; no tokens in logs or error reports. |
| C9 | Role source | ID-token `roles` claim; API call | **Claims for display only.** Authoritative scope comes from the API (PRP-06); the UI never derives permission from claims. |
| C10 | Mock API for tests | MSW; custom Node server | **MSW 2.x in Vitest, a small Node mock server for Playwright**, both under `frontend/tests/`. Needs the serialized dependency step (C6). |
| C11 | Branding | Microsoft logos and marks; neutral | **Neutral, "Fluent-inspired".** No Microsoft logo, badge or affiliation text. Logo slot is an empty region for PRP-24 theme packs. |
| C12 | Operator live gates | any live run | **None for this PRP.** No Azure calls; sign-in is exercised only with a mocked MSAL instance. Real tenant sign-in is recorded as an open item below. |
| C13 | Model and review | opus + review; sonnet + none | **sonnet, review none** (master table; decision D6). Low risk: no authorization logic lives here. |

## Context manifest

### Files that matter

- `PRP.md` sections 1-3 (binding preamble: delivery contract, stack, contracts first).
- `docs/PRD.md` NS-08, NS-10 (quoted above) and section 3 browser target (<=2k visible nodes, owned by PRP-18).
- `docs/ARCHITECTURE.md` diagram 1 (UI -> APIM -> API authorization) and section 6 (search and push enforce the same policy as REST).
- `docs/adr/0002-stack-pins.md` Frontend table: React 19.3, Vite 8.3 (Node >=22.12), TypeScript 6.0.x, Fluent UI 9.74, msal-browser 5.25 / msal-react 5.7, TanStack Query 5.104, react-router 8.4, zustand 5.0, vitest 5.0, Testing Library 16.3, Playwright 1.64, ESLint 10.12 (flat config only), typescript-eslint 8.71, prettier 3.9.
- `docs/RESEARCH-AND-GATES.md` (G09 theme/brand review completes in PRP-24).
- `docs/DECISIONS-LOG.md` D5 (stack pins), D6 (model policy).
- `.claude/hooks/config.ps1` (build and optional gates; PRP-00 made build required), `.env.example` (variable names only), `scripts/validate_planning.py`, `pyproject.toml` and `docker-compose.yml` (read only, not touched).
- Created by PRP-00: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/eslint.config.js`, `frontend/.prettierrc`, `tsconfig.base.json`, `pnpm-lock.yaml`.
- Created by PRP-01: `packages/contracts/ts/` generated types (error taxonomy, `IdentityScope`, telemetry shapes) from `packages/contracts/schemas/`.
- Consumed later: PRP-05 serves the OpenAPI the client mirrors; PRP-06 defines the real role claims; PRP-24 adds `frontend/src/design-system/themes/`.

### Patterns to match

No product code exists yet, so these are rules, not file references.

- TypeScript strict (`strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`); no `any`; no non-null assertion outside tests.
- UI built only from `@fluentui/react-components` v9 and its tokens; no hard-coded hex values outside the token layer.
- Feature code under `frontend/src/features/<name>/`; shared seams only through `app`, `design-system`, `auth`, `api` barrels (`index.ts`).
- API payload types import from `packages/contracts/ts`; never hand-write a payload type that a schema covers.
- Tests: Vitest + Testing Library beside the source (`*.test.tsx`), Playwright under `frontend/tests/e2e`, axe via `@axe-core/playwright` and `vitest-axe`.
- Python-side counterparts (read only): Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`, FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py`, error taxonomy exceptions from `neurosphere_core.errors`. The TS error classes mirror the contract names exactly. `pytest.mark.live` and `pytest.mark.integration` markers (root pyproject) are not used by this PRP.

### Conventions

- ruff (line 100, py312, S rules on) and pyright standard apply to Python only; this PRP writes none. ESLint 10 flat config and Prettier 3.9 apply to TS.
- Conventional commits (`feat(frontend): ...`); owned-file discipline (edit only declared paths); evidence under `docs/evidence/<gate>/` (none produced here).
- Live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1`; this PRP adds none.
- Forward slashes in every command. Python is `python`, not `python3`. Temp files go in `temp/`.

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

PRP-specific gotchas:

- TS 7 and Node 22 are tempting defaults; both are wrong here (C1, C2). Do not bypass the Dependabot cooldown to adopt them.
- `FluentProvider` must wrap the `MsalProvider` children so the login redirect screen is themed. High-contrast is a custom token set, not a legacy v8 theme.
- MSAL Government: authority host is `login.microsoftonline.us`; Graph and ARM audiences differ in Government. The API audience comes from `config.json` (`apiScope`), never hard-coded.
- MSAL `redirectUri` must match the registered SPA URI exactly; popup flows are blocked in some agency browsers, so redirect is the default.
- The UI never sends or reads `domain_id` or `customer_id` to scope calls (the server derives scope); no query-string or local-storage scoping.
- People are pseudonymized by default in the API; the UI displays what it receives and adds no de-pseudonymization path.
- `vite.config.ts` must not inline secrets via `define`; only non-secret `VITE_NS_*` defaults.
- The accessible map alternative (table view) is PRP-18; this PRP still keeps every interactive element keyboard reachable with visible focus.
- A route guard that redirects to login on a missing token is UX, not security; do not write tests claiming it protects data.

### External references

- Fluent UI React v9: https://react.fluentui.dev/ (peer range `<20`, observed 2026-10-08, ADR-0002).
- MSAL React: https://learn.microsoft.com/entra/msal/javascript/react/getting-started (msal-react 5.7 peers React `^19.2.1`, observed 2026-10-08).
- National cloud authorities: https://learn.microsoft.com/entra/identity-platform/authentication-national-cloud (Government login host `login.microsoftonline.us`).
- Vite env and modes: https://vite.dev/guide/env-and-mode (Vite 8.3, Node >=22.12, ADR-0002).
- Playwright accessibility testing: https://playwright.dev/docs/accessibility-testing (Playwright 1.64).
- Node release schedule: https://github.com/nodejs/Release (Node 24 LTS to 2028-04-30, observed 2026-10-08).
- WCAG 2.2: https://www.w3.org/TR/WCAG22/ (full audit is PRP-24; this PRP guards tokens only).

## Implementation blueprint

Shared must-not-touch for every item (the "shared list"): root `pyproject.toml`, `docker-compose.yml`, `docs/RESEARCH-AND-GATES.md`, `frontend/package.json`, `frontend/tsconfig.json`, `frontend/eslint.config.js`, `pnpm-lock.yaml` (PRP-00 files, see C6), `packages/contracts/**` (PRP-01), and any `services/` path.

### Item 1 — vite-app-shell  [P]
- Deliverable: Vite + React 19 + TS 6 strict app entry (`main.tsx`, `App.tsx`), react-router 8 route table, layout with a navigation slot, error boundary, runtime `config.json` loader (cloud, tenantId, clientId, apiBaseUrl, apiScope), bundle size report script.
- Owned files (may edit): `frontend/src/app/`, `frontend/vite.config.ts`, `frontend/index.html`.
- Must NOT touch: `frontend/src/design-system/` (item 2), `frontend/src/auth/` (item 3), `frontend/src/api/` (item 4), `frontend/src/features/workspaces/` (item 5), `frontend/tests/` and `frontend/playwright.config.ts` (item 6); plus the shared list.
- Depends on: none.
- Acceptance criteria:
  - `tsc --noEmit` passes with strict flags; `pnpm --filter frontend build` succeeds and writes a bundle report.
  - Config loader rejects a missing or unknown `cloud` (`commercial` and `government` only) and renders a configuration error screen.
  - Error boundary catches a thrown render error and shows a recoverable message with the correlation ID if present.
- Pattern references: TS strict rules; barrel exports; C7 runtime config.
- Tests to write: `frontend/src/app/config.test.ts`, `frontend/src/app/ErrorBoundary.test.tsx`, `frontend/src/app/routes.test.tsx`.

### Item 2 — design-system  [P]
- Deliverable: Fluent UI v9 provider wrapper, token layer with light, dark and high-contrast sets, typography scale, icon set mapping node types (person, agent, sub-agent, model, source) to icons, theme switcher store (Zustand), neutral logo slot.
- Owned files (may edit): `frontend/src/design-system/`.
- Must NOT touch: `frontend/src/design-system/themes/` (reserved for PRP-24; create nothing there), `frontend/src/app/`, `frontend/src/auth/`, `frontend/src/api/`, `frontend/src/features/`, `frontend/tests/`; plus the shared list.
- Depends on: none.
- Acceptance criteria:
  - Three themes switch at runtime with no navigation, no re-login and no API call (asserted in test).
  - Every foreground/background token pair on the theme gallery passes axe contrast in all three themes.
  - No hex literal outside `tokens/`; a unit test scans for it.
  - Node-type icons expose an accessible name; shape or label differs per type, not color alone.
- Pattern references: Fluent tokens rule; no Microsoft marks (C11).
- Tests to write: `frontend/src/design-system/theme.test.tsx`, `frontend/src/design-system/tokens.test.ts`, `frontend/src/design-system/icons.test.tsx`.

### Item 3 — msal-auth  [P]
- Deliverable: MSAL browser instance factory choosing authority and knownAuthorities by `cloud`, `AuthProvider`, silent and redirect token acquisition for `apiScope`, sign-out, `useRoles()` hook reading role claims for display only, and a `getToken(): Promise<string>` seam as the only token exit.
- Owned files (may edit): `frontend/src/auth/`.
- Must NOT touch: `frontend/src/api/` (item 4 consumes the `getToken` seam by injection), `frontend/src/app/`, `frontend/src/design-system/`, `frontend/src/features/`, `frontend/tests/`; plus the shared list.
- Depends on: none.
- Acceptance criteria:
  - `cloud=government` yields authority host `login.microsoftonline.us`; `cloud=commercial` yields `login.microsoftonline.com` (table-driven test).
  - Unauthenticated render triggers login redirect; no token is written to logs or `console` (spy test).
  - Role display lists the five NS-08 roles only if present in claims; absence shows "no roles"; no code branch grants capability from claims beyond navigation visibility.
- Pattern references: C8, C9; msal-react peer range.
- Tests to write: `frontend/src/auth/authority.test.ts`, `frontend/src/auth/AuthProvider.test.tsx`, `frontend/src/auth/roles.test.ts`.

### Item 4 — api-client  [P]
- Deliverable: typed fetch client using `packages/contracts/ts` types, `x-correlation-id` generation and propagation, error taxonomy mapping, pagination and budget helpers, TanStack Query provider and hook factories.
- Owned files (may edit): `frontend/src/api/`.
- Must NOT touch: `frontend/src/auth/` (item 3), `frontend/src/app/`, `frontend/src/design-system/`, `frontend/src/features/`, `frontend/tests/`; plus the shared list.
- Depends on: none.
- Acceptance criteria:
  - 401, 403, 429, 409 map to `unauthorized`, `forbidden`, `rate_limited`, `stale_version`; unknown 5xx maps to `dependency_transient` with the contract `retryable` flag honored (table-driven tests).
  - 429 honors `Retry-After`; 409 never auto-retries.
  - The client never adds `domain_id` or `customer_id` to a request; a test asserts the outgoing URL and body for a sample call.
  - A 503 from a policy outage surfaces as an error state, never as empty data.
- Pattern references: error taxonomy names from PRP-01; contracts import rule.
- Tests to write: `frontend/src/api/client.test.ts`, `frontend/src/api/errors.test.ts`, `frontend/src/api/pagination.test.ts`.

### Item 5 — role-workspaces
- Deliverable: workspace routes and nav entries for Viewer, Analyst, Steward, Admin, Auditor, each rendering a labelled placeholder page; nav visibility derived from display roles; a forbidden-state component shown on API 403.
- Owned files (may edit): `frontend/src/features/workspaces/`.
- Must NOT touch: `frontend/src/app/`, `frontend/src/design-system/`, `frontend/src/auth/`, `frontend/src/api/`, `frontend/tests/`, other `frontend/src/features/*` (later PRPs); plus the shared list.
- Depends on: items 1, 2, 3.
- Acceptance criteria:
  - Each persona route renders; nav shows only entries suggested by claims.
  - Navigating by URL to a hidden workspace still issues the API call and renders the forbidden state on 403 (component test with mocked client).
  - UI copy makes no claim of enforcement; a code comment states nav is not authorization.
- Pattern references: "Hidden navigation is not authorization; the API must deny."
- Tests to write: `frontend/src/features/workspaces/workspaces.test.tsx`, `frontend/src/features/workspaces/forbidden.test.tsx`.

### Item 6 — test-harness  [P]
- Deliverable: Vitest setup (jsdom, Testing Library, MSW 2.x), Playwright config (headless chromium, mock API server, `webServer` entry), axe helpers, e2e smoke and hidden-route 403 e2e, CI-friendly reporters.
- Owned files (may edit): `frontend/tests/`, `frontend/playwright.config.ts`.
- Must NOT touch: every `frontend/src/**` path (items 1-5); plus the shared list.
- Depends on: item 1 (entry point to serve).
- Acceptance criteria:
  - `pnpm --filter frontend test` runs Vitest including axe checks on the theme gallery and workspace pages.
  - Playwright smoke (load, mocked sign-in, workspace renders) passes headless; the hidden-route e2e asserts a mock-API 403.
  - Test run needs no network and no credentials.
- Pattern references: Vitest + Testing Library + Playwright rule; C10.
- Tests to write: `frontend/tests/e2e/smoke.spec.ts`, `frontend/tests/e2e/hidden-route.spec.ts`, `frontend/tests/setup.ts`, `frontend/tests/mock-api/server.ts`.

## Validation gates

```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
pnpm install --frozen-lockfile
pnpm --filter frontend lint
pnpm --filter frontend typecheck
pnpm --filter frontend test
pnpm --filter frontend build
pnpm --filter frontend exec playwright test --reporter=line
```

No `scripts/gates/` live script in this PRP. A real-tenant sign-in smoke, if ever run, is **operator-approved, requires NS_LIVE_APPROVED=1** and belongs to a later PRP's gate script.

## Live and open gates

| Gate | Touch | Evidence that narrows it |
|---|---|---|
| G09 theme/brand/media review | Starts it (token layer, no brand marks) | Axe-clean theme gallery here; PRP-24 completes the 508/WCAG audit and legal review |
| G12 emulator parity | Not touched | none |
| G02 FedRAMP/DoD boundary | Not touched; Government authority is config only | none; no authorization claim is made |

Open items to carry: real Entra sign-in on a Commercial tenant and on a Government tenant has not run; the Government authority is verified by unit test only.

If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building

- Any authorization enforcement, policy or audit (PRP-06). Nav hiding is cosmetic.
- Agency theme packs and logos (PRP-24 owns `frontend/src/design-system/themes/`); the full WCAG audit (PRP-24).
- Feature pages: dashboards (PRP-14), reconciliation, recommendations (PRP-15), quality (PRP-16), actions and review (PRP-17), map and replay (PRP-18), copilot and charts (PRP-19), MCP admin (PRP-22), sandbox toggle (PRP-24).
- The FastAPI backend, OpenAPI export or WebSocket client (PRP-05, PRP-18).
- Dockerfile and image publishing for the frontend (PRP-13).
- Localization catalogs (tokens are localization-ready only; English UI).

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
- Open gates / untested live items:
- Follow-ups:
