// Private endpoint in THIS resource group. The NIC lands in a caller-supplied (hub) subnet and the
// DNS zone group points at a caller-supplied existing private DNS zone that lives in another RG.
// Declares no private DNS zone, virtual network or subnet: the hub owns all of those.
targetScope = 'resourceGroup'

@description('Name of the private endpoint.')
param name string

@description('Azure region of the private endpoint; must match the region of the subnet virtual network.')
param location string

@description('Resource id of the target service (Cosmos account, Event Hubs namespace, storage account, vault, web app).')
param privateLinkServiceId string

@description('Private link sub-resource group id, for example Sql, namespace, blob, vault or sites.')
param groupId string

@description('Resource id of the existing subnet that hosts the private endpoint NIC.')
param subnetId string

@description('Resource id of the existing private DNS zone (in another resource group) for the zone group.')
param privateDnsZoneId string

@description('Resource tags.')
param tags object = {}

resource endpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    subnet: { id: subnetId }
    privateLinkServiceConnections: [
      {
        name: name
        properties: {
          privateLinkServiceId: privateLinkServiceId
          groupIds: [groupId]
        }
      }
    ]
  }
}

resource zoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: groupId
        properties: { privateDnsZoneId: privateDnsZoneId }
      }
    ]
  }
}

@description('Resource id of the private endpoint.')
output id string = endpoint.id
