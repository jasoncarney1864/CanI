// CanI — low-cost Azure Container Apps deployment (docs/22-low-cost-rebuild.md, ADR-008).
//
// Resource-group scoped. Everything the product needs lives in this one template so a
// fresh subscription goes from empty to running with one `az deployment group create`
// plus one migration-job start. Design rules, in priority order:
//
//   1. Nothing costs money while idle except Postgres. No VNet (removes the load
//      balancer, private endpoints and private DNS zones that were a third of the
//      August 2026 bill), no Key Vault, no container registry (images come from GHCR),
//      APIs and the worker scale to zero, one capped Log Analytics workspace.
//   2. Guardrails are IN the template, not a runbook: a budget scoped to this resource
//      group with real alert emails, an action group, and three alerts. The August
//      incident was a backup job that was defined in IaC and never applied; a deploy
//      that creates the guardrails is the only kind that cannot forget them.
//   3. Production posture by default: ENV=prod (dev-login stub is 404), only `web` is
//      externally reachable, TLS everywhere, blob soft-delete + versioning on.
//
// Vectors live in Postgres via pgvector (migration 0009); the server parameter
// `azure.extensions` below is what allows CREATE EXTENSION vector to succeed.

targetScope = 'resourceGroup'

// ---------------------------------------------------------------------------------------
// Parameters
// ---------------------------------------------------------------------------------------

@description('Short environment label used in resource names and tags.')
param environmentName string = 'prod'

@description('Region for everything except the Static Web App (see swaLocation).')
param location string = resourceGroup().location

@description('Static Web Apps is only offered in a handful of regions; eastus is not one of them.')
param swaLocation string = 'eastus2'

@description('Image tag to deploy for every service (the CD workflow passes the commit SHA).')
param imageTag string

@description('GHCR owner (GitHub user or org) that publishes the images, e.g. jasoncarney1864.')
param ghcrOwner string

@description('GitHub username used to pull from GHCR.')
param ghcrUsername string

@secure()
@description('GitHub token with read:packages, used by Container Apps to pull images.')
param ghcrToken string

@description('Postgres administrator login.')
param postgresAdminLogin string = 'caniadmin'

@secure()
param postgresAdminPassword string

@secure()
param tokenSigningSecret string

@secure()
param sessionSecret string

@description('Entra External ID authority, e.g. https://caniauth.ciamlogin.com/<tenant-id>/v2.0')
param entraOidcAuthority string

param entraOidcClientId string

@secure()
param entraClientSecret string

@description('Azure OpenAI-compatible endpoint of the Foundry resource, e.g. https://<name>.openai.azure.com/')
param azureOpenAIEndpoint string

@secure()
param azureOpenAIApiKey string

param azureOpenAIApiVersion string = '2024-10-21'
param azureOpenAIEmbeddingDeployment string = 'text-embedding-3-small'
param azureOpenAIChatDeployment string = 'gpt-5-mini'

@description('Document Intelligence endpoint of the same Foundry resource, e.g. https://<name>.cognitiveservices.azure.com/')
param azureDocumentIntelligenceEndpoint string

@secure()
param azureDocumentIntelligenceApiKey string

@secure()
@description('Optional. Speech key for the voice feature; empty disables it in the web app.')
param azureSpeechApiKey string = ''

param azureSpeechRegion string = 'eastus'

@description('Public hostname for the web app.')
param customDomain string = 'app.canido.co'

@description('''Custom-domain rollout phase, because a managed certificate cannot be created and bound in one deployment:
0 = no custom domain (first deploy; take the webAppFqdn and customDomainVerificationId outputs to GoDaddy),
1 = domain added to the app unbound so Azure can validate the CNAME + asuid TXT,
2 = managed certificate issued and bound (steady state).''')
@allowed([0, 1, 2])
param customDomainPhase int = 0

@description('Turns the public-law corpus on (retrieval dual-corpus + weekly refresh job).')
param lawCorpusEnabled bool = true

@description('Real NRS fetching in the refresh job. Explicit on purpose (fakes-in-prod incident class).')
param lawFetchEnabled bool = true

@description('Monthly budget for this resource group in USD. Alerts at 50/80/100% actual and 100% forecast.')
param budgetAmountUsd int = 30

@description('Where budget and operational alerts go. Use a mailbox that is actually read.')
param alertEmail string

@description('Start of the current month; budgets must start on the 1st. Defaulted so it never has to be typed.')
param budgetStartDate string = utcNow('yyyy-MM-01')

var tags = {
  project: 'cani'
  environment: environmentName
  owner: 'jason'
  costCenter: 'personal'
  managedBy: 'bicep'
}

var prefix = 'cani-${environmentName}'
var registryServer = 'ghcr.io'
var image = {
  hubApi: '${registryServer}/${ghcrOwner}/cani-hub-api:${imageTag}'
  docsApi: '${registryServer}/${ghcrOwner}/cani-docs-api:${imageTag}'
  web: '${registryServer}/${ghcrOwner}/cani-web:${imageTag}'
  ingestionWorker: '${registryServer}/${ghcrOwner}/cani-ingestion-worker:${imageTag}'
  retrievalWorker: '${registryServer}/${ghcrOwner}/cani-retrieval-worker:${imageTag}'
  migrate: '${registryServer}/${ghcrOwner}/cani-migrate:${imageTag}'
}
var postgresDb = 'cani'
// Storage account names: 3-24 lowercase alphanumerics, globally unique.
var storageAccountName = toLower(replace('canist${environmentName}${uniqueString(resourceGroup().id)}', '-', ''))

// ---------------------------------------------------------------------------------------
// Observability (one workspace, capped) and the alerting plumbing
// ---------------------------------------------------------------------------------------

resource logWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    // August 2026: Log Analytics was the single largest line item ($76) because the
    // Container Apps workspace had no cap at all. 0.5 GB/day is ~15 GB/month, three times
    // the free 5 GB but still a $7 ceiling — and far above what five idle apps emit.
    workspaceCapping: { dailyQuotaGb: json('0.5') }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: '${prefix}-ops'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'cani-ops'
    enabled: true
    emailReceivers: [
      { name: 'owner', emailAddress: alertEmail, useCommonAlertSchema: true }
    ]
  }
}

// ---------------------------------------------------------------------------------------
// Data: Postgres (also the vector store) and Blob Storage
// ---------------------------------------------------------------------------------------

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${prefix}-pg'
  location: location
  tags: tags
  sku: {
    // The only always-on compute in the design. B1ms is the smallest tier Flexible
    // Server offers; HNSW over tens of thousands of chunks is comfortable here.
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: postgresAdminLogin
    administratorLoginPassword: postgresAdminPassword
    storage: {
      storageSizeGB: 32
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: { mode: 'Disabled' }
    network: {
      // No VNet by design (see header). Reachability is controlled by the firewall rule
      // below; transport is TLS-only (Flexible Server default require_secure_transport=on).
      publicNetworkAccess: 'Enabled'
    }
  }
}

// Container Apps on the Consumption plan without a VNet have no stable egress IP, so the
// standard "allow Azure services" rule is the only way to let them in without paying for
// a VNet + NAT. Cost of this choice: any Azure-hosted client that knows the password can
// connect. The password is 48 random chars and lives only in Container Apps secrets.
resource postgresAllowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'AllowAllAzureServicesAndResourcesWithinAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// pgvector must be allow-listed before `CREATE EXTENSION vector` (migration 0009) can run.
resource postgresExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: postgres
  name: 'azure.extensions'
  properties: {
    value: 'VECTOR'
    source: 'user-override'
  }
  dependsOn: [postgresAllowAzure]
}

resource postgresDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: postgresDb
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
  dependsOn: [postgresExtensions]
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
    accessTier: 'Hot'
  }
}

// docs/21 phase 2 hard gate: deletion is tombstone-then-async-cleanup, so the originals
// must survive an accidental or buggy delete long enough to notice. 7-day soft delete and
// versioning on both blobs and containers — the same settings the old account was
// verified to have live.
resource storageBlobServices 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 7 }
    containerDeleteRetentionPolicy: { enabled: true, days: 7 }
    isVersioningEnabled: true
  }
}

var storageConnectionString = 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'

// KEDA's postgresql scaler takes a libpq connection string; sslmode=require matches the
// server's TLS-only posture.
var postgresScalerConnection = 'postgresql://${postgresAdminLogin}:${uriComponent(postgresAdminPassword)}@${postgres.properties.fullyQualifiedDomainName}:5432/${postgresDb}?sslmode=require'

// ---------------------------------------------------------------------------------------
// Container Apps environment
// ---------------------------------------------------------------------------------------

resource containerAppEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logWorkspace.properties.customerId
        sharedKey: logWorkspace.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
    zoneRedundant: false
  }
}

// Managed certificate for the custom domain (phase 2 only). Azure validates ownership via
// the CNAME on `customDomain` plus the asuid TXT record carrying
// customDomainVerificationId — both of which must already be at GoDaddy.
resource customDomainCertificate 'Microsoft.App/managedEnvironments/managedCertificates@2024-03-01' = if (customDomainPhase == 2) {
  parent: containerAppEnv
  name: 'mc-${replace(customDomain, '.', '-')}'
  location: location
  tags: tags
  properties: {
    subjectName: customDomain
    domainControlValidation: 'CNAME'
  }
}

// ---------------------------------------------------------------------------------------
// Shared pieces for every app
// ---------------------------------------------------------------------------------------

var registries = [
  {
    server: registryServer
    username: ghcrUsername
    passwordSecretRef: 'ghcr-token'
  }
]

// Every secret an app could need. Container Apps only stores what is declared; apps
// declare the subset they reference via secretRef below.
var allSecrets = [
  { name: 'ghcr-token', value: ghcrToken }
  { name: 'postgres-password', value: postgresAdminPassword }
  { name: 'postgres-scaler-connection', value: postgresScalerConnection }
  { name: 'token-signing-secret', value: tokenSigningSecret }
  { name: 'session-secret', value: sessionSecret }
  { name: 'storage-connection-string', value: storageConnectionString }
  { name: 'entra-client-secret', value: entraClientSecret }
  { name: 'azure-openai-api-key', value: azureOpenAIApiKey }
  { name: 'docintel-api-key', value: azureDocumentIntelligenceApiKey }
  { name: 'azure-speech-api-key', value: azureSpeechApiKey }
]

// Common to every Python service. ENV=prod is what turns the dev-login stub into a 404
// and makes hub-api refuse to start without Entra configured — the previous template
// never set it, so production ran with dev-mode auth paths reachable.
var pythonCommonEnv = [
  { name: 'ENV', value: 'prod' }
  { name: 'POSTGRES_HOST', value: postgres.properties.fullyQualifiedDomainName }
  { name: 'POSTGRES_PORT', value: '5432' }
  { name: 'POSTGRES_DB', value: postgresDb }
  { name: 'POSTGRES_USER', value: postgresAdminLogin }
  { name: 'POSTGRES_PASSWORD', secretRef: 'postgres-password' }
  { name: 'CANI_TOKEN_SIGNING_SECRET', secretRef: 'token-signing-secret' }
  { name: 'CANI_SESSION_SECRET', secretRef: 'session-secret' }
  { name: 'AZURE_STORAGE_CONNECTION_STRING', secretRef: 'storage-connection-string' }
  { name: 'AZURE_STORAGE_ACCOUNT_NAME', value: storage.name }
]

// Both endpoint AND key, always together: with either missing the provider factory
// silently builds the fakes (CLAUDE.md "Fake providers fail open").
var aiEnv = [
  { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenAIEndpoint }
  { name: 'AZURE_OPENAI_API_KEY', secretRef: 'azure-openai-api-key' }
  { name: 'AZURE_OPENAI_API_VERSION', value: azureOpenAIApiVersion }
  { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: azureOpenAIEmbeddingDeployment }
  { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: azureOpenAIChatDeployment }
]

var lawEnv = [
  { name: 'CANI_LAW_CORPUS_ENABLED', value: string(lawCorpusEnabled) }
  { name: 'CANI_LAW_FETCH_ENABLED', value: string(lawFetchEnabled) }
  { name: 'CANI_LAW_DEFAULT_JURISDICTIONS', value: 'us-nv' }
]

var smallResources = { cpu: json('0.25'), memory: '0.5Gi' }

func healthProbes(port int, readyPath string) array => [
  {
    type: 'Readiness'
    httpGet: { path: readyPath, port: port, scheme: 'HTTP' }
    initialDelaySeconds: 5
    periodSeconds: 10
  }
  {
    type: 'Liveness'
    httpGet: { path: '/healthz', port: port, scheme: 'HTTP' }
    initialDelaySeconds: 15
    periodSeconds: 30
  }
]

// ---------------------------------------------------------------------------------------
// Apps
// ---------------------------------------------------------------------------------------

resource hubApiApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'hub-api'
  location: location
  tags: tags
  properties: {
    environmentId: containerAppEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: false, targetPort: 8001, transport: 'http', allowInsecure: false }
      registries: registries
      secrets: allSecrets
    }
    template: {
      containers: [
        {
          name: 'hub-api'
          image: image.hubApi
          resources: smallResources
          env: concat(pythonCommonEnv, [
            { name: 'ENTRA_OIDC_AUTHORITY', value: entraOidcAuthority }
            { name: 'ENTRA_OIDC_CLIENT_ID', value: entraOidcClientId }
            { name: 'ENTRA_OIDC_CLIENT_SECRET', secretRef: 'entra-client-secret' }
            { name: 'ENTRA_OIDC_REDIRECT_URI', value: 'https://${customDomain}/auth/callback' }
          ])
          probes: healthProbes(8001, '/healthz')
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
        rules: [{ name: 'http', http: { metadata: { concurrentRequests: '20' } } }]
      }
    }
  }
}

resource retrievalWorkerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'retrieval-worker'
  location: location
  tags: tags
  properties: {
    environmentId: containerAppEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: false, targetPort: 8003, transport: 'http', allowInsecure: false }
      registries: registries
      secrets: allSecrets
    }
    template: {
      containers: [
        {
          name: 'retrieval-worker'
          image: image.retrievalWorker
          resources: smallResources
          env: concat(pythonCommonEnv, aiEnv, lawEnv)
          // /readyz exercises Postgres + pgvector on every probe (2026-08-09 lesson: a
          // dead dependency must fail readiness, not liveness).
          probes: healthProbes(8003, '/readyz')
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
        rules: [{ name: 'http', http: { metadata: { concurrentRequests: '10' } } }]
      }
    }
  }
}

resource docsApiApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'docs-api'
  location: location
  tags: tags
  properties: {
    environmentId: containerAppEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: false, targetPort: 8002, transport: 'http', allowInsecure: false }
      registries: registries
      secrets: allSecrets
    }
    template: {
      containers: [
        {
          name: 'docs-api'
          image: image.docsApi
          resources: smallResources
          env: concat(pythonCommonEnv, aiEnv, lawEnv, [
            { name: 'RETRIEVAL_WORKER_URL', value: 'https://${retrievalWorkerApp.properties.configuration.ingress.fqdn}' }
          ])
          probes: healthProbes(8002, '/healthz')
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
        rules: [{ name: 'http', http: { metadata: { concurrentRequests: '20' } } }]
      }
    }
  }
}

resource webApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'web'
  location: location
  tags: tags
  properties: {
    environmentId: containerAppEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true // the only public surface
        targetPort: 3000
        transport: 'http'
        allowInsecure: false
        customDomains: customDomainPhase == 0 ? null : [
          {
            name: customDomain
            bindingType: customDomainPhase == 2 ? 'SniEnabled' : 'Disabled'
            certificateId: customDomainPhase == 2 ? customDomainCertificate.id : null
          }
        ]
      }
      registries: registries
      secrets: allSecrets
    }
    template: {
      containers: [
        {
          name: 'web'
          image: image.web
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'NODE_ENV', value: 'production' }
            { name: 'HUB_API_URL', value: 'https://${hubApiApp.properties.configuration.ingress.fqdn}' }
            { name: 'DOCS_API_URL', value: 'https://${docsApiApp.properties.configuration.ingress.fqdn}' }
            { name: 'AZURE_SPEECH_API_KEY', secretRef: 'azure-speech-api-key' }
            { name: 'AZURE_SPEECH_REGION', value: azureSpeechRegion }
          ]
          probes: [
            {
              type: 'Readiness'
              httpGet: { path: '/api/health', port: 3000, scheme: 'HTTP' }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        // One warm replica so the first visitor is not met by a cold start. Idle
        // replicas bill at the idle rate (a few dollars a month at most).
        minReplicas: 1
        maxReplicas: 3
        rules: [{ name: 'http', http: { metadata: { concurrentRequests: '50' } } }]
      }
    }
  }
}

resource ingestionWorkerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ingestion-worker'
  location: location
  tags: tags
  properties: {
    environmentId: containerAppEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      registries: registries
      secrets: allSecrets
    }
    template: {
      containers: [
        {
          name: 'ingestion-worker'
          image: image.ingestionWorker
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: concat(pythonCommonEnv, aiEnv, lawEnv, [
            { name: 'AZURE_DOCUMENTINTELLIGENCE_ENDPOINT', value: azureDocumentIntelligenceEndpoint }
            { name: 'AZURE_DOCUMENTINTELLIGENCE_API_KEY', secretRef: 'docintel-api-key' }
          ])
        }
      ]
      scale: {
        // Scale-to-zero poller: KEDA wakes it when either queue has work. maxReplicas is
        // 1 on purpose — deletion.process_deletion's single-worker invariant (docs/21
        // §1.7) is only race-free with one replica.
        minReplicas: 0
        maxReplicas: 1
        rules: [
          {
            name: 'queued-jobs'
            custom: {
              type: 'postgresql'
              metadata: {
                // Both queues, same statuses repositories.claim_next_* look for.
                query: 'SELECT (SELECT count(*) FROM ingestion_jobs WHERE status IN (\'queued\', \'retry_pending\')) + (SELECT count(*) FROM deletion_jobs WHERE status = \'queued\')'
                targetQueryValue: '1'
                activationTargetQueryValue: '0'
              }
              auth: [
                { secretRef: 'postgres-scaler-connection', triggerParameter: 'connection' }
              ]
            }
          }
        ]
      }
    }
  }
}

// ---------------------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------------------

// One migration job, updated to each commit's image and started by the CD workflow (the
// previous workflow created a new job per commit and left them all behind).
resource migrateJob 'Microsoft.App/jobs@2024-03-01' = {
  name: '${prefix}-migrate'
  location: location
  tags: tags
  properties: {
    environmentId: containerAppEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      replicaTimeout: 300
      replicaRetryLimit: 1
      registries: registries
      secrets: allSecrets
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: image.migrate
          resources: smallResources
          env: [
            { name: 'POSTGRES_HOST', value: postgres.properties.fullyQualifiedDomainName }
            { name: 'POSTGRES_PORT', value: '5432' }
            { name: 'POSTGRES_DB', value: postgresDb }
            { name: 'POSTGRES_USER', value: postgresAdminLogin }
            { name: 'POSTGRES_PASSWORD', secretRef: 'postgres-password' }
          ]
        }
      ]
    }
  }
  dependsOn: [postgresDatabase]
}

// Weekly public-law refresh (docs/20 §20.7) on the ingestion image.
resource lawRefreshJob 'Microsoft.App/jobs@2024-03-01' = if (lawCorpusEnabled) {
  name: '${prefix}-law-refresh'
  location: location
  tags: tags
  properties: {
    environmentId: containerAppEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Schedule'
      scheduleTriggerConfig: { cronExpression: '0 3 * * 0', parallelism: 1, replicaCompletionCount: 1 }
      replicaTimeout: 1800
      replicaRetryLimit: 1
      registries: registries
      secrets: allSecrets
    }
    template: {
      containers: [
        {
          name: 'law-refresh'
          image: image.ingestionWorker
          command: ['python', '-m', 'ingestion_worker_app.law_refresh']
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: concat(pythonCommonEnv, aiEnv, lawEnv)
        }
      ]
    }
  }
}

// ---------------------------------------------------------------------------------------
// Marketing site (free tier)
// ---------------------------------------------------------------------------------------

resource marketingSite 'Microsoft.Web/staticSites@2023-12-01' = {
  name: '${prefix}-marketing'
  location: swaLocation
  tags: tags
  sku: { name: 'Free', tier: 'Free' }
  properties: {
    stagingEnvironmentPolicy: 'Disabled'
    allowConfigFileUpdates: true
  }
}

// ---------------------------------------------------------------------------------------
// Guardrails: budget + alerts. These are the point of the exercise.
// ---------------------------------------------------------------------------------------

module budget 'budget.bicep' = {
  name: 'budget-${environmentName}'
  scope: subscription()
  params: {
    budgetName: '${prefix}-monthly'
    amountUsd: budgetAmountUsd
    startDate: budgetStartDate
    resourceGroupName: resourceGroup().name
    contactEmails: [alertEmail]
    actionGroupId: actionGroup.id
  }
}

// Public 5xx: the symptom users see. 20 in 5 minutes is well above any health-probe noise.
resource webServerErrorsAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${prefix}-web-5xx'
  location: 'global'
  tags: tags
  properties: {
    description: 'web returned 20+ 5xx responses in 5 minutes'
    severity: 2
    enabled: true
    scopes: [webApp.id]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    targetResourceType: 'Microsoft.App/containerApps'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          criterionType: 'StaticThresholdCriterion'
          name: 'server-errors'
          metricNamespace: 'Microsoft.App/containerApps'
          metricName: 'Requests'
          dimensions: [{ name: 'statusCodeCategory', operator: 'Include', values: ['5xx'] }]
          operator: 'GreaterThan'
          threshold: 20
          timeAggregation: 'Total'
        }
      ]
    }
    actions: [{ actionGroupId: actionGroup.id }]
  }
}

// Postgres is the one fixed-cost, single-instance dependency; sustained CPU saturation on
// a B1ms is the early warning for "retrieval is about to time out".
resource postgresCpuAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${prefix}-pg-cpu'
  location: 'global'
  tags: tags
  properties: {
    description: 'Postgres CPU above 90% for 15 minutes'
    severity: 2
    enabled: true
    scopes: [postgres.id]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    targetResourceType: 'Microsoft.DBforPostgreSQL/flexibleServers'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          criterionType: 'StaticThresholdCriterion'
          name: 'cpu'
          metricNamespace: 'Microsoft.DBforPostgreSQL/flexibleServers'
          metricName: 'cpu_percent'
          operator: 'GreaterThan'
          threshold: 90
          timeAggregation: 'Average'
        }
      ]
    }
    actions: [{ actionGroupId: actionGroup.id }]
  }
}

// Dead-lettered ingestion or deletion jobs are the silent failure mode: the user sees
// "failed" on one document and nobody else sees anything. Both workers log the event
// names below (pipeline.handle_job_failure, deletion.handle_deletion_failure).
resource deadLetterAlert 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: '${prefix}-dead-letter'
  location: location
  tags: tags
  properties: {
    displayName: 'CanI: job dead-lettered'
    description: 'An ingestion or deletion job exhausted its retries in the last 15 minutes'
    severity: 2
    enabled: true
    scopes: [logWorkspace.id]
    evaluationFrequency: 'PT15M'
    windowSize: 'PT15M'
    criteria: {
      allOf: [
        {
          query: 'ContainerAppConsoleLogs_CL | where ContainerAppName_s == "ingestion-worker" | where Log_s has "job_dead_lettered" or Log_s has "deletion_job_dead_lettered"'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
        }
      ]
    }
    actions: { actionGroups: [actionGroup.id] }
    autoMitigate: false
  }
}

// ---------------------------------------------------------------------------------------
// Outputs the CD workflow and the DNS cutover need
// ---------------------------------------------------------------------------------------

output resourceGroupName string = resourceGroup().name
output containerAppEnvName string = containerAppEnv.name
output containerAppEnvDefaultDomain string = containerAppEnv.properties.defaultDomain
@description('Value for the asuid.<customDomain> TXT record at GoDaddy.')
output customDomainVerificationId string = containerAppEnv.properties.customDomainConfiguration.customDomainVerificationId
@description('CNAME target for the custom domain at GoDaddy.')
output webAppFqdn string = webApp.properties.configuration.ingress.fqdn
output postgresHost string = postgres.properties.fullyQualifiedDomainName
output storageAccountName string = storage.name
output migrateJobName string = migrateJob.name
output marketingSiteName string = marketingSite.name
output marketingSiteDefaultHostname string = marketingSite.properties.defaultHostname
