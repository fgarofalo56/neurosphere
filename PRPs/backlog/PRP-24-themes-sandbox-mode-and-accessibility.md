---
name: prp-24-themes-sandbox-mode-and-accessibility
status: backlog
review: none
created: 2026-10-08
model: sonnet
phase: 5
ns: NS-10
depends_on: PRP-03, PRP-04, PRP-18, PRP-19
wave: W8
absorbs: P5.2, G09
---

# PRP-24: Themes, sandbox mode and accessibility

## Goal
Ship agency theme packs with logo slots, a UI sandbox mode with an isolation banner, and an accessibility audit (automated axe across all routes plus recorded human keyboard and screen-reader checks). It is for agency adopters who must brand the product, for evaluators who need a safe synthetic dataset, and for the accessibility and legal reviewers who own gate G09. It lands in W8 because it audits routes built by PRP-04, PRP-18 and PRP-19 and consumes the sandbox generator from PRP-03.

> React/TypeScript with Fluent-inspired default, agency theme tokens/logos, light/dark/high-contrast and role workspaces. WCAG 2.2 AA plus Section 508 testing; no implied Microsoft product affiliation or unapproved brand/badge usage. Theme is presentation, never permission enforcement.

> Real connectors require credentials, consent and applicable licensing; synthetic mode is isolated and available without external credentials.

## Acceptance criteria
- [ ] Item 1: Given any theme pack is selected, When the UI issues API calls, Then the request set, headers and responses are identical to the default theme (recorded-request comparison test); a theme cannot add, remove or alter a permission, role or route guard.
- [ ] Item 1: Theme packs pass contrast checks in light, dark and high-contrast; a logo slot rejects files that are not on the documented type and size allowlist; no theme ships a Microsoft logo or badge.
- [ ] Item 2: Given sandbox mode is on, When any sandbox route is called, Then it reads and writes only sandbox containers; a test that points the sandbox repository at a non-sandbox container name fails closed.
- [ ] Item 2: The isolation banner is visible on every page while sandbox mode is on and is exposed to assistive technology (role and accessible name asserted).
- [ ] Item 3: axe runs across every registered route in light, dark and high-contrast with zero serious or critical issues.
- [ ] Item 3: `docs/accessibility/` holds a keyboard checklist and a screen-reader checklist, each signed with tester, date, assistive technology and version, and any failures logged with a remediation owner.
- [ ] PRP exit: items 1-3 green under `verify-gates -Mode full`; G09 remains OPEN until Product plus legal/accessibility review the evidence (this PRP supplies the 508/WCAG evidence, not the brand or media approvals).

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required; opus | sonnet, review none (D6) |
| 2 | Live gates | run in CI; operator-approved only | Anything live or paid is operator-approved with `NS_LIVE_APPROVED=1` (D7); CI makes no paid calls and no cloud deployments |
| 3 | Government | claim parity; gate | Gated, not banned. No FedRAMP, ATO or parity claim in any artifact this PRP produces |
| 4 | Is theming a security control | yes; no | No (NS-10). Theme is presentation only. Authorization stays at the API; hidden or restyled navigation never grants or removes access |
| 5 | Accessibility standard | WCAG 2.1 AA; WCAG 2.2 AA plus Section 508 | WCAG 2.2 AA plus Section 508 per NS-10. Automated axe is necessary but not sufficient; human keyboard and screen-reader checks are recorded in `docs/accessibility/` |
| 6 | Who signs the manual checklist | agent; human | A human tester. An agent may prepare the checklist template and run axe, but never signs it. Unsigned means G09 evidence is incomplete |
| 7 | Sandbox data source | live subset; synthetic only | Synthetic only, from the PRP-03 generator. Real ingestion is a separate, authorized path and is unreachable from sandbox mode |
| 8 | Sandbox isolation mechanism | UI flag only; server-enforced | Server-enforced: the sandbox router binds to sandbox-named containers only; the UI toggle selects a route family, it is not the control |
| 9 | Brand assets | bundle Microsoft or Fluent marks; neutral defaults | Neutral defaults. Fluent is a component library, not an endorsement; no Microsoft product affiliation, badge or logo is implied. Agency logos are supplied by the adopter |
| 10 | Persisting theme choice | server; local storage | Local storage per browser plus a deployment-level default in config. No server-side per-user theme store in this PRP |
| 11 | Screen-reader matrix | one reader; several | At least one Windows screen reader and one other (for example NVDA and VoiceOver); exact versions recorded at test time, not assumed here |

## Context manifest

### Files that matter
- `PRP.md` - sections 1-3 (binding preamble).
- `docs/PRD.md` - NS-10 text (line 45 onward).
- `docs/ARCHITECTURE.md`, `docs/RESEARCH-AND-GATES.md` (G09 row), `docs/DECISIONS-LOG.md` (D6, D7, D10), `docs/adr/0002-stack-pins.md`.
- `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.claude/hooks/config.ps1`, `.env.example`, `scripts/validate_planning.py`.
- Created by PRP-03: `sandbox/` synthetic generator and `scripts/sandbox/` seed CLI; `docs/dev/local-setup.md`.
- Created by PRP-04: `frontend/src/design-system/` (Fluent provider, token layer, three themes), `frontend/src/features/workspaces/`, `frontend/tests/` (Vitest, Testing Library, Playwright, axe harness), `frontend/playwright.config.ts`.
- Created by PRP-05: `neurosphere_core.errors`, `neurosphere_core.scope`, router registry, `.../clients/`.
- Created by PRP-06: `neurosphere_api.authz` (`require(permission)`), consumed by the sandbox router.
- Created by PRP-18: `frontend/src/features/map/`, `frontend/src/features/map-table/`, `frontend/src/features/replay/` (routes to audit).
- Created by PRP-19: `frontend/src/features/copilot/`, `frontend/src/features/charts/`, `frontend/src/features/reports/` (routes to audit, including the sandboxed chart iframe).

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`; generated contract code is never hand-edited.
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py`.
- Async Azure SDK clients come from `packages/core/neurosphere_core/clients`; errors are the exceptions in `neurosphere_core.errors`.
- Tests sit beside packages; cross-package suites live in `tests/`; markers `pytest.mark.live` and `pytest.mark.integration` are declared in root `pyproject.toml`.
- TypeScript strict with `@fluentui/react-components`; Vitest + Testing Library for unit tests; Playwright under `frontend/tests/e2e`.
- Theme packs are data (typed token objects plus logo slot metadata), layered on the PRP-04 token layer; no component reads a theme to make an access decision.
- The sandbox router is a normal FastAPI module (`neurosphere_api/sandbox/router.py`) using `require(permission)` and a repository constructed with a fixed sandbox container allowlist.

### Conventions
- ruff line 100, py312, S rules on (root `pyproject.toml`); pyright standard; conventional commits; owned-file discipline (an item edits only its declared files).
- Evidence under `docs/evidence/<gate>/`; live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1`.
- Forward slashes only in commands. No em-dashes in docs. Temp files go in `temp/` (gitignored).
- Accessibility evidence under `docs/accessibility/`; axe results exported as JSON from CI, manual results as dated Markdown.

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
- PRP-specific: theme is presentation. A theme pack must not import the API client, auth module or any permission helper (lint boundary test); NS-10 forbids using theme as enforcement.
- PRP-specific: sandbox isolation is enforced server-side by a container allowlist, not by the UI toggle. A client that sends a sandbox flag on a non-sandbox route must still hit real-data authorization.
- PRP-specific: axe catches only a minority of WCAG failures. A green axe run is not an accessibility claim; the signed human checklist is the evidence G09 needs.
- PRP-specific: do not claim Section 508 conformance or publish a VPAT. This PRP produces test evidence; conformance statements need the G09 review.
- PRP-specific: the map is WebGL; the accessible alternative is the PRP-18 table view. Audit both and the reduced-motion path.
- PRP-specific: no Microsoft logo, "powered by" badge or partner mark in themes, banner or docs.

### External references
- WCAG 2.2: https://www.w3.org/TR/WCAG22/ (W3C Recommendation).
- Section 508 standards: https://www.section508.gov/ (confirm current text at execution).
- axe-core rules: https://github.com/dequelabs/axe-core and `@axe-core/playwright` (version pinned at execution, recorded in the `docs/adr/0002-stack-pins.md` appendix by PRP-00).
- Fluent UI React v9 theming and high contrast: https://react.fluentui.dev/ (pinned in docs/adr/0002-stack-pins.md, observed 2026-10-08).
- Gate register: docs/RESEARCH-AND-GATES.md, row G09 (OPEN).

## Implementation blueprint

### Item 1 - agency-theme-tokens  [P]
- Deliverable: agency theme packs (token overrides for light, dark, high-contrast) and logo slots (header, login, report footer) with a type and size allowlist; a documented theme-pack schema; a sample neutral agency pack.
- Owned files (may edit): `frontend/src/design-system/themes/`.
- Must NOT touch: `frontend/src/design-system/` outside `themes/` (PRP-04), `frontend/src/features/sandbox/`, `services/api/neurosphere_api/sandbox/`, `tests/e2e/a11y/`, `docs/accessibility/`, root `pyproject.toml`, `docker-compose.yml`, `docs/RESEARCH-AND-GATES.md`.
- Depends on: none.
- Acceptance criteria:
  - Recorded API request set is identical across default and agency theme (test); no theme module imports `frontend/src/api/` or `frontend/src/auth/` (lint boundary).
  - Every shipped theme meets contrast tokens in all three modes (axe color-contrast on a theme gallery page).
  - A logo file outside the allowlist is rejected with a typed error.
- Pattern references: PRP-04 token layer and Fluent provider; Vitest + Testing Library.
- Tests to write: `frontend/src/design-system/themes/themes.test.ts`, `frontend/src/design-system/themes/no-api-import.test.ts`.

### Item 2 - sandbox-mode  [P]
- Deliverable: UI toggle for sandbox mode with a persistent isolation banner, and a sandbox API module that serves only synthetic data from sandbox containers.
- Owned files (may edit): `frontend/src/features/sandbox/`, `services/api/neurosphere_api/sandbox/`.
- Must NOT touch: `frontend/src/design-system/` (item 1 and PRP-04), `sandbox/` generator (PRP-03), `scripts/sandbox/` (PRP-03), `packages/core/neurosphere_core/clients/` (PRP-05), `tests/e2e/a11y/`, root `pyproject.toml`, `docker-compose.yml`.
- Depends on: none.
- Acceptance criteria:
  - The sandbox repository refuses any container name outside the sandbox allowlist (unit test, plus an integration test against the Cosmos emulator that a non-sandbox container is unreachable).
  - Banner present and announced on every route while sandbox mode is on; absent when off.
  - Sandbox routes use `require(permission)`; a caller without the permission gets 403 and a missing policy store gets 503.
  - Sandbox mode works with no external credentials and no network egress.
- Pattern references: FastAPI router per module; `neurosphere_api.authz`; PRP-03 seed output.
- Tests to write: `services/api/tests/sandbox/test_sandbox_isolation.py`, `tests/integration/sandbox/test_sandbox_containers.py`, `frontend/src/features/sandbox/sandbox.test.tsx`.

### Item 3 - wcag-audit  [P]
- Deliverable: axe CI suite across every registered route in three modes, plus a manual keyboard and screen-reader checklist with signed results and a remediation log.
- Owned files (may edit): `tests/e2e/a11y/`, `docs/accessibility/`.
- Must NOT touch: `frontend/src/` (component fixes are filed as defects against the owning PRP, not edited here), `frontend/playwright.config.ts` (PRP-04), `services/api/neurosphere_api/sandbox/`, `docs/RESEARCH-AND-GATES.md`, root `pyproject.toml`.
- Depends on: none (routes from PRP-04/18/19 are already merged by W8).
- Acceptance criteria:
  - Route list is derived from the router registry, not hand-maintained; a new route without an axe test fails the suite.
  - Zero serious or critical axe violations across light, dark and high-contrast; minor issues are listed in the remediation log with owner.
  - `docs/accessibility/keyboard-checklist.md` and `docs/accessibility/screen-reader-checklist.md` exist with tester, date, technology and version filled by a human; unsigned sections are marked OPEN.
  - The accessible map table view and the sandboxed chart iframe are explicitly covered.
- Pattern references: PRP-04 Playwright + axe harness; PRP-18 table view.
- Tests to write: `tests/e2e/a11y/routes.a11y.spec.ts`, `tests/e2e/a11y/themes.a11y.spec.ts`.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
pnpm --filter frontend test
pnpm --filter frontend exec playwright test tests/e2e/a11y
docker compose up -d --wait
python -m pytest services/api/tests/sandbox
python -m pytest -m integration tests/integration/sandbox
```
There is no live script in this PRP. Human checklist signing is an operator step recorded in `docs/accessibility/`.

## Live and open gates
- G09 (theme/brand/media review): this PRP supplies the 508/WCAG test evidence only. G09 stays OPEN until Product plus legal/accessibility approve brand claims and the human checklists, and until PRP-26 and PRP-27 supply the rendered deck and video.
- Any unsigned manual checklist section is OPEN and listed in the completion note.
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Brand claims approval, VPAT or conformance statements (G09 reviewers own them).
- Deck, scripts, storyboard (PRP-26) and video render (PRP-27).
- Docs site and public assistant (PRP-25).
- Server-side per-user theme storage; localization beyond token readiness.
- Real-data ingestion paths or any bridge between sandbox and non-sandbox data.
- Fixes to component accessibility defects in other PRPs' files (file them against the owner).

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
- axe results (routes x modes) and manual checklist sign-off status:
- G09 status after this PRP (expected OPEN):
- Follow-ups:
