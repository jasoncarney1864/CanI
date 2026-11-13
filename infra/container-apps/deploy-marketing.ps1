#Requires -Version 7.0
<#
.SYNOPSIS
    Build apps/marketing and deploy it to the Static Web App the main template creates —
    the local equivalent of .github/workflows/marketing-static-web-app.yml.
.DESCRIPTION
    The marketing site is a Vite build uploaded with the Static Web Apps CLI. The deployment
    token is read from the resource at run time and held only in this process's environment;
    it is never written to disk or printed.

    First-time custom domain (www.canido.co) — after the GoDaddy CNAME for `www` points at
    the site's default hostname (printed at the end of this script):
        az staticwebapp hostname set -n cani-prod-marketing -g rg-cani-prod-eus --hostname www.canido.co
    The apex (canido.co) stays a GoDaddy forward to https://www.canido.co.
.EXAMPLE
    pwsh infra/container-apps/deploy-marketing.ps1
#>
param(
    [string]$SubscriptionId = $env:CANI_SUBSCRIPTION_ID,
    [string]$ResourceGroup = "rg-cani-prod-eus",
    [string]$SiteName = "cani-prod-marketing",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$site = Join-Path $repoRoot "apps\marketing"

if ($SubscriptionId) { az account set --subscription $SubscriptionId | Out-Null }
Write-Host "Subscription : $(az account show --query name -o tsv)"
Write-Host "Site         : $SiteName ($ResourceGroup)"

if (-not $SkipBuild) {
    Push-Location $site
    try {
        if (-not (Test-Path "node_modules")) { npm ci; if ($LASTEXITCODE -ne 0) { throw "npm ci failed" } }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "marketing build failed" }
    } finally { Pop-Location }
}

$token = az staticwebapp secrets list --name $SiteName --resource-group $ResourceGroup --query properties.apiKey -o tsv
if (-not $token) { throw "Could not read the deployment token for $SiteName." }
$env:SWA_CLI_DEPLOYMENT_TOKEN = $token
try {
    Push-Location $site
    npx --yes @azure/static-web-apps-cli deploy ./dist --env production
    if ($LASTEXITCODE -ne 0) { throw "swa deploy failed" }
} finally {
    Pop-Location
    Remove-Item Env:SWA_CLI_DEPLOYMENT_TOKEN -ErrorAction SilentlyContinue
}

$host_ = az staticwebapp show --name $SiteName --resource-group $ResourceGroup --query defaultHostname -o tsv
$domains = az staticwebapp show --name $SiteName --resource-group $ResourceGroup --query "customDomains | join(', ', @)" -o tsv
Write-Host ""
Write-Host "Default hostname (CNAME target for www) : $host_"
Write-Host "Custom domains bound                     : $(if ($domains) { $domains } else { 'none yet' })"
