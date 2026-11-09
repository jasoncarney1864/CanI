#Requires -Version 7.0
<#
.SYNOPSIS
    Create the model deployments CanI needs on the existing Foundry (AIServices) resource.
.DESCRIPTION
    The low-cost rebuild (docs/22-low-cost-rebuild.md) reuses the Foundry resource that
    already exists in the CanI subscription instead of creating Azure OpenAI, Document
    Intelligence and Speech resources of its own: one AIServices account exposes all three
    APIs, billed per use, nothing while idle. This script is idempotent — re-running it
    with the same names is a no-op.

    Deployment names must match the Bicep parameters azureOpenAIEmbeddingDeployment and
    azureOpenAIChatDeployment (main.parameters.json). If a model version below is not
    offered in the region any more, the script prints the versions that are.
.EXAMPLE
    pwsh infra/container-apps/deploy-models.ps1
#>
param(
    [string]$SubscriptionId = $env:CANI_SUBSCRIPTION_ID,
    [string]$ResourceGroup = "rg-foundry-dev-eus-001",
    [string]$AccountName = "aif-jcarney-dev-eus-001",
    [string]$EmbeddingDeployment = "text-embedding-3-small",
    [string]$EmbeddingModelVersion = "1",
    [string]$ChatDeployment = "gpt-5-mini",
    [string]$ChatModel = "gpt-5-mini",
    [string]$ChatModelVersion = "",
    # Capacity is in thousands of tokens per minute. Both are deliberately small; raise
    # them when a real user hits 429s, not before.
    [int]$EmbeddingCapacity = 50,
    [int]$ChatCapacity = 10
)

$ErrorActionPreference = "Stop"
if (-not $SubscriptionId) { throw "Set CANI_SUBSCRIPTION_ID or pass -SubscriptionId." }
az account set --subscription $SubscriptionId | Out-Null

function Ensure-Deployment([string]$name, [string]$model, [string]$version, [int]$capacity) {
    $existing = az cognitiveservices account deployment show --name $AccountName --resource-group $ResourceGroup --deployment-name $name -o json 2>$null
    if ($LASTEXITCODE -eq 0 -and $existing) {
        $d = $existing | ConvertFrom-Json
        Write-Host "exists  $name -> $($d.properties.model.name) $($d.properties.model.version) ($($d.sku.name) x$($d.sku.capacity))"
        return
    }
    $args = @(
        "--name", $AccountName, "--resource-group", $ResourceGroup,
        "--deployment-name", $name, "--model-name", $model, "--model-format", "OpenAI",
        "--sku-name", "GlobalStandard", "--sku-capacity", $capacity
    )
    if ($version) { $args += @("--model-version", $version) }
    Write-Host "creating $name ($model $version, GlobalStandard x$capacity)..."
    az cognitiveservices account deployment create @args -o none
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Create failed. Versions of '$model' offered to this account:"
        az cognitiveservices account list-models --name $AccountName --resource-group $ResourceGroup `
            --query "[?name=='$model'].{name:name,version:version,skus:join(',', skus[].name)}" -o table
        throw "Could not create deployment $name"
    }
    Write-Host "created $name"
}

Ensure-Deployment $EmbeddingDeployment "text-embedding-3-small" $EmbeddingModelVersion $EmbeddingCapacity
Ensure-Deployment $ChatDeployment $ChatModel $ChatModelVersion $ChatCapacity

Write-Host ""
Write-Host "Endpoints for main.parameters.json:"
Write-Host "  azureOpenAIEndpoint               : https://$AccountName.openai.azure.com/"
Write-Host "  azureDocumentIntelligenceEndpoint : https://$AccountName.cognitiveservices.azure.com/"
Write-Host "Key (use for both CANI_AZURE_OPENAI_API_KEY and CANI_DOCINTEL_API_KEY):"
Write-Host "  az cognitiveservices account keys list --name $AccountName --resource-group $ResourceGroup --query key1 -o tsv"
