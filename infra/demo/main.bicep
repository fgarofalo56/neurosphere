// PRP-32 item 3: the hosted Azure demo, composed from the core service modules, the App Service
// profile and the item 1 demo modules. Attaches to an existing hub: the integration subnet, the
// private endpoint subnet and the privatelink zones are parameters; nothing here creates a VNet,
// a subnet, a private DNS zone, APIM or AI Search. No secret value is ever an input or output:
// the pseudonym key is a Key Vault reference, data access is managed identity, and the shared
// key paths are off on every service module.
targetScope = 'resourceGroup'

// ---------------------------------------------------------------------------------------------
// Parameters
// ---------------------------------------------------------------------------------------------

@description('Name prefix for the sites (<prefix>-web, -api, -workers, -plan), private endpoints and data services. Lowercase letters and digits.')
@minLength(3)
@maxLength(12)
param prefix string = 'nsdemo'

@description('Azure region for every created resource.')
param location string = resourceGroup().location

@description('Container registry host serving the public images (no scheme), including the organisation path.')
param imageRegistry string = 'ghcr.io/fgarofalo56/neurosphere'

@description('Image tag shared by the api, workers and frontend images.')
@minLength(1)
param imageTag string

@description('App Service plan SKU. One instance; B2 supports VNet integration and inbound private endpoints.')
param appServiceSkuName string = 'B2'

@description('Deploy a Key Vault, its private endpoint and the Secrets User assignments. The API refuses to start under NS_ENV=prod without the pseudonym key, so leave this on.')
param deployKeyVault bool = true

@description('Resource id of the hub subnet delegated to Microsoft.Web/serverFarms, used for regional VNet integration of the three sites.')
param integrationSubnetId string

@description('Resource id of the hub subnet that holds the private endpoint NICs.')
param privateEndpointSubnetId string

@description('Resource id of the hub private DNS zone for Cosmos DB (privatelink for the SQL API).')
param cosmosDnsZoneId string

@description('Resource id of the hub private DNS zone for Event Hubs (privatelink for the namespace).')
param eventHubsDnsZoneId string

@description('Resource id of the hub private DNS zone for blob storage.')
param blobDnsZoneId string

@description('Resource id of the hub private DNS zone for App Service sites.')
param webAppsDnsZoneId string

@description('Resource id of the hub private DNS zone for Key Vault. Used only when deployKeyVault is true.')
param keyVaultDnsZoneId string

@description('Microsoft Entra tenant id the API validates tokens against and the SPA signs in to.')
param entraTenantId string

@description('Client (application) id of the Entra app. It is the v2 token audience (a bare GUID) and the SPA client id.')
param entraClientId string

@description('Endpoint of the approved model deployment host (scheme and host only).')
param copilotEndpoint string

@description('Model deployment name on the copilot endpoint.')
param copilotDeployment string = 'mini'

@description('Monthly budget amount for the resource group, in the billing currency.')
@minValue(1)
param budgetAmount int = 200

@description('First day of the budget period, yyyy-MM-01.')
param budgetStartDate string

@description('Email addresses notified by the budget thresholds.')
param budgetContactEmails array

@description('Value of the owner tag.')
param tagOwner string

@description('Value of the delete-after tag (a review date, yyyy-MM-dd).')
param tagDeleteAfter string

@description('Value of the neurosphere:deployment-id tag; the ownership register key.')
param deploymentId string

@description('Value of the neurosphere:created-by tag.')
param createdBy string

// ---------------------------------------------------------------------------------------------
// Names, tags and derived values
// ---------------------------------------------------------------------------------------------

var unique = uniqueString(resourceGroup().id)
var cosmosName = '${prefix}-cosmos-${take(unique, 6)}'
var eventHubsName = '${prefix}-ehns-${take(unique, 6)}'
var storageName = take('${prefix}${unique}', 24)
var keyVaultNameValue = take('${prefix}kv${unique}', 24)
var logAnalyticsName = '${prefix}-law'
var databaseName = 'neurosphere'
var customerId = 'synthco'
var pseudonymSecret = 'ns-auth-pseudonym-key'
var eventHubName = 'telemetry'
var consumerGroupName = 'normalizer'
var archiveContainer = 'ns-archive'
var checkpointContainer = 'ns-ingestion-checkpoints'
var quarantineContainer = 'ns-quarantine'
var cloudName = startsWith(environment().name, 'AzureUSGovernment') ? 'government' : 'commercial'
var apiScope = 'api://${entraClientId}/access_as_user'

// The default site host suffix is the hub zone name without its privatelink prefix, so no Azure
// host is spelled out here and the frontend can name the API before the API site exists.
var webAppsSuffix = replace(last(split(webAppsDnsZoneId, '/')), 'privatelink.', '')
var apiUpstream = 'https://${prefix}-api.${webAppsSuffix}'

var tags = {
  owner: tagOwner
  project: 'neurosphere'
  env: 'demo'
  'delete-after': tagDeleteAfter
  'neurosphere:created-by': createdBy
  'neurosphere:deployment-id': deploymentId
}

var pseudonymSecretUri = 'https://${keyVaultNameValue}${environment().suffixes.keyvaultDns}/secrets/${pseudonymSecret}'
var keyVaultReferences = deployKeyVault
  ? {
      NS_AUTH_PSEUDONYM_KEY: pseudonymSecretUri
      NS_ARCHIVE_PSEUDONYM_KEY: pseudonymSecretUri
    }
  : {}
var keyVaultPlainSettings = deployKeyVault ? { NS_AUTH_PSEUDONYM_KEY_REFERENCE: pseudonymSecretUri } : {}

// ---------------------------------------------------------------------------------------------
// Core service modules (data services are private; shared keys are off in the modules)
// ---------------------------------------------------------------------------------------------

module cosmos '../bicep/modules/cosmos.bicep' = {
  name: '${prefix}-cosmos'
  params: {
    name: cosmosName
    location: location
    tags: tags
    publicNetworkAccess: 'Disabled'
    capacityMode: 'Serverless'
  }
}

module eventHubs '../bicep/modules/eventhubs.bicep' = {
  name: '${prefix}-eventhubs'
  params: {
    name: eventHubsName
    location: location
    tags: tags
    publicNetworkAccess: 'Disabled'
    skuName: 'Standard'
  }
}

module storage '../bicep/modules/storage.bicep' = {
  name: '${prefix}-storage'
  params: {
    name: storageName
    location: location
    tags: tags
    publicNetworkAccess: 'Disabled'
  }
}

// dailyQuotaGb is an int in the module, so the 0.1 GB/day target of the plan is not expressible;
// 1 GB/day is the smallest positive cap. Ingestion must stay reachable for diagnostic settings
// (no private link scope in this demo), which the module's single switch also applies to query.
module logAnalytics '../bicep/modules/loganalytics.bicep' = {
  name: '${prefix}-loganalytics'
  params: {
    name: logAnalyticsName
    location: location
    tags: tags
    publicNetworkAccess: 'Enabled'
    retentionInDays: 30
    dailyQuotaGb: 1
  }
}

module keyVault '../bicep/modules/keyvault.bicep' = if (deployKeyVault) {
  name: '${prefix}-keyvault'
  params: {
    name: keyVaultNameValue
    location: location
    tags: tags
    publicNetworkAccess: 'Disabled'
  }
}

// ---------------------------------------------------------------------------------------------
// Sites
// ---------------------------------------------------------------------------------------------

var commonSettings = union(
  {
    NS_ENV: 'prod'
    NS_CLOUD: cloudName
    NS_STORE_COSMOS_ACCOUNT: cosmosName
    NS_STORE_DATABASE: databaseName
    NS_AUTH_TENANT_ID: entraTenantId
    NS_AUTH_CUSTOMER_ID: customerId
    NS_ARCHIVE_STORAGE_ACCOUNT: storageName
    NS_ARCHIVE_CONTAINER: archiveContainer
  },
  keyVaultPlainSettings
)

var apiSettings = {
  NS_AUTH_AUDIENCES: entraClientId
  NS_INGEST_EVENTHUBS_NAMESPACE: eventHubsName
  NS_INGEST_EVENTHUB_NAME: eventHubName
  NS_COPILOT_MODE: 'approved_endpoint'
  NS_COPILOT_ENDPOINT: copilotEndpoint
  NS_COPILOT_DEPLOYMENT: copilotDeployment
  NS_COPILOT_API_VERSION: '2024-10-21'
  NS_COPILOT_REGION: location
  NS_COPILOT_MODEL_FEATURE: 'model_gpt_4_1_mini'
  NS_COPILOT_SKU: 'Global Standard'
}


// NS_WORKER_OBJECT_ID is the workers' own system-assigned principal id, which exists only after
// the site does (D8). The sites are therefore declared twice with identical resources: the
// bootstrap pass creates them and their identities, the second pass adds the object id. Both
// passes target the same resources, so the result is one plan, three sites.
// Not 'all': the recommendations and evaluation roles read sandbox data from compose volume
// mounts (NS_WORKER_REC_DATA_DIR / NS_WORKER_EVAL_DATA_DIR) that the hosted image does not have.
// Hosted recommendations and evaluations are written by the seeder instead.
var workersBaseSettings = {
  NS_WORKER_ROLES: 'ingestion,projections,aggregates,actions,hitl_timers,lifecycle'
  NS_WORKER_TENANT_ID: entraTenantId
  NS_INGESTION_EVENTHUBS_NAMESPACE: eventHubsName
  NS_INGESTION_EVENTHUB_NAME: eventHubName
  NS_INGESTION_CONSUMER_GROUP: consumerGroupName
  NS_INGESTION_STORAGE_ACCOUNT: storageName
  NS_INGESTION_CHECKPOINT_CONTAINER: checkpointContainer
  NS_QUARANTINE_STORAGE_ACCOUNT: storageName
  NS_QUARANTINE_CONTAINER: quarantineContainer
}

var frontendSettings = {
  NS_UI_CLOUD: cloudName
  NS_UI_TENANT_ID: entraTenantId
  NS_UI_CLIENT_ID: entraClientId
  NS_UI_API_SCOPE: apiScope
  NS_UI_API_UPSTREAM: apiUpstream
}

module appServiceBootstrap '../appservice/main.bicep' = {
  name: '${prefix}-appservice-bootstrap'
  params: {
    location: location
    namePrefix: prefix
    imageRegistry: imageRegistry
    imageTag: imageTag
    apiRepository: 'api'
    workersRepository: 'workers'
    frontendRepository: 'frontend'
    registryAuth: 'anonymous'
    skuName: appServiceSkuName
    capacity: 1
    commonAppSettings: commonSettings
    keyVaultSecretUris: keyVaultReferences
    apiAppSettings: apiSettings
    workersAppSettings: workersBaseSettings
    frontendAppSettings: frontendSettings
    virtualNetworkSubnetId: integrationSubnetId
    vnetRouteAllEnabled: true
    apiPublicNetworkAccess: 'Disabled'
    workersPublicNetworkAccess: 'Disabled'
    frontendPublicNetworkAccess: 'Enabled'
    tags: tags
  }
}

module appService '../appservice/main.bicep' = {
  name: '${prefix}-appservice'
  params: {
    location: location
    namePrefix: prefix
    imageRegistry: imageRegistry
    imageTag: imageTag
    apiRepository: 'api'
    workersRepository: 'workers'
    frontendRepository: 'frontend'
    registryAuth: 'anonymous'
    skuName: appServiceSkuName
    capacity: 1
    commonAppSettings: commonSettings
    keyVaultSecretUris: keyVaultReferences
    apiAppSettings: apiSettings
    workersAppSettings: union(workersBaseSettings, {
      NS_WORKER_OBJECT_ID: appServiceBootstrap.outputs.workersPrincipalId
    })
    frontendAppSettings: frontendSettings
    virtualNetworkSubnetId: integrationSubnetId
    vnetRouteAllEnabled: true
    apiPublicNetworkAccess: 'Disabled'
    workersPublicNetworkAccess: 'Disabled'
    frontendPublicNetworkAccess: 'Enabled'
    tags: tags
  }
}

// ---------------------------------------------------------------------------------------------
// Data plane objects and role assignments (principals come from the bootstrap pass)
// ---------------------------------------------------------------------------------------------

module cosmosData 'modules/cosmos-data.bicep' = {
  name: '${prefix}-cosmos-data'
  dependsOn: [
    cosmos
  ]
  params: {
    accountName: cosmosName
    databaseName: databaseName
  }
}

module cosmosRbac 'modules/cosmos-rbac.bicep' = {
  name: '${prefix}-cosmos-rbac'
  dependsOn: [
    cosmos
  ]
  params: {
    accountName: cosmosName
    databaseName: cosmosData.outputs.databaseName
    apiPrincipalId: appServiceBootstrap.outputs.apiPrincipalId
    workersPrincipalId: appServiceBootstrap.outputs.workersPrincipalId
  }
}

module messaging 'modules/messaging-data.bicep' = {
  name: '${prefix}-messaging'
  dependsOn: [
    eventHubs
    storage
  ]
  params: {
    namespaceName: eventHubsName
    storageAccountName: storageName
    eventHubName: eventHubName
    consumerGroupName: consumerGroupName
    checkpointContainerName: checkpointContainer
    archiveContainerName: archiveContainer
    quarantineContainerName: quarantineContainer
    apiPrincipalId: appServiceBootstrap.outputs.apiPrincipalId
    workersPrincipalId: appServiceBootstrap.outputs.workersPrincipalId
  }
}

module keyVaultRbac 'modules/keyvault-rbac.bicep' = if (deployKeyVault) {
  name: '${prefix}-keyvault-rbac'
  dependsOn: [
    keyVault
  ]
  params: {
    vaultName: keyVaultNameValue
    principalIds: [
      appServiceBootstrap.outputs.apiPrincipalId
      appServiceBootstrap.outputs.workersPrincipalId
    ]
  }
}

module budget 'modules/budget.bicep' = {
  name: '${prefix}-budget'
  params: {
    name: '${prefix}-monthly'
    amount: budgetAmount
    startDate: budgetStartDate
    contactEmails: budgetContactEmails
  }
}

// ---------------------------------------------------------------------------------------------
// Hub private endpoints (NICs in the hub endpoint subnet, A records in the hub zones)
// ---------------------------------------------------------------------------------------------

module cosmosEndpoint 'modules/hub-private-endpoint.bicep' = {
  name: '${prefix}-pe-cosmos'
  params: {
    name: '${prefix}-pe-cosmos'
    location: location
    privateLinkServiceId: cosmos.outputs.id
    groupId: 'Sql'
    subnetId: privateEndpointSubnetId
    privateDnsZoneId: cosmosDnsZoneId
    tags: tags
  }
}

module eventHubsEndpoint 'modules/hub-private-endpoint.bicep' = {
  name: '${prefix}-pe-eventhubs'
  params: {
    name: '${prefix}-pe-eventhubs'
    location: location
    privateLinkServiceId: eventHubs.outputs.id
    groupId: 'namespace'
    subnetId: privateEndpointSubnetId
    privateDnsZoneId: eventHubsDnsZoneId
    tags: tags
  }
}

module blobEndpoint 'modules/hub-private-endpoint.bicep' = {
  name: '${prefix}-pe-blob'
  params: {
    name: '${prefix}-pe-blob'
    location: location
    privateLinkServiceId: storage.outputs.id
    groupId: 'blob'
    subnetId: privateEndpointSubnetId
    privateDnsZoneId: blobDnsZoneId
    tags: tags
  }
}

module apiEndpoint 'modules/hub-private-endpoint.bicep' = {
  name: '${prefix}-pe-api'
  params: {
    name: '${prefix}-pe-api'
    location: location
    privateLinkServiceId: appService.outputs.apiSiteId
    groupId: 'sites'
    subnetId: privateEndpointSubnetId
    privateDnsZoneId: webAppsDnsZoneId
    tags: tags
  }
}

module keyVaultEndpoint 'modules/hub-private-endpoint.bicep' = if (deployKeyVault) {
  name: '${prefix}-pe-keyvault'
  params: {
    name: '${prefix}-pe-keyvault'
    location: location
    privateLinkServiceId: keyVault!.outputs.id
    groupId: 'vault'
    subnetId: privateEndpointSubnetId
    privateDnsZoneId: keyVaultDnsZoneId
    tags: tags
  }
}

// ---------------------------------------------------------------------------------------------
// Diagnostics: the three sites into Log Analytics
// ---------------------------------------------------------------------------------------------

resource apiSite 'Microsoft.Web/sites@2023-12-01' existing = {
  name: '${prefix}-api'
}

resource workersSite 'Microsoft.Web/sites@2023-12-01' existing = {
  name: '${prefix}-workers'
}

resource frontendSite 'Microsoft.Web/sites@2023-12-01' existing = {
  name: '${prefix}-web'
}

var siteLogCategories = [
  'AppServiceHTTPLogs'
  'AppServiceConsoleLogs'
  'AppServicePlatformLogs'
]

resource apiDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${prefix}-api-logs'
  scope: apiSite
  dependsOn: [
    appService
  ]
  properties: {
    workspaceId: logAnalytics.outputs.id
    logs: [for category in siteLogCategories: { category: category, enabled: true }]
    metrics: [{ category: 'AllMetrics', enabled: true }]
  }
}

resource workersDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${prefix}-workers-logs'
  scope: workersSite
  dependsOn: [
    appService
  ]
  properties: {
    workspaceId: logAnalytics.outputs.id
    logs: [for category in siteLogCategories: { category: category, enabled: true }]
    metrics: [{ category: 'AllMetrics', enabled: true }]
  }
}

resource frontendDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${prefix}-web-logs'
  scope: frontendSite
  dependsOn: [
    appService
  ]
  properties: {
    workspaceId: logAnalytics.outputs.id
    logs: [for category in siteLogCategories: { category: category, enabled: true }]
    metrics: [{ category: 'AllMetrics', enabled: true }]
  }
}

// ---------------------------------------------------------------------------------------------
// Outputs (names and ids only; no secret material)
// ---------------------------------------------------------------------------------------------

@description('Name of the API site.')
output apiSiteName string = appService.outputs.apiSiteName

@description('Name of the workers site.')
output workersSiteName string = appService.outputs.workersSiteName

@description('Name of the frontend site.')
output frontendSiteName string = appService.outputs.frontendSiteName

@description('Default host name of the frontend site (the only public surface).')
output frontendHostName string = appService.outputs.frontendHostName

@description('Default host name of the API site (private; reached through its private endpoint).')
output apiHostName string = appService.outputs.apiHostName

@description('Object id of the API managed identity.')
output apiPrincipalId string = appServiceBootstrap.outputs.apiPrincipalId

@description('Object id of the workers managed identity.')
output workersPrincipalId string = appServiceBootstrap.outputs.workersPrincipalId

@description('Cosmos DB account name.')
output cosmosAccountName string = cosmosName

@description('Cosmos DB document endpoint (https URL; the host resolves to the private endpoint).')
output cosmosEndpoint string = cosmos.outputs.documentEndpoint

@description('Cosmos DB database name.')
output cosmosDatabaseName string = cosmosData.outputs.databaseName

@description('Event Hubs namespace name.')
output eventHubsNamespaceName string = eventHubsName

@description('Event Hubs fully qualified namespace host name (no scheme or port).')
output eventHubsFqdn string = replace(
  replace(replace(eventHubs.outputs.serviceBusEndpoint, 'https://', ''), ':443', ''),
  '/',
  ''
)

@description('Event hub name for telemetry.')
output eventHubName string = messaging.outputs.eventHubName

@description('Storage account name (archive, quarantine and checkpoints).')
output storageAccountName string = storageName

@description('Archive container name.')
output archiveContainerName string = messaging.outputs.archiveContainerName

@description('Key Vault name; empty when no vault is deployed.')
output keyVaultName string = deployKeyVault ? keyVaultNameValue : ''

@description('Name (not value) of the pseudonym key secret the deploy script creates once.')
output pseudonymSecretName string = pseudonymSecret

@description('Resource ids of the hub private endpoints created by this deployment.')
output privateEndpointIds array = concat(
  [
    cosmosEndpoint.outputs.id
    eventHubsEndpoint.outputs.id
    blobEndpoint.outputs.id
    apiEndpoint.outputs.id
  ],
  deployKeyVault ? [keyVaultEndpoint!.outputs.id] : []
)
