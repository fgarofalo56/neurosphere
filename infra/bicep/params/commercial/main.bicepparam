// Azure Commercial parameters for modules/main.bicep.
// Hostnames are never listed here; the templates derive them from environment().
using '../../modules/main.bicep'

param namePrefix = 'nsphere'
param location = 'eastus2'
param tags = {
  workload: 'neurosphere'
  cloud: 'commercial'
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
