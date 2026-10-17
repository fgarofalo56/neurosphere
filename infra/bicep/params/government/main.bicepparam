// Azure Government parameters for modules/main.bicep.
// Hostnames are never listed here; the templates derive them from environment(), which
// resolves to Government suffixes when deployed to the AzureUSGovernment cloud.
// Government regions only. Government data never routes to Commercial.
using '../../modules/main.bicep'

param namePrefix = 'nsphere'
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
