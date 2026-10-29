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
// v2 tiers (BasicV2, StandardV2, PremiumV2) need API version 2024-05-01 or later.
// Azure Government availability of the v2 tiers is unverified; main.bicep refuses them there.
@allowed(['Developer', 'Standard', 'Premium', 'BasicV2', 'StandardV2', 'PremiumV2'])
param skuName string = 'Developer'

@description('Scale units for a created service. Capped per tier: Developer 1, Standard 4, Premium 12, BasicV2 10, StandardV2 10, PremiumV2 12.')
@minValue(1)
@maxValue(12)
param skuCapacity int = 1

var capacityCeiling = {
  Developer: 1
  Standard: 4
  Premium: 12
  BasicV2: 10
  StandardV2: 10
  PremiumV2: 12
}
var effectiveCapacity = min(skuCapacity, capacityCeiling[skuName])

resource service 'Microsoft.ApiManagement/service@2024-05-01' = if (empty(reuse)) {
  name: name
  location: location
  tags: tags
  sku: {
    name: skuName
    capacity: effectiveCapacity
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

@description('Gateway URL of a service created by this module; empty when reused (a reused instance is never read).')
output gatewayUrl string = empty(reuse) ? service!.properties.gatewayUrl : ''

@description('True when this module created the service.')
output created bool = empty(reuse)
