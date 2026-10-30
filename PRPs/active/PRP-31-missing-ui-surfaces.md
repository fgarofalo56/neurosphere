---
name: prp-31-missing-ui-surfaces
status: active
started: 2026-10-30
branch: prp-31-missing-ui-surfaces-impl
review: required
priority: P1
created: 2026-10-24
model: sonnet
phase: 5
ns: NS-01, NS-02, NS-03, NS-06, NS-07, NS-08, NS-10
depends_on: PRP-29, PRP-30
wave: W9
absorbs: new
---

# PRP-31: Missing UI surfaces

## Goal
Give every shipped backend capability that has no page a governed, accessible UI, so that "all functionality built" per the PRD is true in the product and not only in the API. An audit on 2026-10-24 compared the PRD, `services/api/neurosphere_api/routers.py` `REGISTERED`, `services/api/openapi.json` and `frontend/src/app/route-manifest.json`. It found these API-only capabilities:
- the catalog: entity search/list/detail, lineage, deprecation, recertification, stale-agent reconciliation and export (PRP-10);
- relationship curation: presented edge, override history, observations and steward decisions (PRP-10);
- the audit log and chain verification (PRP-06);
- the FinOps forecast and federated summaries (PRP-21);
- deployment intelligence: the resource scan and the reuse/create/skip plan (PRP-08), plus the capability matrix rendered as "disabled with reason" (PRP-02);
- evaluation result drill-down (PRP-16);
- the action-plane emergency disable toggle (PRP-17; the UI only reads it today).

This PRP ships those surfaces as eight feature folders on the PRP-28 shell and PRP-30 style system. It also adds one small backend module of UI-facing adapters. The adapters exist because three of those APIs cannot be called safely from the browser as they stand:
- the catalog list/export take `domain_id` as a query parameter, which `ApiClient` forbids;
- a curation decision body carries `domain_id`/`customer_id` and a client-supplied `actor`;
- an auditor holds no `data.read`, so `/me/domains` gives them no domain to pick.

Capabilities with no API at all are listed with a named destination, never faked. MCP admin already has a UI (`/mcp-admin`, `/mcp-admin/server`); this PRP leaves it alone.

### PRD capability -> API -> UI today -> this PRP
| NS | PRD capability | API (today) | UI today | This PRP |
|---|---|---|---|---|
| NS-01 | OTLP / CloudEvents push ingest | `POST /v1/ingest/otlp/traces`, `/otlp/metrics`, `/events` (producer auth) | none; machine-to-machine | No UI (producer API) |
| NS-01 | Quarantine, replay, backpressure, connector health | **no API** | none | Deferred: no API; follow-up ingestion-operations PRP (see NOT building) |
| NS-01 | Cost / latency / coverage dashboards | `GET /api/v1/dashboards/domains/{d}/{metric}` | `/dashboards/*` | none (exists) |
| NS-01 | Reconciliation coverage and variance | `GET /api/v1/reconciliation/domains/{d}` | `/reconciliation` | none (exists) |
| NS-01 | FinOps forecast (PRP-21) | `GET /api/v1/finops/domains/{d}/forecast` | none | Item 6 `/finops/forecast` |
| §3 | Federated cell summaries (PRP-21) | `GET /api/v1/federation/summary`, `/cell-summary` | none | Item 6 `/federation` |
| NS-02 | Entity list and search | `GET /catalog/entities?domain_id=` (query key forbidden by `ApiClient`), `POST /catalog/search` | none | Item 2 domain-path adapters + Item 3 `/catalog` |
| NS-02 | Entity detail, deprecate, recertify | `GET/POST /catalog/entities/{id}[/deprecate\|/recertify]` with If-Match | none | Item 3 `/catalog/entity` |
| NS-02 | Scope-filtered lineage (neighbors, impact) | `POST /catalog/lineage/neighbors`, `/impact` | map viewport only | Item 3 lineage tab (table first) |
| NS-02 | Steward accept / reject / override / lock / unlock | `POST /catalog/curation/edges/{id}/decisions` (body carries scope keys and a client `actor`) | none | Item 2 decision adapter + Item 4 `/catalog/edge` |
| NS-02 | Override history; observed facts kept apart | `GET .../overrides`; `GET .../observations` (`evidence.read`) | none | Item 4 |
| NS-02 | Ownership recertification | `GET /catalog/recertifications` | none | Item 3 `/catalog/recertifications` |
| NS-02 | Stale-agent reconciliation | `POST /catalog/reconcile/stale-agents/dry-run`, `/confirm` | none | Item 3 `/catalog/stale-agents` |
| NS-02 | Export | `GET /catalog/export?domain_id=` (`data.export`) | none | Item 2 domain-path adapter + Item 3 download |
| NS-02 | Create / edit / bulk import | `POST /catalog/entities`, `PUT .../{id}`, `POST /catalog/import` | none | Deferred (Clarification 6) |
| NS-02 | Purview / Unity Catalog integration | **no API** (connector scope) | none | Deferred: connector work, not UI |
| NS-03 | Recommendations | `/api/v1/recommendations/...` | `/recommendations` | none (exists) |
| NS-03 | Quality summary | `GET /api/v1/evaluation/domains/{d}/quality` | `/quality` | none (exists) |
| NS-03 | Evaluation results (dimension, subject, judge) | `GET /api/v1/evaluation/domains/{d}/results` | none | Item 8 `/evaluations` |
| NS-04 | Review queue, assignment, decisions | `/api/v1/review/...` | `/review` | none (exists) |
| NS-04 | SLA / notification configuration | **no API** | none | Deferred (policy admin, see NOT building) |
| NS-05 | Map, map table, replay | `/api/v1/map/...`, `/api/v1/replay/...` | `/map`, `/map/table`, `/replay/traces` | none (exists) |
| NS-06 | Copilot, saved reports | `/api/v1/copilot/...`, `/api/v1/reports/...` | dock, `/reports` | none (exists) |
| NS-06 | Action executor (propose / confirm / approve) | `/api/v1/actions/domains/{d}/intents/...` | `/actions` | none (exists) |
| NS-06 | Emergency disable | `GET/PUT /api/v1/actions/emergency-disable` | read only, in `/actions` | Item 8 `/admin/execution-control` |
| NS-07 | Consented resource scan | `POST /v1/deploy/scan` (`config.manage`) | none | Item 7 `/deploy` |
| NS-07 | Reuse / create / skip plan with cost and checks | `POST /v1/deploy/plan` (pure function) | none | Item 7 `/deploy` |
| NS-07 / NS-08 | Capability matrix, "disabled with reason" (PRP-02) | **no read API** (core loader only; plan items carry `disabled_reason`) | none | Item 2 `GET /api/v1/capabilities` + Item 7 `/deploy/capabilities` |
| NS-07 | Provision after plan approval | **no API** (IaC pipeline, PRP-08) | none | Not building: the operator-approved pipeline stays the only path |
| NS-08 | Audit read and chain verify | `GET /audit/chains/{chain_id}/records`, `/verify` | none | Item 2 domain adapters + Item 5 `/audit` |
| NS-08 | Data lifecycle (retention, hold, deletion, export) | **no API** (`packages/core/neurosphere_core/lifecycle/**` engine only) | none | Deferred: new lifecycle-API PRP (destructive; Opus, review required) |
| NS-08 | ATO evidence inventory, control narratives | docs + `scripts/compliance/` only | none | Deferred to PRP-25 docs site (published docs) |
| NS-08 | Revocation / policy administration | **no API** | none | Deferred (PRP-06 follow-up) |
| NS-09 | MCP server registration admin | `/api/v1/mcp/admin/...` | `/mcp-admin`, `/mcp-admin/server` | none (verified exists) |
| NS-09 | Connector SDK health / rate-limit reporting | **no API** | none | Deferred with ingestion operations |
| NS-10 | Themes, sandbox, role workspaces, WCAG | shipped | shipped | New pages join the PRP-24 axe matrix |

## Acceptance criteria
- [ ] Item 1: all twelve new routes (wire contract) are in `appRoutes.ts`, `route-manifest.json` and `route-samples.ts`; each renders a placeholder page inside the shell. The grouped nav lists them with their permission or role hints. The mock API dispatches to per-feature handler modules through one registry, so no later lane edits `server.ts`, `appRoutes.ts`, `workspaceNav.ts`, the manifest or the samples. The route-manifest Vitest and the "every manifest route has an axe sample" Playwright test are green.
- [ ] Item 2: the UI-facing adapter endpoints in the wire contract exist under `services/api/neurosphere_api/ui_adapters/**`, each with a declared permission.
  - The route inventory test is green; `openapi.json` is regenerated and `test_openapi_drift` is green.
  - Curation decisions are stamped server-side: the actor is the caller principal (`principal_kind: user` only), `decided_at`, `cloud`/`customer_id`/`domain_id`/`edge_id`/`relation_type` come from the stored edge, and the channel is `button`. A body carrying any of those fields is rejected with 422 (test).
  - The audit adapters derive the chain id server-side. A cross-customer or cross-domain request gets 403, and an auditor with no `data.read` can list and read their audit domains (tests).
- [ ] Item 3: `/catalog` lists and searches entities for the selected domain (paged, "N+", unknown never shown as 0). `/catalog/entity` shows the entity, its version/ETag, owner and lifecycle, plus lineage neighbors and impact as a table with a "show on map" link. Deprecate and recertify go through the governed change dialog with If-Match; a 409 shows "changed since you opened it" and reloads (test). The recertifications queue and the stale-agent dry-run -> confirm flow work. Export downloads JSON pages for `data.export` holders only.
- [ ] Item 4: `/catalog/edge` shows the presented edge: status (asserted/inferred/curated), confidence, provenance, evidence ids, first/last observation, validity and lock. Override history is listed, and observations appear in a separate section for `evidence.read` holders only.
  - Accept/reject/override/lock/unlock go through the governed change dialog, which shows the edge id, expected version, before/after and the required reason, plus the expiry for lock/override.
  - A stale edge (409 `stale_edge`) is surfaced, never retried silently.
  - The page never sends `actor`, `domain_id` or `customer_id` (test).
- [ ] Item 5: `/audit` is read-only. Its domain picker is fed by `GET /api/v1/audit/domains` (not `/me/domains`). Records are paged by cursor, and fields are shown exactly as the API returns them (no client-side enrichment, no PII beyond the payload). A "Verify chain" control shows the verification result and break position. A 403 shows `ForbiddenState`.
- [ ] Item 6: `/finops/forecast` shows estimated and invoiced series separately, never summed. It shows the forecast band, the method (`linear_trend_ols`, confidence, fit points, excluded incomplete days) and "forecast unavailable: <reason>" when the API says so. `savings_claim: false` is reflected: no savings wording. `/federation` shows merged totals per currency, per-cell outcome (`ok`/`denied`/`unavailable`), and `complete`/`truncated` badges.
- [ ] Item 7: `/deploy` (Admin, `config.manage`) runs scan -> choices -> plan.
  - The scan form takes subscription ids and a consent record and shows the per-subscription `visible`/`not_visible` result with the visibility note verbatim.
  - The plan shows each item's status, reuse/create/skip, `shared`, checks, cost basis (`estimated`/`no_incremental_cost`/`unknown`), disabled reason and source link. The plan manifest downloads as JSON. There is **no apply control**.
  - `/deploy/capabilities` renders the matrix with availability, GA status and authorization scope as separate columns. Unsupported or unverified rows are shown disabled with their reason, never as supported.
- [ ] Item 8: `/evaluations` lists evaluation results for the domain, with subject and dimension filters and cursor paging, and labels calibration and uncertainty as the API returns them. `/admin/execution-control` shows the kill-switch state (`changed_by` as a pseudonym). Disable (reason code required) and re-enable go through the governed change dialog; the API's 403 for non-`config.manage` callers is shown.
- [ ] Every new page: uses the PRP-30 page template and primitives, contains 0 native form controls (the static test stays green with no new allowlist entries), has Vitest coverage, has one lean Playwright spec, and gets 0 serious/critical axe violations in light, dark, high-contrast and sandbox mode (with the documented tabster exclusion).
- [ ] PRP exit: all items green under `verify-gates -Mode full`; the full frontend Vitest and Playwright suites are green; the frontend CI job stays under its 25-minute cap (measured, reported); `pnpm demo` shows every new page with mock data. The reviewer confirms that every mutation is server-checked, version-bound and audited, and that no page sends scope keys or actor identity.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Scope | every API-only capability; only catalog + audit; also build missing APIs | Every API-only capability in the gap table gets a UI. Missing APIs are added only when they are small read adapters clearly inside the surface's NS (Item 2); anything else is deferred with a named destination |
| 2 | Curation decisions: PRP-17 action executor or PRP-10 curation service | add an executor action kind; reuse the curation service behind the governed change dialog | Reuse PRP-10's `CurationService.decide` through the Item 2 adapter. It already does what the executor would add here: permission recheck at request time, version and ETag binding (409 `stale_edge`), audit before and after, and immutable override history. The executor registers only `model_deployment_swap` (`actions/settings.py:35-37`), and adding a kind is PRP-17 backend scope. The UI never mutates directly: every change goes through the confirm dialog and the server decides |
| 3 | Domain-in-query catalog routes vs `ApiClient`'s forbidden `domain_id` key | relax the client guard; domain-path adapters | Domain-path adapters (Item 2). The `ApiClient` guard (`frontend/src/api/client.ts:46-58`) stays untouched |
| 4 | Client-supplied `actor` in `EdgeOverride` | trust the client; adapter stamps it | The adapter stamps it from the authenticated principal. The underlying gap in `/catalog/curation/edges/{id}/decisions` (the actor is not checked against the caller) is reported to PRP-29 as a security follow-up, not fixed here (PRP-29 owns `catalog/**`) |
| 5 | Audit domain source for auditors (no `data.read`, so `/me/domains` is 403) | reuse the switcher; dedicated endpoint; free-text chain id | A dedicated `GET /api/v1/audit/domains` (domains where the caller holds `audit.read`). Chain ids are derived server-side, never typed or derived in the browser. Nav shows Audit by role claim (`Auditor`, `Admin`), because the permission union from `/me/domains` is empty for auditors |
| 6 | Catalog create / edit / import | full forms; defer | Deferred. Registration flows through connectors, import and CI/CD policy checks (NS-09), and a UI uploader adds file-parsing attack surface. Deprecate, recertify, stale-agent confirm and curation are built |
| 7 | Deploy apply | apply button; none | None. The plan is a pure function (`deploy/plan/router.py:1-4`) and provisioning stays the operator-approved IaC pipeline. The UI downloads the manifest |
| 8 | Deploy consent `consented_by` (`deploy/scan/models.py:38`, free string up to 320 characters) | free text; stamp server-side | Attestation reference field: the UI rejects email-shaped values and labels it "pseudonymous id or ticket reference". Server-side stamping is a PRP-29 follow-up (no adapter here, to keep Item 2 small) |
| 9 | Lineage rendering | new graph view; table first | Table first, with a link to `/map?domain_id=` for visual context. No new graph renderer (sigma/vega import risk) |
| 10 | Shared files with PRP-30 / parallel lanes | every lane edits nav/manifest/mock; one integration item | Item 1 owns every shared file and lands first with placeholders. Lanes own only their feature folder, their mock module and their spec |
| 11 | Governed change dialog | per-feature dialogs; reuse the actions `ConfirmationDialog`; one shared dialog | One `ChangeConfirmDialog` (target, version/ETag, before/after diff, reason, optional expiry). It uses PRP-30's dialog primitive if one is exported, otherwise it lives in `frontend/src/features/governed-change/` (Item 1). The actions `ConfirmationDialog` (`actions/components.tsx:232-312`) is bound to `ActionIntent.confirmation_hash` and stays PRP-17's |
| 12 | Model and review | sonnet; opus | `model: sonnet`; Item 2 runs on **Opus**, because it touches audit read authz and principal stamping (CLAUDE.md model policy for PRP-06-class work). `review: required` |

### Decisions to confirm at plan approval
1. Curation via the PRP-10 service plus the adapter, not the PRP-17 executor (Clarification 2).
2. Item 2's endpoint list, module name `ui_adapters`, and its Opus model; drop any adapter PRP-29 already ships in an equivalent form.
3. The deferrals: catalog create/edit/import, lifecycle API+UI, ingestion/connector operations, revocation/policy/SLA admin, and the evidence viewer (PRP-25).
4. The twelve route paths and nav placement (wire contract).
5. No deploy apply control; `consented_by` handling (Clarifications 7 and 8).
6. The PRP-30 exports (verified against the PRP-30 file on 2026-10-24) and the four gaps it does not cover: band series, dialog, `DetailList`, tabs. Either PRP-30 adds them additively or the lane-local fallback applies.

## Context manifest

### Files that matter
- `docs/PRD.md:8-48` (NS-01..NS-10), `:52-53` (federation, retention). The gap table above is the authoritative mapping.
- `services/api/neurosphere_api/routers.py`:
  - `:54-206`: one `_register_*` hook per module (audit `:61-67`, deploy `:76-85`, catalog `:88-97`, federation/finops `:178-187`).
  - `:208-234`: the `REGISTERED` tuple. Item 2 adds one hook after PRP-29's edits.
- Catalog: `services/api/neurosphere_api/catalog/router.py`:
  - `:93`: `PREFIX = "/catalog"`, outside `/api/v1`; PRP-29 normalises it.
  - `:97-101`: access dependencies (`data.read`, `catalog.curate`, `data.export`).
  - `:150-165`: list with `domain_id` **query**.
  - `:179-213`: deprecate/recertify with `If-Match`.
  - `:240-266`: search and lineage.
  - `:288-305`: export, with a `domain_id` query.
  - `:307-336`: recertifications and stale agents.
- `services/api/neurosphere_api/catalog/models.py:114-186` (`RecertifyRequest`, `RecertificationPage`, `StaleAgentPlan`/`Confirm`/`Outcome`); `packages/core/neurosphere_core/catalog/protocol.py:393-400` (`GraphSearchRequest`, `EntityFilter.domain_ids`).
- Curation: `services/api/neurosphere_api/catalog/curation/router.py`:
  - `:46`: `PREFIX`.
  - `:55-57`: `data.read`/`catalog.curate`/`evidence.read`.
  - `:72-108`: decide, overrides, observations and presented edge.
- `services/api/neurosphere_api/catalog/curation/service.py`:
  - `:84-87`: audit chain `<customer>.<name>`.
  - `:128-158`: `decide(..., channel=)`.
  - `:195-250`: `_validate`. It stamps `decided_at` server-side (`:247-249`) but does **not** check `actor` against the caller.
- `packages/contracts/python/neurosphere_contracts/catalog/v1/edge_override.py:49-60`: the body carries `cloud`, `customer_id`, `domain_id` and `actor`.
- Audit:
  - `services/api/neurosphere_api/audit/router.py:35-37,71-101`: records paged by sequence cursor; verify.
  - `services/api/neurosphere_api/authz/audit_mount.py:52-56` (`audit.verify` maps to `AUDIT_READ`), `:63-71` (chain must start with the caller's customer), `:85-94` (chain -> domain), `:97-108`.
  - `packages/core/neurosphere_core/actions/audit.py:83-89`: `action_audit_chain_id(customer, domain)`.
- `packages/core/neurosphere_core/auth/scope/permissions.py`:
  - `:51-72`: roles and permissions.
  - `:89`: the auditor holds only `audit.read`/`evidence.read`.
  - `:135-148`: `domains_with_permission`.
- `packages/contracts/python/neurosphere_contracts/scope/v1/identity_scope.py:54-59,107`: `principal.principal_id`, `principal_kind`.
- FinOps: `services/api/neurosphere_api/finops/router.py:39,55-80`; `finops/models.py:54-58` (`Amount.status` known/unknown), `:150-176` (separate estimated/invoiced series, `savings_claim: Literal[False]`).
- Federation: `services/api/neurosphere_api/federation/router.py:34,66-97`; `federation/models.py:17-39` (cell `state`, `complete`, `truncated`, `totals`).
- Deploy:
  - `services/api/neurosphere_api/deploy/scan/router.py:21,38-46`; `scan/models.py:34-80`. The response always carries `visibility_limited: true` and `visibility_note`.
  - `deploy/plan/router.py:1-36`; `plan/models.py:85-162` (choices, consent, `PlanItem.kind` service/feature, `disabled_reason`, `source_url`, `PlanCost.basis`).
  - `packages/core/neurosphere_core/capabilities/loader.py`, `validate.py`; `packages/contracts/python/neurosphere_contracts/deployment/v1/capability_matrix_entry.py`.
- Evaluation: `services/api/neurosphere_api/evaluation/router.py:49-66` (results list: `subject_id`, `dimension`, cursor, `limit`).
- Emergency disable: `services/api/neurosphere_api/actions/router.py:206-215`; `actions/models.py:89-97` (body; a reason is required when disabling), `:163-171` (view, `changed_by` pseudonym); frontend read at `frontend/src/features/actions/hooks.ts:26,49-51`.
- `services/api/neurosphere_api/me/router.py:33,38,101-131`: pattern for a small scope-derived read router.
- Frontend shell:
  - `frontend/src/app/appRoutes.ts:1-37`: route list. It imports feature **index** modules; keep new entries on `routes.tsx` imports.
  - `frontend/src/app/workspaceNav.ts:2-3` (light-imports rule), `:21-54` (`buildAppNavItems`, groups), `:61-68`.
  - `frontend/src/app/navigation.ts`: `NAV_GROUPS`, `NavItem.roles`/`permission`, `isNavItemVisible`.
  - `frontend/src/app/route-manifest.json`; `frontend/src/app/route-manifest.test.ts:26-35`.
  - `frontend/src/app/domain.tsx:43-48,225`: `useSelectedDomain()`, `ME_DOMAINS_PATH`.
- `frontend/src/api/client.ts:31-32,101-107` (If-Match support), `:46-58` (`FORBIDDEN_SCOPE_KEYS` on query and body, recursive).
- `frontend/src/design-system/index.ts:6-7`: `PageHeader`/`PageTemplate`/`PageToolbar` (PRP-28). PRP-30 extends them.
- Feature pattern: `frontend/src/features/mcp-admin/paths.ts:1-36`, `routes.tsx`, `index.ts`; `frontend/src/features/sandbox/routes.tsx`. `frontend/src/features/workspaces/index.ts:1` (`ForbiddenState`).
- Mock API: `frontend/tests/mock-api/server.ts`:
  - `:16-24`: per-module imports (`copilot.ts`, `mcpAdmin.ts`).
  - `:75-76,158-162`: `ME_DOMAINS_PATH`, `DOMAIN_OK`, `DOMAIN_FORBIDDEN`.
  - `:1973-2163`: `createMockApi`, the handler chain, and the `mcpAdmin` dispatch at `:2051-2055`.

  See also `frontend/tests/mock-api/mcpAdmin.ts:1-14,60-64,184` (the per-feature module precedent: own state + handler).
- A11y: `frontend/tests/e2e/a11y/route-samples.ts:1-8,25-28,30-147`; `frontend/tests/e2e/a11y/routes.a11y.spec.ts:35-43` (fails when a manifest route has no sample); `frontend/tests/e2e/a11y/axe-support.ts:27,29` (`TABSTER_SENTINEL`, `MODES`).
- `frontend/tests/static/no-native-controls.test.ts:15-16` and its allowlist.
- `frontend/playwright.config.ts:3-4,25,29` (port env); `.github/workflows/ci.yml:50` (frontend `timeout-minutes: 25`; 14m49s at PRP-28, before PRP-24's axe matrix).

### Patterns to match
- Router module: `PREFIX`, `build_router`, `register(registry)`, `require(Permission.X, resource=domain_from_path(...))` (`services/api/neurosphere_api/me/router.py`, `finops/router.py:39-80`).
- Pydantic v2 bodies with `ConfigDict(extra="forbid")` (`catalog/models.py:45`), so a smuggled `actor`/`domain_id` is a 422.
- Feature folder: path-only `paths.ts`, `routes.tsx` (`*Routes`, `*NavItems`), light `index.ts` (`mcp-admin/*`).
- Integration-first hookup with placeholders, so lanes never touch shared files (PRP-28 item 2 / PRP-18/19 item 7 precedent).
- Mock per-feature module with fresh state and a handler (`mcpAdmin.ts`).
- Two-step governed flow: dry-run -> confirm with server re-derivation (`catalog/models.py:158-175`); If-Match/ETag (`McpServerDetailPage`, `client.ts:106`).

### Conventions
- TypeScript 6.0.x strict, `@fluentui/react-components` 9.74.x, React 19, TanStack Query as used by existing hooks. **No new dependencies** (licence gate `python scripts/licenses_report.py --check`).
- Vitest + Testing Library; MSW 3 ignores `onUnhandledRequest` (#92), so prefer the strict `fetchImpl` stub pattern used by `features/overview/overview.test.tsx`.
- Playwright: unique `NS_E2E_APP_PORT`/`NS_MOCK_API_PORT` per worktree.
- API test packages must be uniquely named: `services/api/tests/ui_adapters_api/`.
- Python is `python`, never `python3`; ruff (line 100, py312, S rules); pyright standard; conventional commits; owned-file discipline.
- Strings in `strings.ts` per feature; accessible names stable once specs pin them.

### Gotchas
- **Heavy imports.** The shell, nav and `appRoutes.ts` additions import `paths.ts`/`routes.tsx` only. Never import `features/charts` or `features/map` from a new feature's top level, or sigma (WebGL) and vega reach jsdom and crash unrelated tests. Charts use PRP-30's React-SVG `TimeSeriesChart`/`BarChart`, which need no vega, so never use `features/charts` (the copilot sandbox) for these pages.
- **Scope keys.** `ApiClient` throws on `domain_id`/`customer_id` anywhere in a query or body (recursive). That is why Item 2 exists. `EntityFilter.domain_ids` slips past the key guard but breaks the domain-in-path convention, so use the adapter.
- **Auditor has no `data.read`.** `/me/domains` answers 403, so the shell switcher shows "No domains are assigned to you" for auditors. The audit page must use its own domain list and must not depend on `useSelectedDomain()`. The curation page's observations section is the only part an auditor can read (edge GET needs `data.read`).
- **Curation actor.** `EdgeOverride.actor` is client-supplied and unchecked in the existing route. Never expose that route to the browser; use the adapter. Report the root gap to PRP-29.
- **Edge ids contain `:` and may contain `/`** (`{edge_id:path}`). Always use `encodeURIComponent` in paths and test round-trips.
- **No totals.** Lists are cursor-paged without counts: show "N+", never an invented total. `Amount.status: unknown` renders "unknown", never 0. Mixed currencies are never summed (finops, federation `totals`).
- **Federation cells.** `denied` and `unavailable` cells mean incomplete data and must say so (`complete: false`). Never imply cross-boundary data was merged.
- **Plan wording.** `visibility_note` and `disabled_reason` are shown verbatim. No "authorized", "compliant" or "FedRAMP" wording anywhere in the UI (CLAUDE.md).
- **Fluent tabster.** Axe needs the documented `[data-tabster-dummy]` exclusion (`frontend/tests/e2e/copilot.spec.ts:15`, `axe-support.ts:27`). Dialogs and tabs add sentinels.
- **Route-manifest coupling.** A route in `appRoutes` without a manifest entry fails Vitest; a manifest entry without a sample fails the first a11y test. That is why Item 1 lands all twelve together.
- **CI time.** Each manifest route adds axe runs per mode plus the keyboard and aria-tree passes (about 5 tests per route, about 60 here). Keep feature specs to one file each with shared fixtures. Measure the frontend job on the PR; if it exceeds about 22 minutes, report it. `ci.yml` is not owned here.
- **CodeQL rules that fail PRs.** `js/bad-tag-filter` (no regex HTML parsing), `py/side-effect-in-assert`, `py/uninitialized-local-variable` (match captures), `py/overwritten-inherited-attribute`, and PEP 695 generics in nested defs. Gitleaks: split credential-shaped literals in fixtures. Put these in every brief.
- **OpenAPI component renames.** Using contract models as `response_model` can rename `openapi.json` components (the PRP-15/18/19 precedent). Item 2 reports whether its regeneration diff is purely additive.
- **Shared compose.** Item 2's tests use in-process fakes; no compose lane is needed (fixed compose project name across worktrees).
- **Synthetic data only.** Mock fixtures use `commercial:e2e:sandbox:*` ids and pseudonymous principals; no real names, emails or subscription ids. Subscription ids in fixtures are obviously fake GUIDs split across literals.

### External references
- Fluent UI v9 `Dialog`, `TabList`, `Table`/`DataGrid`, `Field`, `Combobox`, `Badge`: https://react.fluentui.dev/ (already exported by `@fluentui/react-components` 9.74.x).
- WAI-ARIA APG tabs and dialog patterns: https://www.w3.org/WAI/ARIA/apg/patterns/.
- No Microsoft Learn facts are load-bearing here; Azure behaviour is already encoded in PRP-02/08 code.

### PRP-30 dependency (check at plan approval)
`PRPs/backlog/PRP-30-visual-redesign-and-switchable-ui-styles.md` (its "Exports for PRP-31" line) lists these exports, with signatures frozen at its checkpoint: `PageTemplate` v2 (additive `kpis`/`layout`), `KpiCard`, `StatusPill`, `HealthIndicator`, `EmptyState`, `LoadingState`, `ErrorState`, `Timestamp`, `DataTable`, `TimeSeriesChart` (React SVG line/area; it throws `MixedSeriesError` on mixed currencies or units), `Sparkline`, `BarChart`, `ChartLegend`, `NeuroSphereMark` and `useUiStyle`. PRP-31 uses all of them except `NeuroSphereMark`.

PRP-30 does **not** list four things this PRP needs:
- a confidence-band series for `TimeSeriesChart` (forecast band);
- a dialog primitive (`ChangeConfirmDialog`);
- a key/value `DetailList`;
- a tabs layout.

Default: the forecast band is drawn as two dashed bound series plus a table, unless PRP-30 adds a band prop (additive). The dialog lives in `governed-change/` (Item 1). `DetailList` and tabs are lane-local Fluent `TabList`/`<dl>` compositions. Nothing edits `frontend/src/design-system/**`.

### Wire contract (the UI codes against these; the mock implements them in Item 1 placeholders and lane modules)
PRP-29 dependency: `/catalog/**`, `/audit/**` and `/v1/deploy/**` are normalised under `/api/v1` with deprecated aliases. The UI calls only the `/api/v1` forms.

**From PRP-29 (normalised existing routes, shapes unchanged):**
- `GET /api/v1/catalog/entities/{entity_id}` -> `CatalogEntity` + `ETag`.
- `POST /api/v1/catalog/entities/{entity_id}/deprecate` (If-Match) and `.../recertify` `{valid_for_days}` (If-Match) -> `CatalogEntity`; 409 on stale.
- `POST /api/v1/catalog/lineage/neighbors` and `/impact` -> `GraphResult` (budget clamped server-side).
- `GET /api/v1/catalog/recertifications?within_days&include&page_size&cursor` -> `RecertificationPage`.
- `POST /api/v1/catalog/reconcile/stale-agents/dry-run` `{window_days}` -> `StaleAgentPlan`; `.../confirm` `StaleAgentConfirm` -> `StaleAgentOutcome`.
- `GET /api/v1/catalog/curation/edges/{edge_id}` -> `PresentedEdge`; `.../overrides` -> `{edge_id, overrides}`; `.../observations?page_size&cursor` -> `Page[EdgeObservation]` (`evidence.read`).
- `POST /api/v1/deploy/scan` `ScanRequest` -> `ScanResponse`; `POST /api/v1/deploy/plan` `PlanRequest` -> `{plan, manifest}` (`config.manage`).
- Unchanged: `GET /api/v1/finops/domains/{d}/forecast?history_days&horizon_days&currency`; `GET /api/v1/federation/summary?days&cells`, `/cell-summary?days`; `GET /api/v1/evaluation/domains/{d}/results?subject_id&dimension&cursor&limit`; `GET/PUT /api/v1/actions/emergency-disable` `{disabled, reason}`.

**From Item 2 (`ui_adapters`, new):**
- `GET /api/v1/catalog/domains/{domain}/entities?entity_type&lifecycle&page_size&cursor` -> `Page[CatalogEntity]` (`data.read` on `{domain}`).
- `POST /api/v1/catalog/domains/{domain}/search` `{term, entity_types?, budget}` -> `GraphResult` (`data.read` on `{domain}`; the server sets `filters.domain_ids=[domain]`).
- `GET /api/v1/catalog/domains/{domain}/export?entity_type&lifecycle&page_size&cursor` -> `ExportPage` (`data.export` on `{domain}`).
- `POST /api/v1/catalog/domains/{domain}/curation/edges/{edge_id}/decisions` `{decision: accept|reject|override|lock|unlock, reason, expected_edge_version, expected_edge_etag, lock_expiry?, set_confidence?, set_validity?}`.
  - Responses: 201 `DecisionResult`; 409 `stale_edge`; 403 without `catalog.curate` on the edge's domain; 404 when the edge is not in `{domain}`; 422 on extra fields.
  - The server fills `id`, `edge_id`, `relation_type`, `cloud`, `customer_id`, `domain_id` (from the stored edge), `actor` and `lock.actor` (caller principal, users only), and `decided_at`, then calls `CurationService.decide(..., channel="button")`.
- `GET /api/v1/audit/domains` -> `{items: [{domain_id, display_name, display_name_source}]}`: domains where the caller holds `audit.read`, sorted. 403 when there are none.
- `GET /api/v1/audit/domains/{domain}/records?cursor&page_size` -> `Page[AuditRecord]`; `GET /api/v1/audit/domains/{domain}/verify` -> `ChainVerification`. Both need `audit.read` on `{domain}`, and the chain is `action_audit_chain_id(scope.customer_id, domain)`.
- `GET /api/v1/capabilities?cloud&region` -> `{matrix_version, observed_at, items: [CapabilityMatrixEntry]}` (`data.read` anywhere; static, non-sensitive rows; no customer data).

**Frontend routes (Item 1 registers all; manifest patterns):**
`/catalog`, `/catalog/entity` (`?entity_id=`), `/catalog/edge` (`?edge_id=`), `/catalog/recertifications`, `/catalog/stale-agents`, `/audit` (`?audit_domain=`), `/finops/forecast`, `/federation`, `/deploy`, `/deploy/capabilities`, `/evaluations`, `/admin/execution-control`.

Nav entries (added to `workspaceNav.ts` groups; visibility is a usability aid, never authz):
- **Cost & usage:** "Forecast", "Federation".
- **Agents:** "Catalog".
- **Quality:** "Evaluation results".
- **Governance:** "Recertifications" and "Stale agents" (`permission: catalog.curate`); "Audit log" (`roles: Auditor, Admin`); "Deployment", "Capabilities" and "Execution control" (`permission: config.manage`).

`/catalog/edge` is reached from the entity lineage tab and is not in the nav.

## Implementation blueprint

### Item 1 - integration hookup and placeholders
- Deliverable: everything shared, landed once, so that lanes 3-8 edit only their own folders.
  - Eight feature folders, each with `paths.ts` (API and app paths per the wire contract), `routes.tsx` (`*Routes`, `*NavItems`), a light `index.ts` and a placeholder page that renders `PageTemplate` with the final `<h1>` text: `catalog`, `curation`, `audit`, `finops`, `federation`, `deploy`, `evaluations`, `execution-control`.
  - The routes registered in `appRoutes.ts` (imports from `routes.tsx`, not `index.ts`), nav entries in `workspaceNav.ts`, and the twelve patterns in `route-manifest.json`.
  - Twelve `route-samples.ts` entries (ready selector `main h1`; `/audit` sample uses an auditor fixture).
  - The mock API registry: `frontend/tests/mock-api/features/index.ts` exporting an ordered handler list (curation before catalog). There is one module per feature (`features/<name>.ts`, each a placeholder `handle(ctx): boolean` returning `false`) and a shared `features/context.ts` (`FeatureMockContext` = the copilot context plus `role` and `correlationId`), wired into `createMockApi` with a single dispatch line before the GET-only section.
  - `frontend/src/features/governed-change/ChangeConfirmDialog.tsx` (+ test), unless PRP-30 exports an equivalent (Clarification 11).
- Owned files (may edit): `frontend/src/features/{catalog,curation,audit,finops,federation,deploy,evaluations,execution-control}/{paths.ts,routes.tsx,index.ts,PlaceholderPage.tsx}` (new), `frontend/src/features/governed-change/**` (new), `frontend/src/app/appRoutes.ts`, `frontend/src/app/workspaceNav.ts`, `frontend/src/app/route-manifest.json`, `frontend/tests/e2e/a11y/route-samples.ts`, `frontend/tests/mock-api/server.ts` (one import + one dispatch line + an auditor role fixture if absent), `frontend/tests/mock-api/features/**` (new).
- Must NOT touch: `frontend/src/app/{Shell,navigation,routes,domain}.tsx|ts` (PRP-30 shell), `frontend/src/design-system/**`, existing feature folders, existing specs, `services/**`.
- Depends on: PRP-30 merged (it owns the shell and the shared files until then).
- Acceptance criteria: route-manifest Vitest green; `routes.a11y.spec.ts` "every route has a sample" green; every placeholder page passes axe in the three modes; `pnpm demo` shows the twelve placeholder pages; the shell imports no new `index.ts`; the dialog test covers the target/version/diff/reason display, submit disabled until a reason is given, and focus return.
- Pattern references: `workspaceNav.ts:21-54`; `mcp-admin/{paths,routes,index}.ts`; `server.ts:2051-2055` + `mcpAdmin.ts:60-64,184`; `route-samples.ts:30-147`.
- Tests to write: `frontend/src/features/governed-change/ChangeConfirmDialog.test.tsx`; `frontend/tests/mock-api/features/registry.test.ts` (ordered dispatch; placeholder modules return false).

### Item 2 - UI-facing API adapters  [P]
- Deliverable: the Item 2 endpoints of the wire contract as thin adapters over existing services and repositories (no new storage, no new permission constants), registered by one hook, with `openapi.json` regenerated. Model: **Opus**.
- Owned files (may edit): `services/api/neurosphere_api/ui_adapters/**` (new: `catalog.py`, `curation.py`, `audit.py`, `capabilities.py`, `models.py`, `__init__.py` with `register`), `services/api/neurosphere_api/routers.py` (one `_register_ui_adapters` hook + `REGISTERED` entry), `services/api/openapi.json` (regenerated), `services/api/tests/ui_adapters_api/**` (new).
- Must NOT touch: `services/api/neurosphere_api/{catalog,audit,authz,deploy,actions}/**` (PRP-29/PRP-06; import and call only), `packages/**`, `frontend/**`, `infra/**`.
- Depends on: PRP-29 merged (it edits `routers.py`/`openapi.json` and normalises the paths these adapters sit beside).
- Acceptance criteria:
  - Every route declares its permission to the route inventory (`authz/routes.py`); the inventory test is green.
  - Domain-path routes use `require(..., resource=domain_from_path("domain"))`.
  - Curation adapter: an `extra="forbid"` body; actor stamped from `scope.to_contract().principal` and refused for non-`user` principals; the edge looked up and confirmed to be in `{domain}` (else 404); the 409/403/422 paths tested; `channel="button"` lands in the audit record (test reads it back).
  - Audit adapter: cross-customer and cross-domain 403 tests; an auditor-only scope lists and reads its domains; `verify` returns `ChainVerification` unchanged.
  - Capabilities: rows come from the shipped matrix loader; unverified rows stay `unverified`.
  - Route ordering: no PRP-29 catalog route shadows `/api/v1/catalog/domains/...` (test).
  - The openapi diff is reported (additive or not).
- Pattern references: `me/router.py:33-131`; `finops/router.py:39-80`; `curation/router.py:72-85`; `curation/service.py:128-158`; `authz/audit_mount.py:63-108`; `permissions.py:135-148`; `actions/audit.py:83-89`.
- Tests to write: `services/api/tests/ui_adapters_api/test_catalog_adapters.py`, `test_curation_adapter.py`, `test_audit_adapters.py`, `test_capabilities.py`.

### Item 3 - lane: catalog  [P]
- Deliverable: `/catalog` (search box + entity type/lifecycle filters + paged table + export for `data.export`), `/catalog/entity` (detail, version/ETag, owner + recertify-by, lifecycle; lineage neighbors/impact tables with direction and budget-truncation notice; deprecate and recertify through `ChangeConfirmDialog`), `/catalog/recertifications` (due/overdue queue, domain column), `/catalog/stale-agents` (window -> dry-run candidates -> confirm with the plan echoed; per-item outcomes).
- Owned files (may edit): `frontend/src/features/catalog/**`, `frontend/tests/mock-api/features/catalog.ts`, `frontend/tests/e2e/catalog/catalog.spec.ts` (new).
- Must NOT touch: `frontend/src/app/**`, `frontend/src/design-system/**`, other features (import `governed-change` and `workspaces` `ForbiddenState`, never edit them), `frontend/tests/mock-api/{server.ts,features/index.ts}`.
- Depends on: Items 1 and 2.
- Acceptance criteria:
  - The criteria for Item 3 above.
  - No request carries `domain_id`/`customer_id` (the `ApiClient` guard is never tripped; test).
  - A 409 on deprecate/recertify reloads and explains. Export is hidden without `data.export` in the domain's permissions, and the API's 403 is still handled.
  - Lineage links to `/catalog/edge?edge_id=` and to `/map?domain_id=`.
- Pattern references: `catalog/router.py:150-336`; `catalog/models.py:114-186`; `mcp-admin/McpServerDetailPage.tsx` (If-Match flow); `overview/data.ts` ("N+").
- Tests to write: `frontend/src/features/catalog/catalog.test.tsx`; `frontend/tests/e2e/catalog/catalog.spec.ts` (search -> entity -> recertify confirm -> 409 path; axe).

### Item 4 - lane: relationship curation  [P]
- Deliverable: `/catalog/edge`: presented edge summary (status asserted/inferred/curated, confidence, validity, lock state and expiry, provenance, evidence ids, first/last observed), override history table, observations section (rendered only after a 200; a 403 shows "Observations need evidence access"), and decision controls (accept/reject/override/lock/unlock) through `ChangeConfirmDialog`: reason required, lock/override require expiry in the future, before/after diff of status/lock/confidence.
- Owned files (may edit): `frontend/src/features/curation/**`, `frontend/tests/mock-api/features/curation.ts`, `frontend/tests/e2e/curation/curation.spec.ts` (new).
- Must NOT touch: as Item 3.
- Depends on: Items 1 and 2.
- Acceptance criteria:
  - The criteria for Item 4 above.
  - The decision body contains only the Item 2 fields (test inspects the request).
  - Security evidence ids are displayed and never offered for removal.
  - Controls are hidden without `catalog.curate`, but a forced submit still gets the mock's 403 and shows it.
- Pattern references: `curation/router.py:72-108`; `edge_override.py:49-60`; `curation/service.py:195-250` (error reasons to map to messages).
- Tests to write: `frontend/src/features/curation/curation.test.tsx`; `frontend/tests/e2e/curation/curation.spec.ts` (lock with expiry -> 201; stale -> 409 surfaced; axe).

### Item 5 - lane: audit log  [P]
- Deliverable: `/audit`: own domain picker from `GET /api/v1/audit/domains` (selection in `?audit_domain=`, not `domain_id`, so it never fights the shell switcher), a read-only paged records table (sequence, time, operation, outcome, channel, pseudonymous actor, subject id/version; fields as returned), record detail drawer (`DetailList`), "Verify chain" with the result (valid / break at sequence N), and empty/403/503 (`audit_store_unconfigured`) states.
- Owned files (may edit): `frontend/src/features/audit/**`, `frontend/tests/mock-api/features/audit.ts`, `frontend/tests/e2e/audit/audit.spec.ts` (new).
- Must NOT touch: as Item 3.
- Depends on: Items 1 and 2.
- Acceptance criteria: the criteria for Item 5 above; works for an auditor-only token whose `/me/domains` is 403 (e2e); no export or copy-all control; no client-side join with other APIs.
- Pattern references: `audit/router.py:71-101`; `authz/audit_mount.py:63-94`; `workspaces/ForbiddenState.tsx`.
- Tests to write: `frontend/src/features/audit/audit.test.tsx`; `frontend/tests/e2e/audit/audit.spec.ts` (auditor flow, paging, verify, axe).

### Item 6 - lane: FinOps forecast and federation  [P]
- Deliverable: `/finops/forecast` (history/horizon/currency controls within API bounds, separate estimated and invoiced charts with band and table fallback, method card, unavailable reason, unknown/incomplete badges, price version ids) and `/federation` (window days, cell filter, cell outcome list, per-domain summaries, per-currency totals, `complete`/`truncated` badges).
- Owned files (may edit): `frontend/src/features/finops/**`, `frontend/src/features/federation/**`, `frontend/tests/mock-api/features/{finops,federation}.ts`, `frontend/tests/e2e/finops/finops.spec.ts` (new; covers both pages).
- Must NOT touch: as Item 3; `frontend/src/features/charts/**` and `dashboards/**`.
- Depends on: Item 1.
- Acceptance criteria: the criteria for Item 6 above; the chart has a table alternative and non-colour band indication; no savings or "projected savings" wording (static string test).
- Pattern references: `finops/models.py:54-176`; `federation/models.py:17-39`; `dashboards/components.tsx` (badges).
- Tests to write: `frontend/src/features/finops/finops.test.tsx`, `frontend/src/features/federation/federation.test.tsx`; the e2e spec above.

### Item 7 - lane: deployment intelligence  [P]
- Deliverable: `/deploy`, a three-step workbench:
  1. **Scan:** subscription ids, plus a consent record (id, attestation reference with email-shaped values rejected, consented subscriptions).
  2. **Choices:** per manifest service, reuse/create/skip with resource id/SKU/fallback, plus owner consent records for shared resources.
  3. **Plan:** the items table with checks, cost basis, `shared`/`neurosphere_created` badges and disabled reasons with source links, and a manifest JSON download.

  The scan result is held in memory only (not in `localStorage`). Also `/deploy/capabilities`: a matrix table filtered by cloud/region, with availability, GA status and authorization scope as separate columns.
- Owned files (may edit): `frontend/src/features/deploy/**`, `frontend/tests/mock-api/features/deploy.ts`, `frontend/tests/e2e/deploy/deploy.spec.ts` (new).
- Must NOT touch: as Item 3; `infra/**` (PRP-32).
- Depends on: Items 1 and 2 (capabilities endpoint).
- Acceptance criteria: the criteria for Item 7 above; there is no control that provisions, applies or deletes; a Government profile never offers a Commercial-only option as enabled; `visibility_note` is shown verbatim on every scan result.
- Pattern references: `deploy/scan/models.py:34-80`; `deploy/plan/models.py:85-162`; `capability_matrix_entry.py`.
- Tests to write: `frontend/src/features/deploy/deploy.test.tsx`; `frontend/tests/e2e/deploy/deploy.spec.ts` (scan -> choose -> plan, disabled row, axe).

### Item 8 - lane: evaluation results and execution control  [P]
- Deliverable: `/evaluations` (subject id and dimension filters, cursor paging, result rows with dimension, score/label, judge model, calibration state and uncertainty exactly as returned, links to `/quality` and to recommendation detail where the result references one) and `/admin/execution-control` (current state, reason, pseudonymous `changed_by`, `changed_at`; Disable needs a snake_case reason code; Disable and Enable go through `ChangeConfirmDialog` and then `PUT`; the view refreshes from the response).
- Owned files (may edit): `frontend/src/features/evaluations/**`, `frontend/src/features/execution-control/**`, `frontend/tests/mock-api/features/{evaluations,execution-control}.ts`, `frontend/tests/e2e/admin/evaluations-and-control.spec.ts` (new).
- Must NOT touch: as Item 3; `frontend/src/features/{quality,actions}/**` (link, don't edit).
- Depends on: Item 1.
- Acceptance criteria: the criteria for Item 8 above; the reason pattern is validated client-side and the server's 422 is still shown; the actions page's read-only banner still reflects the toggle (e2e reads `/actions` after disabling).
- Pattern references: `evaluation/router.py:49-66`; `actions/models.py:89-97,163-171`; `actions/hooks.ts:26,49-51`.
- Tests to write: `frontend/src/features/evaluations/evaluations.test.tsx`, `frontend/src/features/execution-control/execution-control.test.tsx`; the e2e spec above.

### Waves
- A = Items 1 and 2 [P]. Item 1 is frontend-only, Item 2 backend-only, so they share no file.
- B = Items 3, 4, 5 and 6 [P] (WIP 4).
- C = Items 7 and 8 [P].

After wave A, each lane owns only its feature folder(s), its `frontend/tests/mock-api/features/<name>.ts` module and its own spec directory. `server.ts`, `features/index.ts`, `appRoutes.ts`, `workspaceNav.ts`, `route-manifest.json`, `route-samples.ts` and `governed-change/**` are frozen after Item 1. If a lane needs a change there, it is a sequenced delta item, never a parallel edit.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
uv run pytest -q services/api/tests/ui_adapters_api services/api/tests/authz services/api/tests/catalog services/api/tests/audit services/api/tests/test_app.py services/api/tests/test_openapi_drift.py
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend exec vitest run
pnpm --filter @neurosphere/frontend build
NS_E2E_APP_PORT=<unique> NS_MOCK_API_PORT=<unique> pnpm --filter @neurosphere/frontend exec playwright test tests/e2e/catalog tests/e2e/curation tests/e2e/audit tests/e2e/finops tests/e2e/deploy tests/e2e/admin tests/e2e/a11y
NS_E2E_APP_PORT=<unique> NS_MOCK_API_PORT=<unique> pnpm --filter @neurosphere/frontend exec playwright test
python scripts/licenses_report.py --check
pnpm demo   # manual: open each of the twelve new pages, confirm data, dialogs and states, then stop it
```
No live gate: this PRP makes no cloud calls and needs no `NS_LIVE_APPROVED`. The deploy scan runs against the mock only.

## Live and open gates
- G09 (accessibility) stays OPEN with PRP-24. Axe at 0 serious/critical on the new pages is necessary, not sufficient; there is no screen-reader evidence.
- Real-API compatibility of every page is proven only by Item 2's API tests and the shared wire contract, not by an end-to-end run against a deployed API. The hosted UI deploy session (memory: App Service, Limitlessdata) is where that is exercised, and it is reported OPEN until then.
- The production `app.state` bootstrap for catalog/audit/federation/scan (#104 and the PRP-18/19 open item) is not addressed here. Against a bare API those pages show their 503 "not configured" state, which is tested.

## NOT building
- Catalog entity create/edit forms and bulk import UI (Clarification 6).
- Any deploy apply/provision/delete control; provisioning stays the IaC pipeline (PRP-08, PRP-32 owns `infra/**`).
- Data lifecycle API and UI (retention, legal hold, deletion, export jobs). These are destructive and policy-bound, so they need a dedicated PRP with Opus and required review. The PRP-23 engine has no API yet.
- An ATO evidence/control-narrative viewer; the PRP-25 docs site publishes those documents.
- Ingestion operations (quarantine, replay, backpressure) and connector health/rate-limit pages; there is no API, so they are a follow-up PRP.
- Revocation, policy and SLA/notification administration; there is no API (PRP-06/PRP-17 follow-ups).
- A PRP-17 action kind for curation, or any executor change.
- Fixing the unchecked `actor` in the existing curation route or server-stamping `consented_by` (reported to PRP-29).
- Changes to the shell, design system, existing features or `ci.yml` (PRP-30 and the existing owners).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (six are flagged to confirm at plan approval)

## Execution state
| Item | Status | Branch / worktree | Model | Evidence | Updated |
|---|---|---|---|---|---|
| 1 | merged | worktree-agent-a8d688440d7d599ad | sonnet | typecheck+lint clean; vitest 75f/928t pass (1 unexplained flaky first run, rerun green); touched 12f/95t pass; a11y e2e 500 pass (agent-reported); merged 3a2bb92 | 2026-10-30 |
| 2 | merged | worktree-agent-ac56db059969aac5d | opus | ruff+pyright clean (agent); 505 pass: ui_adapters_api+authz+path_aliases+catalog+audit+test_app+openapi_drift (me); openapi diff additive (+947/-0); two out-of-ownership test fixes approved; merged e261ad2 | 2026-10-30 |
| 3 | merged | worktree-agent-a692229675b41d7c3 | sonnet | tsc+eslint clean; vitest 4f/37t; e2e catalog 7 pass (me); merged 5a6a08e; reason field collected but not sent (endpoints take none); stale-agent confirm uses own dialog | 2026-10-30 |
| 4 | merged | worktree-agent-aeea7d0e2bb52f6de | sonnet | agent-reported: tsc+eslint clean, vitest 3f/22t, e2e curation 6 pass; merged 602c168. OPEN DEFECT: edge GET has no version/etag, so decisions cannot work on a real API until 2b+4b land | 2026-10-30 |
| 5 | merged | worktree-agent-a124232576995f3f4 | sonnet | tsc+eslint clean; vitest 3f/18t; e2e audit 8 pass (me); merged b158425; openSample ignores persona (a11y matrix opens /audit as Viewer -> ForbiddenState) | 2026-10-30 |
| 6 | merged | worktree-agent-a7e8cc1113c8460f9 | sonnet | tsc+eslint clean; vitest 4f/33t; e2e finops 11 pass (me); merged be391fc; invoiced-chart band dashing not guaranteed | 2026-10-30 |
| 7 | merged | worktree-agent-af7487a07fc25fb8f | sonnet | tsc+eslint clean; vitest 3f/18t; e2e deploy 5 pass (me); no apply control, no browser storage (grep); merged a0317d2 | 2026-10-30 |
| 8 | merged | worktree-agent-ac458121c2dffb894 | sonnet | tsc+eslint clean; vitest 4f/17t; e2e admin 7 pass (me); merged 72af36a | 2026-10-30 |
| 2b | todo | | sonnet | delta approved 2026-10-30: GET /api/v1/catalog/domains/{domain}/curation/edges/{edge_id} -> {edge, edge_version, edge_etag} + ETag header, same domain/permission checks | 2026-10-30 |
| 4b | todo | | sonnet | delta: curation page reads the 2b shape; depends on 2b contract | 2026-10-30 |

Plan delta approved 2026-10-30: `frontend/src/features/catalog/` already exists (catalog publication). Items 1 and 3 extend it in place: append to `paths.ts`/`routes.tsx`, add new files, new test `catalog-explorer.test.tsx`; never edit `CatalogPublicationPage.tsx`, `components.tsx` or `catalog.test.tsx`.

## Completion note (filled at ship)
- Date:
- Merged commits:
- Deviations from blueprint and why:
- Descoped items:
- Follow-ups:
