// Log Analytics workspace: reuse-or-create.
targetScope = 'resourceGroup'

@description('Name of the workspace to create. Ignored when reuse is set.')
param name string

@description('Azure region for the workspace. Ignored when reuse is set.')
param location string

@description('Existing Log Analytics workspace resource id to reuse. Empty means create a new workspace.')
param reuse string = ''

@description('Resource tags applied to created resources only.')
param tags object = {}

@description('Public network access for ingestion and query on the created workspace.')
@allowed(['Enabled', 'Disabled'])
param publicNetworkAccess string = 'Disabled'

@description('Data retention in days.')
@minValue(30)
@maxValue(730)
param retentionInDays int = 90

@description('Daily ingestion cap in GB. -1 means no cap and the property is not emitted.')
@minValue(-1)
param dailyQuotaGb int = -1

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = if (empty(reuse)) {
  name: name
  location: location
  tags: tags
  properties: union(
    {
      sku: {
        name: 'PerGB2018'
      }
      retentionInDays: retentionInDays
      features: {
        disableLocalAuth: true
      }
      publicNetworkAccessForIngestion: publicNetworkAccess
      publicNetworkAccessForQuery: publicNetworkAccess
    },
    dailyQuotaGb == -1 ? {} : { workspaceCapping: { dailyQuotaGb: dailyQuotaGb } }
  )
}

@description('Resource id of the workspace in use (reused or newly created).')
output id string = empty(reuse) ? workspace.id : reuse

@description('True when this module created the workspace.')
output created bool = empty(reuse)
