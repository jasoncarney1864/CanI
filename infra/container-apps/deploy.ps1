#Requires -Version 7.0
<#
.SYNOPSIS
    Deploy CanI to Azure Container Apps from your own machine — the local equivalent of
    .github/workflows/deploy.yml's deploy job (docs/22-low-cost-rebuild.md).
.DESCRIPTION
    Creates the resource group if needed, deploys infra/container-apps/main.bicep with the
    checked-in parameters file plus the secrets below, then starts the migration job and
    waits for it. Images must already be in GHCR (the build job in deploy.yml, or
    `docker build` + `docker push ghcr.io/<owner>/cani-<service>:<tag>`).

    Secrets are read from environment variables so they never land in shell history or
    this file. Set them in the session first, e.g. in PowerShell:
        $env:CANI_GHCR_TOKEN = "<PAT with read:packages>"
        $env:CANI_PG_PASSWORD = "<48 random chars>"
        $env:CANI_TOKEN_SIGNING_SECRET = "<48 random chars>"
        $env:CANI_SESSION_SECRET = "<48 random chars>"
        $env:CANI_ENTRA_CLIENT_SECRET = "<from the Entra app registration>"
        $env:CANI_AZURE_OPENAI_API_KEY = "<Foundry resource key>"
        $env:CANI_DOCINTEL_API_KEY = "<same Foundry resource key>"
        $env:CANI_SPEECH_API_KEY = ""   # optional
        $env:CANI_ALERT_EMAIL = "<mailbox that is actually read>"
        $env:CANI_SUBSCRIPTION_ID = "<the CanI subscription id>"
    Generate the three random secrets with:
        python -c "import secrets; print(secrets.token_urlsafe(48))"
.PARAMETER ImageTag
    The image tag to deploy (git SHA by default).
.PARAMETER CustomDomainPhase
    0 on first deploy; 1 after the GoDaddy records are in; 2 once Azure has validated them.
    See main.bicep's parameter description.
.PARAMETER WhatIf
    Run `az deployment group what-if` instead of deploying.
.EXAMPLE
    pwsh infra/container-apps/deploy.ps1 -WhatIf
.EXAMPLE
    pwsh infra/container-apps/deploy.ps1 -ImageTag abc1234 -CustomDomainPhase 2
#>
param(
    [string]$SubscriptionId = $env:CANI_SUBSCRIPTION_ID,
    [string]$ResourceGroup = "rg-cani-prod-eus",
    [string]$Location = "eastus",
    [string]$ImageTag = (git rev-parse --short=7 HEAD),
    [ValidateSet(0, 1, 2)]
    [int]$CustomDomainPhase = 0,
    [switch]$WhatIf,
    [switch]$SkipMigrations
)

$ErrorActionPreference = "Stop"
if (-not $SubscriptionId) { throw "Set CANI_SUBSCRIPTION_ID or pass -SubscriptionId." }
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$template = Join-Path $PSScriptRoot "main.bicep"
$parameters = Join-Path $PSScriptRoot "main.parameters.json"

function Require-Env([string]$name, [bool]$optional = $false) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if (-not $value -and -not $optional) {
        throw "Environment variable $name is not set. See the header of this script."
    }
    return $value
}

$secrets = @{
    ghcrToken                       = Require-Env "CANI_GHCR_TOKEN"
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
    az group create --name $ResourceGroup --location $Location --tags project=cani environment=prod owner=jason managedBy=bicep | Out-Null
}

# Secure parameters go in as `name=value` arguments, which az sends in the request body
# (not the command line of a child process). They are still visible to `ps` on this
# machine for the duration of the call; acceptable for a solo operator's workstation.
$paramArgs = @("imageTag=$ImageTag", "customDomainPhase=$CustomDomainPhase", "alertEmail=$alertEmail")
foreach ($kv in $secrets.GetEnumerator()) { $paramArgs += "$($kv.Key)=$($kv.Value)" }

$deploymentName = "cani-$(Get-Date -Format yyyyMMdd-HHmmss)"
$common = @("--resource-group", $ResourceGroup, "--template-file", $template, "--parameters", "@$parameters", "--parameters") + $paramArgs

if ($WhatIf) {
    az deployment group what-if --name $deploymentName @common
    exit $LASTEXITCODE
}

Write-Host "Deploying $deploymentName (10-15 minutes on first run; Postgres is the slow part)..."
$result = az deployment group create --name $deploymentName @common -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Deployment failed." }
$outputs = $result.properties.outputs

Write-Host ""
Write-Host "Outputs"
Write-Host "  web FQDN (CNAME target)        : $($outputs.webAppFqdn.value)"
Write-Host "  asuid TXT value                : $($outputs.customDomainVerificationId.value)"
Write-Host "  Postgres host                  : $($outputs.postgresHost.value)"
Write-Host "  Storage account                : $($outputs.storageAccountName.value)"
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
