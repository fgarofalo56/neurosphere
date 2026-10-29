// NeuroSphere core infrastructure. Each service is reuse-or-create: a non-empty
// reuse id declares no resource for that service and is passed through as the output id.
// Cloud-specific hostnames are derived with environment(); none are hard-coded.
targetScope = 'resourceGroup'

@description('Short lowercase prefix used to derive resource names (3-10 chars).')
@minLength(3)
@maxLength(10)
param namePrefix string

@description('Azure region. Must be a region of the target cloud (Government regions for Azure Government).')
param location string = resourceGroup().location

@description('Resource tags applied to created resources.')
param tags object = {}

@description('Public network access for created resources.')
@allowed(['Enabled', 'Disabled'])
param publicNetworkAccess string = 'Disabled'

@description('Existing Cosmos DB account resource id to reuse. Empty creates one.')
param reuseCosmos string = ''

@description('Existing Event Hubs namespace resource id to reuse. Empty creates one.')
param reuseEventHubs string = ''

@description('Existing storage account resource id to reuse. Empty creates one.')
param reuseStorage string = ''

@description('Existing key vault resource id to reuse. Empty creates one.')
param reuseKeyVault string = ''

@description('Existing AI Search service resource id to reuse. Empty creates one.')
param reuseSearch string = ''

@description('Existing Log Analytics workspace resource id to reuse. Empty creates one.')
param reuseLogAnalytics string = ''

@description('Existing API Management resource id to reuse. Empty creates one.')
param reuseApim string = ''

@description('APIM publisher email; used only when APIM is created.')
param apimPublisherEmail string = ''

@description('APIM publisher name; used only when APIM is created.')
param apimPublisherName string = ''

@description('SKU for a created APIM service. v2 tiers are refused in Azure Government (availability unverified, see government/sovereign-profile.yaml).')
@allowed(['Developer', 'Standard', 'Premium', 'BasicV2', 'StandardV2', 'PremiumV2'])
param apimSkuName string = 'Developer'

@description('APIM scale units for a created service (capped per tier by the module).')
@minValue(1)
@maxValue(12)
param apimSkuCapacity int = 1

@description('Write GatewayLogs, GatewayLlmLogs and GatewayMCPLogs to the workspace. Created APIM only; a reused instance is never modified.')
param enableApimDiagnostics bool = true

@description('Publish the NeuroSphere MCP server through a created APIM instance. Off by default; ignored for a reused APIM.')
param enableApimMcpFront bool = false

@description('NeuroSphere API base URL (no trailing /mcp) the gateway forwards to. Required when enableApimMcpFront.')
param apimMcpBackendUrl string = ''

@description('Token audience (MCP app registration) the gateway accepts. Required when enableApimMcpFront.')
param apimMcpAudience string = ''

var isGovernment = environment().name == 'AzureUSGovernment'
var isV2Sku = endsWith(apimSkuName, 'V2')
// Deliberate deploy-time failure: looking up a missing key fails the deployment, because the
// v2 tiers are unverified in Azure Government.
var v2GovernmentGate = { ok: '' }
var v2GovernmentGuard = v2GovernmentGate[(isGovernment && isV2Sku) ? 'apim_v2_tiers_unverified_in_government' : 'ok']

var suffix =uniqueString(resourceGroup().id)
var compact = toLower(replace(namePrefix, '-', ''))

module cosmos 'cosmos.bicep' = {
  name: 'ns-cosmos'
  params: {
    name: '${compact}-cosmos-${suffix}'
    location: location
    reuse: reuseCosmos
    tags: tags
    publicNetworkAccess: publicNetworkAccess
  }
}

module eventHubs 'eventhubs.bicep' = {
  name: 'ns-eventhubs'
  params: {
    name: '${compact}-eh-${suffix}'
    location: location
    reuse: reuseEventHubs
    tags: tags
    publicNetworkAccess: publicNetworkAccess
  }
}

module storage 'storage.bicep' = {
  name: 'ns-storage'
  params: {
    name: take('${compact}st${suffix}', 24)
    location: location
    reuse: reuseStorage
    tags: tags
    publicNetworkAccess: publicNetworkAccess
  }
}

module keyVault 'keyvault.bicep' = {
  name: 'ns-keyvault'
  params: {
    name: take('${compact}-kv-${suffix}', 24)
    location: location
    reuse: reuseKeyVault
    tags: tags
    publicNetworkAccess: publicNetworkAccess
  }
}

module search 'search.bicep' = {
  name: 'ns-search'
  params: {
    name: '${compact}-search-${suffix}'
    location: location
    reuse: reuseSearch
    tags: tags
    publicNetworkAccess: publicNetworkAccess
  }
}

module logAnalytics 'loganalytics.bicep' = {
  name: 'ns-loganalytics'
  params: {
    name: '${compact}-law-${suffix}'
    location: location
    reuse: reuseLogAnalytics
    tags: tags
    publicNetworkAccess: publicNetworkAccess
  }
}

module apim 'apim.bicep' = {
  name: 'ns-apim'
  params: {
    name: '${compact}-apim-${suffix}'
    location: location
    reuse: reuseApim
    tags: tags
    publisherEmail: apimPublisherEmail
    // v2GovernmentGuard is '' unless a v2 tier is requested in Government, which fails the deployment.
    publisherName: '${apimPublisherName}${v2GovernmentGuard}'
    skuName: apimSkuName
    skuCapacity: apimSkuCapacity
  }
}

// Created instances only: a reused APIM is never modified.
module apimDiagnostics 'apim-diagnostics.bicep' = if (enableApimDiagnostics && empty(reuseApim)) {
  name: 'ns-apim-diagnostics'
  params: {
    apimName: '${compact}-apim-${suffix}'
    workspaceId: logAnalytics.outputs.id
  }
}

module apimMcpFront 'apim-mcp-front.bicep' = if (enableApimMcpFront && empty(reuseApim)) {
  name: 'ns-apim-mcp-front'
  params: {
    apimName: '${compact}-apim-${suffix}'
    backendUrl: apimMcpBackendUrl
    resourceUrl: '${apim.outputs.gatewayUrl}/mcp'
    audience: apimMcpAudience
  }
}

module network 'network/main.bicep' = {
  name: 'ns-network'
  params: {
    namePrefix: namePrefix
    location: location
    tags: tags
    // Reuse mode must not touch shared resources: only created services get a private endpoint.
    cosmosId: cosmos.outputs.created ? cosmos.outputs.id : ''
    eventHubsId: eventHubs.outputs.created ? eventHubs.outputs.id : ''
    storageId: storage.outputs.created ? storage.outputs.id : ''
    keyVaultId: keyVault.outputs.created ? keyVault.outputs.id : ''
    searchId: search.outputs.created ? search.outputs.id : ''
  }
}

@description('Cosmos DB account resource id.')
output cosmosId string = cosmos.outputs.id

@description('Event Hubs namespace resource id.')
output eventHubsId string = eventHubs.outputs.id

@description('Storage account resource id.')
output storageId string = storage.outputs.id

@description('Key vault resource id.')
output keyVaultId string = keyVault.outputs.id

@description('AI Search service resource id.')
output searchId string = search.outputs.id

@description('Log Analytics workspace resource id.')
output logAnalyticsId string = logAnalytics.outputs.id

@description('API Management resource id.')
output apimId string = apim.outputs.id

@description('Cloud name reported by the deployment environment (AzureCloud or AzureUSGovernment).')
output cloudName string = environment().name

@description('Entra login endpoint of the deployment cloud, derived from environment().')
output loginEndpoint string = environment().authentication.loginEndpoint

@description('Key Vault DNS suffix of the deployment cloud, derived from environment().')
output keyVaultDnsSuffix string = environment().suffixes.keyvaultDns
