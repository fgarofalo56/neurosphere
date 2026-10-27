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

@description('Capacity mode of the created account. Serverless forbids throughput and is single-region; the EnableServerless capability is emitted only when Serverless.')
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
    // 2024-11-15 has no properties.capacityMode; serverless is the EnableServerless capability.
    capacityMode == 'Serverless' ? { capabilities: [{ name: 'EnableServerless' }] } : {}
  )
}

// The reused account may live in another group; these are only read when reuse is set.
var reuseParts = split(reuse, '/')
var reuseSubscription = empty(reuse) ? subscription().subscriptionId : reuseParts[2]
var reuseGroup = empty(reuse) ? resourceGroup().name : reuseParts[4]
var reuseName = empty(reuse) ? name : last(reuseParts)

resource reused 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = if (!empty(reuse)) {
  name: reuseName
  scope: resourceGroup(reuseSubscription, reuseGroup)
}

@description('Resource id of the Cosmos DB account in use (reused or newly created).')
output id string = empty(reuse) ? account.id : reuse

@description('True when this module created the account.')
output created bool = empty(reuse)

@description('Document endpoint (https URL) of the account in use. ARM evaluates only the branch the ternary takes, and the created branch is a same-template reference, so it waits for the account.')
output documentEndpoint string = empty(reuse)
  ? account!.properties.documentEndpoint
  : reused!.properties.documentEndpoint
