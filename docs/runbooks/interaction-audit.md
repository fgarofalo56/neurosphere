# Interaction audit: encrypted content store

Status date: 2026-11-25. This runbook covers where opt-in captured interaction content rests
(PRP-102). Capture itself (PRP-103) and the explorer (PRP-104) add their own sections later.
Nothing in this runbook makes the product capture content: capture stays off by default, and the
store refuses every write until the customer retention policy opts in.

## What exists after PRP-102

| Piece | Where | State |
|---|---|---|
| Envelope encryption | `neurosphere_core.crypto` | Built, tested with a fake Key Vault and the local key |
| Interaction store (index plus encrypted content) | `neurosphere_core.interactions` | Built; nothing calls it until PRP-103 |
| Lifecycle data class `interaction_content` | `neurosphere_core.interactions.lifecycle_delete`, `build_targets` | Built; registered only when the worker passes the backends (PRP-103 wires it) |
| Cosmos containers | `interaction_index`, `interaction_capture_policies`, `policy_definitions`, `policy_violations`, `policy_exceptions`, `notification_outbox` | Declared in the registry and the IaC export; empty |
| Hosted Key Vault key, role assignment, content blob container | PRP-109 | OPEN |
| Live wrap and unwrap against a real vault | PRP-136 (`NS_LIVE_APPROVED=1`) | OPEN |

## Why capture is impossible until a policy opts in

Two independent gates must both be open before a single byte of content is stored:

1. The customer retention policy (`NS_LIFECYCLE_POLICY_FILE`, see the lifecycle runbook) sets
   `retain_prompt_response_bodies: true` AND has a rule for the data class `interaction_content`.
   No policy, an invalid policy, the opt-in set to false, or no such rule refuses every write with
   `content_retention_not_enabled`. The refusal is counted on `ns.interactions.store.refusals`
   (attribute `ns.reason`); content is never logged.
2. An approved capture policy exists for the domain and source (PRP-103). Until PRP-103 ships,
   nothing calls the store at all.

Sample retention policy rule (the 90-day default chosen by the owner, GD-5):

```json
{
  "policy_version": "records-2026-2",
  "retain_prompt_response_bodies": true,
  "rules": [
    {"data_class": "interaction_content", "min_retention_days": 0, "max_retention_days": 90}
  ]
}
```

A real policy also lists every other data class it governs; one `data_class` may appear once.

## What the store accepts

The write API takes only a PRP-99 `RedactedContent` document, never a string or bytes. Before
any I/O the document is validated against the `RedactedContent` JSON Schema, including the
`secret_free_text` patterns that Pydantic ignores (ADR-0004). A failure is refused with
`content_not_secret_free` and nothing is written. The schema is vendored as package data
(`interactions/redacted_content.schema.json`) because the contract schema files are not in the
runtime images; a drift test rebuilds the bundle from the contract and compares it byte for byte.

The index document is a PRP-99 `InteractionRecord`: metadata only. Its `content_ref` (blob
pointer, key identifier, `aes_256_gcm`, SHA-256 of the stored envelope, byte length) is the only
link to the content, and it holds no hash of plaintext.

## Envelope format

One blob per interaction, named `<customer>/<domain>/<yyyy>/<mm>/<dd>/<interaction_id>.env`
(the domain id is percent-encoded where it contains a slash). The blob is a versioned binary
envelope, big-endian:

| Field | Size |
|---|---|
| Magic `NSEV` | 4 bytes |
| Format version (1) | 1 byte |
| Key identifier (versioned Key Vault key id, or `local:` plus a fingerprint) | 2-byte length, up to 512 bytes |
| Wrap algorithm (`RSA-OAEP-256`, or `local-a256gcm`) | 1-byte length, up to 64 bytes |
| Wrapped data key | 2-byte length, up to 2048 bytes |
| Nonce | 1-byte length, exactly 12 bytes |
| Ciphertext with the 16-byte GCM tag | 4-byte length |

Each interaction gets a fresh 256-bit data key and a fresh random 96-bit nonce. The GCM
associated data binds the customer, domain, interaction id and format version plus the envelope
header (version, key id, wrap algorithm), so a blob copied to another interaction, or a header
edited in place, fails with `content_integrity_failed`. Reads check the stored byte length and
SHA-256 before decrypting.

## Key configuration

The configuration source is the stored setting `InteractionCaptureSetting` (PRP-99):
`kek_provider` (`key_vault_key` or `local_development`), `kek_uri`, the content storage account
and container, and the identity reference used to reach them.

| `kek_provider` | Where it works | Key |
|---|---|---|
| `key_vault_key` | every environment | An RSA key (2048 or 3072 bits recommended) in a vault that uses the Azure RBAC permission model. The workload identity needs only `Key Vault Crypto Service Encryption User` on that key or vault. `kek_uri` is `https://<vault>.vault.azure.net/keys/<name>` (Commercial) or `.vault.usgovcloudapi.net` (Government), with or without a version. |
| `local_development` | `NS_ENV=local` only; refused everywhere else | A 32-byte key file at `NS_INTERACTION_LOCAL_KEY_FILE`, created on first use with owner-only permissions. Never copy it anywhere else. |

The vault host must match the deployment cloud: a Government deployment refuses a Commercial
vault and the reverse (`key_host_refused`), before any token is requested. The vault URI, key
name, key identifier and key material are never logged; `httpx` request logs for key operations
are filtered.

## Key rotation

Create a new version of the same Key Vault key. When `kek_uri` has no version, new interactions
wrap with the current version (resolved once per process; restart the workers to pick up a new
version promptly). Every envelope records the exact versioned key id it was wrapped with, and
unwrap always uses that recorded version, so old versions keep decrypting old content. Do not
disable or delete an old key version while content wrapped by it is still retained; once all
such content has expired (at most the retention rule's maximum after the rotation), the old
version may be disabled. A recorded key id that names a different vault or key is refused.

## Purge, holds and expiry

- Expiry runs through the lifecycle engine for the data class `interaction_content`. A record is
  due at the earlier of its own `expires_at` (the earlier of the capture policy's
  `retention_days` and the rule's `max_retention_days`) and `captured_at` plus the rule's
  `max_retention_days`, never before `min_retention_days`.
- A legal hold that selects `data_class=interaction_content`, a record, or a subject keeps the
  record; the outcome records `LEGAL_HOLD`.
- A purge deletes the blob first, then the index document, and deletes only the blob name the
  store computes for that interaction, never a pointer read from the document. A purge
  interrupted between the two steps reads as `content_purged` and is completed by the next run.
- Lifecycle export returns index metadata only and never decrypts. Pseudonymize deletes the
  content blob and clears `principal_id` and `content_ref` (content cannot be pseudonymized in
  place; PRP-83 confirms the data-subject semantics).
- Turning `retain_prompt_response_bodies` off stops new writes immediately; stored content then
  expires through its rule. Reverting the code leaves blobs nothing can read: purge them first
  through the lifecycle API (`lifecycle.manage`).

## Reason codes

| Reason | Meaning |
|---|---|
| `content_retention_not_enabled` | The retention policy does not opt in (see above); nothing written |
| `content_not_secret_free` | The content failed the `RedactedContent` schema; nothing written |
| `content_integrity_failed` | Tampered or mismatched envelope, header, size, hash or key id |
| `key_wrap_unavailable` | Key Vault unreachable, throttled (429), timed out or answered badly |
| `key_host_refused` | The `kek_uri` is malformed or names another cloud's vault |
| `content_purged` | The index exists but its content was purged |
| `interaction_not_found`, `interaction_exists` | Read of an unknown id; second write of the same id |
| `content_record_mismatch`, `interaction_index_invalid` | The index document disagrees with the content or the contract |
| `interaction_store_unavailable`, `content_container_missing` | Cosmos or blob storage unavailable; the content container is missing outside `NS_ENV=local` |
| `invalid_query` | An index query or continuation token that does not belong to that query |

Orphan blobs left by a failed index write are counted on `ns.interactions.store.orphan_cleanup`
(attribute `ns.outcome`: `removed`, `failed`, or `kept` when the outcome of the write is unknown).

## Verification

Every external fact the encryption code relies on was read from the cited page on the status
date. Nothing here is from memory. U-1 and U-2 are the design's verify-first unknowns.

### U-1: Key Vault key wrap and unwrap over REST (confirmed)

| Fact | Value | Source (retrieved 2026-11-25) |
|---|---|---|
| Wrap operation | `POST {vaultBaseUrl}/keys/{key-name}/{key-version}/wrapkey?api-version=2025-07-01`; needs the `keys/wrapKey` permission | [Wrap Key](https://learn.microsoft.com/en-us/rest/api/keyvault/keys/wrap-key/wrap-key) |
| Unwrap operation | `POST {vaultBaseUrl}/keys/{key-name}/{key-version}/unwrapkey?api-version=2025-07-01`; needs the `keys/unwrapKey` permission | [Unwrap Key](https://learn.microsoft.com/en-us/rest/api/keyvault/keys/unwrap-key/unwrap-key) |
| `key-version` | A required path parameter on both operations. A key identifier without a version must be resolved to its current version first (Get Key, which the role below allows through `keys/read`). | same pages |
| Request body | `alg` (required), `value` (required, base64url); `aad`, `iv`, `tag` are optional and only for authenticated symmetric algorithms | same pages |
| Response body | `KeyOperationResult`: `kid` (the versioned key identifier), `value` (base64url). The published wrap sample shows standard base64 characters in `value`, so the decoder accepts both alphabets. | same pages |
| Token scope | `https://vault.azure.net/.default` (Commercial); the Government vault scope is `https://vault.usgovcloudapi.net/.default`, the same scopes the connector-config secret reader already uses | same pages; [Key Vault DNS suffixes](https://learn.microsoft.com/azure/key-vault/general/about-keys-secrets-certificates#dns-suffixes-for-object-identifiers) |
| Algorithm used | `RSA-OAEP-256` on RSA keys (2048, 3072, 4096 bits), software or HSM. `RSA-OAEP` and `RSA1_5` are "not recommended" and are not accepted by this product. AES key wrap (`A256KW`) needs an `oct-HSM` key, which a vault supports only on the Premium tier. | [Key types, algorithms, and operations](https://learn.microsoft.com/azure/key-vault/keys/about-keys-details); [About keys](https://learn.microsoft.com/azure/key-vault/keys/about-keys#key-types-and-protection-methods) |
| Least-privilege role | `Key Vault Crypto Service Encryption User` (`e147488a-f6f5-4113-8e2d-b22465e65bf6`): data actions `keys/read`, `keys/wrap/action`, `keys/unwrap/action` only. Works only on vaults that use the Azure RBAC permission model. | [Built-in roles: Security](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/security#key-vault-crypto-service-encryption-user); [Key Vault RBAC guide](https://learn.microsoft.com/azure/key-vault/general/rbac-guide#azure-built-in-roles-for-key-vault-data-plane-operations) |
| Vault host per cloud | Commercial `<vault>.vault.azure.net`; Azure US Government `<vault>.vault.usgovcloudapi.net`. Data-plane key operations (including `wrapKey` and `unwrapKey`) go to this host in both clouds. | [Key Vault DNS suffixes](https://learn.microsoft.com/azure/key-vault/general/about-keys-secrets-certificates#dns-suffixes-for-object-identifiers); [Compare Azure Government and global Azure](https://learn.microsoft.com/azure/azure-government/compare-azure-government-global-azure#guidance-for-developers); [Access Key Vault behind a firewall](https://learn.microsoft.com/azure/key-vault/general/access-behind-firewall#control-plane-endpoints) |
| Throttling | Per vault per region, per 10 seconds, "all other transactions" (wrap and unwrap included): RSA 2048 software 4,000, HSM 2,000; RSA 3072 software 1,000, HSM 500; RSA 4096 software 500, HSM 250. Limits are weighted and enforced on their sum; the subscription-wide limit is five times the per-vault limit. Exceeding them returns HTTP 429. | [Azure Key Vault service limits](https://learn.microsoft.com/azure/key-vault/general/service-limits) |
| Retry guidance | Clients that call the REST API directly should retry with exponential backoff on throttling. | [Reliability in Azure Key Vault](https://learn.microsoft.com/azure/reliability/reliability-key-vault#resilience-to-transient-faults) |

What this means for capacity: each captured interaction costs one wrap, and each content read
costs one unwrap. With an RSA 2048 software key, one vault absorbs about 400 such operations per
second before it returns 429. Use RSA 2048 or 3072 for the key-encryption key, not 4096.

Not verified on any page: a Government-specific statement that the role and the wrap operations
behave identically there. The DNS-suffix and data-plane pages list Government with the same key
operations; a live wrap in each cloud is evidence owed by PRP-136 (gate OPEN). If a cloud turns out
not to support key wrap, content capture is disabled there with `key_wrap_unavailable`. No weaker
fallback, such as a Key Vault secret used as the key-encryption key, is built (GD-18).

### U-2: the `cryptography` library for AES-256-GCM (confirmed)

| Fact | Value | Source (retrieved 2026-11-25) |
|---|---|---|
| Version | `cryptography` 50.0.2, already in the lockfile as a transitive dependency; the same version is imported in the workspace environment | `uv.lock`; `importlib.metadata.version("cryptography")` |
| Licence | `Apache-2.0 OR BSD-3-Clause` (package `License-Expression` metadata), already an allowed row in the licence report | installed package metadata; [cryptography on PyPI](https://pypi.org/project/cryptography/) |
| Key | `AESGCM.generate_key(bit_length=256)` returns a random key; bit length 128, 192 or 256 | [AEAD docs, 50.0.2](https://github.com/pyca/cryptography/blob/50.0.2/docs/hazmat/primitives/aead.rst) |
| Encrypt | `AESGCM(key).encrypt(nonce, data, associated_data)` returns the ciphertext with the 16-byte tag appended; never reuse a nonce with a key; NIST recommends a 96-bit (12-byte) nonce | same page |
| Decrypt | `AESGCM(key).decrypt(nonce, data, associated_data)`; raises `cryptography.exceptions.InvalidTag` when the ciphertext, key, nonce or associated data is wrong | same page |
| Size limit | `encrypt` raises `OverflowError` when data or associated data exceeds 2^31 - 1 bytes | same page |

A local round trip (`encrypt` then `decrypt` with associated data) was run against the installed
50.0.2 on the status date and returned the plaintext.
