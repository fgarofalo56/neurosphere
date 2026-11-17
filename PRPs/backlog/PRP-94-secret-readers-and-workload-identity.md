---
name: PRP-94-secret-readers-and-workload-identity
status: backlog
priority: P1
order: 85
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: sonnet
phase: 8
ns: NS-07, NS-08
depends_on: [PRP-86-contracts-platform-dimension-and-credential-kinds, PRP-89-postgres-foundation-catalog-and-security-stores, PRP-92-kafka-and-object-store-adapters, PRP-95-model-telemetry-and-analytics-adapters, PRP-102-encrypted-interaction-store-and-retention]
wave: W37
branch: prp-94-secret-readers
allow_parallel: true
issues: []
---

# PRP-94: Secret readers and workload identity for AWS, GCP and Kubernetes

## Goal
Give every non-Azure deployment a way to reach its database, broker, buckets, model endpoints and connector secrets without a static credential in configuration. Secret readers for AWS Secrets Manager, Google Secret Manager, a mounted Kubernetes secret file and the Vault KV HTTP API sit beside the existing Key Vault reader behind one reader Protocol, dispatched by `CredentialReference.kind`, each refusing a reference that does not belong to the deployment (account, project, path or mount allowlist) before any network call, the way `parse_key_vault_secret` checks the vault suffix today. Token providers fill the hooks PRP-89 (PostgreSQL pool), PRP-92 (Kafka, S3, GCS) and PRP-95 (Bedrock, Vertex, OpenAI-compatible, and the PostgreSQL analytics executor's pool factory) left open, and this PRP wires the real providers (and PRP-89's pool for the analytics executor) through the PRP-87/PRP-88 seams where those PRPs' tests only injected static ones: EKS and GKE workload identity, RDS IAM database tokens, Cloud SQL IAM, MSK and Google Managed Kafka authentication. Configuration, logs, audit records, exceptions and OpenAPI carry references only, never values. It is for the operator of an AWS, GCP or on-prem install (owner decision 2026-11-16) and runs in W37 after the contract kinds (PRP-86) and the hooks exist.

Out of scope: the reference kinds themselves and `check_credential_reference` (PRP-86 contracts and `admin/connectors/references.py`); Helm `serviceAccount.identity` blocks and the CSI `SecretProviderClass` parameters (PRP-96); IAM roles, service accounts and empty secret entries in Terraform (PRP-97); MCP outbound credentials (the registered server has no reference field today, `packages/core/neurosphere_core/mcp/outbound_auth.py:41-52`; follow-up); real AWS and GCP runs (OPEN, PRP-98).

## Why
- Original PRD 5f (`git show 9fbf5f4c:docs/PRD.md`, lines 96-106): "provider-specific managed-service substitutions ... behind a common abstraction layer" and "only infra adapters differ"; the hard constraint "No secrets in files/prompts/logs; vault/managed identity in production" (`CLAUDE.md`) must hold on every target.
- v1.2 excluded it: `docs/PRD.md:4` ("not a commitment to deploy the platform on AWS/GCP/on-prem"), `docs/PRD.md:57`, `PRP.md:7` ("No commitment to platform hosting on AWS/GCP/on-prem"). On 2026-11-16 the owner decided to add back all four targets; PRP-85 amends those lines.
- Only one reader exists: `SecretReader` (`services/workers/neurosphere_workers/connector_config/keyvault.py:64`; PRP-85 defines the neutral Protocol in core and this PRP re-points the worker one to it) with `KeyVaultSecretReader` (`:95`) and a hard-wired `build_reader` (`connector_config/resolve.py:70-76`). It refuses anything but `key_vault_secret` (`keyvault.py:120-121`).
- The contract allowed only `key_vault_secret|managed_identity` (`packages/contracts/python/neurosphere_contracts/admin/v1/credential_reference.py:22`); PRP-86 adds `aws_secrets_manager`, `gcp_secret_manager`, `kubernetes_secret`, `vault_kv`, `workload_identity`, and nothing reads them yet.
- "Outside local, only managed identity" is expressed as Azure-only (`packages/core/neurosphere_core/clients/factories.py:56-63`), and the principal pseudonym key reference must be a Key Vault URI (`packages/core/neurosphere_core/auth/scope/pseudonym.py:24,45`; `services/api/neurosphere_api/runtime/pseudonym.py:74-93`; worker `runtime/identity.py:69-80`), so a non-Azure API cannot start with a real key.
- The frontend credential field accepts only the two Azure kinds (`frontend/src/features/admin/sources/credentialReference.ts:4-30`, `types.ts:45-49`).

## Acceptance criteria
- [ ] Key wrapping for interaction content: for each platform a `KeyWrapper` (PRP-102 protocol) implementation exists and is selected by platform: AWS KMS (aws), Google Cloud KMS (gcp), Vault transit (kubernetes and on-prem), each refusing a key reference outside the deployment's allowlist before any network call and never logging key ids beyond the id, URI or material; where no provider is available or verified for a platform, content capture is disabled there with reason `capture_key_wrap_unavailable` and the capability and coverage pages say so, with no plaintext or local-file fallback outside `NS_ENV=local`. Each provider's wrap and unwrap API facts are verify-first.
- [ ] Given a stored connector config whose credential is any supported kind for the active `NS_PLATFORM`, When the worker resolves it, Then the matching reader returns the value as `SecretStr`; Given a kind not supported on the platform (for example `key_vault_secret` on `aws`), Then resolution fails with `credential_reference_invalid` and the role idles with that reason; the Key Vault path on Azure is unchanged (`services/workers/tests/connector_config_worker` passes unmodified).
- [ ] Each reader refuses, before requesting any token or making any call: a `secret_arn` outside the allowlisted accounts and region or not a `secretsmanager` ARN; a `secret_version_name` outside the allowlisted projects; a `kubernetes_secret_name`/`kubernetes_secret_key` pair that fails the name grammar or whose file (`<mount root>/<name>/<key>`) resolves outside the configured mount roots; a `vault_mount`/`vault_path`/`vault_key` outside the allowlisted mount and prefix or an address not exactly equal to the configured one. Hostname checks are exact or leading-dot suffix checks.
- [ ] Every reader failure (refused reference, 4xx, 5xx, timeout, malformed body, token failure) raises the one neutral error with a reason code only; no ARN, resource name, path, secret name or value appears in exceptions, logs (including `httpx` and `botocore` loggers), audit payloads, readiness reasons or OpenAPI examples. A leak test greps all captured output for the reference and the value.
- [ ] Token providers: PostgreSQL pool connects with an RDS IAM token or a Cloud SQL IAM token through the PRP-89 hook; Kafka clients authenticate through the PRP-92 hook for MSK and Managed Kafka; S3 and GCS clients use workload identity credentials; Bedrock and Vertex adapters receive tokens through the PRP-95 hook. Each is proven against recorded transports for request shape, and each UNVERIFIED mechanism has a recorded verification outcome (clarification 5); a mechanism found unsupported is shipped as its fallback and reported disabled with a reason, never silently.
- [ ] Credential guard: outside `NS_ENV=local`, a password, key, connection string with credentials or static access key in any `NS_*` setting of the portable adapters is refused at startup with a reason code; credentials come only from workload identity or a reader reference. Local containers keep working with local-only settings.
- [ ] The pseudonym key reference accepts any secret kind valid for the platform (Key Vault URI on Azure exactly as today); API and workers still refuse a key without a reference and still require equal keys.
- [ ] Vault reader conformance runs against a local OpenBao dev server; AWS and GCP readers against recorded transports; the Kubernetes reader against a temporary mount with the `..data` symlink layout; each suite has a broken reader that skips the allowlist and fails.
- [ ] Frontend: the credential-reference field offers the kinds the deployment's platform supports, validates each client-side as a hint, and never accepts a value-shaped input (for example a string with `-----BEGIN`, `AKIA` prefix or a JWT shape); vitest, lint and typecheck pass.
- PRP exit: touched suites, `tests/security/authz`, ruff, pyright, frontend gates, `validate_planning.py` pass; the OpenBao conformance run passes locally with output recorded; PR open with CI green.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| D-1 | Hosting axis (program decision D-1) | new `DeploymentTarget` axis beside `NS_CLOUD`; widen the cloud enum | Decided by the owner 2026-11-16: a new `DeploymentTarget` axis (`NS_PLATFORM` = azure, aws, gcp, kubernetes; default azure) beside the existing `NS_CLOUD` boundary class; `government` is valid only with azure; canonical IDs are unchanged (they keep the `commercial:` first segment on AWS, GCP and on-prem). Recorded in the PRP-85 multicloud-hosting ADR |
| D-2 | Backend strategy (program decision D-2) | a native service adapter per cloud; one portable backend set | Decided by the owner 2026-11-16: one portable backend set (PostgreSQL, Kafka API, S3 API plus native GCS, generic OIDC, OTLP, OpenAI-compatible/Bedrock/Vertex model adapters) running on each cloud's managed service or in-cluster, not a native service adapter per cloud (no DynamoDB, Firestore or Pub/Sub adapters). Recorded in the PRP-85 multicloud-hosting ADR |
| 3 | Reader clients | official SDKs; HTTP | AWS Secrets Manager through `aiobotocore` (pinned by PRP-87, owner decision D-9 in PRP-85); Google Secret Manager through its REST API over `httpx` with a `google-auth` token; Vault KV over `httpx`; no new dependency. If item 1 finds one missing from `uv.lock`, a `[serial-after: PRP-90, PRP-91]` dependency item is added and reported |
| 4 | Vault reader (owner decision D-8 in PRP-85) | include; defer | Decided 2026-11-16 (D-8): include (works with OpenBao and HashiCorp Vault through the HTTP API); history: had it been deferred, item 3 would drop `vault_kv.py`, the OpenBao fragment and the `NS_SECRETS_VAULT_*` settings without affecting the other readers |
| 5 | UNVERIFIED mechanisms | assume; verify first | Each is the first step of its item, outcome recorded in `docs/runbooks/workload-identity.md`: (a) `aiokafka` SASL support for MSK IAM (OAUTHBEARER plus a signer) and for Google Managed Kafka; fallback SASL/SCRAM or PLAIN over TLS with the password from a reader reference; (b) Cloud SQL IAM database authentication from Python with `asyncpg` without the proxy sidecar (access token as password over TLS); fallback the Cloud SQL Auth Proxy sidecar documented for PRP-96, or a password from Secret Manager; (c) RDS IAM token generation through `botocore` presigning with the pinned version; fallback a password from Secrets Manager |
| 6 | Pseudonym key value | fetched by the app; injected by the platform | ASSUMPTION: the value still arrives by platform injection (environment or mounted file); only the reference grammar widens. Runtime fetch is a follow-up |
| 7 | Azure guard | replace; keep | Keep `_refuse_secrets_outside_local` in `core/clients/factories.py` untouched; the generalised guard lives in the cloudauth package and is called by the portable adapters |
| 8 | Caching | none; short TTL | ASSUMPTION: readers do not cache values; callers keep today's lifetime (resolve at role start). Token providers cache tokens until shortly before expiry |
| 9 | Real cloud runs | now; OPEN | OPEN: every real IAM, Secrets Manager, Secret Manager, MSK, Managed Kafka, RDS and Cloud SQL run needs `NS_LIVE_APPROVED=1`; handed to PRP-98 / PRP-64 |

## Context manifest

### Files to read first
- `temp/audit/multicloud-program-design.md` sections 1.2 ("Secret references", "Client construction"), 3.2 ("Workload identity", "Secret references"), M10 and section 9.
- `PRPs/backlog/PRP-85-*.md`, `PRP-86-*.md`, `PRP-87-*.md`, `PRP-89-*.md`, `PRP-92-*.md`, `PRP-95-*.md` - "Interfaces provided": `SecretReader` and `TokenProvider` ports, new reference kinds and their grammar, the cloudauth package skeleton and pins, the pool, Kafka, object-store and model hooks.
- `services/workers/neurosphere_workers/connector_config/keyvault.py` - reader shape, single reason code, `httpx` log filter.
- `services/workers/neurosphere_workers/connector_config/resolve.py:60-130` - `build_reader`, `_secret`, idle reasons.
- `packages/core/neurosphere_core/admin/connectors/references.py` - `parse_key_vault_secret`, `check_credential_reference`.
- `packages/core/neurosphere_core/clients/factories.py:56-63` - the Azure credential guard to mirror.
- `packages/core/neurosphere_core/auth/scope/pseudonym.py:20-60` - `PseudonymKey` reference rule.
- `services/api/neurosphere_api/runtime/pseudonym.py`, `services/workers/neurosphere_workers/runtime/identity.py:60-90` - key resolution on both sides.
- `frontend/src/features/admin/sources/credentialReference.ts`, `CredentialReferenceField.tsx`, `types.ts`.

### Interfaces consumed
- PRP-85 (`neurosphere_core.platform`): `ports.SecretReader` (`read(reference) -> SecretStr`; item 1 re-points the worker Protocol in `connector_config/keyvault.py` to it), the registry of platform settings (the `NS_SECRETS_*` and `NS_WORKLOAD_IDENTITY` rows are this PRP's), `ports.TokenProvider` (`get_token(*scopes) -> AccessToken(token: SecretStr, expires_on)`, `close()`), `DeploymentTarget`, `registry.PortName.secret_reader` / `token_provider` and `BackendRegistry` with the `neurosphere.backends` entry-point group. The worker-local `TokenProvider = Callable[[], Awaitable[str]]` in `keyvault.py` is adapted, not duplicated.
- PRP-86: `CredentialReference.kind` values `aws_secrets_manager`, `gcp_secret_manager`, `kubernetes_secret`, `vault_kv`, `workload_identity` with per-kind members (`secret_arn`, `secret_version_name`, `kubernetes_secret_name`, `kubernetes_secret_key`, `vault_mount`, `vault_path`, `vault_key`, `workload_identity_subject`) and `check_credential_reference` per platform; regenerated TypeScript types.
- PRP-87: `packages/adapters-cloudauth` skeleton with `aiobotocore`, `google-auth` pinned; licence rows.
- PRP-89: `create_pool(settings, *, token_provider=...)`, `NS_POSTGRES_AUTH=token`.
- PRP-92: Kafka client and SIEM sink authentication hook, S3 and GCS client credential hook (names per PRP-92 "Interfaces provided").
- PRP-95: model and judge adapters taking a `TokenProvider` (Bedrock, Vertex, OpenAI-compatible) and the PostgreSQL analytics executor taking an injected pool factory; PRP-95's tests inject static providers and this PRP wires the real ones (item 6).

### Interfaces provided
- Package `neurosphere_adapters_cloudauth`: `readers/` (`AwsSecretsManagerReader`, `GcpSecretManagerReader`, `KubernetesSecretFileReader`, `VaultKvReader`), `ReaderSet` (dispatch by kind, platform-supported kinds table, Key Vault reader registered on Azure), `SecretReaderUnavailableError` (reason `credential_unavailable`); `tokens/` (`eks_credentials`, `gke_credentials`, `rds_iam_token_provider`, `cloudsql_iam_token_provider`, `msk_auth`, `managed_kafka_auth`, `bedrock_token`, `vertex_token`); `guard.refuse_static_credentials(settings, **values)`.
- Settings (env prefix `NS_SECRETS_`): `AWS_ACCOUNTS`, `AWS_REGION`, `GCP_PROJECTS`, `K8S_MOUNT_ROOTS`, `VAULT_ADDRESS`, `VAULT_MOUNT`, `VAULT_PATH_PREFIX`, `VAULT_AUTH` (`kubernetes`), `VAULT_ROLE`; `NS_WORKLOAD_IDENTITY` (`azure|eks|gke|none`).
- Compose fragment `infra/compose/portable/secrets.yml` (OpenBao dev server, own project name, `127.0.0.1`).

### Patterns to match
- Reader with one reason code and a log filter: `connector_config/keyvault.py:40-140`.
- Reference parse before any call: `admin/connectors/references.py:70-95`.
- Recorded HTTP transports: `services/workers/tests/connector_config_worker/test_keyvault_reader.py`.
- Contract kit plus broken implementation: `tests/unit/connector_conformance/test_reference_connectors_conformance.py`.

### Gotchas
- CodeQL fails a PR that logs a secret-named variable; do not interpolate `secret`, `password`, `token` names into log messages even when the value is a reference. Hostname checks need a leading dot (`host == base or host.endswith("." + base)`).
- `botocore` logs request URLs and headers at DEBUG; install a filter like `_DropVaultRequests` for the `botocore` and `aiobotocore` loggers and test it.
- Kubernetes secret volumes are symlinks into a `..data` directory; resolve the real path and check it stays under the mount root, rather than refusing all symlinks.
- RDS and Cloud SQL tokens expire (minutes); the pool must ask for a token per new connection, not once at start.
- A test fixture must never contain a real-looking key (gitleaks fingerprints are commit-scoped): build fake values at runtime.
- Only one session may run the portable compose fragments; PRP-90 is the W37 compose-stack holder, and this PRP's OpenBao steps run `[serial-after: PRP-90, PRP-91]` (after both released the lane).
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/adapters-cloudauth/neurosphere_adapters_cloudauth/**
  - packages/adapters-cloudauth/tests/**
  - services/workers/neurosphere_workers/connector_config/**
  - services/workers/tests/connector_config_readers/**
  - services/workers/neurosphere_workers/runtime/identity.py
  - services/api/neurosphere_api/runtime/pseudonym.py
  - services/api/tests/runtime_pseudonym_platforms/**
  - packages/core/neurosphere_core/auth/scope/pseudonym.py
  - tests/conformance/secrets/**
  - tests/security/authz/test_secret_reference*.py
  - infra/compose/portable/secrets.yml
  - frontend/src/features/admin/sources/credentialReference.ts
  - frontend/src/features/admin/sources/credentialReference.test.ts
  - frontend/src/features/admin/sources/CredentialReferenceField.tsx
  - frontend/src/features/admin/sources/types.ts
  - docs/runbooks/workload-identity.md
  - docs/runbooks/connector-config.md
tier1: []
tier2_appends:
  - services/workers/neurosphere_workers/runtime/settings.py
  - services/api/neurosphere_api/runtime/settings.py
  - mkdocs.yml
must_not_touch:
  - packages/adapters-cloudauth/pyproject.toml
  - packages/adapters-postgres/**
  - packages/adapters-kafka/**
  - packages/adapters-objectstore/**
  - packages/adapters-models/**
  - packages/contracts/**
  - packages/core/neurosphere_core/admin/connectors/references.py
  - packages/core/neurosphere_core/clients/factories.py
  - services/api/neurosphere_api/runtime/builders/**
  - services/workers/neurosphere_workers/runtime/factories.py
  - pyproject.toml
  - uv.lock
  - infra/helm/**
```

## Implementation blueprint

Parallelization: item 1 first. Items 2 and 3 [P] after item 1. Items 4 and 5 [P] after item 1. Item 6 after 2-5. Item 7 [P] after item 1. Item 8 last.

### Item 1 - Reader set and Key Vault behind it
- Deliverable: first step, confirm in `uv.lock` the pinned `aiobotocore` and `google-auth` versions and their licence rows (record them; if missing, add the `[serial-after]` item of clarification 3). Then `ReaderSet` dispatching by kind with a per-platform supported-kinds table, the neutral error, the static-credential guard, and the Key Vault reader registered unchanged; `connector_config/resolve.py` builds the reader set instead of a lone Key Vault reader.
- Owned files: `neurosphere_adapters_cloudauth/{__init__,reader_set,errors,guard,settings}.py`, `connector_config/resolve.py`, `connector_config/keyvault.py` (registration only), `packages/adapters-cloudauth/tests/test_reader_set.py`, `test_guard.py`.
- Must NOT touch: `references.py`, `factories.py`.
- Depends on: PRP-86, PRP-89, PRP-92, PRP-95 merged.
- Acceptance criteria: criteria 1 and 5; existing `services/workers/tests/connector_config_worker` passes unchanged.
- Tests: the files above plus `services/workers/tests/connector_config_readers/test_resolve_platforms.py`.
- Pattern references: `connector_config/resolve.py:60-130`.

### Item 2 - AWS Secrets Manager and Google Secret Manager readers  [P]
- Deliverable: `readers/aws_secrets_manager.py` (ARN parse and allowlist, `GetSecretValue` through `aiobotocore`, `SecretString` only, binary refused), `readers/gcp_secret_manager.py` (resource-name parse and allowlist, `versions/<n>:access` REST call, base64 payload decode); log filters; recorded transports for success, 400, 403, 404, 429, 5xx, timeout, malformed body.
- Owned files: those two modules, `packages/adapters-cloudauth/tests/readers_cloud/**`, `tests/conformance/secrets/{checks,broken,test_aws_recorded,test_gcp_recorded}.py`.
- Depends on: item 1.
- Acceptance criteria: criteria 2, 3 and 7 for both readers.
- Tests: the files above.
- Pattern references: `connector_config/keyvault.py:95-140`.

### Item 3 - Kubernetes secret file and Vault KV readers  [P] (OpenBao run `[serial-after: PRP-90, PRP-91]`)
- Deliverable: `readers/kubernetes_file.py` (mount-root allowlist, real-path check, size cap, UTF-8 only), `readers/vault_kv.py` (exact address, mount and prefix allowlist, Kubernetes auth login with the projected service-account token, KV v2 read); compose fragment `infra/compose/portable/secrets.yml`; OpenBao conformance with marker `portable`.
- Owned files: those modules, the fragment, `packages/adapters-cloudauth/tests/readers_local/**`, `tests/conformance/secrets/{test_kubernetes_file,test_openbao}.py`.
- Depends on: item 1.
- Acceptance criteria: criteria 2, 3 and 7; traversal and symlink escape refused.
- Tests: the files above.
- Pattern references: `keyvault.py`, PRP-89 `tests/conformance/conftest.py`.

### Item 4 - Database IAM tokens  [P]
- Deliverable: first step, verify and record (c) RDS token generation and (b) Cloud SQL IAM without the proxy (clarification 5) with a recorded transport or a local signature check; then `tokens/rds.py` and `tokens/cloudsql.py` as PRP-89 pool token providers with expiry-aware caching, plus the documented fallback for any mechanism found unsupported.
- Owned files: `tokens/{__init__,rds,cloudsql,cache}.py`, `packages/adapters-cloudauth/tests/tokens_db/**`.
- Depends on: item 1.
- Acceptance criteria: criterion 4 for the database; pool asks for a fresh token per new connection (test with a fake pool).
- Tests: `packages/adapters-cloudauth/tests/tokens_db/test_rds.py`, `test_cloudsql.py`.
- Pattern references: `keyvault.py` `default_vault_token_provider`.

### Item 5 - Broker, bucket and model credentials  [P]
- Deliverable: first step, verify and record (a) `aiokafka` SASL support for MSK IAM and Google Managed Kafka; then `tokens/kafka.py` (MSK and Managed Kafka through the PRP-92 hook, or the SCRAM/PLAIN fallback with a reader reference), `tokens/workload.py` (EKS and GKE credential sources for S3, GCS, Bedrock and Vertex via `aiobotocore` and `google-auth`), handed to the PRP-92 and PRP-95 hooks.
- Owned files: `tokens/{kafka,workload}.py`, `packages/adapters-cloudauth/tests/tokens_services/**`.
- Depends on: item 1.
- Acceptance criteria: criterion 4 for broker, buckets and models; fallback reported as a readiness reason (`kafka_iam_unsupported` or similar), never silent.
- Tests: `packages/adapters-cloudauth/tests/tokens_services/test_kafka_auth.py`, `test_workload.py`.
- Pattern references: PRP-92 and PRP-95 hook tests.

### Item 6 - Pseudonym key reference and composition wiring
- Deliverable: `PseudonymKey` accepts any secret-reference kind valid for the platform (Key Vault rule unchanged on Azure); API `runtime/pseudonym.py` and worker `runtime/identity.py` validate through the reader set's kind table; `NS_WORKLOAD_IDENTITY` and `NS_SECRETS_*` Tier-2 settings fields; registration of the real token providers for the PRP-89 pool, the PRP-92 Kafka and object-store clients and the PRP-95 model adapters, and of PRP-89's pool as the PRP-95 analytics executor's pool factory, through the PRP-87/PRP-88 seams (in `neurosphere_adapters_cloudauth.registration`) without builder edits (if impossible, `[serial-after: PRP-90, PRP-91]` and report).
- Owned files: `auth/scope/pseudonym.py`, `services/api/neurosphere_api/runtime/pseudonym.py`, `services/workers/neurosphere_workers/runtime/identity.py`, Tier-2 lines, `services/api/tests/runtime_pseudonym_platforms/**`.
- Depends on: items 2-5.
- Acceptance criteria: criterion 6; `services/api/tests/runtime_api/test_pseudonym_key.py` passes unchanged.
- Tests: `services/api/tests/runtime_pseudonym_platforms/test_reference_kinds.py`, `services/workers/tests/connector_config_readers/test_worker_key.py`.
- Pattern references: `runtime/pseudonym.py:60-95`.

### Item 7 - Frontend credential field  [P]
- Deliverable: kind list from the regenerated contract types filtered by the platform the API reports; per-kind hint patterns; value-shape refusal.
- Owned files: `credentialReference.ts`, `credentialReference.test.ts`, `CredentialReferenceField.tsx`, `types.ts`.
- Depends on: item 1 (kind table).
- Acceptance criteria: criterion 8; existing `sources.test.tsx` passes.
- Tests: `frontend/src/features/admin/sources/credentialReference.test.ts` (new), `sources.test.tsx`.
- Pattern references: `credentialReference.ts` today.

### Item 8 - Integration and close-out
- Deliverable: secrecy suite `tests/security/authz/test_secret_reference_leaks.py` (criterion 3 over every reader and token provider); `docs/runbooks/workload-identity.md` (per platform: identity binding, allowlists, verification outcomes of clarification 5, fallbacks, OPEN runs) and a `connector-config.md` section; `mkdocs.yml` line; rebase, Tier-3 regeneration; `changelog.d/PRP-94-secret-readers-and-workload-identity.md`; completion note with env vars and the product check.
- Owned files: the suite, runbooks, Tier-2 lines, this PRP file, Tier-3 files.
- Depends on: items 1-7.
- Acceptance criteria: validation gates pass; CI green.

## Cut line
The Vault transit key-wrap provider (and, if the session overruns, the Google Cloud KMS one) is the cuttable unit: what remains merges safely because capture is then disabled on that platform with reason `capture_key_wrap_unavailable`, recorded in the completion note with a follow-up issue. The secret readers, database IAM tokens and broker, bucket and model credentials are never cut.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q packages/adapters-cloudauth/tests services/workers/tests/connector_config_worker services/workers/tests/connector_config_readers services/api/tests/runtime_api services/api/tests/runtime_pseudonym_platforms packages/core/tests/auth tests/conformance/secrets tests/security/authz
docker compose -f infra/compose/portable/secrets.yml up -d --wait
python scripts/portable/run_conformance.py --backend secrets
docker compose -f infra/compose/portable/secrets.yml down -v
pnpm --filter @neurosphere/frontend lint
pnpm --filter @neurosphere/frontend typecheck
pnpm --filter @neurosphere/frontend test
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
No data migration: stored connector configs with Key Vault references keep resolving on Azure; new kinds are accepted only where the platform supports them. Turn off: `NS_WORKLOAD_IDENTITY=none` and Key Vault references on Azure behave as today. Revert: revert the PR; stored configs that use a new kind then fail closed with `credential_reference_invalid` (the worker role idles), never fall back to a plaintext path.

## Live and open gates
None run here. OPEN: AWS Secrets Manager, Google Secret Manager, EKS and GKE workload identity, RDS IAM and Cloud SQL IAM database auth, MSK and Managed Kafka auth, S3, GCS, Bedrock and Vertex tokens against real services, and a real Vault or OpenBao cluster with Kubernetes auth. Each needs `NS_LIVE_APPROVED=1` and an operator; handed to PRP-98, recorded with PRP-64.

## NOT building
Writing or rotating secrets; caching secret values; MCP outbound credential providers; Secrets Store CSI parameters and Helm identity blocks; Terraform IAM; Azure workload identity changes; AWS GovCloud or Google Assured Workloads.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (D-1 and D-2 were decided by the owner 2026-11-16; rows 6 and 8 are ASSUMPTIONS; row 4 is owner decision D-8 in PRP-85; row 5 outcomes are settled inside items 4 and 5; hook names depend on PRP-89, PRP-92 and PRP-95 as merged)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | todo | | |
| 2 | todo | | |
| 3 | todo | | |
| 4 | todo | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | |
| 8 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an operator configure and use it without editing files or calling raw APIs?):
