// API Management diagnostics: gateway, LLM and MCP logs to the deployment's Log Analytics workspace.
// Deploy ONLY for a created instance (main.bicep guards on apim.outputs.created); a reused
// instance is never modified.
targetScope = 'resourceGroup'

@description('Name of the API Management service created by this deployment.')
param apimName string

@description('Log Analytics workspace resource id that receives the logs.')
param workspaceId string

resource service 'Microsoft.ApiManagement/service@2024-05-01' existing = {
  name: apimName
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'ns-apim-diagnostics'
  scope: service
  properties: {
    workspaceId: workspaceId
    logAnalyticsDestinationType: 'Dedicated'
    logs: [
      {
        category: 'GatewayLogs'
        enabled: true
      }
      {
        category: 'GatewayLlmLogs'
        enabled: true
      }
      {
        category: 'GatewayMCPLogs'
        enabled: true
      }
    ]
  }
}

@description('Resource id of the diagnostic setting.')
output id string = diagnostics.id
