// Optional (off by default): publish NeuroSphere's own MCP server through a CREATED API Management
// instance. Passthrough MCP API, Entra token enforcement, credential stripping and an RFC 9728
// protected-resource-metadata operation. Bodies are never read (streaming stays unbuffered).
// Policy text: policies/*.xml (the enforcement text mirrors the gateway connector templates).
targetScope = 'resourceGroup'

@description('Name of the API Management service created by this deployment.')
param apimName string

@description('Base URL of the NeuroSphere API, without the trailing /mcp.')
param backendUrl string

@description('Public MCP resource URL through the gateway (gateway URL plus /mcp). Must equal NS_MCP_RESOURCE_SERVER_URL.')
param resourceUrl string

@description('Token audience accepted by the gateway (MCP app registration application ID URI or client id).')
param audience string

@description('Entra tenant id used to derive the cloud-correct issuer and OpenID configuration.')
param tenantId string = tenant().tenantId

@description('Delegated scope every caller must hold.')
param requiredScope string = 'mcp.invoke'

@description('Calls per minute per caller.')
@minValue(1)
param rateLimitCalls int = 60

var authorizationServer = '${environment().authentication.loginEndpoint}${tenantId}/v2.0'

var namedValues = {
  'ns-mcp-openid-config-url': '${authorizationServer}/.well-known/openid-configuration'
  'ns-mcp-audience': audience
  'ns-mcp-required-scope': requiredScope
  'ns-mcp-rate-limit-calls': string(rateLimitCalls)
  'ns-mcp-resource-url': resourceUrl
  'ns-mcp-authorization-server': authorizationServer
}

resource service 'Microsoft.ApiManagement/service@2024-05-01' existing = {
  name: apimName
}

resource values 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = [
  for item in items(namedValues): {
    parent: service
    name: item.key
    properties: {
      displayName: item.key
      value: item.value
      secret: false
    }
  }
]

resource backend 'Microsoft.ApiManagement/service/backends@2024-05-01' = {
  parent: service
  name: 'ns-mcp-api'
  properties: {
    protocol: 'http'
    url: backendUrl
  }
}

resource api 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: service
  name: 'ns-mcp'
  dependsOn: [backend]
  properties: {
    displayName: 'NeuroSphere MCP'
    path: ''
    protocols: ['https']
    subscriptionRequired: false
    serviceUrl: backendUrl
  }
}

resource mcpPost 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = {
  parent: api
  name: 'mcp-post'
  properties: {
    displayName: 'MCP POST'
    method: 'POST'
    urlTemplate: '/mcp'
  }
}

resource mcpGet 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = {
  parent: api
  name: 'mcp-get'
  properties: {
    displayName: 'MCP GET'
    method: 'GET'
    urlTemplate: '/mcp'
  }
}

resource mcpDelete 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = {
  parent: api
  name: 'mcp-delete'
  properties: {
    displayName: 'MCP DELETE'
    method: 'DELETE'
    urlTemplate: '/mcp'
  }
}

resource prm 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = {
  parent: api
  name: 'protected-resource-metadata'
  properties: {
    displayName: 'Protected resource metadata'
    method: 'GET'
    urlTemplate: '/.well-known/oauth-protected-resource/mcp'
  }
}

resource apiPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: api
  name: 'policy'
  dependsOn: [values]
  properties: {
    format: 'rawxml'
    value: loadTextContent('policies/apim-mcp-enforcement.xml')
  }
}

resource prmPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2024-05-01' = {
  parent: prm
  name: 'policy'
  dependsOn: [values]
  properties: {
    format: 'rawxml'
    value: loadTextContent('policies/apim-mcp-prm.xml')
  }
}

@description('Resource id of the MCP front API.')
output apiId string = api.id
