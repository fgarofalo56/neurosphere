# Interaction audit: encrypted content store

Status date: 2026-11-25. This runbook covers where opt-in captured interaction content rests
(PRP-102). Capture itself (PRP-103) and the explorer (PRP-104) add their own sections later.
Nothing in this runbook makes the product capture content: capture stays off by default, and the
store refuses every write until the customer retention policy opts in.

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
