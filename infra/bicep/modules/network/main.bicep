// NeuroSphere network baseline (PRP-12 item 3): VNet, deny-by-default NSGs, private endpoints
// and private DNS for the data plane. APIM is the only resource that may take public ingress.
// Cloud-specific DNS zone names are derived from environment(); no hostname is hard-coded.
// NSG rules use service tags, which are cloud-neutral names.
targetScope = 'resourceGroup'

@description('Short lowercase prefix used to derive resource names.')
@minLength(3)
@maxLength(10)
param namePrefix string

@description('Azure region. Must be a region of the target cloud.')
param location string = resourceGroup().location

@description('Resource tags applied to created resources.')
param tags object = {}

@description('Address space of the virtual network.')
param vnetAddressPrefix string = '10.40.0.0/16'

@description('Address prefix of the application subnet.')
param appSubnetPrefix string = '10.40.0.0/24'

@description('Address prefix of the private endpoint subnet.')
param privateEndpointSubnetPrefix string = '10.40.1.0/24'

@description('Cosmos DB account resource id. Empty skips its private endpoint.')
param cosmosId string = ''

@description('Event Hubs namespace resource id. Empty skips its private endpoint.')
param eventHubsId string = ''

@description('Storage account resource id (blob). Empty skips its private endpoint.')
param storageId string = ''

@description('Key vault resource id. Empty skips its private endpoint.')
param keyVaultId string = ''

@description('AI Search service resource id. Empty skips its private endpoint.')
param searchId string = ''

var compact = toLower(replace(namePrefix, '-', ''))

// Private DNS zone names follow Learn "Azure Private Endpoint private DNS zone values". Each is
// built from environment() suffixes (storage, keyvaultDns, portal), so the Commercial and
// Government names differ with no literal hostname in this file. The expected names per cloud
// are asserted in tests/security/network/test_bicep_network.py.
var isGovernment = environment().name == 'AzureUSGovernment'
var storageSuffix = environment().suffixes.storage
var portalDomain = replace(replace(environment().portal, 'https://portal.', ''), '/', '')
var platformSuffix = replace(storageSuffix, 'core.', '')
var zoneBlob = 'privatelink.blob.${storageSuffix}'
var zoneEventHubs = 'privatelink.servicebus.${platformSuffix}'
var zoneKeyVault = 'privatelink${replace(environment().suffixes.keyvaultDns, '.vault.', '.vaultcore.')}'
var zoneCosmos = 'privatelink.documents.${portalDomain}'
var zoneSearch = 'privatelink.search.${isGovernment ? portalDomain : platformSuffix}'

var endpoints = [
  { key: 'cosmos', groupId: 'Sql', zone: zoneCosmos, targetId: cosmosId }
  { key: 'eventhubs', groupId: 'namespace', zone: zoneEventHubs, targetId: eventHubsId }
  { key: 'storage', groupId: 'blob', zone: zoneBlob, targetId: storageId }
  { key: 'keyvault', groupId: 'vault', zone: zoneKeyVault, targetId: keyVaultId }
  { key: 'search', groupId: 'searchService', zone: zoneSearch, targetId: searchId }
]

// Inbound: VNet-only, then deny. Outbound: VNet and explicit service tags, then deny Internet.
var securityRules = [
  {
    name: 'AllowVnetInbound'
    properties: {
      priority: 100
      direction: 'Inbound'
      access: 'Allow'
      protocol: '*'
      sourceAddressPrefix: 'VirtualNetwork'
      sourcePortRange: '*'
      destinationAddressPrefix: 'VirtualNetwork'
      destinationPortRange: '*'
    }
  }
  {
    name: 'DenyAllInbound'
    properties: {
      priority: 4096
      direction: 'Inbound'
      access: 'Deny'
      protocol: '*'
      sourceAddressPrefix: '*'
      sourcePortRange: '*'
      destinationAddressPrefix: '*'
      destinationPortRange: '*'
    }
  }
  {
    name: 'AllowVnetOutbound'
    properties: {
      priority: 100
      direction: 'Outbound'
      access: 'Allow'
      protocol: '*'
      sourceAddressPrefix: 'VirtualNetwork'
      sourcePortRange: '*'
      destinationAddressPrefix: 'VirtualNetwork'
      destinationPortRange: '*'
    }
  }
  {
    name: 'AllowEntraOutbound'
    properties: {
      priority: 110
      direction: 'Outbound'
      access: 'Allow'
      protocol: 'Tcp'
      sourceAddressPrefix: 'VirtualNetwork'
      sourcePortRange: '*'
      destinationAddressPrefix: 'AzureActiveDirectory'
      destinationPortRange: '443'
    }
  }
  {
    name: 'AllowMonitorOutbound'
    properties: {
      priority: 120
      direction: 'Outbound'
      access: 'Allow'
      protocol: 'Tcp'
      sourceAddressPrefix: 'VirtualNetwork'
      sourcePortRange: '*'
      destinationAddressPrefix: 'AzureMonitor'
      destinationPortRange: '443'
    }
  }
  {
    name: 'DenyInternetOutbound'
    properties: {
      priority: 4000
      direction: 'Outbound'
      access: 'Deny'
      protocol: '*'
      sourceAddressPrefix: '*'
      sourcePortRange: '*'
      destinationAddressPrefix: 'Internet'
      destinationPortRange: '*'
    }
  }
]

resource appNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${compact}-app-nsg'
  location: location
  tags: tags
  properties: {
    securityRules: securityRules
  }
}

resource peNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${compact}-pe-nsg'
  location: location
  tags: tags
  properties: {
    securityRules: securityRules
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${compact}-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [vnetAddressPrefix]
    }
    subnets: [
      {
        name: 'app'
        properties: {
          addressPrefix: appSubnetPrefix
          networkSecurityGroup: { id: appNsg.id }
        }
      }
      {
        name: 'private-endpoints'
        properties: {
          addressPrefix: privateEndpointSubnetPrefix
          networkSecurityGroup: { id: peNsg.id }
          privateEndpointNetworkPolicies: 'Enabled'
        }
      }
    ]
  }
}

resource zones 'Microsoft.Network/privateDnsZones@2024-06-01' = [
  for e in endpoints: if (!empty(e.targetId)) {
    name: e.zone
    location: 'global'
    tags: tags
  }
]

resource zoneLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [
  for (e, i) in endpoints: if (!empty(e.targetId)) {
    parent: zones[i]
    name: '${compact}-${e.key}-link'
    location: 'global'
    tags: tags
    properties: {
      registrationEnabled: false
      virtualNetwork: { id: vnet.id }
    }
  }
]

resource privateEndpoints 'Microsoft.Network/privateEndpoints@2024-05-01' = [
  for e in endpoints: if (!empty(e.targetId)) {
    name: '${compact}-pe-${e.key}'
    location: location
    tags: tags
    properties: {
      subnet: { id: '${vnet.id}/subnets/private-endpoints' }
      privateLinkServiceConnections: [
        {
          name: '${compact}-${e.key}'
          properties: {
            privateLinkServiceId: e.targetId
            groupIds: [e.groupId]
          }
        }
      ]
    }
  }
]

resource zoneGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = [
  for (e, i) in endpoints: if (!empty(e.targetId)) {
    parent: privateEndpoints[i]
    name: 'default'
    properties: {
      privateDnsZoneConfigs: [
        {
          name: e.key
          properties: { privateDnsZoneId: zones[i].id }
        }
      ]
    }
  }
]

@description('Virtual network resource id.')
output vnetId string = vnet.id

@description('Application subnet resource id.')
output appSubnetId string = '${vnet.id}/subnets/app'

@description('Private endpoint subnet resource id.')
output privateEndpointSubnetId string = '${vnet.id}/subnets/private-endpoints'

@description('Private DNS zone names derived for the deployment cloud, keyed by service.')
output zoneNames object = {
  cosmos: zoneCosmos
  eventhubs: zoneEventHubs
  storage: zoneBlob
  keyvault: zoneKeyVault
  search: zoneSearch
}
