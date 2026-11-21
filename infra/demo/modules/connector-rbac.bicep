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

@description('PRP-139: object (principal) id of the API managed identity. Needed only with apimServiceName.')
param apiPrincipalId string = ''

@description('PRP-139: name of an existing Log Analytics workspace in this resource group the gateway_poll role queries. Empty skips the assignment. Log Analytics Data Reader for the workers identity on that workspace only; no table-level condition (follow-up).')
param logAnalyticsWorkspaceName string = ''

@description('PRP-139: name of an existing API Management service in this resource group the API reads through ARM at gateway registration. Empty skips the assignment. API Management Service Reader Role for the API identity on that service only.')
param apimServiceName string = ''

// Foundry User (formerly Azure AI User). Learn: use the role definition id, not the name.
var foundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
// Built-in Storage Blob Data Reader role definition id.
var storageBlobDataReader = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
// PRP-139, verified against Microsoft Learn 2026-11-21: Log Analytics Data Reader.
var logAnalyticsDataReader = '3b03c2da-16b3-4a49-8834-0f8130efdd3b'
// PRP-139, verified against Microsoft Learn 2026-11-21: API Management Service Reader Role.
var gatewayServiceReaderRole = '71522526-b88f-4d52-b57f-d31fc3546d0d'

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = if (!empty(logAnalyticsWorkspaceName)) {
  name: empty(logAnalyticsWorkspaceName) ? 'unused' : logAnalyticsWorkspaceName
}

resource apimService 'Microsoft.ApiManagement/service@2023-09-01-preview' existing = if (!empty(apimServiceName)) {
  name: empty(apimServiceName) ? 'unused' : apimServiceName
}

resource workspaceReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(logAnalyticsWorkspaceName)) {
  scope: logAnalyticsWorkspace
  name: guid(logAnalyticsWorkspace.id, workersPrincipalId, logAnalyticsDataReader)
  properties: {
    principalId: workersPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', logAnalyticsDataReader)
  }
}

resource apimReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(apimServiceName)) {
  scope: apimService
  name: guid(apimService.id, apiPrincipalId, gatewayServiceReaderRole)
  properties: {
    principalId: apiPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', gatewayServiceReaderRole)
  }
}

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
