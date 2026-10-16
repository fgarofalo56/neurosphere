// Key Vault: reuse-or-create. RBAC authorization on; no access policies.
targetScope = 'resourceGroup'

@description('Name of the key vault to create (3-24 chars). Ignored when reuse is set.')
@minLength(3)
@maxLength(24)
param name string

@description('Azure region for the vault. Ignored when reuse is set.')
param location string

@description('Existing key vault resource id to reuse. Empty means create a new vault.')
param reuse string = ''

@description('Resource tags applied to created resources only.')
param tags object = {}

@description('Public network access for the created vault.')
@allowed(['Enabled', 'Disabled'])
param publicNetworkAccess string = 'Disabled'

@description('Microsoft Entra tenant id that owns the vault.')
param tenantId string = tenant().tenantId

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = if (empty(reuse)) {
  name: name
  location: location
  tags: tags
  properties: {
    tenantId: tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
    publicNetworkAccess: toLower(publicNetworkAccess)
  }
}

@description('Resource id of the key vault in use (reused or newly created).')
output id string = empty(reuse) ? vault.id : reuse

@description('True when this module created the vault.')
output created bool = empty(reuse)
