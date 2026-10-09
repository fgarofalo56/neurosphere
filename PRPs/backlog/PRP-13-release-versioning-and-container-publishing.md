---
name: prp-13-release-versioning-and-container-publishing
status: backlog
review: none
created: 2026-10-08
model: sonnet
phase: 1
ns: NS-10
depends_on: PRP-00, PRP-04, PRP-05
wave: W5
absorbs: new
---

# PRP-13: Release versioning and container publishing

## Goal
Make NeuroSphere releasable: multi-stage non-root Dockerfiles for api, workers and frontend; a tag-triggered `release.yml` that publishes to GHCR, attaches an SBOM, signs with cosign and packages the Helm chart; a SemVer and changelog policy tied to contract and migration versions; a versioned migrations runner for Cosmos document versions and analytics schemas; and a release Definition-of-Done checklist that points only at `docs/evidence/` paths. Audience: the operator cutting releases and the downstream PRPs (PRP-20 profile smoke, PRP-21 DR, PRP-25 docs) that need images and migration tooling. It lands in W5 because the app skeleton (PRP-05) and the frontend (PRP-04) exist to be containerized. It serves NS-10's enablement and documentation intent and PRP.md section 3's rule that "Migrations are versioned, backwards compatible and tested on representative snapshots."

> NS-10: "Branded static documentation/Pages site, API/SDK references, ADRs, setup/migration/security/operations/DR runbooks, walkthroughs and synthetic sandbox."

> PRP.md section 3: "Migrations are versioned, backwards compatible and tested on representative snapshots."

## Acceptance criteria
- [ ] Item 1: Given a clean checkout, When CI builds the three images, Then each builds and `docker run --rm <image> id -u` prints a non-zero uid.
- [ ] Item 2: Given tag `v0.1.0` on a release branch, When `release.yml` runs, Then signed images exist in GHCR with an attached SBOM and a packaged Helm chart; the workflow fails closed with no `|| true`.
- [ ] Item 3: Release notes are generated from conventional commits and written into `CHANGELOG.md` under a version heading; SemVer rules document how contract `v1` dirs and migration versions align.
- [ ] Item 4: Given a sandbox snapshot, When the runner applies forward migrations then rollback, Then document versions return to the starting state and snapshot tests pass; re-running forward is a no-op (idempotent).
- [ ] Item 5: `docs/release/dod-checklist.md` links only to `docs/evidence/` paths and to the master-index definition of done; no claim lacks an evidence path.
- [ ] PRP exit: `verify-gates -Mode full` passes; `release.yml` has been exercised at least with a dry-run or a pre-release tag in the private repo, output recorded.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Model and review | opus + review; sonnet + none | Sonnet, review: none (D6). Release workflow risk is mitigated by dry-run exercise and the PRP-12 scans |
| 2 | Registry | GHCR; ACR; both | GHCR only. ACR mirroring is a deployment concern for PRP-08/PRP-20 |
| 3 | Signing | cosign keyless (OIDC); cosign with key | Keyless via GitHub OIDC; no signing key stored anywhere. Verify command documented in `docs/release/` |
| 4 | SBOM | syft attach; none | syft SPDX or CycloneDX attached as OCI attestation; format named in the workflow. PRP-12 `security.yml` scans images; this PRP only publishes and attaches |
| 5 | Versioning | CalVer; SemVer | SemVer. Pre-1.0 means minor bumps may break; contract schemas stay additive-only per PRP-01 ADR-0004 |
| 6 | One version or per-component | single; per-image | Single product version across the three images and the chart; contract and migration versions tracked separately and recorded in release notes |
| 7 | Changelog tool | conventional-changelog; hand edited; custom script | Script in `scripts/release/` reading conventional commits; `CHANGELOG.md` already exists in Keep-a-Changelog form and keeps that structure |
| 8 | Migration scope | Cosmos only; plus analytics | Cosmos document versions and analytics schema versions behind adapters (PRP-11 supplies adapters; the runner defines the interface and a fixture implementation) |
| 9 | Publish trigger | tag; manual dispatch | Tag `v*.*.*` plus manual `workflow_dispatch` with `dry_run: true` default |
| 10 | Live items | publish to public registry | Repo is private (D1); GHCR package visibility stays private until the operator decides. No `NS_LIVE_APPROVED` script is needed, but first real tag push needs operator approval (ask before push) |
| 11 | Emulators | run migrations against live Cosmos | Emulator only (D8). Cosmos vNext emulator has no range/composite indexes, so snapshot tests assert document shape, not index behavior (G12) |
| 12 | Base images | latest; digest pinned | Pinned by digest recorded in Dockerfile comments; Dependabot may bump with cooldown |

## Context manifest

### Files that matter
- `PRP.md` sections 1-3, `docs/PRD.md` NS-10, `docs/ARCHITECTURE.md` (compute row: AKS and App Service share container code).
- `docs/adr/0002-stack-pins.md` (Python 3.12, Node 24, Helm 4.3, action versions: checkout v7, setup-python v7, setup-node v7, pnpm/action-setup v6, setup-uv v7).
- `CHANGELOG.md` (exists, Keep-a-Changelog, "Release automation arrives with PRP-13"), `CONTRIBUTING.md` (conventional commits), `SECURITY.md`.
- `pyproject.toml`, `docker-compose.yml`, `infra/compose/eventhubs.config.json`, `.claude/hooks/config.ps1`, `.env.example`, `scripts/validate_planning.py`.
- `.github/workflows/ci.yml`, `codeql.yml`, `secret-scan.yml` (read only for conventions).
- Created by PRP-00: workspace members and lockfiles (`uv.lock`, `pnpm-lock.yaml`), Mermaid render job. By PRP-01: `packages/contracts/schemas/` and `docs/adr/0004-contract-versioning.md`. By PRP-04: `frontend/` app. By PRP-05: `services/api/neurosphere_api/`, `services/workers/neurosphere_workers/`, `services/api/Dockerfile.dev`, `services/workers/Dockerfile.dev`, `packages/core/neurosphere_core/clients/`. By PRP-08: `infra/helm/` chart that item 2 packages. By PRP-12: `.github/workflows/security.yml`.

### Patterns to match
- Pydantic v2 models with `model_config = ConfigDict(extra="forbid")` for migration step descriptors and the migration ledger document.
- FastAPI routers per module under `services/api/neurosphere_api/<module>/router.py` (the images only package them; no router changes here).
- Async Azure SDK clients from `packages/core/neurosphere_core/clients`; the migration runner accepts a repository protocol so fixtures can stand in.
- Error taxonomy exceptions from `neurosphere_core.errors` (`stale_version` for ledger races, `dependency_transient` for retryable store failures).
- Tests beside packages plus cross-package suites in `tests/`; `pytest.mark.integration` for compose-backed migration tests.
- TS strict and Vitest apply to the frontend image build only (build must run `pnpm build` with the existing config).

### Conventions
- ruff (line 100, py312, S rules on), pyright standard, conventional commits (`feat(release): ...`), owned-file discipline.
- Evidence under `docs/evidence/<gate>/`; `scripts/gates/*` refuse without `NS_LIVE_APPROVED=1`.
- Workflow actions pinned to the majors in ADR-0002; no `|| true`.

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
- PRP-specific: `Dockerfile.dev` files (PRP-05) are for compose; production `Dockerfile` files here are separate and must not copy `.env*`; `.dockerignore` must exclude `.env`, `.git`, `temp/`, `docs/evidence/`.
- PRP-specific: images must contain no dev issuer enablement; `NS_ENV` defaults to non-local in images.
- PRP-specific: the migrations runner is for Cosmos document versions and analytics schemas, not for Event Hubs or blob layout. Migrations must be backwards compatible (expand then contract across two releases).
- PRP-specific: Helm 4 chart packaging uses `helm package`; do not assume App Service runs Helm (ARCHITECTURE compute row).
- PRP-specific: cosign keyless needs `id-token: write` permission on that job only; no other job gets it.
- PRP-specific: `CHANGELOG.md` is shared with every PRP's "Unreleased" entries; item 3 changes its automation, not its history.

### External references
- Keep a Changelog 1.1.0, https://keepachangelog.com/en/1.1.0/ and Semantic Versioning, https://semver.org/ (both already cited in `CHANGELOG.md`).
- Helm 4 and Helm 3 end of security fixes 2027-02-10, https://helm.sh/blog/helm-v3-end-of-life/, observed 2026-10-08.
- Cosmos DB vNext emulator limits, https://learn.microsoft.com/azure/cosmos-db/emulator-linux, observed 2026-10-08.
- Cosmos hierarchical partition keys (Python SDK 4.6 or later, new containers only), https://learn.microsoft.com/azure/cosmos-db/hierarchical-partition-keys, observed 2026-10-08 (dated 2026-04-27).
- GitHub Actions versions pinned in `docs/adr/0002-stack-pins.md`, observed 2026-10-08.
- cosign keyless signing and GHCR documentation: retrieve current URLs at implementation time and record them with the observed date in `docs/release/`; none were observed during planning.

## Implementation blueprint

### Item 1 — dockerfiles  [P]
- Deliverable: multi-stage, non-root Dockerfiles for api, workers, frontend plus a shared `.dockerignore`.
- Owned files (may edit): `services/api/Dockerfile`, `services/workers/Dockerfile`, `frontend/Dockerfile`, `.dockerignore`, `tests/release/test_dockerfiles.py`.
- Must NOT touch: `services/api/Dockerfile.dev`, `services/workers/Dockerfile.dev` (PRP-05), `.github/workflows/`, `docker-compose.yml`, root `pyproject.toml`, `infra/helm/`.
- Depends on: none.
- Acceptance criteria:
  - `docker build` succeeds for all three from repo root using lockfiles (`uv sync --frozen`, `pnpm install --frozen-lockfile`).
  - Containers run as non-root (uid check) with read-only root filesystem where supported.
  - Image contains no `.env*`, `.git` or test fixtures (checked by `docker run ... find`).
- Pattern references: ADR-0002 pins; Python 3.12 and Node 24 base images.
- Tests to write: `tests/release/test_dockerfiles.py` (static checks: USER directive present, no `latest` tag, no `ADD http`).

### Item 2 — publish-workflow
- Deliverable: `release.yml` triggered by `v*.*.*` tags and manual dispatch with `dry_run`; builds images, pushes to GHCR, attaches SBOM, cosign signs by digest, packages the Helm chart.
- Owned files (may edit): `.github/workflows/release.yml`, `tests/release/test_release_workflow.py`.
- Must NOT touch: `.github/workflows/ci.yml`, `security.yml` (PRP-12), `codeql.yml`, `secret-scan.yml`, the Dockerfiles (item 1).
- Depends on: item 1.
- Acceptance criteria:
  - Dry-run on a branch completes all steps except push and sign, with logged outputs.
  - Tag `v0.1.0` (or a pre-release tag) yields signed images; `cosign verify` command in `docs/release/` succeeds against the published digest.
  - Least-privilege `permissions:` per job; no `|| true`.
- Pattern references: existing workflow layout in `ci.yml`.
- Tests to write: `actionlint` in gate; `tests/release/test_release_workflow.py` (parses YAML, asserts no suppressed failures, `id-token` only on the signing job).

### Item 3 — versioning-policy  [P]
- Deliverable: SemVer policy, changelog generator from conventional commits, mapping between product version, contract schema version and migration version.
- Owned files (may edit): `docs/release/versioning.md`, `docs/release/release-process.md`, `CHANGELOG.md`, `scripts/release/`, `tests/release/test_changelog.py`.
- Must NOT touch: `docs/release/dod-checklist.md` (item 5), `packages/contracts/`, `.github/workflows/`, `docs/RESEARCH-AND-GATES.md`.
- Depends on: none.
- Acceptance criteria:
  - `python scripts/release/changelog.py --from <tag> --to HEAD` prints Keep-a-Changelog sections from conventional commits; unknown commit types are listed, not dropped.
  - Existing `CHANGELOG.md` history is preserved byte for byte below the new section.
  - Policy states pre-1.0 rules and additive-only contract rule.
- Pattern references: `CHANGELOG.md`, `CONTRIBUTING.md`.
- Tests to write: `tests/release/test_changelog.py` (fixture git log in, expected markdown out).

### Item 4 — migration-tooling  [P]
- Deliverable: versioned migrations runner with ledger document, forward and rollback, dry-run, idempotency, snapshot test harness, repository protocol for Cosmos and for PRP-11 analytics adapters.
- Owned files (may edit): `packages/core/neurosphere_core/migrations/`, `tests/integration/migrations/`.
- Must NOT touch: `packages/core/neurosphere_core/clients/` (PRP-05), `packages/core/neurosphere_core/analytics/` (PRP-11), `packages/contracts/`, `docker-compose.yml`.
- Depends on: none.
- Acceptance criteria:
  - Forward then rollback on a sandbox snapshot restores the original documents (hash compare); second forward is a no-op.
  - Backwards-compat rule enforced: a migration that removes a field in the same release it is deprecated fails a lint test.
  - Concurrent runner instances: loser gets `stale_version`, no double apply.
- Pattern references: Pydantic strict models, `neurosphere_core.errors`.
- Tests to write: `tests/integration/migrations/test_forward_rollback.py`, `tests/integration/migrations/test_idempotent.py`, `tests/integration/migrations/test_concurrent_runners.py`, unit tests beside the package.

### Item 5 — dod-evidence-template
- Deliverable: release Definition-of-Done checklist mirroring the master-index definition of done, each line linking an `docs/evidence/` path.
- Owned files (may edit): `docs/release/dod-checklist.md`, `tests/release/test_dod_links.py`.
- Must NOT touch: other `docs/release/` files (item 3), `docs/evidence/` contents, `docs/RESEARCH-AND-GATES.md`.
- Depends on: item 3.
- Acceptance criteria:
  - Every checklist line has an evidence path under `docs/evidence/` or is marked OPEN with the gate id.
  - A test fails if a link points outside `docs/evidence/` (except the master index).
  - Checklist does not claim FedRAMP, ATO or parity.
- Pattern references: PRP.md section 4 definition of done.
- Tests to write: `tests/release/test_dod_links.py`.

## Validation gates
```
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode fast    # per item
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full    # before merge
python scripts/validate_planning.py
```
Feature-specific:
- `docker build -f services/api/Dockerfile -t ns-api:dev .` and the same for workers and frontend, then `docker run --rm --entrypoint id ns-api:dev -u`
- `docker compose up -d --wait` then `python -m pytest tests/integration/migrations -m integration -q`
- `python -m pytest tests/release -q`
- `actionlint .github/workflows/release.yml`
- `helm lint infra/helm` and `helm package infra/helm`
- Dry run: `gh workflow run release.yml -f dry_run=true` (operator approval before first real tag push; ask before push).

## Live and open gates
- G08 (dependency versions and licences): image SBOM attachment adds evidence; status stays NARROWED.
- G12 (emulator parity): migration snapshot tests run on the Cosmos vNext emulator only; record that index behavior and RU cost are not exercised.
- G07 (workload/SLO/DR): untouched; PRP-21 owns restore evidence that uses this migration tooling.
- If a live item did not run, record it OPEN in the completion note and in docs/RESEARCH-AND-GATES.md; never report it as a skipped green test.

## NOT building
- Image vulnerability scanning and SBOM generation workflow (PRP-12 `security.yml`); this PRP only attaches and publishes.
- Bicep or Helm chart contents (PRP-08); this PRP packages the chart.
- Government registry or sovereign mirror setup (PRP-20).
- Analytics adapter schemas themselves (PRP-11); only the runner interface.
- Documentation site and runbooks (PRP-25).
- Automatic production deployment from a tag.

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
- Open gates recorded (ids and where):
- Follow-ups:
