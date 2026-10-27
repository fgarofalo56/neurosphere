// Key Vault Secrets User for app identities, scoped to the existing vault (PRP-32 D4).
targetScope = 'resourceGroup'

@description('Name of the existing Key Vault in this resource group.')
param vaultName string

@description('Object (principal) ids that may read secrets (the API, and the workers if they resolve the pseudonym key).')
param principalIds array

// Built-in Key Vault Secrets User role definition id.
var keyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: vaultName
}

resource assignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in principalIds: {
    scope: vault
    name: guid(vault.id, principalId, keyVaultSecretsUser)
    properties: {
      principalId: principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUser)
    }
  }
]
