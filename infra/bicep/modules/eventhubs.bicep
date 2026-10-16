// Event Hubs namespace: reuse-or-create. Local (SAS) auth disabled; access is by RBAC only.
targetScope = 'resourceGroup'

@description('Name of the Event Hubs namespace to create. Ignored when reuse is set.')
param name string

@description('Azure region for the namespace. Ignored when reuse is set.')
param location string

@description('Existing Event Hubs namespace resource id to reuse. Empty means create a new namespace.')
param reuse string = ''

@description('Resource tags applied to created resources only.')
param tags object = {}

@description('Public network access for the created namespace.')
@allowed(['Enabled', 'Disabled'])
param publicNetworkAccess string = 'Disabled'

@description('Namespace SKU.')
@allowed(['Standard', 'Premium'])
param skuName string = 'Standard'

resource namespace 'Microsoft.EventHub/namespaces@2024-01-01' = if (empty(reuse)) {
  name: name
  location: location
  tags: tags
  sku: {
    name: skuName
    tier: skuName
    capacity: 1
  }
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
    publicNetworkAccess: publicNetworkAccess
  }
}

@description('Resource id of the Event Hubs namespace in use (reused or newly created).')
output id string = empty(reuse) ? namespace.id : reuse

@description('True when this module created the namespace.')
output created bool = empty(reuse)
