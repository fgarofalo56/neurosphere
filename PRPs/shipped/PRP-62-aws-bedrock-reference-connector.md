---
name: PRP-62-aws-bedrock-reference-connector
status: shipped
shipped: 2026-11-16
pr: 317
priority: P3
order: 50
review: required
created: 2026-11-14
model: sonnet
orchestrator_model: sonnet
implementer_model: sonnet
phase: 6
ns: NS-09, NS-01
depends_on: [PRP-42-connector-configuration-and-credential-references]
wave: W23
branch: prp-62-aws-bedrock-connector
allow_parallel: true
issues: [256]
---

# PRP-62: AWS Bedrock reference connector (metadata only)

## Goal
Add a seventh reference connector, `connectors/reference/aws-bedrock/`, built on the connector SDK, that reads AWS Bedrock metadata for one AWS account and region: the model inventory (foundation models available, custom models, provisioned throughput, guardrails, agents), usage metrics from CloudWatch (`AWS/Bedrock` invocation and token counts by model), cost from Cost Explorer for the Bedrock service, and whether invocation logging is configured (the setting only, never the logs). It closes the "no AWS Bedrock connector" gap named in the 2026-11-06 validation and gives PRP-61 and the cost ledger a second cloud to see. It is Commercial only (a Government NeuroSphere deployment refuses it, never bridging data), reads metadata only (no model invocation, no prompt, response or log content), holds no credential at rest, and passes the contract kit with fakes. The live run needs an AWS account the owner approves and is handed to PRP-64. This PRP owns the new dependency (an AWS SDK) end to end: `pyproject.toml`, `uv.lock`, the licence register, the ADR-0002 pin and the five `uv --frozen` Dockerfiles.

Out of scope: storing a Bedrock connector configuration and running it as a worker role (needs a new `ConnectorConfig.connector_kind` value in the PRP-37 contracts and a role in `services/workers/**`; filed as a follow-up after PRP-42 and PRP-61 release the contracts); mapping Bedrock usage into `TelemetryEvent` or ledger entries; AWS GovCloud; Azure or other-cloud connectors; any write action on AWS; shadow-AI discovery on AWS (PRP-61 is Azure only); the live run (PRP-64).

## Why
- The validation records "no cloud coverage beyond Azure (no AWS Bedrock connector)" and decided to keep metadata only (`docs/validation/PRODUCT-VALIDATION-2026-11-06.md:67-72`); a repo-wide grep finds `bedrock` only in that document (lane-d step 7).
- `docs/connectors/coverage.md` lists built and unbuilt targets and requires every built target to cite a documented API, so a new row with citations is part of the work (rule at its top: "no invented APIs").
- The connector SDK gives manifest validation, health, coverage, freshness, credential brokering and the contract kit (`connectors/sdk-python/neurosphere_connector/{connector.py,manifest.py,vault.py,contract_kit.py}`); six reference connectors already run through `tests/unit/connector_conformance/test_reference_connectors_conformance.py`.
- Credentials must be references, never values (assumption A7): `CredentialRef` vault ids only (`packages/contracts/schemas/connectors/v1/connector-manifest.schema.json`, `vault_ref` pattern) and `CredentialBroker` resolves per call so rotation works.
- Adding a workspace member without copying it into the five `uv --frozen` images breaks the build: `connectors/reference/azure-billing` appears in `services/api/Dockerfile:25`, `services/api/Dockerfile.dev:23`, `services/workers/Dockerfile:25`, `services/workers/Dockerfile.dev:23` and `scripts/sandbox/Dockerfile.seed:24`; the licence gate fails an unknown licence (`scripts/licenses_report.py`, `docs/licenses.md`).

## Acceptance criteria
- [x] Dependency: the connector's `pyproject.toml` depends on `neurosphere-connector` and one AWS SDK pinned to a major range; the root `pyproject.toml` lists the member in `dependencies` and `[tool.uv.sources]`; `uv lock --check` passes after `uv.lock` is updated and the diff touches only the new member and its transitive packages (no unrelated version moves); `python scripts/licenses_report.py` passes and `docs/licenses.md` carries a row per new package; `docs/adr/0002-stack-pins.md` has a pin row per new package with licence and URL.
- [x] Images: all five Dockerfiles copy `connectors/reference/aws-bedrock`; `tests/release/test_dockerfiles.py` passes; the API and worker images build with `uv sync --frozen` (build run locally if Docker is available, otherwise reported unverified).
- [x] Manifest: built with `build_manifest`; read-only (`advisory=true`, no write support), capabilities `catalog_discovery`, `usage_reports`, `cost_ingest`, `health_reporting`; `supported_clouds: [commercial]`; credential references are vault ids or federation, never values; `check_connector_contract` returns no violations.
- [x] Government: constructing the connector with a Government cloud raises the typed `capability_unavailable` error with reason `aws_bedrock_government_unsupported`; nothing is read and no request is made (test with a socket guard).
- [x] Inventory: foundation models, custom models, provisioned throughput, guardrails and agents are returned as bounded, typed metadata (id, name, status, provider, modality names, created time); each list is capped (`max_items`), sets `truncated` and partial coverage at the cap, and is `None` when its call failed, never `[]`.
- [x] Usage and cost: hourly invocation and token counts per model id (CloudWatch) and daily cost (Cost Explorer) are returned for an explicit window; a missing datapoint is `None` not 0; cost carries `estimated` versus `invoiced` as the API reports it and the currency; no price is computed here.
- [x] Metadata only: a test injects reader payloads containing prompt-like text, a key and a log-group name and asserts the typed outputs, `repr`, health report and logs contain none of them; the reader exposes no invoke, `converse`, log-read or object-read operation (an interface test enumerates the protocol).
- [x] Credentials: the SDK client is built per call from a `CredentialBroker` secret (static key JSON) or from a web-identity role assumption, whichever the settings select; no key is stored on the instance, logged or put in an exception; `notify_rotated` takes effect on the next call (test).
- [x] Resilience: AWS throttling and 5xx map to `rate_limited` and `dependency_transient` with capped backoff and a page budget; the connector never loops past its caps; health reflects the last error class only.
- [x] Conformance: `tests/unit/connector_conformance/test_aws_bedrock*.py` runs the read-profile contract kit against the connector with fakes and a deliberately broken variant that the kit rejects.
- [x] Docs: `connectors/reference/aws-bedrock/README.md` holds the least-privilege read-only IAM policy (action names verified against AWS documentation, with observation dates), the IAM trust or key-handling guidance, the Cost Explorer request-cost warning, and the exact live-check command; `docs/connectors/coverage.md` has a "built (PRP-62), not live-tested" row with citations; G04 stays OPEN.
- [x] A live-check script `connectors/reference/aws-bedrock/scripts/live_check.py` refuses without `NS_LIVE_APPROVED=1` (exit 2, no import of the SDK, no network) and otherwise performs one bounded read of each source and writes a whitelisted evidence JSON.
- PRP exit: touched suites, ruff, pyright, licence and Dockerfile checks and `validate_planning.py` pass; the live run is written OPEN and handed to PRP-64.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | AWS SDK | `boto3` (sync, wrapped with `asyncio.to_thread`); `aioboto3`/`aiobotocore`; hand-signed SigV4 over `httpx` | ASSUMPTION: `boto3`, imported lazily only in the real reader so unit tests and the contract kit run without botocore; avoids `aiobotocore`'s tight `botocore` pin. Confirm at plan approval; if the licence gate rejects a transitive package, stop and ask before allowlisting |
| 2 | Credential model | Static key in Key Vault; web-identity federation from Entra; both | ASSUMPTION: support both through one provider interface, prefer web identity (no secret at rest). Static key is a vault reference resolved per call by `CredentialBroker`. If the federation path exceeds the session, ship static-key first and file the federation follow-up |
| 3 | Where it runs | Library only; worker role | Library plus a live-check script. A worker role and a stored config need a contract kind and `services/workers/**`, which this PRP does not own; follow-up issue |
| 4 | Output shapes | Reuse `TelemetryEvent`; own typed models | Own typed read models (like `AzureBillingConnector` and `FoundryDiscoveryConnector`); ingestion mapping is the future role's job |
| 5 | What counts as "metadata" | Includes logs; excludes | Excludes any log, prompt, response or object content; invocation-logging is read as a boolean plus destination type only, no names of buckets or log groups are kept |
| 6 | Regions | One; many | One region per connector instance; the operator creates one instance per region |
| 7 | Cost API | Cost Explorer; CUR in S3 | Cost Explorer `GetCostAndUsage` (no bucket access, no object reads). ASSUMPTION; request cost applies per paginated call, documented in the README |
| 8 | Government and GovCloud | Support; refuse | Refuse: manifest Commercial only, typed refusal; no cross-boundary bridging |

## Context manifest

### Files to read first
- `connectors/reference/azure-billing/neurosphere_connector_azure_billing/connector.py` and `pyproject.toml` - the closest shape: read-only connector, advisory manifest, coverage and freshness, per-package pyproject.
- `connectors/reference/foundry/neurosphere_connector_foundry/{connector.py,reader.py,capabilities.py}` - reader protocol, capped lists, `None` for failed sources, truncation flags.
- `connectors/sdk-python/neurosphere_connector/{connector.py,manifest.py,vault.py,health.py,contract_kit.py}` - `BaseConnector`, `build_manifest`, `CredentialBroker`, health, the kit.
- `tests/unit/connector_conformance/test_reference_connectors_conformance.py:1-180` - socket guard, `_load`, fakes and parametrized cases (read, not edited).
- `docs/connectors/coverage.md` - table format, citation and "no invented APIs" rule; add one row.
- `pyproject.toml:25-60`, `docs/adr/0002-stack-pins.md:125-140`, `scripts/licenses_report.py:60-95` - member lists, pin table format, allowlist and platform-gated maps.
- `services/api/Dockerfile`, `services/workers/Dockerfile`, their `.dev` twins, `scripts/sandbox/Dockerfile.seed` and `tests/release/test_dockerfiles.py` - COPY lines to add.
- `packages/contracts/schemas/connectors/v1/connector-manifest.schema.json` - enums for capabilities, granularity, auth modes, `supported_clouds`, `credential_refs`.
- `PRPs/backlog/PRP-42-connector-configuration-and-credential-references.md` - credential reference vocabulary.

### Interfaces consumed
- Connector SDK (shipped, PRP-09): `BaseConnector`, `build_manifest`, `CredentialBroker`, `SecretValue`, `check_connector_contract`.
- PRP-37/PRP-42: the `CredentialReference` vocabulary (Key Vault secret URI or managed identity) as the model for how an operator will later configure this connector; this PRP does not call PRP-42 routes.
- `neurosphere_core.cloud.profile.CloudName`, `neurosphere_core.errors` (`CapabilityUnavailableError`, `DependencyTransientError`).
- Microsoft Entra token for web identity (only in the federation provider, injected as a callable).

### Interfaces provided
- Package `neurosphere_connector_aws_bedrock`: `AwsBedrockConnector`, `BedrockReader` protocol, `Boto3BedrockReader`, result models (`BedrockInventory`, `BedrockUsagePoint`, `BedrockCostPoint`, `InvocationLoggingState`), `AwsCredentialProvider` implementations.
- A conformance test and `scripts/live_check.py` that PRP-64 runs; evidence path `docs/evidence/G04/aws-bedrock-<stamp>.json`.
- A worker-role follow-up note in the completion note (contract kind, role name, settings) for the PRP that picks it up.

### Patterns to match
- `connectors/reference/azure-billing/.../connector.py:1-70` (docstring with observed documentation URLs and dates, manifest builder, `BaseConnector.guarded_call`).
- `connectors/reference/foundry/.../connector.py:60-140` (capped, `None`-on-failure lists with `truncated`).
- `connectors/sdk-python/neurosphere_connector/vault.py` (`SecretValue` never leaks; log lines carry the logical name only).
- `tests/unit/connector_conformance/test_reference_connectors_conformance.py:60-100` (socket guard) and the broken-connector case.

### Gotchas
- AWS service and action names in this PRP are from memory of the AWS API surface and are UNVERIFIED: item 2 must verify each against current AWS documentation (context7 or web fetch; subagents lack the Learn MCP) and cite the page and date in the module docstring and the README. Do not ship an API name that was not read.
- `uv lock` may re-resolve unrelated packages; inspect the diff and, if anything unrelated moves, hand-patch the new member only (precedent: PRP-35 completion note) or stop and ask.
- `python-dateutil` and `six` (boto3 transitive) report licence strings that the gate may not recognise ("Dual License"); the gate fails on UNKNOWN. Resolve with a verified `ALIASES` entry only if the metadata is a known permissive licence; otherwise report and ask. Never allowlist silently.
- `docs/licenses.md` is generated; regenerate with `python scripts/licenses_report.py`, never hand-edit.
- A new workspace package must be copied into all five Dockerfiles; the dev images copy members by directory.
- Boto3 is synchronous: never call it on the event loop; use `asyncio.to_thread` and a bounded semaphore. Do not read AWS config from the host: build clients from explicit credentials and region, never `~/.aws`.
- CodeQL: no logging of names that look like secrets; compare AWS hostnames as DNS labels with a leading dot.
- Cost Explorer calls are billed per request; the live check must page-cap and state the expected request count.

Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - connectors/reference/aws-bedrock/**
  - tests/unit/connector_conformance/test_aws_bedrock*.py
  - docs/connectors/coverage.md
tier1:
  - pyproject.toml
  - uv.lock
  - docs/licenses.md
  - docs/adr/0002-stack-pins.md
  - services/api/Dockerfile
  - services/api/Dockerfile.dev
  - services/workers/Dockerfile
  - services/workers/Dockerfile.dev
  - scripts/sandbox/Dockerfile.seed
tier2_appends:
  - scripts/licenses_report.py
must_not_touch:
  - services/workers/**
  - services/api/neurosphere_api/**
  - packages/contracts/**
  - connectors/reference/azure-billing/**
  - connectors/reference/foundry/**
  - tests/unit/connector_conformance/test_reference_connectors_conformance.py
```

## Implementation blueprint

Parallelization map: item 1 (dependency plumbing, Tier 1) first so the lock and images are settled; item 2 (API verification and models) next; items 3 and 4 depend on 2 and are independent of each other [P]; item 5 needs 3 and 4; item 6 needs 5; item 7 closes out. All Tier-1 files are edited by item 1 only.

### Item 1 - Dependency, licence, pin and images
- Deliverable: connector `pyproject.toml` (SDK dependency range), root `pyproject.toml` member lines, regenerated `uv.lock`, regenerated `docs/licenses.md`, ADR-0002 pin rows, five Dockerfile COPY lines, and, only if verified and necessary, one `ALIASES` line in `scripts/licenses_report.py`. A minimal package stub (`__init__.py`) so the workspace resolves.
- Owned files: `connectors/reference/aws-bedrock/pyproject.toml`, `connectors/reference/aws-bedrock/neurosphere_connector_aws_bedrock/__init__.py`, and the Tier-1 files above.
- Must NOT touch: any other connector or service.
- Depends on: none.
- Acceptance criteria: dependency, licence and image criteria; the lock diff is reported in the item notes.
- Tests: `uv lock --check`, `uv run pytest -q tests/release tests/unit/infra`, `python scripts/licenses_report.py --check` if the script has that mode (else run it and `git diff --stat docs/licenses.md`).
- Pattern references: `connectors/reference/azure-billing/pyproject.toml`, `docs/adr/0002-stack-pins.md:137`.

### Item 2 - AWS API verification, models and manifest
- Deliverable: a short verified API table in the module docstring (service, operation, IAM action, documentation URL, observation date) for each read; Pydantic models (frozen, `extra="forbid"`); the manifest via `build_manifest`; the `BedrockReader` protocol with only read operations.
- Owned files: `connectors/reference/aws-bedrock/neurosphere_connector_aws_bedrock/{models.py,reader.py,manifest.py}`.
- Must NOT touch: connector class (item 3) and the boto3 reader (item 4).
- Depends on: item 1.
- Acceptance criteria: manifest and metadata-only protocol criteria; every API cited was read in this session.
- Tests: `connectors/reference/aws-bedrock/tests/test_models_and_manifest.py` (new), including the protocol-enumeration test.
- Pattern references: `foundry/.../reader.py`, `azure-billing/.../export_reader.py`.

### Item 3 - Connector class  [P]
- Deliverable: `AwsBedrockConnector(BaseConnector)` with `inventory()`, `usage(window)`, `cost(window)`, `logging_state()`; caps, truncation, `None` discipline, coverage and freshness, Government refusal, `guarded_call` health.
- Owned files: `connectors/reference/aws-bedrock/neurosphere_connector_aws_bedrock/connector.py`, `connectors/reference/aws-bedrock/tests/test_connector.py`.
- Must NOT touch: items 2 and 4 files except to fix a defect (record it).
- Depends on: item 2.
- Acceptance criteria: Government, inventory, usage-and-cost, metadata-only and resilience criteria against a scripted fake reader.
- Tests: `connectors/reference/aws-bedrock/tests/test_connector.py`.
- Pattern references: `foundry/.../connector.py`, `azure-billing/.../connector.py`.

### Item 4 - Real reader and credential providers  [P]
- Deliverable: `Boto3BedrockReader` (lazy import, `to_thread`, bounded concurrency, botocore retry config off in favour of the connector's capped backoff, pagination caps), `StaticKeyProvider` (from `CredentialBroker`), `WebIdentityProvider` (role ARN, session name, injected token callable, expiry-aware refresh), IAM policy text constant used by the README test.
- Owned files: `connectors/reference/aws-bedrock/neurosphere_connector_aws_bedrock/{boto3_reader.py,credentials.py}`, `connectors/reference/aws-bedrock/tests/test_boto3_reader.py`, `test_credentials.py`.
- Must NOT touch: connector class.
- Depends on: item 2.
- Acceptance criteria: credentials criterion (rotation, no leak); the reader maps AWS error codes to typed errors using botocore stubs (`botocore.stub.Stubber` or a fake client factory) with no network; an import of the module without boto3 installed still works until the reader is constructed.
- Tests: `connectors/reference/aws-bedrock/tests/test_boto3_reader.py`, `test_credentials.py`.
- Pattern references: `connectors/sdk-python/neurosphere_connector/vault.py`, `foundry/.../reader.py`.

### Item 5 - Contract-kit conformance
- Deliverable: `tests/unit/connector_conformance/test_aws_bedrock_conformance.py` (new file; the existing conformance file is not edited): socket guard, fake reader, read-profile kit, broken-connector negative case.
- Owned files: `tests/unit/connector_conformance/test_aws_bedrock*.py`.
- Must NOT touch: the existing conformance test.
- Depends on: items 3, 4.
- Acceptance criteria: conformance criterion; the negative case fails the kit.
- Tests: `tests/unit/connector_conformance`.
- Pattern references: `tests/unit/connector_conformance/test_reference_connectors_conformance.py`.

### Item 6 - README, coverage row and live-check script
- Deliverable: README with verified IAM policy and trust guidance, `scripts/live_check.py` (refusal first, bounded reads, whitelisted evidence), coverage row in `docs/connectors/coverage.md`, a test that the README policy matches the constant and the script refuses without approval.
- Owned files: `connectors/reference/aws-bedrock/README.md`, `connectors/reference/aws-bedrock/scripts/live_check.py`, `connectors/reference/aws-bedrock/tests/test_live_check.py`, `docs/connectors/coverage.md` (one row).
- Must NOT touch: other coverage rows.
- Depends on: item 5.
- Acceptance criteria: docs and live-check criteria; `python connectors/reference/aws-bedrock/scripts/live_check.py` exits 2 without `NS_LIVE_APPROVED`.
- Tests: `connectors/reference/aws-bedrock/tests/test_live_check.py`.
- Pattern references: `scripts/gates/g16_judge_live.py:80-90` (refusal first).

### Item 7 - Integration and close-out
- Deliverable: run the full gates, rebase and re-check `uv lock --check`, `python scripts/prp_status.py --write`, `PRPs/INDEX.md`, CHANGELOG, completion note with the follow-up for the worker role and `ConnectorConfig` kind, the OPEN live run and "Env vars for the operator" (`NS_LIVE_APPROVED`, the live-check variables).
- Owned files: this PRP file, `CHANGELOG.md`.
- Depends on: item 6.

## Validation gates
```bash
uv sync --frozen --group dev
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q connectors/reference/aws-bedrock/tests tests/unit/connector_conformance connectors/sdk-python/tests tests/release
python scripts/licenses_report.py
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```
Optional when Docker is available: build `services/api/Dockerfile` and `services/workers/Dockerfile` to prove `uv sync --frozen`.

## Migration and rollback
No data migration: the connector is a library nothing calls yet. Roll back by reverting the PR; the member, lock entries, licence and pin rows and the Dockerfile lines go together. If the licence gate or the lock diff cannot be made clean, ship nothing and report; do not allowlist to get green.

## Live and open gates
A live read needs an AWS account and region the owner names, a read-only IAM role or key the operator installs (never in a file or the chat), `NS_LIVE_APPROVED=1`, and a Cost Explorer request cap; it is handed to PRP-64 as part of the G04 item and is OPEN here. G04 remains OPEN. No Government or GovCloud claim is made.

## NOT building
A worker role, stored connector configuration or admin page for Bedrock; ingestion of Bedrock usage as telemetry; price computation; model invocation, guardrail evaluation or log reading; AWS write actions; GovCloud or multi-region fan-out; other providers (Anthropic, Google, xAI, Cursor remain documented gaps).

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [x] All clarification questions are decided, not guessed (rows 1, 2 and 7 are flagged ASSUMPTIONS; AWS API names are verified in item 2)

## Execution state

| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | prp-62-aws-bedrock-connector | boto3 1.44.3; lock adds only boto3, botocore, jmespath, s3transfer, python-dateutil, six + member; ALIASES "dual license" verified from dist LICENSE+classifiers |
| 2 | merged | prp-62-aws-bedrock-connector | APIs verified vs botocore 1.44.3 models, AWS Service Reference JSON (IAM actions, IsWrite false), AWS docs (metrics, GetCostAndUsage); test files prefixed test_aws_bedrock_ to avoid basename clashes |
| 3 | merged | prp-62-aws-bedrock-connector | connector + tests |
| 4 | merged | prp-62-aws-bedrock-connector | credentials module is aws_auth.py (secret guard refuses *credentials* file names); botocore retries need total_max_attempts=1 |
| 5 | merged | prp-62-aws-bedrock-connector | test_aws_bedrock_conformance.py; one-line edit to the existing six-connectors coverage test (listed must_not_touch) was unavoidable: it pins the on-disk set, so the new member broke it. Flag for review |
| 6 | merged | prp-62-aws-bedrock-connector | README, scripts/live_check.py (exit 2 without NS_LIVE_APPROVED=1), iam.py policy constant, coverage row; live run OPEN |
| 7 | merged | prp-62-aws-bedrock-connector | close-out at landing: main merged, `uv lock --check` clean, changelog fragment, planning files regenerated |

## Completion note
- Date, PR number, merge commit: 2026-11-16, PR #317 (squash merge on main by the unattended landing run).
- Deviations: (1) the credentials module is `aws_auth.py`, not `credentials.py` (the repo secret guard refuses file names containing "credentials"); (2) test files are prefixed `test_aws_bedrock_` so basenames cannot clash across connector test directories; (3) one-line edit to `tests/unit/connector_conformance/test_reference_connectors_conformance.py` (listed must_not_touch) because `test_all_six_reference_connectors_are_covered` pins the on-disk connector set and failed once the member existed: review this; (4) `scripts/licenses_report.py` gained one verified ALIASES line (`dual license` -> `Apache-2.0 AND BSD-3-Clause`, python-dateutil 2.9.0.post0, read from its LICENSE and classifiers); (5) `usage()` takes an explicit `model_ids` list (at most 50) because discovering ids from CloudWatch would need the extra `cloudwatch:ListMetrics` action; (6) botocore `retries.max_attempts` means retries, so the reader and STS client use `total_max_attempts: 1`; (7) the two Dockerfile builds were not run (see OPEN gates).
- Descoped items: none. The web-identity path shipped alongside the static key.
- OPEN gates: G04 (live AWS read, handed to PRP-64; needs an owner-approved AWS account, a read-only role or key and `NS_LIVE_APPROVED=1`); the API and worker image builds with `uv sync --frozen` (Docker not run in this session; COPY lines and `uv lock --check` verified); `STS AssumeRoleWithWebIdentity` against a real OIDC provider (unit-tested with an injected exchange only).
- Env vars for the operator: `NS_LIVE_APPROVED` (live check), `NS_AWS_BEDROCK_KEY_JSON` (static-key live check only; the operator exports it, never in a file or chat). No `.env.example` change.
- Follow-up issues filed: none filed from the unattended run. Needed: a stored connector configuration (a new `ConnectorConfig.connector_kind` value `aws_bedrock` in the contracts, after PRP-42 and PRP-61 release them) and a worker role (`aws-bedrock-inventory`, settings: region, auth mode, role ARN or vault reference, `max_items`, cost services) in `services/workers/**`, then mapping usage into `TelemetryEvent` and ledger entries.
- Operator product check: not yet. The connector is a library plus a live-check script; there is no stored connector configuration or worker role, so an operator cannot enable it without code (see the follow-up above). Not claimed as usable.
