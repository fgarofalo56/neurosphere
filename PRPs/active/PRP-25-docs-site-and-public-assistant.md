---
name: prp-25-docs-site-and-public-assistant
status: backlog
review: none
created: 2026-10-08
model: sonnet
phase: 5
ns: NS-10
depends_on: PRP-09, PRP-13, PRP-22
wave: W9
absorbs: P5.1
---

# PRP-25: Docs site and public assistant

## Goal
Ship the branded static documentation site (with Pages deployment), generated API/SDK/MCP references, install/migration/ops/DR/security runbooks with persona walkthroughs, and a separate public docs assistant. It is for adopters, operators and evaluators who need to install and run NeuroSphere from documentation alone. It lands in W9 because the references need the connector SDK (PRP-09), release and image conventions (PRP-13) and the MCP surface (PRP-22). The site tool decision is time-sensitive: MkDocs Material 9.7 is scheduled EOL 2026-11-05.

> Branded static documentation/Pages site, API/SDK references, ADRs, setup/migration/security/operations/DR runbooks, walkthroughs and synthetic sandbox. Public docs assistant uses a separate rate-limited read-only backend and published docs only; never production credentials/data. GitHub Pages cannot host its own dynamic secret-bearing backend.

## Acceptance criteria
- [ ] Item 1: `docs/adr/0008-docs-site-tool.md` records the choice between MkDocs Material 9.7 and Zensical (MIT, same authors) with criteria, evidence and date before any site configuration is committed; the site builds with the chosen tool and the link check passes.
- [ ] Item 1: Given a push to the default branch, When the docs workflow runs, Then the site deploys to Pages from a build that contains no secrets and no `|| true`.
- [ ] Item 2: API reference is generated from the committed OpenAPI JSON (PRP-05 export); connector SDK and MCP tool references are generated or extracted from source; regeneration produces no diff in CI.
- [ ] Item 3: Given a new user with only the published docs, When they follow the install runbook on a clean machine, Then they reach a healthy compose stack (or documented deploy) with no undocumented step; the test is recorded with tester, date and deviations.
- [ ] Item 3: Runbooks exist for install, migration, operations, DR and security, plus one walkthrough per persona (Viewer, Analyst, Steward, Admin, Auditor) tied to sandbox data.
- [ ] Item 4: The assistant answers only from published docs, is rate limited (429 `rate_limited` beyond the limit), exposes no write path, and no production configuration or secret is reachable from its process or image.
- [ ] PRP exit: items 1-4 green under `verify-gates -Mode full`; the new-user test is recorded; the Pages workflow has run at least once on a branch preview or the first deploy is listed OPEN.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|---|---|---|
| 1 | Model and review | sonnet/none; sonnet/required; opus | sonnet, review none (D6) |
| 2 | Live gates | run in CI; operator-approved only | Anything live or paid is operator-approved with `NS_LIVE_APPROVED=1` (D7); CI makes no paid calls and no cloud deployments |
| 3 | Government | claim parity; gate | Gated, not banned. No FedRAMP, ATO or parity claim in any artifact this PRP produces |
| 4 | Docs tool | MkDocs Material 9.7; Zensical; both | Decided by the item 1 ADR before building. MkDocs Material 9.7 EOL is 2026-11-05 (stack pins); Zensical is MIT by the same authors. Recommendation: choose on measured migration cost (nav, search, admonitions, SVG diagram support) and record it; do not pick by default |
| 5 | Mermaid in docs | render in browser; pre-rendered SVG | Use the pre-rendered SVGs in `docs/diagrams/` (PRP-00 item 3, G10 closed). Do not depend on client-side mermaid for correctness |
| 6 | Where the public assistant runs | GitHub Pages; same backend as the product; separate service | Separate service (`services/docs-assistant/`). GitHub Pages cannot host a secret-bearing backend (NS-10); the assistant never shares the product API, database or credentials |
| 7 | Assistant corpus | whole repo; published docs only | Published docs only (the built site content). Not source, not `docs/evidence/`, not `.env*`, not anything under a path that is not published |
| 8 | Assistant model | any; approved endpoint | Provider and model chosen by the operator at execution; no paid calls in CI (tests use a stub). Responses cite the source page; the assistant abstains when no page supports an answer |
| 9 | Rate limiting | none; per-IP; per-key | Per-client limit enforced in the service with a documented default; the exact numbers are configuration, tested by a rate-limit test, and are not performance claims |
| 10 | Abuse and injection | trust corpus; treat as untrusted | Corpus text is untrusted input. The assistant has no tools, no network egress beyond its model endpoint, and no ability to act on the product |
| 11 | Reference generation | hand-written; generated | Generated from the committed OpenAPI, SDK sources and MCP registry so references cannot drift |
| 12 | Runbook validation | author review; new-user test | New-user test required (item 3 AC); an author walking their own steps does not count |

## Context manifest

### Files that matter
- `PRP.md` - sections 1-3 (binding preamble).
- `docs/PRD.md` - NS-10 text (line 45 onward).
- `docs/ARCHITECTURE.md`, `docs/RESEARCH-AND-GATES.md` (G09 row, toolchain support line), `docs/DECISIONS-LOG.md` (D6, D7, D10), `docs/adr/0002-stack-pins.md` (MkDocs Material row).
- `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.claude/hooks/config.ps1`, `.env.example`, `scripts/validate_planning.py`.
- `docs/diagrams/` - five rendered SVGs (G10 closed 2026-10-08); `docs/adr/` - ADR index source.
- Created by PRP-00: `scripts/render_mermaid.py`, `docs/licenses.md`, CI link/diagram checks, `CONTRIBUTING.md` quick start.
- Created by PRP-03: `docs/dev/local-setup.md`, `sandbox/`, `scripts/sandbox/`.
- Created by PRP-05: committed OpenAPI JSON from the app factory; `docs/ops/slo.md`.
- Created by PRP-09: `connectors/sdk-python/`, `connectors/sdk-ts/`, `docs/connectors/coverage.md`.
- Created by PRP-13: `docs/release/`, `CHANGELOG.md`, Dockerfiles, `.github/workflows/release.yml`.
- Created by PRP-22: MCP server/client tool registry under `services/api/neurosphere_api/mcp/`.
- Other runbook inputs if present by W9: `docs/security/runbooks/` (PRP-12), `docs/ops/dr-runbook.md` (PRP-21), `docs/compliance/` (PRP-23). Link to them; do not copy or edit.

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")`; generated contract code is never hand-edited.
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py`.
- Async Azure SDK clients come from `packages/core/neurosphere_core/clients`; errors are the exceptions in `neurosphere_core.errors`.
- Tests sit beside packages; cross-package suites live in `tests/`; markers `pytest.mark.live` and `pytest.mark.integration` are declared in root `pyproject.toml`.
- TypeScript strict with `@fluentui/react-components`; Vitest + Testing Library for unit tests; Playwright under `frontend/tests/e2e`.
- The assistant is an independent FastAPI service with its own `pyproject.toml`, Dockerfile and configuration surface; it imports nothing from `neurosphere_api`.
- Docs references are produced by scripts checked into the owning item, with CI regeneration-diff checks (same pattern as PRP-01 codegen drift).

### Conventions
- ruff line 100, py312, S rules on (root `pyproject.toml`); pyright standard; conventional commits; owned-file discipline (an item edits only its declared files).
- Evidence under `docs/evidence/<gate>/`; live scripts under `scripts/gates/` refuse without `NS_LIVE_APPROVED=1`.
- Forward slashes only in commands. No em-dashes in docs. Temp files go in `temp/` (gitignored).
- Docs are Markdown with relative links; the link check runs in CI; no `|| true`. Reference pages carry the source commit and generation date.

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
- PRP-specific: MkDocs Material 9.7 reaches EOL 2026-11-05. Item 1 starts with the ADR; do not commit site configuration for either tool before the ADR exists. Insiders were merged into 9.7, so no Insiders-only feature assumptions.
- PRP-specific: GitHub Pages is static. The public assistant cannot live there, and the site must not embed any key, token or backend URL that carries privilege (NS-10).
- PRP-specific: the assistant reads published docs only. Build its index from the built site artifact, never from the repository tree, so unpublished or sensitive paths cannot leak.
- PRP-specific: docs must not claim FedRAMP, ATO, compliance parity or Government availability beyond the capability matrix and `docs/RESEARCH-AND-GATES.md`.
- PRP-specific: runbooks that name commands must be executed by someone new; unexecuted runbooks are drafts and are labelled so.
- PRP-specific: `docs/` also holds evidence and internal planning; the nav must publish an explicit allowlist of pages, not the whole tree.
- PRP-specific: a public endpoint invites abuse; the assistant has rate limits, request size limits and does not retain full user prompts beyond what a privacy statement allows.

### External references
- MkDocs Material and EOL notice: https://squidfunk.github.io/mkdocs-material/ (EOL scheduled 2026-11-05, per docs/adr/0002-stack-pins.md, observed 2026-10-08).
- Zensical (successor, MIT, same authors): confirm URL and current feature parity at execution; cited in the docs/RESEARCH-AND-GATES.md toolchain support line.
- GitHub Pages and deployment via Actions: https://docs.github.com/pages (confirm current at execution).
- OpenAPI export from the FastAPI app factory: PRP-05 item 2 output.
- MCP spec 2026-07-28 and SDK 2.x: docs/adr/0002-stack-pins.md.

## Implementation blueprint

### Item 1 - docs-site  [P]
- Deliverable: ADR choosing between MkDocs Material 9.7 and Zensical (written and recorded first), the site config for the chosen tool, nav with an explicit publish allowlist, ADR index, home page, and a Pages deploy workflow.
- Owned files (may edit): `mkdocs.yml` or `zensical.toml` (whichever the ADR selects; only one is created), `docs/index.md`, `.github/workflows/docs.yml`, `docs/adr/0008-docs-site-tool.md`, `tests/docs/test_nav_allowlist.py`, `tests/docs/test_adr_0008_present.py`.
- Must NOT touch: `docs/reference/`, `docs/runbooks/`, `docs/walkthroughs/`, `services/docs-assistant/`, `.github/workflows/ci.yml` and other workflows (PRP-00, PRP-13), existing ADRs 0001-0007, root `pyproject.toml`, `package.json`, `docker-compose.yml`, `docs/RESEARCH-AND-GATES.md`.
- Depends on: none.
- Acceptance criteria:
  - ADR 0008 lists options, criteria (EOL, migration cost, search, SVG handling, licence), the decision and the date; it exists before the config file.
  - Build succeeds in strict mode; link check passes; the nav publishes only allowlisted pages.
  - Pages workflow uses least-privilege `permissions`, pinned actions, no secrets, no `|| true`.
- Pattern references: `docs/adr/0002-stack-pins.md` format; PRP-00 CI conventions.
- Tests to write: `tests/docs/test_nav_allowlist.py`, `tests/docs/test_adr_0008_present.py`.

### Item 2 - api-sdk-reference  [P]
- Deliverable: generated API reference from the committed OpenAPI JSON, connector SDK references (Python and TypeScript), and MCP tool/resource reference; generation scripts.
- Owned files (may edit): `docs/reference/`, `tests/docs/test_reference_coverage.py`.
- Must NOT touch: `docs/index.md`, `mkdocs.yml`, `zensical.toml`, `docs/runbooks/`, `docs/walkthroughs/`, the OpenAPI JSON itself (PRP-05), `connectors/`, `services/api/neurosphere_api/mcp/`.
- Depends on: none.
- Acceptance criteria:
  - Reference output is reproducible from committed inputs; regeneration produces no diff.
  - Every public endpoint in the OpenAPI JSON appears; every MCP tool in the registry appears with its scope requirement.
  - Pages state the error taxonomy and mark preview or unverified features as such.
- Pattern references: PRP-01 codegen drift check.
- Tests to write: `tests/docs/test_reference_coverage.py`.

### Item 3 - runbooks-and-walkthroughs  [P]
- Deliverable: install, migration, operations, DR and security runbooks plus persona walkthroughs bound to sandbox data; a recorded new-user test.
- Owned files (may edit): `docs/runbooks/`, `docs/walkthroughs/`, `tests/docs/test_runbook_commands.py`.
- Must NOT touch: `docs/reference/`, `docs/security/` (PRP-12), `docs/ops/` (PRP-05, PRP-21), `docs/compliance/` (PRP-23), `docs/dev/` (PRP-03), `docs/index.md`, `docs/RESEARCH-AND-GATES.md`.
- Depends on: none.
- Acceptance criteria:
  - A person who did not write the runbook completes install from the docs alone; deviations are recorded in `docs/runbooks/new-user-test.md` with date and tester.
  - One walkthrough per persona exists and each references a sandbox scenario that exists.
  - DR and security runbooks link to, and do not restate, the owning PRP documents; every command is copy-pasteable and uses forward slashes.
- Pattern references: `docs/dev/local-setup.md` style; PRP-12 runbook layout.
- Tests to write: `tests/docs/test_runbook_commands.py` (parses fenced commands, checks they reference existing scripts).

### Item 4 - public-docs-assistant
- Deliverable: a separate, rate-limited, read-only service that answers questions from the published docs only, with citations and abstention.
- Owned files (may edit): `services/docs-assistant/`.
- Must NOT touch: `services/api/`, `services/workers/`, `packages/core/`, `docker-compose.yml`, `docs/` (all), `.github/workflows/`, `tests/docs/`, root `pyproject.toml`.
- Depends on: Item 1 (needs the published site artifact format).
- Acceptance criteria:
  - Index is built from the built site artifact; a test proves a file outside the published set is not retrievable.
  - Rate limit test: requests beyond the configured limit return 429 `rate_limited`; request size limit enforced.
  - No production configuration, secret or product API URL is present in the image or environment (image scan test and config schema `extra="forbid"`).
  - With no supporting page, the answer abstains; every answer cites a docs URL.
- Pattern references: FastAPI service layout; PRP-12 injection corpus idea (a small local corpus is acceptable if PRP-12 is not merged).
- Tests to write: `services/docs-assistant/tests/test_corpus_boundary.py`, `services/docs-assistant/tests/test_rate_limit.py`, `services/docs-assistant/tests/test_abstain.py`.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
```
python -m pytest tests/docs services/docs-assistant/tests
python scripts/render_mermaid.py
```
Plus the docs build and link check commands for the tool chosen in item 1 (named in `docs/adr/0008-docs-site-tool.md`). There is no live script; any deployment of the assistant to a hosting service is operator-approved and not performed by this PRP.

## Live and open gates
- G09 (theme/brand/media review): docs branding and claims are inputs to the review; this PRP does not close it.
- No Government or live-environment gate closes here. The first public Pages deploy and any hosted assistant deployment are operator actions; if not performed, list them OPEN.
- Recorded new-user test: if no independent tester ran it, the runbooks stay labelled draft and the item is OPEN.
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Sales deck, persona scripts, storyboard (PRP-26) and video (PRP-27).
- Theme packs, sandbox mode, accessibility audit (PRP-24).
- Hosting or paying for the assistant's model endpoint; choosing a production host.
- Any dynamic or secret-bearing backend on GitHub Pages.
- Product features, API changes, or edits to the OpenAPI source.
- Localization beyond English.

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
- Docs tool chosen (ADR 0008) and EOL handling:
- New-user test: tester, date, result (or OPEN):
- Follow-ups:
