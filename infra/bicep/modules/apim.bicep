// API Management: reuse-or-create. Reuse is the expected enterprise path; a reused
// instance is never modified by this module (no writes against the reused id).
targetScope = 'resourceGroup'

@description('Name of the API Management service to create. Ignored when reuse is set.')
param name string

@description('Azure region for the service. Ignored when reuse is set.')
param location string

@description('Existing API Management resource id to reuse. Empty means create a new service.')
param reuse string = ''

@description('Resource tags applied to created resources only.')
param tags object = {}

@description('Publisher contact email. Required only when creating.')
param publisherEmail string = ''

@description('Publisher organization name. Required only when creating.')
param publisherName string = ''

@description('API Management SKU for a created service.')
@allowed(['Developer', 'Standard', 'Premium'])
param skuName string = 'Developer'

resource service 'Microsoft.ApiManagement/service@2022-08-01' = if (empty(reuse)) {
  name: name
  location: location
  tags: tags
  sku: {
    name: skuName
    capacity: 1
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
    customProperties: {
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls10': 'False'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls11': 'False'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Ssl30': 'False'
    }
  }
}

@description('Resource id of the API Management service in use (reused or newly created).')
output id string = empty(reuse) ? service.id : reuse

@description('True when this module created the service.')
output created bool = empty(reuse)
