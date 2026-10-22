// Azure Government parameters for modules/main.bicep.
// Hostnames are never listed here; the templates derive them from environment(), which
// resolves to Government suffixes when deployed to the AzureUSGovernment cloud.
// Government regions only. Government data never routes to Commercial.
using '../../modules/main.bicep'

// Host-level record (endpoints, audiences, private DNS zones, egress hosts, disabled options):
// sovereign-profile.yaml in this folder.
param namePrefix = 'nsphere'
// Default region. The customer selects: usgovvirginia, usgovarizona or usgovtexas.
// usgovtexas is Fabric-only (AI Search semantic ranker and agentic retrieval are not available there).
param location = 'usgovvirginia'
param tags = {
  workload: 'neurosphere'
  cloud: 'government'
}
param publicNetworkAccess = 'Disabled'

// Set any of these to an existing resource id to reuse instead of create.
param reuseCosmos = ''
param reuseEventHubs = ''
param reuseStorage = ''
param reuseKeyVault = ''
param reuseSearch = ''
param reuseLogAnalytics = ''
param reuseApim = ''
