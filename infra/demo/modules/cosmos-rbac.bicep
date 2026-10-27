// Cosmos data-plane RBAC for the app identities (PRP-06 posture, see scripts/gates/prp06_cosmos_live.py):
//   - read / create / query / metadata on the database,
//   - replace and upsert only on non-audit containers,
//   - replace only (no upsert, no delete) on the audit tail,
//   - nothing beyond read/create/query on the audit records container, so it is append-only at the service.
// No built-in account-wide Data Contributor role is assigned to any app identity. Operator seeding
// grants are not declared here; the seed-access script grants and revokes them with az.
targetScope = 'resourceGroup'

@description('Name of the existing Cosmos DB account in this resource group.')
param accountName string

@description('Database name.')
param databaseName string = 'neurosphere'

@description('Object (principal) id of the API managed identity.')
param apiPrincipalId string

@description('Object (principal) id of the workers managed identity.')
param workersPrincipalId string

@description('Containers that get no replace or upsert permission at all (the append-only audit records).')
param appendOnlyContainers array = ['audit']

@description('Containers that get replace but no upsert or delete (the audit chain tail, written with an ETag-conditioned replace).')
param replaceOnlyContainers array = ['audit_tail']

var registry = loadJsonContent('../../compose/cosmos-containers.json')
var principals = [apiPrincipalId, workersPrincipalId]
var dataActionPrefix = 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers'
var skipWrite = concat(appendOnlyContainers, replaceOnlyContainers)
var writeContainers = filter(map(registry.containers, c => c.name), n => !contains(skipWrite, n))
var dbScope = '${account.id}/dbs/${databaseName}'

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: accountName
}

resource baseRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleDefinitions@2024-11-15' = {
  parent: account
  name: guid(account.id, 'ns-app-base')
  properties: {
    roleName: 'ns-app-read-create-query'
    type: 'CustomRole'
    assignableScopes: [account.id]
    permissions: [
      {
        dataActions: [
          'Microsoft.DocumentDB/databaseAccounts/readMetadata'
          '${dataActionPrefix}/items/read'
          '${dataActionPrefix}/items/create'
          '${dataActionPrefix}/executeQuery'
        ]
      }
    ]
  }
}

resource writeRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleDefinitions@2024-11-15' = {
  parent: account
  name: guid(account.id, 'ns-app-write')
  properties: {
    roleName: 'ns-app-replace-upsert'
    type: 'CustomRole'
    assignableScopes: [account.id]
    permissions: [
      {
        dataActions: [
          '${dataActionPrefix}/items/replace'
          '${dataActionPrefix}/items/upsert'
        ]
      }
    ]
  }
}

resource tailRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleDefinitions@2024-11-15' = {
  parent: account
  name: guid(account.id, 'ns-app-replace-only')
  properties: {
    roleName: 'ns-app-replace-only'
    type: 'CustomRole'
    assignableScopes: [account.id]
    permissions: [
      {
        dataActions: [
          '${dataActionPrefix}/items/replace'
        ]
      }
    ]
  }
}

resource baseAssignments 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = [
  for p in principals: {
    parent: account
    name: guid(account.id, baseRole.id, p, dbScope)
    properties: {
      roleDefinitionId: baseRole.id
      principalId: p
      scope: dbScope
    }
  }
]

var writePairs = flatten(map(writeContainers, c => map(principals, p => { container: c, principal: p })))
var tailPairs = flatten(map(replaceOnlyContainers, c => map(principals, p => { container: c, principal: p })))

resource writeAssignments 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = [
  for pair in writePairs: {
    parent: account
    name: guid(account.id, writeRole.id, pair.principal, pair.container)
    properties: {
      roleDefinitionId: writeRole.id
      principalId: pair.principal
      scope: '${dbScope}/colls/${pair.container}'
    }
  }
]

resource tailAssignments 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = [
  for pair in tailPairs: {
    parent: account
    name: guid(account.id, tailRole.id, pair.principal, pair.container)
    properties: {
      roleDefinitionId: tailRole.id
      principalId: pair.principal
      scope: '${dbScope}/colls/${pair.container}'
    }
  }
]

@description('Resource id of the read/create/query role definition.')
output baseRoleId string = baseRole.id

@description('Resource id of the replace/upsert role definition.')
output writeRoleId string = writeRole.id

@description('Resource id of the replace-only role definition.')
output replaceOnlyRoleId string = tailRole.id
