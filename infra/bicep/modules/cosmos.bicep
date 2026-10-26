// Cosmos DB (NoSQL) account: reuse-or-create. Key auth disabled; access is by RBAC only.
targetScope = 'resourceGroup'

@description('Name of the Cosmos DB account to create. Ignored when reuse is set.')
param name string

@description('Azure region for the account. Ignored when reuse is set.')
param location string

@description('Existing Cosmos DB account resource id to reuse. Empty means create a new account.')
param reuse string = ''

@description('Resource tags applied to created resources only.')
param tags object = {}

@description('Public network access for the created account.')
@allowed(['Enabled', 'Disabled'])
param publicNetworkAccess string = 'Disabled'

@description('Capacity mode of the created account. Serverless forbids throughput and is single-region; the property is emitted only when Serverless.')
@allowed(['Provisioned', 'Serverless'])
param capacityMode string = 'Provisioned'

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = if (empty(reuse)) {
  name: name
  location: location
  kind: 'GlobalDocumentDB'
  tags: tags
  properties: union(
    {
      databaseAccountOfferType: 'Standard'
      disableLocalAuth: true
      minimalTlsVersion: 'Tls12'
      publicNetworkAccess: publicNetworkAccess
      locations: [
        {
          locationName: location
          failoverPriority: 0
          isZoneRedundant: false
        }
      ]
      consistencyPolicy: {
        defaultConsistencyLevel: 'Session'
      }
    },
    capacityMode == 'Serverless' ? { capacityMode: 'Serverless' } : {}
  )
}

@description('Resource id of the Cosmos DB account in use (reused or newly created).')
output id string = empty(reuse) ? account.id : reuse

@description('True when this module created the account.')
output created bool = empty(reuse)
