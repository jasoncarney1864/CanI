// Container Apps migration from AKS
// Cost savings: ~50-70% reduction by eliminating node pools and cluster management fees
// Architecture: Hub-API + Docs-API + Web + 2 workers on consumption-based billing.
// Vectors live in Qdrant Cloud (managed) — Azure Files/SMB cannot host Qdrant's storage engine.

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

@description('Qdrant endpoint URL. Qdrant Cloud cluster URL (https://<cluster-id>.<region>.<cloud>.cloud.qdrant.io:6333), or an internal Container Apps FQDN if you ever move back to self-hosting.')
param qdrantUrl string

@description('Qdrant API key. Required for Qdrant Cloud. Sourced from the qdrant-api-key Key Vault secret by deploy-with-secrets.ps1.')
@secure()
param qdrantApiKey string

// Container images are parameters, NOT hardcoded, because container-apps-cd-dev.yml
// deploys images out-of-band via `az containerapp update --image ...:<git-sha>`. If these
// were pinned in the template, every infra deploy would silently roll all five apps back
// to whatever digest happened to be committed. deploy.ps1 reads the currently-running
// image off each app and passes it through, so an infra change never moves an image.
@description('Currently-running hub-api image. Supplied by deploy.ps1 from the live app.')
param hubApiImage string

@description('Currently-running docs-api image. Supplied by deploy.ps1 from the live app.')
param docsApiImage string

@description('Currently-running web image. Supplied by deploy.ps1 from the live app.')
param webImage string

@description('Currently-running ingestion-worker image. Supplied by deploy.ps1 from the live app.')
param ingestionWorkerImage string

@description('Currently-running retrieval-worker image. Supplied by deploy.ps1 from the live app.')
param retrievalWorkerImage string

@description('Azure Storage account name')
param storageAccountName string = 'cani6ada34dffd'

@description('Microsoft Entra OIDC Authority (tenant endpoint)')
param entraOidcAuthority string

@description('Microsoft Entra OIDC Client ID')
param entraOidcClientId string

@description('Public custom domain the web app is served on (used for the OIDC redirect_uri, NOT the Container Apps auto-generated FQDN)')
param customDomain string = 'app.canido.co'

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
          name: 'qdrant-api-key'
          value: qdrantApiKey
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
          image: hubApiImage
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
            { name: 'ENTRA_OIDC_REDIRECT_URI', value: 'https://${customDomain}/auth/callback' }
            { name: 'AZURE_CLIENT_ID', value: managedIdentityClientId }
            { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenAIEndpoint }
            { name: 'AZURE_OPENAI_API_VERSION', value: '2024-10-21' }
            { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: 'text-embedding-3-small' }
            { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: 'gpt-5-1' }
            { name: 'QDRANT_URL', value: qdrantUrl }
            { name: 'QDRANT_COLLECTION', value: 'cani_docs_${environmentName}_v2' }
            { name: 'QDRANT_API_KEY', secretRef: 'qdrant-api-key' }
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
        {
          name: 'qdrant-api-key'
          value: qdrantApiKey
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'docs-api'
          image: docsApiImage
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
            { name: 'QDRANT_URL', value: qdrantUrl }
            { name: 'QDRANT_COLLECTION', value: 'cani_docs_${environmentName}_v2' }
            { name: 'QDRANT_API_KEY', secretRef: 'qdrant-api-key' }
            { name: 'RETRIEVAL_WORKER_URL', value: 'https://retrieval-worker.internal.${containerAppEnv.properties.defaultDomain}' }
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
          image: webImage
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
        {
          name: 'qdrant-api-key'
          value: qdrantApiKey
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'ingestion-worker'
          image: ingestionWorkerImage
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
            { name: 'QDRANT_URL', value: qdrantUrl }
            { name: 'QDRANT_COLLECTION', value: 'cani_docs_${environmentName}_v2' }
            { name: 'QDRANT_API_KEY', secretRef: 'qdrant-api-key' }
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
        {
          name: 'qdrant-api-key'
          value: qdrantApiKey
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'retrieval-worker'
          image: retrievalWorkerImage
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
            { name: 'QDRANT_URL', value: qdrantUrl }
            { name: 'QDRANT_COLLECTION', value: 'cani_docs_${environmentName}_v2' }
            { name: 'QDRANT_API_KEY', secretRef: 'qdrant-api-key' }
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

// Scheduled Qdrant snapshot -> Blob Storage (docs/09 section 9.10, Sprint 2 C1).
// Replaces the deleted Kubernetes CronJob (k8s/base/qdrant/snapshot-cronjob.yaml). This
// matters MORE on Qdrant Cloud's free tier, which has no automatic backups of its own.
// Runs on the ingestion-worker image, which already carries httpx + the blob SDK, and
// tracks the same image the worker runs. Restore stays a manual operator action --
// see runbooks/backup-restore-drill.md.
resource qdrantSnapshotJob 'Microsoft.App/jobs@2024-03-01' = {
  name: 'qdrant-snapshot'
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
      triggerType: 'Schedule'
      scheduleTriggerConfig: {
        cronExpression: '0 2 * * *' // daily 02:00 UTC, same slot as the old CronJob
        parallelism: 1
        replicaCompletionCount: 1
      }
      replicaTimeout: 1800
      replicaRetryLimit: 2
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
          name: 'qdrant-api-key'
          value: qdrantApiKey
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'qdrant-snapshot'
          image: ingestionWorkerImage
          command: [
            'python'
            '-m'
            'cani_shared.backup'
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
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
            { name: 'QDRANT_URL', value: qdrantUrl }
            { name: 'QDRANT_COLLECTION', value: 'cani_docs_${environmentName}_v2' }
            { name: 'QDRANT_API_KEY', secretRef: 'qdrant-api-key' }
          ]
        }
      ]
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
