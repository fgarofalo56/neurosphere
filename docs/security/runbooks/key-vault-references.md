# Runbook: consuming secrets through Key Vault references

Scope: how NeuroSphere components obtain a secret without it ever appearing in
a file, a Helm value, a Bicep parameter, a log or a prompt. Related:
[secret-rotation.md](secret-rotation.md), `SECURITY.md`, `docs/SECURITY.md`.

## Order of preference

1. **Managed identity / workload identity, no secret at all.** Cosmos, Event
   Hubs, Storage and AI Search are reached with Entra tokens and Azure RBAC.
   Prefer disabling local (key/SAS) authentication on those resources.
2. **Key Vault reference** when a secret is unavoidable (for example a
   third-party connector credential). The workload holds a pointer to the
   vault object, never the value.
3. **Never**: literals in values files, `.env` committed, Bicep parameters
   carrying a secret, container image layers, CI logs.

## Where references are used

### Kubernetes (Helm): Secrets Store CSI

`infra/helm/templates/secretproviderclass.yaml` renders a `SecretProviderClass`
(provider `azure`) only when `secretProviderClass.enabled` is true. Inputs, from
`infra/helm/values.yaml`:

- `secretProviderClass.keyVaultName`: required when enabled (`<vault-name>`).
- `secretProviderClass.tenantId`: required when enabled.
- `serviceAccount.workloadIdentity.clientId`: required; the pod authenticates
  with workload identity (`usePodIdentity` stays `"false"`).
- `secretProviderClass.objects`: list of `{name, type}` (secret, key or cert).
  These are object names, never values.

Rule: the `env:` map in values stays free of secrets; values are mounted from
the CSI volume.

### App Service / Container Apps

Use a Key Vault reference in the app setting or the Container Apps secret
(`keyVaultUrl` plus a user-assigned managed identity), for example a setting
whose value is the reference syntax pointing at
`https://<vault-name>.<keyvault-dns-suffix>/secrets/<secret-name>`. Grant the
identity the `Key Vault Secrets User` role on that vault only. Pin no version in
the reference when you want rotation to flow through (see rotation runbook).

### Bicep

`infra/bicep/modules/keyvault.bicep` creates or reuses the vault with RBAC
authorization (no access policies), soft delete, purge protection and public
network access disabled by default. In templates:

- Pass secrets to modules only as `@secure()` parameters resolved by
  `getSecret()` on an existing vault resource, or as a `reference` in a
  parameter file (`reference.keyVault.id` plus `secretName`). Never as a
  literal.
- Do not output secrets from any module.
- Role assignments use RBAC on the vault, scoped to the consuming identity.

## Commercial versus Government vault DNS

Derive the vault DNS suffix from `environment().suffixes.keyvaultDns` (see the
`keyVaultDnsSuffix` output in `infra/bicep/modules/main.bicep`). Do not
hardcode a `vault.azure.net` or Government equivalent in code, values or
docs. Government and Commercial vaults are separate; never copy a secret from
one cloud to the other to fill a gap.

## Local development

- Use emulators (`docker compose up -d --wait`); no paid calls and no cloud
  secrets.
- Copy `.env.example` (placeholders only) to an untracked `.env`. `.env` is
  git-ignored and blocked by `.githooks/` and CI.
- The dev token issuer is allowed only when `NS_ENV=local`; any other value
  must use the real Entra issuer.

## Verifying a reference works (presence and behaviour, not value)

- `az keyvault secret show --vault-name <vault-name> --name <secret-name> --query attributes`
  shows enabled state and dates without printing the value (do not omit
  `--query`).
- Check the pod mount lists the object name (file exists) and that the
  dependent API call returns a success status.
- Never echo, log or paste a secret value into a ticket, chat or file.
