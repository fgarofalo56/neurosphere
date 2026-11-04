// Azure AI Search service: reuse-or-create. API-key auth disabled; access is by RBAC only.
targetScope = 'resourceGroup'

@description('Name of the search service to create. Ignored when reuse is set.')
param name string

@description('Azure region for the service. Ignored when reuse is set.')
param location string

@description('Existing search service resource id to reuse. Empty means create a new service.')
param reuse string = ''

@description('Resource tags applied to created resources only.')
param tags object = {}

@description('Public network access for the created service.')
@allowed(['Enabled', 'Disabled'])
param publicNetworkAccess string = 'Disabled'

@description('Search SKU.')
@allowed(['basic', 'standard', 'standard2'])
param skuName string = 'standard'

resource service 'Microsoft.Search/searchServices@2023-11-01' = if (empty(reuse)) {
  name: name
  location: location
  tags: tags
  sku: {
    name: skuName
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    disableLocalAuth: true
    publicNetworkAccess: publicNetworkAccess == 'Enabled' ? 'enabled' : 'disabled'
  }
}

@description('Resource id of the search service in use (reused or newly created).')
output id string = empty(reuse) ? service.id : reuse

@description('True when this module created the service.')
output created bool = empty(reuse)

var serviceNameInUse = empty(reuse) ? name : last(split(reuse, '/'))
var searchSuffix = environment().name == 'AzureUSGovernment' ? '.search.azure.us' : '.search.windows.net'

@description('Service name in use: the created name, or the last segment of the reused resource id.')
output serviceName string = serviceNameInUse

@description('Data-plane endpoint (host only, no key). Callers use Entra ID/managed identity; set NS_SEARCH_SERVICE to serviceName.')
output endpoint string = 'https://${serviceNameInUse}${searchSuffix}/'
