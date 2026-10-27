// Cosmos data plane objects on an existing serverless account: one database and every container
// from the PRP-29 registry export. Entra data-plane tokens cannot create databases or containers,
// so they are declared here. Serverless: no throughput is ever set.
targetScope = 'resourceGroup'

@description('Name of the existing Cosmos DB account in this resource group.')
param accountName string

@description('Database name.')
param databaseName string = 'neurosphere'

// Registry export (neurosphere_core.stores.containers). Inlined at build time.
var registry = loadJsonContent('../../compose/cosmos-containers.json')

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: accountName
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: account
  name: databaseName
  properties: {
    resource: { id: databaseName }
  }
}

resource containers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = [
  for c in registry.containers: {
    parent: database
    name: c.name
    properties: {
      resource: union(
        {
          id: c.name
          partitionKey: union(
            {
              paths: c.partition_key.paths
              kind: c.partition_key.kind
            },
            c.partition_key.kind == 'MultiHash' ? { version: 2 } : {}
          )
        },
        c.default_ttl == null ? {} : { defaultTtl: c.default_ttl }
      )
    }
  }
]

@description('Database name.')
output databaseName string = database.name

@description('Names of the containers declared.')
output containerNames array = [for c in registry.containers: c.name]
