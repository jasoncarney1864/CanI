// Container Apps migration from AKS
// Cost savings: ~50-70% reduction by eliminating node pools and cluster management fees
// Architecture: Hub-API + Docs-API + Web + 2 workers + Qdrant on consumption-based billing

targetScope = 'resourceGroup'

@description('Environment name (dev, prod)')
param environmentName string = 'dev'

@description('Location for all resources')
param location string = resourceGroup().location

@description('Container registry name (existing)')
param acrName string

@description('Container registry login server')
param acrLoginServer string

@description('Azure OpenAI endpoint')
param azureOpenAIEndpoint string = 'https://cani-openai.openai.azure.com/'

@description('PostgreSQL host')
param postgresHost string

@description('PostgreSQL database name')
param postgresDb string = 'cani'

@description('PostgreSQL user')
param postgresUser string = 'caniadmin'

@description('PostgreSQL password')
@secure()
param postgresPassword string

@description('JWT token signing secret')
@secure()
param tokenSigningSecret string

@description('Session cookie encryption secret')
@secure()
param sessionSecret string

@description('Azure Storage connection string')
@secure()
param storageConnectionString string

@description('Microsoft Entra OIDC client secret')
@secure()
param entraClientSecret string

@description('Azure Storage account name')
param storageAccountName string = 'cani6ada34dffd'

@description('Microsoft Entra OIDC Authority (tenant endpoint)')
param entraOidcAuthority string

@description('Microsoft Entra OIDC Client ID')
param entraOidcClientId string

@description('Key Vault name for secrets')
param keyVaultName string

@description('Key Vault resource group (if different from deployment RG)')
param keyVaultResourceGroup string = resourceGroup().name

@description('Managed Identity ID for workload identity')
param managedIdentityId string

@description('Managed Identity Client ID')
param managedIdentityClientId string

@description('VNet resource group name for private networking')
param vnetResourceGroup string = 'cani-workload-core-canido-dev-eastus2-rgca86c588'

@description('VNet name for Container Apps integration')
param vnetName string = 'cani-workload-vnet84822d25'

@description('Container Apps subnet name (must be delegated to Microsoft.App/environments)')
param containerAppsSubnetName string = 'ContainerAppsSubnet'

// Existing resources
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
  scope: resourceGroup(keyVaultResourceGroup)
}

// Reference existing VNet and subnet for private networking
resource vnet 'Microsoft.Network/virtualNetworks@2023-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroup)
}

resource containerAppsSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-05-01' existing = {
  parent: vnet
  name: containerAppsSubnetName
}

// Log Analytics workspace for Container Apps
resource logWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: 'cani-logs-${environmentName}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// Container Apps Environment
resource containerAppEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cani-env-${environmentName}'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logWorkspace.properties.customerId
        sharedKey: logWorkspace.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    vnetConfiguration: {
      infrastructureSubnetId: containerAppsSubnet.id
      internal: false
    }
  }
}

// Storage account for Qdrant persistence
resource qdrantStorage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'caniqd${uniqueString(resourceGroup().id)}'
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource qdrantStorageFileService 'Microsoft.Storage/storageAccounts/fileServices@2023-01-01' = {
  parent: qdrantStorage
  name: 'default'
}

resource qdrantFileShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-01-01' = {
  parent: qdrantStorageFileService
  name: 'qdrant-data'
  properties: {
    shareQuota: 20 // 20 GiB (matches k8s PVC)
    enabledProtocols: 'SMB'
  }
}

// Qdrant storage mount
resource qdrantStorageMount 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  parent: containerAppEnv
  name: 'qdrant-storage'
  properties: {
    azureFile: {
      accountName: qdrantStorage.name
      accountKey: qdrantStorage.listKeys().keys[0].value
      shareName: qdrantFileShare.name
      accessMode: 'ReadWrite'
    }
  }
}

// Qdrant Container App (replacement for StatefulSet)
resource qdrantApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'qdrant'
  location: location
  properties: {
    environmentId: containerAppEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false // internal only
        targetPort: 6333
        transport: 'http'
        allowInsecure: true // Allow HTTP for internal-only traffic
      }
      // No registries config - using public Docker Hub image
    }
    template: {
      containers: [
        {
          name: 'qdrant'
          image: 'qdrant/qdrant:v1.9.7'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          volumeMounts: [
            {
              volumeName: 'qdrant-storage'
              mountPath: '/qdrant/storage'
            }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/'
                port: 6333
                scheme: 'HTTP'
              }
              initialDelaySeconds: 15
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/'
                port: 6333
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1 // single instance (matches k8s StatefulSet replicas: 1)
      }
      volumes: [
        {
          name: 'qdrant-storage'
          storageName: qdrantStorageMount.name
          storageType: 'AzureFile'
        }
      ]
    }
  }
}

// Hub API Container App
resource hubApiApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'hub-api'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    environmentId: containerAppEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8001
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: acrLoginServer
          identity: managedIdentityId
        }
      ]
      secrets: [
        {
          name: 'postgres-password'
          value: postgresPassword
        }
        {
          name: 'token-signing-secret'
          value: tokenSigningSecret
        }
        {
          name: 'session-secret'
          value: sessionSecret
        }
        {
          name: 'storage-connection-string'
          value: storageConnectionString
        }
        {
          name: 'entra-client-secret'
          value: entraClientSecret
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'hub-api'
          image: '${acrLoginServer}/hub-api:latest' // override in workflow
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            { name: 'POSTGRES_HOST', value: postgresHost }
            { name: 'POSTGRES_PORT', value: '5432' }
            { name: 'POSTGRES_DB', value: postgresDb }
            { name: 'POSTGRES_USER', value: postgresUser }
            { name: 'POSTGRES_PASSWORD', secretRef: 'postgres-password' }
            { name: 'CANI_TOKEN_SIGNING_SECRET', secretRef: 'token-signing-secret' }
            { name: 'CANI_SESSION_SECRET', secretRef: 'session-secret' }
            { name: 'AZURE_STORAGE_CONNECTION_STRING', secretRef: 'storage-connection-string' }
            { name: 'AZURE_STORAGE_ACCOUNT_NAME', value: storageAccountName }
            { name: 'ENTRA_OIDC_CLIENT_SECRET', secretRef: 'entra-client-secret' }
            { name: 'ENTRA_OIDC_AUTHORITY', value: entraOidcAuthority }
            { name: 'ENTRA_OIDC_CLIENT_ID', value: entraOidcClientId }
            // ENTRA_OIDC_REDIRECT_URI will be computed and updated after deployment
            // It should be: https://<web-app-fqdn>/auth/callback
            { name: 'AZURE_CLIENT_ID', value: managedIdentityClientId }
            { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenAIEndpoint }
            { name: 'AZURE_OPENAI_API_VERSION', value: '2024-10-21' }
            { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: 'text-embedding-3-small' }
            { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: 'gpt-5-1' }
            { name: 'QDRANT_URL', value: 'http://qdrant:6333' }
            { name: 'QDRANT_COLLECTION', value: 'cani_docs_${environmentName}_v2' }
          ]
          probes: [
            {
              type: 'Readiness'
              httpGet: {
                path: '/healthz'
                port: 8001
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/healthz'
                port: 8001
                scheme: 'HTTP'
              }
              initialDelaySeconds: 15
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 5
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '20'
              }
            }
          }
        ]
      }
    }
  }
}

// Docs API Container App
resource docsApiApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'docs-api'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    environmentId: containerAppEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8002
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: acrLoginServer
          identity: managedIdentityId
        }
      ]
      secrets: [
        {
          name: 'postgres-password'
          value: postgresPassword
        }
        {
          name: 'token-signing-secret'
          value: tokenSigningSecret
        }
        {
          name: 'session-secret'
          value: sessionSecret
        }
        {
          name: 'storage-connection-string'
          value: storageConnectionString
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'docs-api'
          image: '${acrLoginServer}/docs-api@sha256:85e9ac48a086c370bde6191edbf3089d0162837730132c9396572ed6144e6a6e'
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            { name: 'POSTGRES_HOST', value: postgresHost }
            { name: 'POSTGRES_PORT', value: '5432' }
            { name: 'POSTGRES_DB', value: postgresDb }
            { name: 'POSTGRES_USER', value: postgresUser }
            { name: 'POSTGRES_PASSWORD', secretRef: 'postgres-password' }
            { name: 'CANI_TOKEN_SIGNING_SECRET', secretRef: 'token-signing-secret' }
            { name: 'CANI_SESSION_SECRET', secretRef: 'session-secret' }
            { name: 'AZURE_STORAGE_CONNECTION_STRING', secretRef: 'storage-connection-string' }
            { name: 'AZURE_STORAGE_ACCOUNT_NAME', value: storageAccountName }
            { name: 'AZURE_CLIENT_ID', value: managedIdentityClientId }
            { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenAIEndpoint }
            { name: 'AZURE_OPENAI_API_VERSION', value: '2024-10-21' }
            { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: 'text-embedding-3-small' }
            { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: 'gpt-5-1' }
            { name: 'QDRANT_URL', value: 'http://qdrant:6333' }
            { name: 'QDRANT_COLLECTION', value: 'cani_docs_${environmentName}_v2' }
          ]
          probes: [
            {
              type: 'Readiness'
              httpGet: {
                path: '/healthz'
                port: 8002
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/healthz'
                port: 8002
                scheme: 'HTTP'
              }
              initialDelaySeconds: 15
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 10
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '20'
              }
            }
          }
        ]
      }
    }
  }
}

// Web (Next.js) Container App
resource webApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'web'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    environmentId: containerAppEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true // public-facing
        targetPort: 3000
        transport: 'http'
        allowInsecure: false
        // Custom domain removed for initial deployment - add back later with certificate
      }
      registries: [
        {
          server: acrLoginServer
          identity: managedIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'web'
          image: '${acrLoginServer}/web@sha256:df9e5554c67951841b75090b8507c2d40cf3819fbfea250dbedee8a5d538d012'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'HUB_API_URL', value: 'https://${hubApiApp.properties.configuration.ingress.fqdn}' }
            { name: 'DOCS_API_URL', value: 'https://${docsApiApp.properties.configuration.ingress.fqdn}' }
          ]
          probes: [
            {
              type: 'Readiness'
              httpGet: {
                path: '/api/health'
                port: 3000
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 10
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
}

// Ingestion Worker Container App (KEDA-enabled)
resource ingestionWorkerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ingestion-worker'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    environmentId: containerAppEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [
        {
          server: acrLoginServer
          identity: managedIdentityId
        }
      ]
      secrets: [
        {
          name: 'postgres-password'
          value: postgresPassword
        }
        {
          name: 'token-signing-secret'
          value: tokenSigningSecret
        }
        {
          name: 'session-secret'
          value: sessionSecret
        }
        {
          name: 'storage-connection-string'
          value: storageConnectionString
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'ingestion-worker'
          image: '${acrLoginServer}/ingestion-worker@sha256:81bbeaaec0799a6bf3742518b48762ca03a8250cadfe191161af4b296027237f'
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            { name: 'POSTGRES_HOST', value: postgresHost }
            { name: 'POSTGRES_PORT', value: '5432' }
            { name: 'POSTGRES_DB', value: postgresDb }
            { name: 'POSTGRES_USER', value: postgresUser }
            { name: 'POSTGRES_PASSWORD', secretRef: 'postgres-password' }
            { name: 'CANI_TOKEN_SIGNING_SECRET', secretRef: 'token-signing-secret' }
            { name: 'CANI_SESSION_SECRET', secretRef: 'session-secret' }
            { name: 'AZURE_STORAGE_CONNECTION_STRING', secretRef: 'storage-connection-string' }
            { name: 'AZURE_STORAGE_ACCOUNT_NAME', value: storageAccountName }
            { name: 'AZURE_CLIENT_ID', value: managedIdentityClientId }
            { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenAIEndpoint }
            { name: 'AZURE_OPENAI_API_VERSION', value: '2024-10-21' }
            { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: 'text-embedding-3-small' }
            { name: 'QDRANT_URL', value: 'http://qdrant:6333' }
            { name: 'QDRANT_COLLECTION', value: 'cani_docs_${environmentName}_v2' }
          ]
        }
      ]
      scale: {
        minReplicas: 0 // scale to zero when idle
        maxReplicas: 5
        rules: [
          {
            name: 'postgres-scaling'
            custom: {
              type: 'postgresql'
              metadata: {
                targetQueryValue: '5' // scale when >5 pending jobs
                query: 'SELECT COUNT(*) FROM ingestion_jobs WHERE status = \'pending\''
                connectionFromEnv: 'POSTGRES_CONNECTION_STRING'
              }
              // Note: identity authentication not supported in custom scale rules
              // The container's managed identity will be used for POSTGRES_CONNECTION_STRING
            }
          }
        ]
      }
    }
  }
}

// Retrieval Worker Container App (KEDA-enabled)
resource retrievalWorkerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'retrieval-worker'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    environmentId: containerAppEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8003
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: acrLoginServer
          identity: managedIdentityId
        }
      ]
      secrets: [
        {
          name: 'postgres-password'
          value: postgresPassword
        }
        {
          name: 'token-signing-secret'
          value: tokenSigningSecret
        }
        {
          name: 'session-secret'
          value: sessionSecret
        }
        {
          name: 'storage-connection-string'
          value: storageConnectionString
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'retrieval-worker'
          image: '${acrLoginServer}/retrieval-worker@sha256:76f5c89a3ad1e8dfca0945eda1c6b5ce5607ae0636395759e9b77543bd824f88'
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            { name: 'POSTGRES_HOST', value: postgresHost }
            { name: 'POSTGRES_PORT', value: '5432' }
            { name: 'POSTGRES_DB', value: postgresDb }
            { name: 'POSTGRES_USER', value: postgresUser }
            { name: 'POSTGRES_PASSWORD', secretRef: 'postgres-password' }
            { name: 'CANI_TOKEN_SIGNING_SECRET', secretRef: 'token-signing-secret' }
            { name: 'CANI_SESSION_SECRET', secretRef: 'session-secret' }
            { name: 'AZURE_STORAGE_CONNECTION_STRING', secretRef: 'storage-connection-string' }
            { name: 'AZURE_STORAGE_ACCOUNT_NAME', value: storageAccountName }
            { name: 'AZURE_CLIENT_ID', value: managedIdentityClientId }
            { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenAIEndpoint }
            { name: 'AZURE_OPENAI_API_VERSION', value: '2024-10-21' }
            { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: 'text-embedding-3-small' }
            { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: 'gpt-5-1' }
            { name: 'QDRANT_URL', value: 'http://qdrant:6333' }
            { name: 'QDRANT_COLLECTION', value: 'cani_docs_${environmentName}_v2' }
          ]
          probes: [
            {
              type: 'Readiness'
              httpGet: {
                path: '/healthz'
                port: 8003
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 5
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

// Outputs for workflow consumption
output containerAppEnvId string = containerAppEnv.id
output containerAppEnvDefaultDomain string = containerAppEnv.properties.defaultDomain
output webAppFqdn string = webApp.properties.configuration.ingress.fqdn
output hubApiFqdn string = hubApiApp.properties.configuration.ingress.fqdn
output docsApiFqdn string = docsApiApp.properties.configuration.ingress.fqdn
output retrievalWorkerFqdn string = retrievalWorkerApp.properties.configuration.ingress.fqdn
output qdrantFqdn string = qdrantApp.properties.configuration.ingress.fqdn
