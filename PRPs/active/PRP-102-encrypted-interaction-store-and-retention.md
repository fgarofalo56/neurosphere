---
name: PRP-102-encrypted-interaction-store-and-retention
status: active
priority: P0
order: 102
review: required
created: 2026-11-16
model: opus
orchestrator_model: opus
implementer_model: opus
phase: 9
ns: NS-01, NS-08
depends_on: [PRP-99-governance-contracts-a]
wave: W21
branch: prp-102-encrypted-interaction-store
allow_parallel: true
issues: []
---

# PRP-102: Encrypted interaction store, retention and legal hold

## Goal
Ship the place where opt-in captured interaction content lives, and nothing that puts content into it. It adds an envelope-encryption helper (`neurosphere_core.crypto`: AES-256-GCM with a fresh data key per content blob, the data key wrapped by a Key Vault key through the workload identity, a local file key only under `NS_ENV=local`), an interaction store port whose write API accepts only already-redacted content (blob-backed encrypted content plus a Cosmos metadata index `interaction_index`), the lifecycle data class `interaction_content` with legal-hold support and a purge that deletes blob and index together, and the first real use of `RetentionPolicy.retain_prompt_response_bodies`: no content can be written unless the customer's retention policy opts in. As the W21 stores owner it also declares the containers PRP-105 and PRP-107 consume. It is for PRP-103 (edge capture, W22), PRP-104 (explorer, W23) and PRP-83 (data-subject requests, W32). Opus: it is the only place in the product where captured content rests.

Out of scope: detection and redaction (PRP-101); deciding what to capture and calling the store (PRP-103); reading content for people, export, replay (PRP-104); wiring the lifecycle target into the worker composition (`workers/runtime/factories.py` is Tier-1; PRP-103 carries it as a `[serial-after: PRP-107]` item); the hosted Key Vault key, blob container and RBAC (PRP-109); a live key wrap (PRP-136); key-wrap providers for AWS, GCP or Vault (PRP-94); DSR erase and export over this data class (PRP-83).

## Why
- The owner asked on 2026-11-16 for "the ultimate team AI governance and auditing tool" with every identified gap planned; interaction audit (G-a) needs a store that is safe by construction. `docs/PRD.md:26` (NS-05) already promises "Payload access, retention, export and legal hold follow policy."
- There is no application-level encryption anywhere in the tree (design G-a; `docs/compliance/ssp/families/sc.md:72` "Encryption at rest is a platform service capability").
- The retention opt-in exists and is dead: `RetentionPolicy.retain_prompt_response_bodies` is a required field (`packages/core/neurosphere_core/lifecycle/policy.py:35-39`) surfaced as `PolicyState.bodies_retained` (`:58-61`) and `LifecycleEngine.bodies_retained` (`lifecycle/engine.py:157-158`); nothing reads it outside tests.
- The lifecycle engine is ready to take a new data class: precedence `AUDIT_IMMUTABILITY > LEGAL_HOLD > MIN_RETENTION > SUBJECT_REQUEST > MAX_RETENTION_EXPIRY` (`lifecycle/models.py:24-31`), `LegalHold` selectors including `data_class` (`models.py:138-157`), the `LifecycleTarget` protocol (`lifecycle/targets.py:23-58`) and `build_targets` (`services/workers/neurosphere_workers/lifecycle/assembly.py:57-93`).
- A Key Vault REST pattern without a vendor SDK already exists: `services/workers/neurosphere_workers/connector_config/keyvault.py:1-9,36-52,95-140` (host check per cloud, workload-identity token, httpx, request-URL log filter).
- `cryptography` is only transitive today (via `pyjwt[crypto]` in `packages/core/pyproject.toml`), locked at `uv.lock:499-500`, with rows already in `docs/licenses.md:50` and `docs/adr/0002-stack-pins.md:146`; a direct dependency still needs the licence gate re-run and the ADR row updated to "direct".

## Acceptance criteria
- [ ] Given redacted content and a key wrapper, When stored, Then the blob holds only a versioned envelope (format version, key id with version, wrapped data key, nonce, ciphertext and tag); a byte scan of every written blob finds none of the synthetic canary strings in the content; associated data binds customer, domain, interaction id and format version, so a blob copied to another interaction id fails to decrypt with `content_integrity_failed`.
- [ ] The store write API takes only PRP-99's `RedactedContent` (whose `redaction_state` admits only `redacted` and `not_required`) and validates it against the `RedactedContent` JSON Schema, including the `secret_free_text` `not` patterns, before any I/O (Pydantic ignores `not`, ADR-0004); a failure is refused with `content_not_secret_free` and nothing is written; there is no write method that takes `str` or `bytes`. The index document validates as `InteractionRecord`, whose `content_ref` (`pointer`, `kek_uri`, `algorithm: aes_256_gcm`, `ciphertext_sha256`, `byte_length`) is the only link to the blob and holds no plaintext hash.
- [ ] Given `PolicyState.bodies_retained` false (no policy, invalid policy, or opt-in false) or no `interaction_content` rule in the policy, Then every write is refused with `content_retention_not_enabled` and nothing is written; the refusal is counted, not logged with content.
- [ ] `KeyVaultKeyWrapper` checks the vault host against the deployment cloud before requesting a token (a Government deployment refuses a Commercial vault host and the reverse) and never logs the vault URI, key name or any key material; `LocalFileKeyWrapper` refuses to construct unless `NS_ENV=local`.
- [ ] Given a legal hold selecting `data_class=interaction_content` (or a record or subject), When expiry runs in `execute` mode, Then held records are kept and the outcome records `LEGAL_HOLD`; unheld expired records are purged with blob and index removed together; a purge interrupted after the blob delete is completed on the next run and a read of such a record answers `content_purged`.
- [ ] The lifecycle target's `export` returns index metadata only, never content; `pseudonymize` deletes the content blob and pseudonymizes the index record (content cannot be pseudonymized in place) - ASSUMPTION row 6.
- [ ] Containers `interaction_index`, `interaction_capture_policies`, `policy_definitions`, `policy_violations`, `policy_exceptions` and `notification_outbox` are in `stores/containers.py`, the exported `infra/compose/cosmos-containers.json` matches (`python -m neurosphere_core.stores --check`) and the hosted-demo container drift test passes.
- [ ] `cryptography` is a direct dependency of `packages/core`, the licence report passes, and ADR-0002 states the verified version and that it is direct.
- PRP exit: touched suites, `tests/security/interaction_store`, ruff, pyright, `validate_planning.py` pass; PR open with CI green.

## Clarifications (decided)
| # | Question | Options offered | Decision |
|---|----------|-----------------|----------|
| 1 | Reverse the metadata-only decision | keep; reverse for opt-in | Decided by the owner 2026-11-16 (GD-14): the 2026-11-06 metadata-only decision is reversed for opt-in capture only; capture stays OFF by default and "bodies disabled by default" stays true; the orchestrator records it in the decision log. Here: this PRP stores nothing by itself |
| 2 | Retention default for content | 30 days; 90 days; match telemetry | Decided by the owner 2026-11-16 (GD-5): content is kept 90 days by default (the owner chose 90 over the recommended 30), no minimum, each deployment can set its own value, legal hold overrides; retaining bodies must be set explicitly in the retention policy. Here: two inputs: PRP-99 `CapturePolicy.retention_days` (default 90, 1-365) and the customer retention policy, which is never defaulted (`lifecycle/policy.py:1-5`). `InteractionRecord.expires_at` is the earlier of the two; a retention policy without an `interaction_content` rule disables writes; the runbook's sample rule uses `max_retention_days: 90` |
| 3 | Key-encryption key | Key Vault key wrap; Key Vault secret as KEK; platform only | Key Vault key wrap/unwrap over REST (design 2.1), verify-first (U-1). Decided by the owner 2026-11-16 (GD-18): if Key Vault key wrap is unavailable in a cloud, content capture is disabled there (`key_wrap_unavailable`); no weaker fallback (such as a Key Vault secret as the key-encryption key) is built |
| 4 | Crypto library | `cryptography`; another vetted library | `cryptography` AESGCM, verify-first (U-2): API, licence and the version in `uv.lock` re-checked at execution, never from memory |
| 5 | Where capture policies live | `admin_config` kind; own container | Own container `interaction_capture_policies` (partition `/customer_id`, `/domain_id`), declared here as the W21 stores owner; capture policies are NOT an `admin_kind` (PRP-99 clarification 3; `CapturePolicy` carries its own `version`); PRP-103 builds `CapturePolicyStore` over it and PRP-108 changes it only through PRP-103's functions |
| 6 | DSR export and pseudonymize on content | include content; metadata only | ASSUMPTION: lifecycle export returns metadata only (content export is PRP-104's audited path); pseudonymize deletes the blob. PRP-83 confirms the DSR semantics |
| 7 | Blob location and key settings | env vars; stored setting | The PRP-99 stored-setting member `InteractionCaptureSetting` (`kek_provider` `key_vault_key` or `local_development`, `kek_uri`, `content_storage_account_resource_id`, `content_container`, `credential`) is the configuration source; `InteractionSettings` is built from it. Only `NS_INTERACTION_LOCAL_KEY_FILE` is an env var (local key path, `NS_ENV=local` only). ASSUMPTION: the content container is created on first use only under `NS_ENV=local` (Azurite); hosted creation is PRP-109 |

## Context manifest

### Files to read first
- `services/workers/neurosphere_workers/connector_config/keyvault.py` - REST, host check, token provider, log filter.
- `packages/core/neurosphere_core/lifecycle/{policy,targets,models,engine}.py` - policy, protocol, holds, precedence.
- `packages/core/neurosphere_core/lifecycle/archive_backend.py` - a blob-backed lifecycle target (name validation, unsupported operations reported, not faked).
- `packages/core/neurosphere_core/ledger/lifecycle_delete.py:133` and `catalog/lifecycle_delete.py:160` - target factories.
- `services/workers/neurosphere_workers/lifecycle/assembly.py:57-93` - `build_targets`.
- `packages/core/neurosphere_core/stores/containers.py:94-160` - `ContainerSpec` rows; `stores/__main__.py` export.
- `packages/core/neurosphere_core/mcp/cosmos_store.py:86-140` - ETag create and replace.
- `PRPs/backlog/PRP-99-governance-contracts-a.md` "Interfaces provided" (Interactions; `InteractionCaptureSetting`) - the record, redacted content and settings shapes.

### Interfaces consumed
- PRP-99 (W20): `neurosphere_contracts.interactions.v1` `InteractionRecord` (index document: ids, agent, tool, service, model, principal pseudonym, policy id and version, `redaction_state` `redacted`|`not_required`|`redaction_failed`, `parts`, `content_ref` or null, `findings_summary`, `sensitivity_categories`, `data_asset_ids`, `retention_class`, `expires_at`, `legal_hold_ids`; no content property), `RedactedContent` and `secret_free_text`, `DetectionFinding`, `CapturePolicy` (`retention_days`); `admin/v1` `InteractionCaptureSetting` and validator `check_kek_uri_cloud`; container names fixed in its conventions paragraph.
- Shipped: `LifecycleTarget`, `TargetRecord`, `LegalHold`, `load_policy_file`, `NS_LIFECYCLE_POLICY_FILE`, `neurosphere_core.cloud` (`CloudName`, `profile_for`, `NS_ENV`), `clients.factories.blob_account_url`.

### Interfaces provided
- `neurosphere_core.crypto`: `KeyWrapper` protocol (`key_id`, `wrap(data_key) -> WrappedKey`, `unwrap(WrappedKey) -> bytes`), `KeyVaultKeyWrapper`, `LocalFileKeyWrapper`, `Envelope` (format version, key id, wrapped key, nonce, ciphertext), `seal(plaintext, aad, wrapper) -> Envelope`, `open_envelope(envelope, aad, wrapper) -> bytes`; reasons `key_wrap_unavailable`, `content_integrity_failed`, `key_host_refused`.
- `neurosphere_core.interactions`: `InteractionStore` protocol (`put`, `get_metadata`, `read_content`, `query_index`, `delete`), `InMemoryInteractionStore` (tests and `NS_ENV=local`), `BlobInteractionContent`, `CosmosInteractionIndex`, `InteractionSettings.from_setting(InteractionCaptureSetting, cloud)` (plus `NS_INTERACTION_LOCAL_KEY_FILE` for `local_development`), `validate_redacted_content(doc)` (JSON Schema check), `content_writes_enabled(policy_state) -> bool`.
- Lifecycle: `DATA_CLASS_INTERACTION = "interaction_content"`, `interaction_target(name, backend)`, `build_targets(..., interaction_index=None, interaction_blobs=None)`.
- Containers: `interaction_index` and `interaction_capture_policies` (`/customer_id`, `/domain_id` and `/customer_id`), `policy_definitions`, `policy_violations`, `policy_exceptions` (`/customer_id`, `/domain_id`; owner module names `neurosphere_core.governance.policy.cosmos_store`), `notification_outbox` (`/customer_id`, `default_ttl=TTL_PER_ITEM` so PRP-107 sets the expiry per row; owner `neurosphere_core.notifications.cosmos_store`).
- Runbook `docs/runbooks/interaction-audit.md` (created here; PRP-103 and PRP-104 add sections).

### Patterns to match
- REST to Key Vault with httpx, host check, no SDK: `connector_config/keyvault.py:95-140`.
- Lifecycle blob target that refuses rather than fakes: `lifecycle/archive_backend.py:1-10,164`.
- Local-only fallback that refuses elsewhere: the recorded copilot mode rule (D15 in `docs/DECISIONS-LOG.md`) and `runtime/builders/blob.py:7-12`.
- Container rows: `stores/containers.py:98-160`.

### Gotchas
- UNVERIFIED (design U-1): Key Vault keys expose wrap and unwrap over REST usable with the workload identity, in Commercial and Government; the RBAC role that grants only wrap and unwrap; the key types and algorithms; the API version. Item 1 fetches the Microsoft documentation and records each fact with URL and date. If false: capture disabled in that cloud with `key_wrap_unavailable` (no silent fallback).
- UNVERIFIED (design U-2): `cryptography` provides AES-GCM with the API assumed, and its licence passes the gate as a direct dependency. If false: another vetted library; the lockfile owner stays this PRP.
- CodeQL fails PRs on logging names that look like secrets: never log `key`, `wrapped_key`, `data_key` variables even as reason extras; reason codes only. Add `httpx` URL filtering as `keyvault.py:45-52` does for the key endpoints.
- Test keys are generated at runtime (`os.urandom`), never committed; gitleaks scans fixtures.
- Nonces are random 96-bit per seal and a data key is never reused across blobs; a test asserts distinct nonces and wrapped keys for two seals of the same plaintext.
- A new workspace dependency must be visible to all five `uv --frozen` Dockerfiles; `cryptography` is already in the lock, so only `pyproject.toml` and `uv.lock` change, but run the Dockerfile closure check anyway.
- `infra/demo/modules/cosmos-data.bicep` inlines the JSON export through `loadJsonContent` (`tests/unit/hosted_demo/test_cosmos_container_drift.py:1-6`); expect to regenerate the JSON, not hand-edit Bicep.
Shared rules and traps: `PRPs/reference/parallel-build-reference.md`.

## Ownership
```ownership
owns:
  - packages/core/neurosphere_core/crypto/**
  - packages/core/neurosphere_core/interactions/__init__.py
  - packages/core/neurosphere_core/interactions/models.py
  - packages/core/neurosphere_core/interactions/settings.py
  - packages/core/neurosphere_core/interactions/store.py
  - packages/core/neurosphere_core/interactions/cosmos_index.py
  - packages/core/neurosphere_core/interactions/blob_content.py
  - packages/core/neurosphere_core/interactions/lifecycle_delete.py
  - packages/core/tests/envelope_crypto/**
  - packages/core/tests/interaction_store/**
  - services/workers/neurosphere_workers/lifecycle/assembly.py
  - services/workers/tests/lifecycle_interactions/**
  - tests/security/interaction_store/**
  - docs/runbooks/interaction-audit.md
tier1:
  - packages/core/neurosphere_core/stores/containers.py
  - infra/compose/cosmos-containers.json
  - infra/demo/modules/cosmos-data.bicep
  - packages/core/pyproject.toml
  - pyproject.toml
  - uv.lock
  - docs/licenses.md
  - docs/adr/0002-stack-pins.md
tier2_appends:
  - mkdocs.yml
must_not_touch:
  - services/workers/neurosphere_workers/runtime/factories.py
  - services/api/**
  - packages/core/neurosphere_core/payload/**
  - packages/core/neurosphere_core/lifecycle/**
  - packages/core/neurosphere_core/classification/**
  - packages/contracts/**
  - infra/demo/main.bicep
  - infra/helm/**
```

## Implementation blueprint

Parallelization: item 1 first; items 2 and 3 [P]; item 4 after 3; item 5 after 4; item 6 after 5; item 7 last.

### Item 1 - Verify-first: Key Vault key wrap and the crypto library
- Deliverable: fetch Microsoft Learn pages for Key Vault key wrap and unwrap (REST operation, API version, request and response fields, supported key types and algorithms, the least-privilege data-plane role, Government host suffix, service throttling limits for wrap and unwrap, since every captured interaction costs one wrap and every read one unwrap) and the `cryptography` documentation and licence for AES-GCM; record each fact, URL and retrieval date in `docs/runbooks/interaction-audit.md` "Verification". Record U-1 and U-2 as confirmed or false; if false, stop and report before item 3.
- Owned files: `docs/runbooks/interaction-audit.md`.
- Must NOT touch: code.
- Depends on: PRP-99 merged.
- Acceptance criteria: every external fact used by items 3 and 4 has a cited source; nothing from memory.
- Tests: none (documentation).
- Pattern references: `docs/connectors/` verification style (design 2.5).

### Item 2 - Stores and lockfiles (Tier-1, first commit)  [P]
- Deliverable: the six containers in "Interfaces provided" added to `CONTAINERS`; JSON export regenerated; `cryptography` added to `packages/core/pyproject.toml` dependencies with the bound the lock already resolves; `uv lock` refreshed; licence report row and ADR-0002 row updated to direct use with the version verified in item 1.
- Owned files: Tier-1 files listed in the ownership block.
- Must NOT touch: any other PRP's module.
- Depends on: item 1 (version and licence).
- Acceptance criteria: criterion 7 and 8; `python -m neurosphere_core.stores --check` passes; the five Dockerfiles still resolve with `uv sync --frozen` (closure check noted in the item).
- Tests: `packages/core/tests/stores_registry`, `tests/unit/hosted_demo/test_cosmos_container_drift.py`.
- Pattern references: `stores/containers.py:140-160`.

### Item 3 - Envelope encryption and key wrappers  [P]
- Deliverable: `neurosphere_core/crypto/` with `Envelope`, `seal`, `open_envelope`, `KeyWrapper`, `KeyVaultKeyWrapper` (httpx, workload-identity token provider, cloud host check, timeouts, reason codes), `LocalFileKeyWrapper` (`NS_ENV=local` only; key file created with owner-only permissions under the path given, refused elsewhere).
- Owned files: `packages/core/neurosphere_core/crypto/**`, `packages/core/tests/envelope_crypto/**`.
- Must NOT touch: `connector_config/keyvault.py` (copy the pattern, do not import worker code into core).
- Depends on: item 1.
- Acceptance criteria: criteria 1 (cryptographic part) and 4; tampered ciphertext, tag, AAD or key id fails with `content_integrity_failed`; a fake transport proves wrap and unwrap requests carry no plaintext.
- Tests: `packages/core/tests/envelope_crypto/test_envelope.py`, `test_keyvault_wrapper.py`, `test_local_wrapper.py`.
- Pattern references: `connector_config/keyvault.py:68-140`.

### Item 4 - Interaction store: index and encrypted content
- Deliverable: `interactions/{models,settings,store,cosmos_index,blob_content}.py`: JSON Schema validation of `RedactedContent`, `InteractionStore` and the in-memory twin, Cosmos index over `interaction_index` (metadata from PRP-99's interaction record, bounded queries by agent, principal pseudonym, time, tool, data asset, detected category), blob content (one envelope per interaction, name `{customer}/{domain}/{yyyy}/{mm}/{dd}/{interaction_id}.env`), retention gate `content_writes_enabled`.
- Owned files: the `interactions` modules listed in the ownership block, `packages/core/tests/interaction_store/**`.
- Must NOT touch: `interactions/{policy,capture}.py` (PRP-103).
- Depends on: items 2 and 3.
- Acceptance criteria: criteria 1-3; the index document validates as PRP-99's interaction record and has no content field; queries are partition-scoped and page-bounded.
- Tests: `packages/core/tests/interaction_store/test_store.py`, `test_retention_gate.py`, `test_index_queries.py`.
- Pattern references: `mcp/cosmos_store.py:86-140`, `lifecycle/archive_backend.py:33-40` (strict blob names).

### Item 5 - Lifecycle data class, holds and purge
- Deliverable: `interactions/lifecycle_delete.py` with `interaction_target` (get, list by data class and subject, delete blob then index, pseudonymize per row 6, metadata-only export); `build_targets` gains optional `interaction_index` and `interaction_blobs` arguments (absent means not registered, as today for the archive).
- Owned files: `interactions/lifecycle_delete.py`, `services/workers/neurosphere_workers/lifecycle/assembly.py`, `services/workers/tests/lifecycle_interactions/**`.
- Must NOT touch: `workers/runtime/factories.py` (wired by PRP-103's serial item), `lifecycle/**` core engine.
- Depends on: item 4.
- Acceptance criteria: criteria 5 and 6 through the real engine with in-memory backends; existing `lifecycle_worker` and `packages/core/tests/lifecycle` suites pass unchanged.
- Tests: `services/workers/tests/lifecycle_interactions/test_interaction_target.py`, `test_holds_beat_expiry.py`, plus `services/workers/tests/lifecycle_worker`, `packages/core/tests/lifecycle`.
- Pattern references: `ledger/lifecycle_delete.py:133`, `lifecycle/archive_backend.py:164`.

### Item 6 - Security negative suite
- Deliverable: tests that write synthetic content with canaries and a generated fake credential-shaped value already replaced by a placeholder, then assert: no canary in blob bytes, index documents, logs (caplog at DEBUG over the whole run) or exception text; no key material or vault URI in logs; cross-cloud vault host refused; writes refused for each non-redacted state and when retention is off.
- Owned files: `tests/security/interaction_store/**`.
- Must NOT touch: shared authz harness.
- Depends on: item 5.
- Acceptance criteria: criteria 1-4 proven end to end.
- Tests: `tests/security/interaction_store/test_no_plaintext_at_rest.py`, `test_no_key_material_logged.py`, `test_refusals.py`.
- Pattern references: `tests/security/authz/test_admin_producers_secrecy.py`.

### Item 7 - Integration and close-out
- Deliverable: runbook sections (envelope format, key rotation by new key version with old versions still unwrapping, the sample retention policy rule, how capture stays impossible until a policy opts in, purge and hold behaviour); `mkdocs.yml` nav line; changelog fragment; Tier-3 regeneration; completion note with the env vars and the hosted needs handed to PRP-109 (key, role assignment, blob container) and the live wrap handed to PRP-136.
- Owned files: runbook, `mkdocs.yml` (one line), this PRP file, changelog fragment, Tier-3 files.
- Depends on: items 1-6.
- Acceptance criteria: validation gates pass; CI green.

## Validation gates
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run python -m neurosphere_core.stores --check
uv run pytest -q packages/core/tests/envelope_crypto packages/core/tests/interaction_store packages/core/tests/stores_registry packages/core/tests/lifecycle services/workers/tests/lifecycle_interactions services/workers/tests/lifecycle_worker tests/security/interaction_store tests/unit/hosted_demo packages/core/tests/test_import_boundaries.py tests/docs/test_nav_allowlist.py
python scripts/licenses_report.py --check
python scripts/prp_status.py --check
python scripts/validate_planning.py
powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/verify-gates.ps1 -Mode full
```

## Migration and rollback
New containers are additive and empty. No existing data changes. The store writes nothing unless a retention policy opts in AND PRP-103 calls it, so rollback before PRP-103 is a plain revert. After capture exists, turning `retain_prompt_response_bodies` off stops writes immediately; stored content expires through its rule (no mass delete); legal holds keep held content. Reverting the code leaves encrypted blobs that cannot be read without this code and the key; purge them first through the lifecycle API (`lifecycle.manage`).

## Live and open gates
None run here. A real Key Vault wrap and unwrap, the hosted blob container and the role assignment are OPEN: provisioned by PRP-109 and evidenced by PRP-136 with `NS_LIVE_APPROVED=1`.

## NOT building
- Content capture, detection or any reader for people (PRP-103, PRP-101, PRP-104).
- A Key Vault secret used as a key-encryption key, or capture without a key wrap; customer-managed key rotation automation; HSM-specific options.
- Key-wrap providers for AWS KMS, GCP KMS or Vault transit (PRP-94; content capture is disabled on those platforms until then).
- Any statement that encryption makes content "compliant"; no FedRAMP, ATO or compliance claim.

## Definition of Ready check
- [x] Every item has owned files declared
- [x] Every item has acceptance criteria and pattern references
- [x] Gates are executable commands, not intentions
- [ ] All clarification questions are decided, not guessed (rows 1-2 are GD decisions made 2026-11-16; rows 5-7 are ASSUMPTIONS; U-1 and U-2 are verify-first)

## Execution state
| Item | Status | Branch/worktree | Notes |
|---|---|---|---|
| 1 | merged | orchestrator, `prp-102-encrypted-interaction-store` | 2026-11-25 s-30eda2: plan approved by the owner (Opus implementers; items 2 and 3 parallel; independent review on items 3, 4, 5; rows 5-7 kept as ASSUMPTIONS). U-1 and U-2 confirmed, see runbook "Verification". Finding: `key-version` is a required wrap/unwrap path segment and `kek_uri` may omit it, so item 3 resolves the current version through Get Key. Runbook nav line pulled forward from item 7 (the nav test requires it) |
| 2 | merged | `prp-102-item-2-stores` (43e3f882, merge 7f0409b9) | Six containers; `cryptography>=50.0.2,<51` and `jsonschema>=4.26,<5` (orchestrator scope addition for item 4's runtime schema check) now direct in core; uv.lock +4 lines, no version change. `docs/licenses.md` is generated and unchanged (rows already right); "direct" recorded in ADR-0002's hand-kept table. Orchestrator fixed `tests/unit/hosted_demo/test_cosmos_container_drift.py` count 32 to 38 (b2ab7de4). Verified: stores --check, 111 passed (stores_registry, hosted_demo, registry parity, Dockerfiles), licences PASS |
| 3 | merged | `prp-102-item-3-crypto` (e044e051, merge d5eea651; review fixes cfc2af61) | Verified on integration: 77 passed, ruff, pyright clean; Snyk code scan 0 issues. Independent review APPROVE (no blockers). Orchestrator applied 2 suggestions: unwrap 400 maps to `content_integrity_failed`; public entry points re-raise through `without_context` (no `__context__` chain). Deviations: URI checks run in the constructor; local wrapper refusal is `InvalidSchemaError(reason="config")`; `seal` over 2^31-1 raises `ValueError("content_too_large")`; no 429 retry (callers own backoff). Follow-up issue at close-out: cap Key Vault response size, unlink a partly written local key file, refuse a group/other-readable local key file |
| 4 | in-progress | | |
| 5 | todo | | |
| 6 | todo | | |
| 7 | todo | | |

## Completion note (filled at ship)
- Date and PR:
- Deviations:
- Descoped items:
- OPEN gates:
- Env vars for the operator:
- Follow-up issues:
- Product check (can an operator use it without editing files):
