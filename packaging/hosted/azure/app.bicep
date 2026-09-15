targetScope = 'resourceGroup'
param location string = 'centralus'
param appName string = 'ca-dtm-builder-pilot-cus'
param environmentName string = 'cae-dtm-builder-pilot-cus'
param identityName string = 'id-dtm-builder-pilot-cus'
param registryName string = 'acrdtmpilotcus0910'
param metadataAccountName string = 'stdtmmetacus0910'
@minLength(36)
@maxLength(36)
param tenantId string
@minLength(36)
@maxLength(36)
param clientId string
@minLength(36)
@maxLength(36)
param employeeObjectId string
@description('64 lowercase hexadecimal characters from the published, verified registry manifest, not Docker image ID.')
@minLength(64)
@maxLength(64)
param imageDigestHex string
@secure()
@minLength(1)
param entraClientSecret string
@secure()
@minLength(1)
param tokenStoreSasUrl string
@description('Keep false on first deployment. Enable only after auth configuration and assignment are read back.')
param externalIngress bool = false

resource environment 'Microsoft.App/managedEnvironments@2026-01-01' existing = { name: environmentName }
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = { name: identityName }
resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' existing = { name: registryName }
// Internal ingress has a different hostname. Reapply updates origin/probes together.
var hostname = externalIngress ? '${appName}.${environment.properties.defaultDomain}' : '${appName}.internal.${environment.properties.defaultDomain}'
resource app 'Microsoft.App/containerApps@2026-01-01' = {
  name: appName
  location: location
  tags: { purpose: 'dtm-isolated-pilot', owner: 'seth@dtmfleet.com' }
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: externalIngress, targetPort: 8080, transport: 'http', allowInsecure: false }
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
      secrets: [
        { name: 'pilot-entra-client-secret', value: entraClientSecret }
        { name: 'pilot-token-store-sas', value: tokenStoreSasUrl }
      ]
    }
    template: {
      containers: [{
        name: 'boundary'
        image: '${registry.properties.loginServer}/dtm-hosted-boundary@sha256:${imageDigestHex}'
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'DTM_RUNTIME_MODE', value: 'hosted' }
          { name: 'DTM_CLOUD', value: '0' }
          { name: 'DTM_HOSTED_ORIGIN', value: 'https://${hostname}' }
          { name: 'DTM_HOSTED_TENANT_ID', value: tenantId }
          { name: 'DTM_HOSTED_CLIENT_ID', value: clientId }
          { name: 'DTM_METADATA_ACCOUNT', value: metadataAccountName }
          { name: 'DTM_METADATA_TABLE', value: 'DtmPilotMetadata' }
          { name: 'DTM_METADATA_IDENTITY_CLIENT_ID', value: identity.properties.clientId }
          { name: 'DTM_WORKSPACE_DIR', value: '/tmp/dtm-hosted-workspace' }
          { name: 'DTM_ARTIFACT_ROOT', value: '/tmp/dtm-artifacts' }
        ]
        probes: [for kind in ['Startup', 'Liveness', 'Readiness']: {
          type: kind
          httpGet: { path: '/healthz', port: 8080, httpHeaders: [{ name: 'Host', value: hostname }] }
          initialDelaySeconds: 5
          periodSeconds: 10
          timeoutSeconds: 3
          failureThreshold: kind == 'Startup' ? 30 : 3
        }]
      }]
      scale: {
        minReplicas: 0
        maxReplicas: 1
        rules: [{ name: 'http', http: { metadata: { concurrentRequests: '10' } } }]
      }
    }
  }
}
resource auth 'Microsoft.App/containerApps/authConfigs@2026-01-01' = {
  parent: app
  name: 'current'
  properties: {
    platform: { enabled: true }
    globalValidation: { unauthenticatedClientAction: 'Return401', excludedPaths: ['/healthz'] }
    httpSettings: { requireHttps: true }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: clientId
          clientSecretSettingName: 'pilot-entra-client-secret'
          openIdIssuer: '${az.environment().authentication.loginEndpoint}${tenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [clientId]
          defaultAuthorizationPolicy: { allowedPrincipals: { identities: [employeeObjectId] } }
        }
      }
    }
    login: {
      allowedExternalRedirectUrls: []
      nonce: { validateNonce: true, nonceExpirationInterval: '00:05:00' }
      cookieExpiration: { convention: 'FixedTime', timeToExpiration: '00:30:00' }
      tokenStore: { enabled: true, azureBlobStorage: { sasUrlSettingName: 'pilot-token-store-sas' } }
    }
  }
}
output origin string = 'https://${hostname}'
output redirectUri string = 'https://${hostname}/.auth/login/aad/callback'
output authResourceId string = auth.id
