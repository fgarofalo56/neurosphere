// PRP-58 item 1: identity roles the connector worker roles need (#220), assigned to the workers
// identity only and only at the scope of one named resource, never at resource-group or
// subscription scope.
//   - Foundry User (the role formerly named Azure AI User; the id is unchanged by the rename and is
//     verified against Microsoft Learn, "Azure built-in roles", AI + machine learning) on one
//     Foundry account: reader access to the account and its projects, for foundry_discovery.
//   - Storage Blob Data Reader on one storage account: the Cost Management export container, for
//     billing_export.
// The Key Vault Secrets User role for the producer secret already exists (keyvault-rbac.bicep).
//
// main.bicep deploys this module once per entry at that entry's own resource group scope, because
// a Foundry account or the export storage account can live in another group or subscription. Each
// deployment names exactly one target; the other name stays empty and creates nothing.
targetScope = 'resourceGroup'

@description('Object (principal) id of the workers managed identity.')
param workersPrincipalId string

@description('Name of an existing Foundry (Cognitive Services) account in this resource group. Empty skips the Foundry assignment.')
param foundryAccountName string = ''

@description('Name of an existing storage account in this resource group that holds the Cost Management export container. Empty skips the Blob assignment.')
param exportStorageAccountName string = ''

// Foundry User (formerly Azure AI User). Learn: use the role definition id, not the name.
var foundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
// Built-in Storage Blob Data Reader role definition id.
var storageBlobDataReader = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (!empty(foundryAccountName)) {
  name: empty(foundryAccountName) ? 'unused' : foundryAccountName
}

resource exportStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = if (!empty(exportStorageAccountName)) {
  name: empty(exportStorageAccountName) ? 'unused' : exportStorageAccountName
}

resource foundryReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(foundryAccountName)) {
  scope: foundryAccount
  name: guid(foundryAccount.id, workersPrincipalId, foundryUser)
  properties: {
    principalId: workersPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUser)
  }
}

resource blobReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(exportStorageAccountName)) {
  scope: exportStorage
  name: guid(exportStorage.id, workersPrincipalId, storageBlobDataReader)
  properties: {
    principalId: workersPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataReader)
  }
}
