#Requires -Version 7.0
<#
.SYNOPSIS
    Deploy Container Apps with secrets retrieved from Key Vault
.DESCRIPTION
    Retrieves all required secrets from Key Vault and deploys the Container Apps infrastructure.
    Temporarily enables Key Vault public access if needed, then disables it after retrieval.
#>

param(
    [string]$ResourceGroup = "cani-container-apps-dev",
    [string]$Location = "eastus2",
    [string]$KeyVaultName = "cani-platform-kv2e5cf1f6",
    [string]$KeyVaultResourceGroup = "cani-platform-core-canido-dev-eastus2-rged7032c2",
    [switch]$WhatIf,
    [switch]$SkipValidation
)

$ErrorActionPreference = "Stop"

Write-Host "🔐 Retrieving secrets from Key Vault: $KeyVaultName" -ForegroundColor Cyan

# Check if Key Vault is accessible
try {
    $kvAccess = az keyvault secret list --vault-name $KeyVaultName --query "[0].name" -o tsv 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "⚠️  Key Vault is not accessible. Checking public access..." -ForegroundColor Yellow
        $kv = az keyvault show --name $KeyVaultName --resource-group $KeyVaultResourceGroup | ConvertFrom-Json
        if ($kv.properties.publicNetworkAccess -eq "Disabled") {
            Write-Host "🔓 Temporarily enabling Key Vault public access..." -ForegroundColor Yellow
            az keyvault update --name $KeyVaultName --resource-group $KeyVaultResourceGroup --public-network-access Enabled --default-action Allow | Out-Null
            Start-Sleep -Seconds 5  # Wait for propagation
            $restorePrivateAccess = $true
        }
    }
} catch {
    Write-Error "Failed to access Key Vault: $_"
    exit 1
}

# Retrieve secrets
Write-Host "📥 Retrieving secrets..." -ForegroundColor Cyan
try {
    $tokenSigningSecret = az keyvault secret show --vault-name $KeyVaultName --name cani-token-signing-secret --query value -o tsv
    $sessionSecret = az keyvault secret show --vault-name $KeyVaultName --name cani-session-secret --query value -o tsv
    $storageConnectionString = az keyvault secret show --vault-name $KeyVaultName --name azure-storage-connection-string --query value -o tsv
    $entraClientSecret = az keyvault secret show --vault-name $KeyVaultName --name entra-oidc-client-secret --query value -o tsv
    $postgresPassword = az keyvault secret show --vault-name $KeyVaultName --name postgres-password --query value -o tsv
    $qdrantApiKey = az keyvault secret show --vault-name $KeyVaultName --name qdrant-api-key --query value -o tsv
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($qdrantApiKey)) {
        throw "Key Vault secret 'qdrant-api-key' is missing or empty. Create it first: az keyvault secret set --vault-name $KeyVaultName --name qdrant-api-key --value '<key from Qdrant Cloud>' --output none"
    }
    # These two were dropped in the AKS->Container Apps migration and nothing errored:
    # the missing OpenAI key silently swapped in FakeEmbedder/FakeGrounder, and the
    # missing Document Intelligence key permanently failed every OCR ingestion job
    # (both discovered 2026-08-12 during the post-corruption re-ingest). Hard-fail here
    # if absent — a deploy without them produces a system that lies.
    $azureOpenAIApiKey = az keyvault secret show --vault-name $KeyVaultName --name azure-openai-api-key --query value -o tsv
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($azureOpenAIApiKey)) {
        throw "Key Vault secret 'azure-openai-api-key' is missing or empty. Without it the workers run fake AI providers."
    }
    $azureDocumentIntelligenceApiKey = az keyvault secret show --vault-name $KeyVaultName --name azure-documentintelligence-api-key --query value -o tsv
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($azureDocumentIntelligenceApiKey)) {
        throw "Key Vault secret 'azure-documentintelligence-api-key' is missing or empty. Without it OCR ingestion fails permanently."
    }

    # Unlike the two above, missing LiveAvatar secrets don't degrade silently — docs-api's
    # /avatar/session-token returns 503 rather than faking a session (see main.bicep's
    # liveAvatarApiKey param comment) — so this warns instead of hard-failing the deploy.
    $liveAvatarApiKey = az keyvault secret show --vault-name $KeyVaultName --name liveavatar-api-key --query value -o tsv 2>$null
    $liveAvatarAvatarId = az keyvault secret show --vault-name $KeyVaultName --name liveavatar-avatar-id --query value -o tsv 2>$null
    if ([string]::IsNullOrWhiteSpace($liveAvatarApiKey) -or [string]::IsNullOrWhiteSpace($liveAvatarAvatarId)) {
        Write-Host "⚠️  LiveAvatar Key Vault secret(s) missing or empty — the avatar feature will report 503 (not configured) after this deploy." -ForegroundColor Yellow
        $liveAvatarApiKey = ""
        $liveAvatarAvatarId = ""
    }

    Write-Host "✅ Retrieved secrets successfully" -ForegroundColor Green
} catch {
    Write-Error "Failed to retrieve secrets: $_"
    exit 1
} finally {
    # Restore private access if we enabled it
    if ($restorePrivateAccess) {
        Write-Host "🔒 Restoring Key Vault private access..." -ForegroundColor Yellow
        az keyvault update --name $KeyVaultName --resource-group $KeyVaultResourceGroup --public-network-access Disabled | Out-Null
    }
}

# Convert secrets to SecureStrings
$securePostgresPassword = ConvertTo-SecureString -String $postgresPassword -AsPlainText -Force
$secureTokenSigningSecret = ConvertTo-SecureString -String $tokenSigningSecret -AsPlainText -Force
$secureSessionSecret = ConvertTo-SecureString -String $sessionSecret -AsPlainText -Force
$secureStorageConnectionString = ConvertTo-SecureString -String $storageConnectionString -AsPlainText -Force
$secureEntraClientSecret = ConvertTo-SecureString -String $entraClientSecret -AsPlainText -Force
$secureQdrantApiKey = ConvertTo-SecureString -String $qdrantApiKey -AsPlainText -Force
$secureAzureOpenAIApiKey = ConvertTo-SecureString -String $azureOpenAIApiKey -AsPlainText -Force
$secureAzureDocumentIntelligenceApiKey = ConvertTo-SecureString -String $azureDocumentIntelligenceApiKey -AsPlainText -Force
$secureLiveAvatarApiKey = ConvertTo-SecureString -String $liveAvatarApiKey -AsPlainText -Force
$secureLiveAvatarAvatarId = ConvertTo-SecureString -String $liveAvatarAvatarId -AsPlainText -Force

# Clear plaintext secrets from memory
$postgresPassword = $null
$tokenSigningSecret = $null
$sessionSecret = $null
$storageConnectionString = $null
$entraClientSecret = $null
$qdrantApiKey = $null
$azureOpenAIApiKey = $null
$azureDocumentIntelligenceApiKey = $null
$liveAvatarApiKey = $null
$liveAvatarAvatarId = $null

Write-Host "🚀 Deploying Container Apps..." -ForegroundColor Cyan

# Call the main deployment script with all parameters
$deployParams = @{
    ResourceGroup = $ResourceGroup
    Location = $Location
    PostgresPassword = $securePostgresPassword
    TokenSigningSecret = $secureTokenSigningSecret
    SessionSecret = $secureSessionSecret
    StorageConnectionString = $secureStorageConnectionString
    EntraClientSecret = $secureEntraClientSecret
    QdrantApiKey = $secureQdrantApiKey
    AzureOpenAIApiKey = $secureAzureOpenAIApiKey
    AzureDocumentIntelligenceApiKey = $secureAzureDocumentIntelligenceApiKey
    LiveAvatarApiKey = $secureLiveAvatarApiKey
    LiveAvatarAvatarId = $secureLiveAvatarAvatarId
}

if ($WhatIf) { $deployParams['WhatIf'] = $true }
if ($SkipValidation) { $deployParams['SkipValidation'] = $true }

& "$PSScriptRoot\deploy.ps1" @deployParams
