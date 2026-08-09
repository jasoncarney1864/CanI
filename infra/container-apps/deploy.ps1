# Container Apps Deployment Script
# Run from repo root: pwsh infra/container-apps/deploy.ps1

param(
    [string]$ResourceGroup = "cani-container-apps-dev",
    [string]$Location = "eastus2",
    [securestring]$PostgresPassword,
    [securestring]$TokenSigningSecret,
    [securestring]$SessionSecret,
    [securestring]$StorageConnectionString,
    [securestring]$EntraClientSecret,
    [securestring]$QdrantApiKey,
    [string]$AcrLoginServer = "canishared19088c8d54.azurecr.io",
    [switch]$WhatIf,
    [switch]$SkipValidation
)

$ErrorActionPreference = "Stop"

Write-Host "🚀 CanI Container Apps Migration Deployment" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan

# Prompt for secrets if not provided
if (-not $PostgresPassword) {
    Write-Host "`n🔑 PostgreSQL password required for deployment" -ForegroundColor Yellow
    $PostgresPassword = Read-Host "Enter PostgreSQL password for caniadmin" -AsSecureString
}

if (-not $TokenSigningSecret) {
    Write-Host "`n🔑 Token signing secret required for deployment" -ForegroundColor Yellow
    $TokenSigningSecret = Read-Host "Enter CANI_TOKEN_SIGNING_SECRET" -AsSecureString
}

if (-not $SessionSecret) {
    Write-Host "`n🔑 Session secret required for deployment" -ForegroundColor Yellow
    $SessionSecret = Read-Host "Enter CANI_SESSION_SECRET" -AsSecureString
}

if (-not $StorageConnectionString) {
    Write-Host "`n🔑 Storage connection string required for deployment" -ForegroundColor Yellow
    $StorageConnectionString = Read-Host "Enter AZURE_STORAGE_CONNECTION_STRING" -AsSecureString
}

if (-not $EntraClientSecret) {
    Write-Host "`n🔑 Entra OIDC client secret required for deployment" -ForegroundColor Yellow
    $EntraClientSecret = Read-Host "Enter ENTRA_OIDC_CLIENT_SECRET" -AsSecureString
}

if (-not $QdrantApiKey) {
    Write-Host "`n🔑 Qdrant Cloud API key required for deployment" -ForegroundColor Yellow
    $QdrantApiKey = Read-Host "Enter QDRANT_API_KEY" -AsSecureString
}

# Check Azure CLI login
Write-Host "`n🔐 Checking Azure CLI authentication..." -ForegroundColor Yellow
$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Host "❌ Not logged in to Azure CLI. Run: az login" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Logged in as: $($account.user.name)" -ForegroundColor Green
Write-Host "   Subscription: $($account.name) ($($account.id))" -ForegroundColor Gray

# Create resource group if it doesn't exist
Write-Host "`n📦 Checking resource group: $ResourceGroup" -ForegroundColor Yellow
$rgExists = az group exists --name $ResourceGroup
if ($rgExists -eq "false") {
    Write-Host "   Creating resource group..." -ForegroundColor Yellow
    az group create --name $ResourceGroup --location $Location --tags "environment=dev" "project=cani" "migration=aks-to-container-apps" | Out-Null
    Write-Host "✅ Resource group created" -ForegroundColor Green
} else {
    Write-Host "✅ Resource group exists" -ForegroundColor Green
}

# Container images are owned by container-apps-cd-dev.yml, not by this template. Read
# whatever each app is running right now and pass it straight back in, so an infra deploy
# is image-neutral. First-time bootstrap (app does not exist yet) falls back to :latest.
function Get-LiveImage {
    param([string]$AppName, [string]$Fallback)
    $img = az containerapp show --name $AppName --resource-group $ResourceGroup `
        --query "properties.template.containers[0].image" -o tsv 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($img)) {
        Write-Host "   $AppName not deployed yet - bootstrapping with $Fallback" -ForegroundColor Yellow
        return $Fallback
    }
    Write-Host "   $AppName -> $img" -ForegroundColor Gray
    return $img
}

Write-Host "`n📦 Resolving currently-running container images..." -ForegroundColor Yellow
$hubApiImage          = Get-LiveImage -AppName "hub-api"          -Fallback "$AcrLoginServer/hub-api:latest"
$docsApiImage         = Get-LiveImage -AppName "docs-api"         -Fallback "$AcrLoginServer/docs-api:latest"
$webImage             = Get-LiveImage -AppName "web"              -Fallback "$AcrLoginServer/web:latest"
$ingestionWorkerImage = Get-LiveImage -AppName "ingestion-worker" -Fallback "$AcrLoginServer/ingestion-worker:latest"
$retrievalWorkerImage = Get-LiveImage -AppName "retrieval-worker" -Fallback "$AcrLoginServer/retrieval-worker:latest"

$imageParams = @(
    "hubApiImage=$hubApiImage"
    "docsApiImage=$docsApiImage"
    "webImage=$webImage"
    "ingestionWorkerImage=$ingestionWorkerImage"
    "retrievalWorkerImage=$retrievalWorkerImage"
)

$bicepFile = Join-Path $PSScriptRoot "main.bicep"
$parametersFile = Join-Path $PSScriptRoot "main.parameters.json"

# Validation
if (-not $SkipValidation) {
    Write-Host "`n🔍 Validating Bicep template..." -ForegroundColor Yellow
    $validationOutput = az deployment group validate `
        --resource-group $ResourceGroup `
        --template-file $bicepFile `
        --parameters $parametersFile `
        --parameters postgresPassword=DummyPasswordForValidation123! `
        --parameters tokenSigningSecret=DummyTokenSigningSecret123456789012345678901234567890 `
        --parameters sessionSecret=DummySessionSecret123456789012345678901234567890 `
        --parameters storageConnectionString="DefaultEndpointsProtocol=https;AccountName=dummy;AccountKey=dummykey123;EndpointSuffix=core.windows.net" `
        --parameters entraClientSecret=DummyEntraClientSecret12345678901234567890 `
        --parameters qdrantApiKey=DummyQdrantApiKey1234567890 `
        --parameters $imageParams `
        --output json 2>&1
    
    $validationExitCode = $LASTEXITCODE
    
    if ($validationExitCode -ne 0) {
        Write-Host "❌ Validation failed:" -ForegroundColor Red
        Write-Host $validationOutput -ForegroundColor Red
        exit 1
    }
    
    try {
        $validation = $validationOutput | ConvertFrom-Json
        if ($validation.error) {
            Write-Host "❌ Validation failed:" -ForegroundColor Red
            Write-Host ($validation.error | ConvertTo-Json -Depth 10) -ForegroundColor Red
            exit 1
        }
    } catch {
        # If JSON parsing fails but exit code was 0, validation likely succeeded
        if ($validationExitCode -eq 0) {
            Write-Host "✅ Template validation passed" -ForegroundColor Green
        } else {
            Write-Host "❌ Validation failed (JSON parse error):" -ForegroundColor Red
            Write-Host $validationOutput -ForegroundColor Red
            exit 1
        }
    }
    
    Write-Host "✅ Template validation passed" -ForegroundColor Green
}

# What-if analysis
if ($WhatIf) {
    Write-Host "`n🔮 Running What-If analysis..." -ForegroundColor Yellow
    az deployment group what-if `
        --resource-group $ResourceGroup `
        --template-file $bicepFile `
        --parameters $parametersFile `
        --parameters postgresPassword=DummyPasswordForValidation123! `
        --parameters tokenSigningSecret=DummyTokenSigningSecret123456789012345678901234567890 `
        --parameters sessionSecret=DummySessionSecret123456789012345678901234567890 `
        --parameters storageConnectionString="DefaultEndpointsProtocol=https;AccountName=dummy;AccountKey=dummykey123;EndpointSuffix=core.windows.net" `
        --parameters entraClientSecret=DummyEntraClientSecret12345678901234567890 `
        --parameters qdrantApiKey=DummyQdrantApiKey1234567890 `
        --parameters $imageParams
    
    Write-Host "`n⚠️  What-If mode enabled - no changes deployed" -ForegroundColor Yellow
    exit 0
}

# Deploy
Write-Host "`n🚢 Deploying Container Apps infrastructure..." -ForegroundColor Yellow
$deploymentName = "container-apps-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Write-Host "   Deployment name: $deploymentName" -ForegroundColor Gray

# Convert secure strings to plain text for Azure CLI (CLI requires plain text parameters)
function ConvertFrom-SecureStringToPlainText {
    param([securestring]$SecureString)
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureString)
    $PlainText = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)
    return $PlainText
}

$postgresPasswordPlain = ConvertFrom-SecureStringToPlainText $PostgresPassword
$tokenSigningSecretPlain = ConvertFrom-SecureStringToPlainText $TokenSigningSecret
$sessionSecretPlain = ConvertFrom-SecureStringToPlainText $SessionSecret
$storageConnectionStringPlain = ConvertFrom-SecureStringToPlainText $StorageConnectionString
$entraClientSecretPlain = ConvertFrom-SecureStringToPlainText $EntraClientSecret
$qdrantApiKeyPlain = ConvertFrom-SecureStringToPlainText $QdrantApiKey

try {
    $deployment = az deployment group create `
        --resource-group $ResourceGroup `
        --template-file $bicepFile `
        --parameters $parametersFile `
        --parameters postgresPassword=$postgresPasswordPlain `
        --parameters tokenSigningSecret=$tokenSigningSecretPlain `
        --parameters sessionSecret=$sessionSecretPlain `
        --parameters storageConnectionString=$storageConnectionStringPlain `
        --parameters entraClientSecret=$entraClientSecretPlain `
        --parameters qdrantApiKey=$qdrantApiKeyPlain `
        --parameters $imageParams `
        --name $deploymentName `
        --output json | ConvertFrom-Json

    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Deployment failed!" -ForegroundColor Red
        exit 1
    }
} finally {
    # Clear all plain text secrets from memory
    $postgresPasswordPlain = $null
    $tokenSigningSecretPlain = $null
    $sessionSecretPlain = $null
    $storageConnectionStringPlain = $null
    $entraClientSecretPlain = $null
    $qdrantApiKeyPlain = $null
}

Write-Host "✅ Deployment completed successfully!" -ForegroundColor Green

# Show outputs
Write-Host "`n📊 Deployment Outputs:" -ForegroundColor Cyan
$deployment.properties.outputs.PSObject.Properties | ForEach-Object {
    Write-Host "   $($_.Name): $($_.Value.value)" -ForegroundColor Gray
}

# ENTRA_OIDC_REDIRECT_URI is set from the `customDomain` bicep parameter (app.canido.co),
# not the Container Apps auto-generated FQDN — do not override it here (see incident
# 2026-08-06: pointing it at the auto FQDN broke sign-in with AADSTS50011).


# Grant permissions
Write-Host "`n🔑 Granting managed identity permissions..." -ForegroundColor Yellow

# Get ACR resource ID
$acrId = az acr show --name canishared19088c8d54 --query id -o tsv

# Grant AcrPull role
Write-Host "   Granting AcrPull to managed identity..." -ForegroundColor Gray
az role assignment create `
    --assignee 984dbce5-2209-4df0-b904-41bdcce2596c `
    --role AcrPull `
    --scope $acrId `
    --output none 2>$null

# Grant Key Vault access
Write-Host "   Granting Key Vault secret access..." -ForegroundColor Gray
az keyvault set-policy `
    --name cani-platform-kv2e5cf1f6 `
    --object-id 984dbce5-2209-4df0-b904-41bdcce2596c `
    --secret-permissions get list `
    --output none 2>$null

Write-Host "✅ Permissions granted" -ForegroundColor Green

# Next steps
Write-Host "`n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "✅ Infrastructure deployed successfully!" -ForegroundColor Green
Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "1. Build and push initial images:" -ForegroundColor White
Write-Host "   cd apps && docker compose build && docker compose push" -ForegroundColor Gray
Write-Host "`n2. Update GitHub Actions environment variables:" -ForegroundColor White
Write-Host "   CONTAINER_APPS_RESOURCE_GROUP = $ResourceGroup" -ForegroundColor Gray
Write-Host "   (See docs/container-apps-migration-guide.md Phase 5)" -ForegroundColor Gray
Write-Host "`n3. Test workflow:" -ForegroundColor White
Write-Host "   gh workflow run container-apps-cd-dev.yml" -ForegroundColor Gray
Write-Host "`n4. Monitor for 7 days, then decommission AKS" -ForegroundColor White
Write-Host "   (See migration guide for full steps)" -ForegroundColor Gray
Write-Host "`n📖 Full migration guide: docs/container-apps-migration-guide.md" -ForegroundColor Cyan
