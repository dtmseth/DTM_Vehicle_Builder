targetScope = 'resourceGroup'

param location string = 'centralus'
param registryName string = 'acrdtmpilotcus0910'
param metadataAccountName string = 'stdtmmetacus0910'
param tokenAccountName string = 'stdtmtokencus0910'
param backupAccountName string = 'stdtmbackupcus0910'
param environmentName string = 'cae-dtm-builder-pilot-cus'
param identityName string = 'id-dtm-builder-pilot-cus'
param workspaceName string = 'law-dtm-builder-pilot-cus'
var tags = { purpose: 'dtm-isolated-pilot', owner: 'seth@dtmfleet.com' }

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
  tags: tags
}
resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' = {
  name: registryName
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    roleAssignmentMode: 'LegacyRegistryPermissions'
    policies: { azureADAuthenticationAsArmPolicy: { status: 'enabled' } }
  }
}
resource pullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, 'AcrPull')
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
resource accounts 'Microsoft.Storage/storageAccounts@2025-01-01' = [for (name, i) in [metadataAccountName, tokenAccountName, backupAccountName]: {
  name: name
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    // Only the isolated platform token account permits a service SAS.
    allowSharedKeyAccess: i == 1
    encryption: {
      keySource: 'Microsoft.Storage'
      services: {
        table: { enabled: true, keyType: 'Service' }
        blob: { enabled: true, keyType: 'Account' }
      }
    }
  }
}]
resource tables 'Microsoft.Storage/storageAccounts/tableServices@2025-01-01' = {
  parent: accounts[0]
  name: 'default'
}
resource metadata 'Microsoft.Storage/storageAccounts/tableServices/tables@2025-01-01' = {
  parent: tables
  name: 'DtmPilotMetadata'
}
resource tableRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(metadata.id, identity.id, 'TableContributor')
  scope: metadata
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
resource tokenBlobs 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: accounts[1]
  name: 'default'
}
resource tokens 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: tokenBlobs
  name: 'auth-tokens'
  properties: { publicAccess: 'None' }
}
resource backupBlobs 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: accounts[2]
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 7 }
    containerDeleteRetentionPolicy: { enabled: true, days: 7 }
  }
}
resource backups 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: backupBlobs
  name: 'job-snapshots'
  properties: { publicAccess: 'None' }
}
resource backupRetention 'Microsoft.Storage/storageAccounts/managementPolicies@2025-01-01' = {
  parent: accounts[2]
  name: 'default'
  properties: {
    policy: {
      rules: [{
        name: 'expire-pilot-job-snapshots'
        enabled: true
        type: 'Lifecycle'
        definition: {
          filters: { blobTypes: ['blockBlob'], prefixMatch: ['job-snapshots/'] }
          actions: { baseBlob: { delete: { daysAfterModificationGreaterThan: 14 } } }
        }
      }]
    }
  }
}
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  tags: tags
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}
resource environment 'Microsoft.App/managedEnvironments@2026-01-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}
// No credentials or listKeys results are outputs.
output environmentId string = environment.id
output defaultDomain string = environment.properties.defaultDomain
output registryServer string = registry.properties.loginServer
output runtimeIdentityId string = identity.id
output runtimeIdentityClientId string = identity.properties.clientId
output metadataAccount string = accounts[0].name
output metadataTable string = metadata.name
output workspaceId string = logs.id
