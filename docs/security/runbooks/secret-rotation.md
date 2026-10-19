# Runbook: secret rotation

Applies to any secret that cannot be eliminated by managed identity. All
secrets are consumed through Key Vault references
([key-vault-references.md](key-vault-references.md)). This runbook names no
secret values and no real vault names; use `<vault-name>`, `<secret-name>`.

## Principles

- Prefer removing the secret: managed identity, workload identity, and disabling
  local auth (key/SAS) on storage, Event Hubs and Cosmos where supported.
- Rotate by **overlap**: create a new version, move consumers, then revoke the
  old one. Never rotate in a single destructive step.
- Verify by **presence and behaviour, never the value**.
- Rotation is a change: record who, when, which object and which version id (not
  the value) in the change record.

## Secret classes, cadence and procedure

| Class | Preferred state | Cadence | Notes |
|---|---|---|---|
| Connector credentials (provider APIs) | Least-privilege, read-only where possible | 90 days, or on any suspicion | Stored as a Key Vault secret; connector reads via reference |
| Entra app client secret | Replace with managed identity or a certificate | Secret 90 days at most; certificate per policy | Keep two valid credentials during overlap |
| Entra app certificate | Key Vault certificate with auto-renew | Before expiry, per vault policy | Renew creates a new version |
| Storage / Event Hubs / Cosmos keys | Local auth disabled, none issued | Only if ever enabled: 90 days | Use primary/secondary alternation |
| Federated or CI credentials | Workload identity federation, no secret | n/a | |

Cadences are defaults; the operator may tighten them. They are not a
compliance claim (control narratives belong to PRP-23).

## Procedure (dual-version overlap)

1. **Announce** the window to the operator. Confirm no incident is open (if one
   is, use [credential-leak-response.md](credential-leak-response.md) instead).
2. **Create the new credential** at the provider (second client secret, secondary
   key, new connector token). Do not revoke the old one.
3. **Add a new Key Vault secret version** under the same `<secret-name>`:
   set it via the portal or CLI reading from a secure prompt or pipeline
   secret, never a literal on the command line or in shell history.
4. **Let consumers pick it up.** CSI mounts refresh on the driver's rotation
   interval; App Service/Container Apps references without a pinned version
   refresh automatically; restart pods if rotation polling is off.
5. **Verify behaviour** (below) against the new version.
6. **Revoke the old credential** at the provider, then disable the old Key Vault
   version (`az keyvault secret set-attributes --enabled false` on the old
   version id).
7. **Re-verify** and close the change record.

## Verification (never print the value)

- Presence and state:
  `az keyvault secret show --vault-name <vault-name> --name <secret-name> --query attributes`
  (check `enabled`, `expires`, `updated`).
- Versions: `az keyvault secret list-versions --vault-name <vault-name> --name <secret-name> --query "[].{id:id,enabled:attributes.enabled}"`.
- Behaviour: call the dependent API or connector health endpoint and expect a
  success status; confirm the old credential now fails with an authorization
  status.
- Pods: confirm the mounted object exists and the workload reports healthy.

## Rollback

While the old credential is still valid (before step 6), pin consumers to the
previous Key Vault secret version id (the versioned reference, not the
versionless one) and restart them. Key Vault cannot make an older version
"latest" without writing its value again, so do not try. After step 6,
rollback is a forward fix: issue another new credential. Never restore a
credential believed compromised.

## Expiry and drift

- Set `expires` on every secret; alert via Azure Monitor on near-expiry.
- Soft delete and purge protection are on (`infra/bicep/modules/keyvault.bicep`);
  a deleted secret can be recovered within the retention window.
- Quarterly: list secrets with no expiry and fix them.
