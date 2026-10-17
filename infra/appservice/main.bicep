// App Service profile: runs the SAME api and workers container images as the AKS Helm chart
// (infra/helm). Image registry/tag/repositories are parameters whose values in main.bicepparam
// must equal infra/helm/values.yaml + ci values; tests/unit/infra/test_helm_render.py proves it.
// No secrets here: app settings use Key Vault references supplied as parameter values only.
targetScope = 'resourceGroup'

@description('Azure region for the plan and web apps.')
param location string = resourceGroup().location

@description('Name prefix for the plan and web apps.')
@minLength(3)
@maxLength(20)
param namePrefix string

@description('Container registry host serving the images (no scheme). Same value as image.registry in the Helm chart.')
@minLength(1)
param imageRegistry string

@description('Image tag. Same value as image.tag in the Helm chart.')
@minLength(1)
param imageTag string

@description('API image repository. Same value as api.repository in the Helm chart.')
param apiRepository string = 'neurosphere/api'

@description('Workers image repository. Same value as workers.repository in the Helm chart.')
param workersRepository string = 'neurosphere/workers'

@description('App Service plan SKU (Linux, container capable).')
param skuName string = 'P1v3'

@description('Instance count for the plan.')
@minValue(1)
param capacity int = 2

@description('Non-secret application settings merged into both apps.')
param commonAppSettings object = {}

@description('Settings whose values are Key Vault secret URIs; rendered as @Microsoft.KeyVault(SecretUri=...) references. Values are URIs, never secret material.')
param keyVaultSecretUris object = {}

@description('Resource id of the user-assigned managed identity used for Key Vault references and registry pull. Empty uses the system-assigned identity.')
param userAssignedIdentityId string = ''

@description('Resource tags.')
param tags object = {}

var apiImage = '${imageRegistry}/${apiRepository}:${imageTag}'
var workersImage = '${imageRegistry}/${workersRepository}:${imageTag}'

var useUserAssigned = !empty(userAssignedIdentityId)
var identity = useUserAssigned
  ? {
      type: 'UserAssigned'
      userAssignedIdentities: {
        '${userAssignedIdentityId}': {}
      }
    }
  : {
      type: 'SystemAssigned'
    }

var kvRefSettings = reduce(
  items(keyVaultSecretUris),
  {},
  (acc, item) =>
    union(acc, {
      '${item.key}': '@Microsoft.KeyVault(SecretUri=${item.value})'
    })
)

var plainSettings = [for item in items(commonAppSettings): { name: item.key, value: string(item.value) }]
var kvSettings = [for item in items(kvRefSettings): { name: item.key, value: string(item.value) }]

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${namePrefix}-plan'
  location: location
  tags: tags
  kind: 'linux'
  sku: {
    name: skuName
    capacity: capacity
  }
  properties: {
    reserved: true
  }
}

resource api 'Microsoft.Web/sites@2023-12-01' = {
  name: '${namePrefix}-api'
  location: location
  tags: tags
  kind: 'app,linux,container'
  identity: identity
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    keyVaultReferenceIdentity: useUserAssigned ? userAssignedIdentityId : null
    siteConfig: {
      linuxFxVersion: 'DOCKER|${apiImage}'
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      alwaysOn: true
      healthCheckPath: '/readyz'
      acrUseManagedIdentityCreds: true
      acrUserManagedIdentityID: useUserAssigned ? userAssignedIdentityId : null
      appSettings: concat(
        [
          { name: 'WEBSITES_PORT', value: '8000' }
          { name: 'WEBSITES_ENABLE_APP_SERVICE_STORAGE', value: 'false' }
        ],
        plainSettings,
        kvSettings
      )
    }
  }
}

resource workers 'Microsoft.Web/sites@2023-12-01' = {
  name: '${namePrefix}-workers'
  location: location
  tags: tags
  kind: 'app,linux,container'
  identity: identity
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    keyVaultReferenceIdentity: useUserAssigned ? userAssignedIdentityId : null
    siteConfig: {
      linuxFxVersion: 'DOCKER|${workersImage}'
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      alwaysOn: true
      healthCheckPath: '/healthz'
      acrUseManagedIdentityCreds: true
      acrUserManagedIdentityID: useUserAssigned ? userAssignedIdentityId : null
      appSettings: concat(
        [
          { name: 'WEBSITES_PORT', value: '8090' }
          { name: 'WEBSITES_ENABLE_APP_SERVICE_STORAGE', value: 'false' }
        ],
        plainSettings,
        kvSettings
      )
    }
  }
}

output apiImage string = apiImage
output workersImage string = workersImage
output apiPrincipalId string = useUserAssigned ? '' : api.identity.principalId
output workersPrincipalId string = useUserAssigned ? '' : workers.identity.principalId
