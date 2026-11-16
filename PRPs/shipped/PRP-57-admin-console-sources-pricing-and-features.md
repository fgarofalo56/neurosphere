---
name: PRP-57-admin-console-sources-pricing-and-features
status: shipped
shipped: 2026-11-16
pr: 313
priority: P0
order: 44
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-01, NS-06, NS-09, NS-10
depends_on: [PRP-41-producer-registry, PRP-42-connector-configuration-and-credential-references, PRP-44-platform-configuration, PRP-45-system-status-first-run-and-feature-settings, PRP-53-admin-console-identity-status-and-audit]
wave: W18
branch: prp-57-admin-console-sources
allow_parallel: true
issues: [250]
---

# PRP-57: Admin console, part 2: data sources, pricing and feature settings

## Goal
Finish the admin console with the pages an operator needs to get real data in and the product configured: ingest producers (generate-once secret shown once, rotate, disable), connector configurations with credential references, gateway registration, catalog import (dry run first), price sheets and budgets, models and feature settings (copilot, judge, search, scan, MCP server, write targets) and the HITL review policy. Every page calls an API shipped in W14-W16 (PRP-41, 42, 44, 45) and the existing gateway and catalog routes; none stores or displays a credential value. It is frontend only, for the deployment administrator, and builds on the PRP-53 shared folder and landing. Controls are usability aids: the API decides access on every request.

Out of scope: identity, domains, system status and audit pages (PRP-53); any backend route, permission or contract (PRP-37/PRP-65, 41, 42, 44, 45); turning a stored write target into a registered connector and more than one target per kind (PRP-54, this PRP only edits the stored entries); hot reload of settings (assumption A1: they apply on restart); live provider runs (PRP-58, PRP-64); the Government and Commercial differences are shown from API responses, not decided in the UI.

## Why
- Producers, connectors, price sheets, budgets, the review policy and the feature settings have no UI and, before W14-W16, no API: `docs/validation/PRODUCT-VALIDATION-2026-11-06.md:25-40` lists each as "cannot do in the product"; lane-d unit F2 scopes this page set.
- Gateway registration is a raw `POST /api/v1/gateways/domains/{domain}/gateways` (`services/api/neurosphere_api/gateway/router.py:205`); `frontend/src/features/gateways/*` has no register control (lane-d step 1, "Gateway registration" row).
- Catalog import has no page: `POST /api/v1/catalog/import` takes at most `MAX_IMPORT_ITEMS = 100` documents with a `dry_run` flag (`services/api/neurosphere_api/catalog/models.py:43,75-79`) and no UI calls it (lane-d step 1, "Catalog entity create / edit").
- Credentials must be references only (assumption A7): the secret is generated once by the API and returned a single time (`ProducerSecretIssued`, PRP-41), so the UI has a show-once obligation that no existing page has.
- The route manifest, the axe samples and the real-stack walk fail any route without an entry (`frontend/tests/e2e/a11y/route-samples.ts:15-17`), so registration is part of the work.

## Acceptance criteria
- [x] Producers (`/admin/sources/producers`): list with status and `rotated_at`; create returns the secret once in a modal with a copy button and an explicit "I stored it" confirm; closing the modal clears it from component state and the query cache, and a reload cannot show it again; rotate repeats the same flow; disable and enable use `ChangeConfirmDialog` and `If-Match`. The secret never appears in a URL, a toast, a console log, a snapshot or a visual baseline.
- [x] Connectors (`/admin/sources/connectors`): create and replace a `ConnectorConfig` for `gateway_poll`, `foundry_discovery`, `billing_export` and `otel` with `domain_ids`, bounded scalar settings and a credential reference; the credential field accepts only a Key Vault secret URI or a managed-identity client id, rejects anything that does not look like a reference before sending (the API stays the authority and its 422 field pointer is shown), and shows `warnings` such as `producer_not_in_store`; enable, disable and retire work; a note explains restart-to-apply and the Key Vault role the operator must grant.
- [x] Gateways (`/admin/gateways`): a register form for `RegisterGatewayBody` (ARM resource id, optional workspace id) per readable domain that posts to the existing route, shows the 201 and links to `/gateways/detail`; a 403, 409 or 422 is shown with its code.
- [x] Catalog import (`/admin/catalog-import`): paste or upload JSON, client-side limit of 100 items, a required dry run that renders per-item `valid | created | rejected | failed | skipped` with codes, then a commit that is enabled only after a clean dry run of the same payload (digest compared); `committed` false after commit lists what was created.
- [x] Pricing (`/admin/pricing`): upload a versioned price sheet (source, retrieval date, cloud applicability, rows) and list versions with the active one marked; budgets list, create and edit per domain with thresholds; amounts are decimal strings, never floats; an unknown price shows unknown, not 0.
- [x] Features (`/admin/features`): one card per stored setting key (`copilot`, `judge`, `search`, `scan`, `mcp_server`, `write_targets`) showing source (`stored | env | default`), revision, `restart_required` and the validation error text on a 422; a save sends `If-Match`, shows the returned diff and the "applies after restart" notice; secret-looking fields are not offered at all (references only); `write_targets` states that registration needs PRP-54 until it ships.
- [x] Review policy (`/admin/review-policy`): edit kind defaults and action overrides (SLA, escalation and expiry in whole seconds shown as hours and minutes), with a preview of the effective policy and the API's validation text.
- [x] Every list has loading, empty, error and forbidden states; a 409 `stale_version` offers reload; no page enables a control the API will refuse by hiding the 403.
- [ ] `frontend/tests/mock-api/features/admin-sources.ts` serves every route above with 403, 409 and 422 fixtures; vitest covers each page; Playwright `frontend/tests/e2e/admin-sources/**` covers create-producer (secret shown once), create-connector, dry-run-then-import, upload-price-sheet and save-setting; the a11y suite has a sample for each new pattern with zero serious or critical violations; Docker-only visual baselines exist.
- [ ] `pnpm --filter @neurosphere/frontend lint`, `typecheck`, `test`, `format`, `test:e2e` pass; `python scripts/validate_planning.py` passes.
- PRP exit: an operator can register a producer, a connector, a gateway and a price sheet, import catalog entities and change a feature setting from the UI on the mock API with no file edit; the same walk against the composed stack is OPEN until PRP-38's real-stack job covers these pages.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Show-once secret handling | Keep in cache; clear on close | Clear on close and on unmount; mutation result is read once (`reset()` after confirm); test asserts the DOM and cache are empty afterwards |
| 2 | Credential input | Free text; typed reference | Typed reference only (Key Vault URI or managed identity client id), A7; the pattern check is a hint, the API validates |
| 3 | Gateway registration location | Extend `/gateways`; new page | New page under admin; `features/gateways/**` belongs to nobody in W18 but is left untouched to avoid a second owner (list and detail stay there) |
| 4 | Import safety | Commit directly; dry run first | Dry run required, commit only for the same payload digest |
| 5 | Settings apply time | Live; restart | ASSUMPTION: A1 restart-required; the page shows PRP-45's `restart_required` and never claims a live change |
| 6 | Write-target editor | Here; PRP-54 | Stored entries only (PRP-45 key `write_targets`); registration is PRP-54, flagged in the UI |
| 7 | Route paths of PRP-44 and PRP-45 settings routes | Assume; read at start | Item 1 reads the shipped completion notes and `services/api/openapi.json` before coding; paths here are UNVERIFIED for PRP-44 |
| 8 | Visual baselines | Rows in `visual.spec.ts` `PAGES`; new spec | ASSUMPTION: append rows to `PAGES` (same as PRP-53); the secret modal is not baselined |

## Context manifest

### Files to read first
- `frontend/src/features/admin/shared/**` and `frontend/src/features/admin/routes.tsx` (from PRP-53) - tabs, `useEtagMutation`, `areas.ts`, strings; reuse, do not fork.
- `frontend/tests/mock-api/features/admin-core.ts` (PRP-53) - fixture style, 403 persona, ETags.
- `frontend/src/features/governed-change/ChangeConfirmDialog.tsx` - confirm dialog for enable, disable, retire, save.
- `frontend/src/features/catalog/{EntityForm.tsx,entityFormModel.ts,hooks.ts}` - a write form with validation and typed errors.
- `frontend/src/features/gateways/{paths.ts,types.ts,hooks.ts}` - the gateway routes and types to reuse.
- `frontend/src/app/{appRoutes.ts,route-manifest.json,workspaceNav.ts}`, `frontend/tests/e2e/a11y/route-samples.ts`, `frontend/tests/e2e/visual/visual.spec.ts` - registries.
- `services/api/neurosphere_api/catalog/models.py:43-102` (`ImportRequest`, `ImportResult`) and `gateway/models.py:14-25` (`RegisterGatewayBody`) - wire shapes.
- Provider PRPs' "Interfaces provided" and completion notes (41, 42, 44, 45) plus `services/api/openapi.json`.

### Interfaces consumed
- PRP-41 (`/api/v1/admin/sources/producers`): `POST` (201, `ProducerSecretIssued`), `GET`, `GET /{producer_id}`, `POST /{producer_id}/rotate|disable|enable`; `ETag` on reads, `If-Match` on mutations; type `ProducerRecord`.
- PRP-42 (`/api/v1/admin/sources/connectors`): `POST`, `GET` (optional `connector_kind`), `GET|PUT /{config_id}`, `POST /{config_id}/enable|disable`, `DELETE /{config_id}`; types `ConnectorConfig`, `CredentialReference`; reason codes `connector_credential_unavailable`, `producer_not_in_store`.
- PRP-44 (platform configuration, `/api/v1/admin/platform/...`): price sheet upload and versions (`PriceSheetUpload`), budgets (`Budget`), review policy (`ReviewPolicyDocument`). Exact paths UNVERIFIED until it ships.
- PRP-45: `GET /api/v1/admin/system/settings`, `GET|PUT /api/v1/admin/system/settings/{key}` for the six keys; type `SystemSetting`.
- Existing: `POST|GET /api/v1/gateways/domains/{domain}/gateways`; `POST /api/v1/catalog/import`; `GET /api/v1/me/domains` for the domain pickers.
- PRP-53: `admin/shared`, `ADMIN_AREAS`, fixture ids.

### Interfaces provided
- Routes in `route-manifest.json`: `/admin/sources/producers`, `/admin/sources/connectors`, `/admin/gateways`, `/admin/catalog-import`, `/admin/pricing`, `/admin/features`, `/admin/review-policy`.
- `adminSourcesRoutes` and `adminSourcesNavItems()` in `frontend/src/features/admin/sources/routes.tsx` (light module); the other folders export their own routes through it.
- Mock module `frontend/tests/mock-api/features/admin-sources.ts` with fixture ids for later specs (PRP-64 operator walk-throughs, PRP-63 smoke).

### Patterns to match
- `frontend/src/features/catalog/catalog-write.test.tsx` (form and dialog tests), `frontend/src/features/mcp-admin/hooks.ts:25-60` (mutation hooks).
- `frontend/src/features/execution-control/ExecutionControlPage.tsx` (an admin write with a typed error and a confirm).
- `frontend/tests/e2e/admin/evaluations-and-control.spec.ts` (admin e2e on the mock API); `frontend/tests/mock-api/features/audit.ts` (mock style).

### Gotchas
- A secret held in React Query cache survives navigation: use a local mutation with `reset()`, and keep `gcTime: 0` for that mutation.
- axe: the show-once modal needs a focus trap, a labelled copy button and an `aria-live` announcement; Fluent dialog tests need `hidden: true` queries.
- Import payloads can contain arbitrary strings: render them as text, never as HTML; cap the preview.
- `docs/validation` names `config.manage` customer-level for producers and connectors but a deployment-scoped role for system settings (PRP-45); a user can hold one and not the other, so each page handles its own 403.
- Dates and money: decimal strings from the API are shown as received, formatted without float conversion.
- Visual baselines are Docker-only; unique `NS_E2E_APP_PORT`/`NS_MOCK_API_PORT`.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - frontend/src/features/admin/sources/**
  - frontend/src/features/admin/gateways/**
  - frontend/src/features/admin/catalog-import/**
  - frontend/src/features/admin/pricing/**
  - frontend/src/features/admin/features/**
  - frontend/src/features/admin/review-policy/**
  - frontend/tests/mock-api/features/admin-sources.ts
  - frontend/tests/e2e/admin-sources/**
tier1: []
tier2_appends:
  - frontend/src/features/admin/shared/areas.ts
  - frontend/src/app/appRoutes.ts
  - frontend/src/app/route-manifest.json
  - frontend/src/app/workspaceNav.ts
  - frontend/tests/mock-api/features/index.ts
  - frontend/tests/e2e/a11y/route-samples.ts
  - frontend/tests/real-stack/routes.spec.ts
  - frontend/tests/e2e/visual/visual.spec.ts
  - services/api/tests/runtime_routes/manifest_calls.py
  - tests/integration/real_stack/test_manifest_routes.py
must_not_touch:
  - services/api/neurosphere_api/**
  - packages/**
  - frontend/src/features/admin/identity/**
  - frontend/src/features/admin/domains/**
  - frontend/src/features/admin/system/**
  - frontend/src/features/admin/audit/**
  - frontend/src/features/gateways/**
  - frontend/src/features/catalog/**
  - frontend/tests/mock-api/server.ts
```

## Implementation blueprint

Parallelization map: item 1 first (mock handlers and path discovery); items 2-6 are independent pages in separate folders [P]; item 7 registers and owns e2e, a11y and visual; item 8 closes out.

### Item 1 - Path discovery and mock handlers
- Deliverable: a short `frontend/src/features/admin/sources/apiPaths.ts` listing every route above with its source PRP (paths read from the shipped notes and `openapi.json`, discrepancies reported); `admin-sources.ts` serving all routes with ETags, a show-once producer secret (synthetic), 403/409/422 fixtures, a 100-item import with mixed outcomes, a price sheet with two versions; list entry in `index.ts`.
- Owned files: `frontend/src/features/admin/sources/apiPaths.ts`, `frontend/tests/mock-api/features/admin-sources.ts`, `frontend/tests/mock-api/features/index.ts` (append).
- Must NOT touch: `server.ts`, `admin-core.ts`.
- Depends on: none (PRP-53 shipped).
- Acceptance criteria: each handler answers its method and path and passes on others; the secret appears in exactly one response body.
- Tests: `frontend/tests/mock-api/features/registry.test.ts`, `frontend/tests/mock-api/features/admin-sources.test.ts` (new).
- Pattern references: `tests/mock-api/features/admin-core.ts`, `audit.ts`.

### Item 2 - Producers and connectors  [P]
- Deliverable: `ProducersPage` (show-once flow), `ConnectorsPage` with a per-kind form, `CredentialReferenceField`, hooks, types.
- Owned files: `frontend/src/features/admin/sources/**` (except `apiPaths.ts`, item 1).
- Must NOT touch: other admin folders.
- Depends on: item 1.
- Acceptance criteria: producers and connectors criteria; the secret-cleared test; a value pasted into the credential field is blocked client-side and, if sent anyway in a test, the 422 is rendered.
- Tests: `frontend/src/features/admin/sources/sources.test.tsx` (new).
- Pattern references: `catalog/EntityForm.tsx`, `mcp-admin/McpServersPage.tsx`.

### Item 3 - Gateway registration and catalog import  [P]
- Deliverable: `RegisterGatewayPage`, `CatalogImportPage` with dry-run digest gate and results table.
- Owned files: `frontend/src/features/admin/gateways/**`, `frontend/src/features/admin/catalog-import/**`.
- Must NOT touch: `features/gateways/**`, `features/catalog/**`.
- Depends on: item 1.
- Acceptance criteria: gateway and import criteria; import over 100 items is blocked client-side with the limit stated.
- Tests: `frontend/src/features/admin/gateways/gateways-admin.test.tsx`, `frontend/src/features/admin/catalog-import/import.test.tsx` (new).
- Pattern references: `gateways/GatewayModePanel.tsx` (a gateway write), `catalog/catalog-write.test.tsx`.

### Item 4 - Pricing and budgets  [P]
- Deliverable: `PriceSheetsPage` (upload, versions), `BudgetsPage`, shared decimal-string helpers.
- Owned files: `frontend/src/features/admin/pricing/**`.
- Must NOT touch: other admin folders, `finops`.
- Depends on: item 1.
- Acceptance criteria: pricing criterion; a malformed row shows the API's field pointer; no float conversion (test with `0.1 + 0.2` style values).
- Tests: `frontend/src/features/admin/pricing/pricing.test.tsx` (new).
- Pattern references: `finops/ForecastPage.tsx`.

### Item 5 - Models and feature settings  [P]
- Deliverable: `FeatureSettingsPage` with one card and one form per key, diff on save, restart notice.
- Owned files: `frontend/src/features/admin/features/**`.
- Must NOT touch: `admin/system/**` (PRP-53 shows the read-only summary).
- Depends on: item 1.
- Acceptance criteria: features criterion; no secret-looking field is rendered for any key; a 422 shows the validator text.
- Tests: `frontend/src/features/admin/features/features.test.tsx` (new).
- Pattern references: `execution-control/ExecutionControlPage.tsx`.

### Item 6 - Review policy  [P]
- Deliverable: `ReviewPolicyPage` with per-kind and per-action rows, duration inputs, effective-policy preview.
- Owned files: `frontend/src/features/admin/review-policy/**`.
- Must NOT touch: `features/review/**`.
- Depends on: item 1.
- Acceptance criteria: review-policy criterion; durations round-trip as whole seconds.
- Tests: `frontend/src/features/admin/review-policy/review-policy.test.tsx` (new).
- Pattern references: `review/` list pages for the HITL vocabulary.

### Item 7 - Registration, e2e, a11y and visual
- Deliverable: Tier-2 lines (appRoutes, manifest, nav, `areas.ts`, route samples, real-stack rows, `manifest_calls.py` rows), Playwright specs, visual rows and Docker-generated baselines.
- Owned files: `frontend/tests/e2e/admin-sources/**` and the Tier-2 appends listed.
- Must NOT touch: existing registry lines.
- Depends on: items 2-6.
- Acceptance criteria: manifest, axe and keyboard suites pass; e2e covers the five flows named in the criteria; visual check passes in Docker.
- Tests: `frontend/tests/e2e/admin-sources/producers.spec.ts`, `connectors.spec.ts`, `import.spec.ts`, `pricing.spec.ts`, `features.spec.ts` (new).
- Pattern references: `tests/e2e/admin/evaluations-and-control.spec.ts`.

### Item 8 - Integration and close-out
- Deliverable: rebase, `python scripts/prp_status.py --write`, `PRPs/INDEX.md`, CHANGELOG, completion note including the operator product check and the list of paths that differed from this PRP.
- Owned files: this PRP file, `CHANGELOG.md`.
- Depends on: item 7.

## Validation gates
```bash
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
pnpm --filter @neurosphere/frontend format
NS_E2E_APP_PORT=5281 NS_MOCK_API_PORT=5282 pnpm --filter @neurosphere/frontend test:e2e
uv run pytest -q services/api/tests/runtime_routes tests/docs
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Visual baselines: `pnpm --filter @neurosphere/frontend visual:update` in the pinned Docker image, then `visual:check`.

## Migration and rollback
No migration: the pages call existing APIs. Revert the PR to remove the routes, nav entries and `areas.ts` lines together. A deployment missing a provider route shows that page's error state only.

## Live and open gates
No live gate in this PRP. The composed-stack walk (real producer and connector creation against the emulators) is OPEN until PRP-38's real-stack job covers these pages; hosted verification belongs to PRP-58 and PRP-64 (operator).

## NOT building
Backend routes, contracts or permissions; identity, domain, status and audit pages (PRP-53); write-target registration and multi-target UI (PRP-54); live reload of settings; alert delivery for budgets; evaluation suites and judge dataset editing; lifecycle holds; branding editor; any control that stores or displays a credential value.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (rows 5 and 8 are flagged ASSUMPTIONS; PRP-44 paths are confirmed in item 1)

## Execution state

| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | done | prp-57-admin-console-sources | done on branch, PR pending |
| 2 | done | prp-57-admin-console-sources | done on branch, PR pending |
| 3 | done | prp-57-admin-console-sources | done on branch, PR pending |
| 4 | done | prp-57-admin-console-sources | done on branch, PR pending |
| 5 | done | prp-57-admin-console-sources | done on branch, PR pending |
| 6 | done | prp-57-admin-console-sources | done on branch, PR pending |
| 7 | done | prp-57-admin-console-sources | e2e, a11y, real-stack rows done; visual baselines generated in Docker |
| 8 | done | land-prp-57 | close-out on PR 313 |

## Completion note (filled at ship)
- Date, PR number, merge commit: 2026-11-16, PR 313 (squash merge commit is the PR's merge commit on main).
- Deviations: item 8 asked for a `CHANGELOG.md` entry; the current convention is the fragment `changelog.d/PRP-57-admin-console-sources-pricing-and-features.md`, which was written instead. The integrator worked from branch `land-prp-57` and pushed to `prp-57-admin-console-sources` because another worktree held the branch name. No openapi.json or docs/reference regeneration was needed (frontend only, no API or SDK change).
- Descoped items: none. No `[serial-after]` items exist in this PRP. The "Models" half of the features criterion is covered only by the copilot and judge endpoint cards; no model catalog or model-swap UI is in this PRP.
- OPEN gates: the composed-stack (real-stack) walk of these pages is OPEN until PRP-38's real-stack job covers them; hosted verification belongs to PRP-58 and PRP-64. The e2e, a11y and visual acceptance boxes are left unticked here and rest on the PR's CI shards (frontend-e2e); local close-out ran lint, typecheck, vitest (1219 passed) and prettier only.
- Env vars for the operator: none new.
- Follow-up issues filed: none filed by the integrator. Reviewer follow-ups: the review was a partial read of the roughly 6,700-line diff (pricing, review-policy, gateway-register and mock-API code were not read, no tests were run by the reviewer). The import digest in `importPayload.ts` is a non-cryptographic cyrb53 hash; it only compares what the same operator pasted so it is acceptable, and SubtleCrypto SHA-256 would be a cheap hardening step. Price sheet versions have no `active` flag in the API: `apiPaths.ts` documents that the UI marks the newest effective date as active, and that rule should be confirmed against the backend semantics.
- Operator product check (can an operator use this without editing files or calling raw APIs?): yes on the mock API for producers, connectors, gateway registration, catalog import, price sheets, feature settings and review policy; against the composed stack it is unverified (OPEN above).
