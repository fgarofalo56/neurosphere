// Event Hubs and Blob data plane for the demo: the telemetry hub, the normalizer consumer group,
// the worker blob containers, and least-privilege RBAC. Names default to the workers' own settings
// (NS_INGESTION_*, NS_ARCHIVE_CONTAINER, quarantine container) so no override is needed.
targetScope = 'resourceGroup'

@description('Name of the existing Event Hubs namespace in this resource group.')
param namespaceName string

@description('Name of the existing storage account in this resource group.')
param storageAccountName string

@description('Event hub name (NS_INGESTION_EVENTHUB_NAME).')
param eventHubName string = 'telemetry'

@description('Consumer group used by the ingestion worker (NS_INGESTION_CONSUMER_GROUP).')
param consumerGroupName string = 'normalizer'

@description('Event hub partition count.')
@minValue(1)
@maxValue(32)
param partitionCount int = 4

@description('Event hub message retention in days (Standard allows 1 to 7).')
@minValue(1)
@maxValue(7)
param retentionDays int = 1

@description('Blob container for Event Hubs checkpoints (NS_INGESTION_CHECKPOINT_CONTAINER).')
param checkpointContainerName string = 'ns-ingestion-checkpoints'

@description('Blob container for the redacted archive (NS_ARCHIVE_CONTAINER).')
param archiveContainerName string = 'ns-archive'

@description('Blob container for quarantined events.')
param quarantineContainerName string = 'ns-quarantine'

@description('Object (principal) id of the API managed identity.')
param apiPrincipalId string

@description('Object (principal) id of the workers managed identity.')
param workersPrincipalId string

// Built-in role definition ids (GUIDs, not hosts).
var eventHubsDataSender = '2b629674-e913-4c01-ae53-ef4638d8f975'
var eventHubsDataReceiver = 'a638d3c7-ab3a-418d-83e6-5f17a39d4fde'
var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageBlobDataReader = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'

resource namespace 'Microsoft.EventHub/namespaces@2024-01-01' existing = {
  name: namespaceName
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource hub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: namespace
  name: eventHubName
  properties: {
    partitionCount: partitionCount
    retentionDescription: {
      cleanupPolicy: 'Delete'
      retentionTimeInHours: retentionDays * 24
    }
  }
}

resource consumerGroup 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = {
  parent: hub
  name: consumerGroupName
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: storage
  name: 'default'
}

resource checkpoints 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: checkpointContainerName
}

resource archive 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: archiveContainerName
}

resource quarantine 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: quarantineContainerName
}

resource apiSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: hub
  name: guid(hub.id, apiPrincipalId, eventHubsDataSender)
  properties: {
    principalId: apiPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', eventHubsDataSender)
  }
}

resource workersReceiver 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: hub
  name: guid(hub.id, workersPrincipalId, eventHubsDataReceiver)
  properties: {
    principalId: workersPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', eventHubsDataReceiver)
  }
}

resource workersCheckpoints 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: checkpoints
  name: guid(checkpoints.id, workersPrincipalId, storageBlobDataContributor)
  properties: {
    principalId: workersPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributor)
  }
}

resource workersArchive 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: archive
  name: guid(archive.id, workersPrincipalId, storageBlobDataContributor)
  properties: {
    principalId: workersPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributor)
  }
}

resource workersQuarantine 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: quarantine
  name: guid(quarantine.id, workersPrincipalId, storageBlobDataContributor)
  properties: {
    principalId: workersPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributor)
  }
}

// The replay API reads the redacted archive (ArchiveTraceReader) and never writes it.
resource apiArchiveReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: archive
  name: guid(archive.id, apiPrincipalId, storageBlobDataReader)
  properties: {
    principalId: apiPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataReader)
  }
}

@description('Event hub name.')
output eventHubName string = hub.name

@description('Consumer group name.')
output consumerGroupName string = consumerGroup.name

@description('Checkpoint blob container name.')
output checkpointContainerName string = checkpoints.name

@description('Archive blob container name.')
output archiveContainerName string = archive.name

@description('Quarantine blob container name.')
output quarantineContainerName string = quarantine.name
