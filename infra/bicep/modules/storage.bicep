// Storage account: reuse-or-create. Shared key access disabled; access is by RBAC only.
targetScope = 'resourceGroup'

@description('Name of the storage account to create (3-24 lowercase alphanumerics). Ignored when reuse is set.')
@minLength(3)
@maxLength(24)
param name string

@description('Azure region for the account. Ignored when reuse is set.')
param location string

@description('Existing storage account resource id to reuse. Empty means create a new account.')
param reuse string = ''

@description('Resource tags applied to created resources only.')
param tags object = {}

@description('Public network access for the created account.')
@allowed(['Enabled', 'Disabled'])
param publicNetworkAccess string = 'Disabled'

@description('Storage SKU.')
@allowed(['Standard_LRS', 'Standard_GRS', 'Standard_ZRS'])
param skuName string = 'Standard_LRS'

resource account 'Microsoft.Storage/storageAccounts@2023-05-01' = if (empty(reuse)) {
  name: name
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: skuName
  }
  properties: {
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: publicNetworkAccess
    defaultToOAuthAuthentication: true
  }
}

@description('Resource id of the storage account in use (reused or newly created).')
output id string = empty(reuse) ? account.id : reuse

@description('True when this module created the account.')
output created bool = empty(reuse)
