#Requires -Version 7.0
<#
.SYNOPSIS
    Deploy CanI to Azure Container Apps from your own machine — the local equivalent of
    .github/workflows/deploy.yml (docs/22-low-cost-rebuild.md). No GitHub involved.
.DESCRIPTION
    Sequence:
      1. Resource group (created if missing).
      2. Phase 1 Bicep deploy with deployApps=false: registry, Postgres, storage, logs,
         budget, alerts. Skipped when the registry already exists.
      3. `az acr build` of the six images — built in Azure, not on this machine.
      4. Phase 2 Bicep deploy with deployApps=true: the apps and jobs.
      5. Start the migration job and wait for it.

    Secrets come from environment variables, or from -SecretsFile (KEY=VALUE lines, one per
    line, kept OUTSIDE the repository — e.g. C:\Users\<you>\.cani\prod.env). Required:
        CANI_SUBSCRIPTION_ID        the CanI subscription id
        CANI_ALERT_EMAIL            a mailbox that is actually read
        CANI_PG_PASSWORD            >= 32 chars
        CANI_TOKEN_SIGNING_SECRET   >= 32 chars
        CANI_SESSION_SECRET         >= 32 chars
        CANI_ENTRA_CLIENT_SECRET    from the Entra app registration
        CANI_AZURE_OPENAI_API_KEY   Foundry resource key
        CANI_DOCINTEL_API_KEY       same Foundry resource key
    Optional:
        CANI_SPEECH_API_KEY         same Foundry key enables the voice feature; empty disables it
    Generate the three random secrets with:
        python -c "import secrets; print(secrets.token_urlsafe(48))"
.PARAMETER ImageTag
    Tag for the six images (short git SHA by default). Reused as-is with -SkipBuild.
.PARAMETER CustomDomainPhase
    0 on first deploy; 1 after the GoDaddy records are in; 2 once Azure has validated them.
.EXAMPLE
    pwsh infra/container-apps/deploy.ps1 -SecretsFile $HOME\.cani\prod.env -WhatIf
.EXAMPLE
    pwsh infra/container-apps/deploy.ps1 -SecretsFile $HOME\.cani\prod.env -CustomDomainPhase 2
#>
param(
    [string]$SecretsFile,
    [string]$SubscriptionId,
    [string]$ResourceGroup = "rg-cani-prod-eus",
    [string]$Location = "eastus",
    [string]$ImageTag = (git rev-parse --short=7 HEAD),
    [ValidateSet(0, 1, 2)]
    [int]$CustomDomainPhase = 0,
    [switch]$SkipBuild,
    [switch]$SkipMigrations,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$template = Join-Path $PSScriptRoot "main.bicep"
$parameters = Join-Path $PSScriptRoot "main.parameters.json"

if ($SecretsFile) {
    if (-not (Test-Path $SecretsFile)) { throw "Secrets file not found: $SecretsFile" }
    foreach ($line in Get-Content $SecretsFile) {
        if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$' -and -not $line.StartsWith("#")) {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim('"'))
        }
    }
}
if (-not $SubscriptionId) { $SubscriptionId = $env:CANI_SUBSCRIPTION_ID }
if (-not $SubscriptionId) { throw "Set CANI_SUBSCRIPTION_ID (or -SubscriptionId)." }

function Require-Env([string]$name, [bool]$optional = $false) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if (-not $value -and -not $optional) { throw "Environment variable $name is not set. See the header of this script." }
    return $value
}

$secrets = @{
    postgresAdminPassword           = Require-Env "CANI_PG_PASSWORD"
    tokenSigningSecret              = Require-Env "CANI_TOKEN_SIGNING_SECRET"
    sessionSecret                   = Require-Env "CANI_SESSION_SECRET"
    entraClientSecret               = Require-Env "CANI_ENTRA_CLIENT_SECRET"
    azureOpenAIApiKey               = Require-Env "CANI_AZURE_OPENAI_API_KEY"
    azureDocumentIntelligenceApiKey = Require-Env "CANI_DOCINTEL_API_KEY"
    azureSpeechApiKey               = (Require-Env "CANI_SPEECH_API_KEY" $true) ?? ""
}
$alertEmail = Require-Env "CANI_ALERT_EMAIL"
foreach ($name in "postgresAdminPassword", "tokenSigningSecret", "sessionSecret") {
    if ($secrets[$name].Length -lt 32) { throw "$name must be at least 32 characters (config.py enforces this at startup)." }
}

az account set --subscription $SubscriptionId | Out-Null
Write-Host "Subscription : $(az account show --query name -o tsv) ($SubscriptionId)"
Write-Host "Resource grp : $ResourceGroup ($Location)"
Write-Host "Image tag    : $ImageTag"
Write-Host "Domain phase : $CustomDomainPhase"

if (-not (az group exists --name $ResourceGroup | ConvertFrom-Json)) {
    Write-Host "Creating resource group..."
    az group create --name $ResourceGroup --location $Location --tags project=cani environment=prod owner=jason managedBy=bicep -o none
}

# Secure parameters are passed as name=value arguments; az sends them in the request body.
# They are visible to `ps` on this machine for the duration of the call — acceptable for a
# solo operator's workstation.
function Invoke-Deploy([bool]$deployApps, [string]$label) {
    $paramArgs = @("imageTag=$ImageTag", "customDomainPhase=$CustomDomainPhase", "alertEmail=$alertEmail", "deployApps=$($deployApps.ToString().ToLower())")
    foreach ($kv in $secrets.GetEnumerator()) { $paramArgs += "$($kv.Key)=$($kv.Value)" }
    $name = "cani-$label-$(Get-Date -Format yyyyMMdd-HHmmss)"
    $common = @("--resource-group", $ResourceGroup, "--template-file", $template, "--parameters", "@$parameters", "--parameters") + $paramArgs
    if ($WhatIf) {
        az deployment group what-if --name $name @common
        if ($LASTEXITCODE -ne 0) { throw "what-if failed" }
        return $null
    }
    Write-Host "Deploying $name (deployApps=$deployApps)..."
    $json = az deployment group create --name $name @common -o json
    if ($LASTEXITCODE -ne 0) { throw "Deployment $name failed." }
    return ($json | ConvertFrom-Json).properties.outputs
}

# Phase 1: everything except the apps, so the registry exists before images are built.
$acrName = az acr list --resource-group $ResourceGroup --query "[0].name" -o tsv 2>$null
if (-not $acrName -or $WhatIf) {
    $out1 = Invoke-Deploy $false "phase1"
    if ($WhatIf) { exit 0 }
    $acrName = $out1.acrName.value
}
$acrLoginServer = az acr show --name $acrName --query loginServer -o tsv
Write-Host "Registry     : $acrLoginServer"

# Build in Azure. ACR Basic allows one concurrent build, so these run one after another;
# six images take roughly 10-15 minutes. The .dockerignore keeps the context small.
if (-not $SkipBuild) {
    $images = @(
        @{ name = "cani-hub-api"; file = "apps/hub-api/Dockerfile" },
        @{ name = "cani-docs-api"; file = "apps/docs-api/Dockerfile" },
        @{ name = "cani-retrieval-worker"; file = "apps/retrieval-worker/Dockerfile" },
        @{ name = "cani-ingestion-worker"; file = "apps/ingestion-worker/Dockerfile" },
        @{ name = "cani-web"; file = "apps/web/Dockerfile" },
        @{ name = "cani-migrate"; file = "db/Dockerfile" }
    )
    foreach ($img in $images) {
        Write-Host "Building $($img.name):$ImageTag in ACR..."
        az acr build --registry $acrName --image "$($img.name):$ImageTag" --image "$($img.name):latest" --file $img.file $repoRoot --no-logs -o none
        if ($LASTEXITCODE -ne 0) { throw "ACR build failed for $($img.name)" }
    }
}

# Phase 2: the apps and jobs.
$outputs = Invoke-Deploy $true "phase2"

Write-Host ""
Write-Host "Outputs"
Write-Host "  web FQDN (CNAME target)        : $($outputs.webAppFqdn.value)"
Write-Host "  asuid TXT value                : $($outputs.customDomainVerificationId.value)"
Write-Host "  Postgres host                  : $($outputs.postgresHost.value)"
Write-Host "  Storage account                : $($outputs.storageAccountName.value)"
Write-Host "  Registry                       : $($outputs.acrLoginServer.value)"
Write-Host "  Marketing site default host    : $($outputs.marketingSiteDefaultHostname.value)"

if ($SkipMigrations) { exit 0 }

$job = $outputs.migrateJobName.value
Write-Host ""
Write-Host "Starting migration job $job..."
$execution = az containerapp job start --name $job --resource-group $ResourceGroup --query name -o tsv
$deadline = (Get-Date).AddMinutes(5)
do {
    Start-Sleep -Seconds 10
    $status = az containerapp job execution show --name $job --resource-group $ResourceGroup --job-execution-name $execution --query properties.status -o tsv
    Write-Host "  $execution : $status"
} while ($status -in "Running", "Processing", "Unknown" -and (Get-Date) -lt $deadline)

az containerapp job logs show --name $job --resource-group $ResourceGroup --execution $execution --container migrate --format text 2>$null
if ($status -ne "Succeeded") { throw "Migration job ended with status '$status'." }

Write-Host ""
Write-Host "Done. Smoke check:"
Write-Host "  curl https://$($outputs.webAppFqdn.value)/api/health"
