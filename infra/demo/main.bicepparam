using './main.bicep'

// Placeholders and non-sensitive defaults only. scripts/gates/hosted_demo.py generates the real
// parameter file at deploy time from operator arguments (hub subnet and zone ids, tenant and
// client ids, budget contacts, tags); none of those values belong in this public repository.
param prefix = 'nsdemo'
param location = 'centralus'
param appServiceSkuName = 'B2'
param deployKeyVault = true
param imageTag = '0.1.0-rc.2'
param copilotDeployment = 'mini'
param copilotMode = 'disabled'
param budgetAmount = 200

// PRP-138: Entra claim to role mapping (NS_AUTH_ROLE_MAPPINGS). Off by default. The deploy script
// fills it from --entra-role-mappings-file; the tenant and client ids in it are not committed.
// Shape: { tenant_id: '<tenant guid>', audience: '<api app id>', entries: [ { id: 'ns-admins',
//   claim: 'roles', value: 'admin', role: 'admin', domains: 'all', customer_control: true } ] }
param entraRoleMappings = {}

// PRP-139: the data mode and customer id. The deploy script writes both from --data-mode and
// --customer-id and fills the two id lists from --log-analytics-workspace-ids and
// --apim-service-ids; the defaults here are the synthetic hosted demo and assign nothing.
param dataMode = 'demo'
param customerId = 'synthco'
param logAnalyticsWorkspaceIds = []
param apimServiceIds = []

param integrationSubnetId = 'REPLACED-AT-DEPLOY'
param privateEndpointSubnetId = 'REPLACED-AT-DEPLOY'
param cosmosDnsZoneId = 'REPLACED-AT-DEPLOY'
param eventHubsDnsZoneId = 'REPLACED-AT-DEPLOY'
param blobDnsZoneId = 'REPLACED-AT-DEPLOY'
param webAppsDnsZoneId = 'REPLACED-AT-DEPLOY'
param keyVaultDnsZoneId = 'REPLACED-AT-DEPLOY'
param entraTenantId = 'REPLACED-AT-DEPLOY'
param entraClientId = 'REPLACED-AT-DEPLOY'
param copilotEndpoint = 'REPLACED-AT-DEPLOY'
param budgetStartDate = 'REPLACED-AT-DEPLOY'
param budgetContactEmails = []
param tagOwner = 'REPLACED-AT-DEPLOY'
param tagDeleteAfter = 'REPLACED-AT-DEPLOY'
param deploymentId = 'REPLACED-AT-DEPLOY'
param createdBy = 'REPLACED-AT-DEPLOY'
