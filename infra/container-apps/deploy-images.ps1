#Requires -Version 7.0
<#
.SYNOPSIS
    Build, push, and deploy application images to Azure Container Apps without GitHub
    Actions — the local equivalent of .github/workflows/container-apps-cd-dev.yml's
    build-and-push + deploy jobs.
.DESCRIPTION
    Runs the same `docker build/push` and `az containerapp` commands the CD workflow runs,
    just from your own machine with your own `az login` session instead of the workflow's
    federated identity. Useful when GitHub Actions is unavailable (billing, outage) or for
    a faster local iteration loop on a subset of services.

    You need: Docker running locally, `az login` completed, and RBAC equivalent to the
    workflow's identity (AcrPush on the registry, Contributor on the Container Apps
    resource group, and read access to the Key Vault secret the migration job references).
.PARAMETER Services
    Subset of images to build/push/deploy. Defaults to all six. 'migrate' only builds,
    pushes, and runs the migration job — it has no long-running container app to update.
.EXAMPLE
    pwsh infra/container-apps/deploy-images.ps1
    Build, push, and deploy every service tagged with the current commit SHA.
.EXAMPLE
    pwsh infra/container-apps/deploy-images.ps1 -Services docs-api,retrieval-worker
    Redeploy just two services — a fast iteration loop, skips migrate/other apps.
.EXAMPLE
    pwsh infra/container-apps/deploy-images.ps1 -SkipBuild -ImageTag abc1234def
    Re-point Container Apps at an image already in ACR, without rebuilding.
#>

param(
    [ValidateSet("hub-api", "docs-api", "web", "ingestion-worker", "retrieval-worker", "migrate")]
    [string[]]$Services = @("hub-api", "docs-api", "web", "ingestion-worker", "retrieval-worker", "migrate"),
    [string]$ImageTag,
    [string]$ResourceGroup = "cani-container-apps-dev",
    [string]$EnvironmentName = "dev",
    [string]$AcrName = "canishared19088c8d54",
    [string]$AcrLoginServer = "canishared19088c8d54.azurecr.io",
    [string]$KeyVaultName = "cani-platform-kv2e5cf1f6",
    [string]$ManagedIdentityId = "/subscriptions/833d780f-03ed-4f6b-959e-f87d2a1435da/resourcegroups/cani-workload-core-canido-dev-eastus2-rgca86c588/providers/Microsoft.ManagedIdentity/userAssignedIdentities/cani-secrets-id94978007",
    [string]$PostgresHostName = "cani-pg484bf91d.postgres.database.azure.com",
    [switch]$SkipBuild,
    [switch]$SkipMigration,
    [switch]$SkipSmokeCheck
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$containerAppsEnv = "cani-env-$EnvironmentName"
$keyVaultUri = "https://$KeyVaultName.vault.azure.net/"

$dockerfiles = @{
    "hub-api"          = "apps/hub-api/Dockerfile"
    "docs-api"         = "apps/docs-api/Dockerfile"
    "ingestion-worker" = "apps/ingestion-worker/Dockerfile"
    "retrieval-worker" = "apps/retrieval-worker/Dockerfile"
    "web"              = "apps/web/Dockerfile"
    "migrate"          = "db/Dockerfile"
}

Write-Host "🚀 CanI Container Apps — local image deploy (no GitHub Actions required)" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan

Write-Host "`n🔐 Checking Azure CLI authentication..." -ForegroundColor Yellow
$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Host "❌ Not logged in to Azure CLI. Run: az login" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Logged in as: $($account.user.name)" -ForegroundColor Green
Write-Host "   Subscription: $($account.name) ($($account.id))" -ForegroundColor Gray

if (-not $ImageTag) {
    $ImageTag = (git -C $repoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($ImageTag)) {
        Write-Host "❌ Could not resolve a git commit SHA for the image tag — pass -ImageTag explicitly." -ForegroundColor Red
        exit 1
    }
    # The workflow always builds a clean checkout; a dirty local tree means the image you're
    # about to build may not actually match what this SHA says it is. Warn, don't block —
    # this script exists partly for "the pipeline is down and I need to ship a hotfix now".
    $dirty = git -C $repoRoot status --porcelain
    if ($dirty) {
        Write-Host "⚠️  Working tree has uncommitted changes — the image will include them, but the tag ($($ImageTag.Substring(0,7))) implies otherwise." -ForegroundColor Yellow
    }
}
$jobSha = $ImageTag.Substring(0, [Math]::Min(12, $ImageTag.Length))  # matches the workflow's `cut -c1-12` for the migration job name
$revSha = $ImageTag.Substring(0, [Math]::Min(7, $ImageTag.Length))   # matches `cut -c1-7` for the revision suffix
Write-Host "`n🏷️  Image tag: $ImageTag" -ForegroundColor Gray

# ---- Build & push (matrix job equivalent) --------------------------------------------

if (-not $SkipBuild) {
    Write-Host "`n📦 Logging in to ACR: $AcrName" -ForegroundColor Yellow
    az acr login --name $AcrName
    if ($LASTEXITCODE -ne 0) { Write-Host "❌ az acr login failed" -ForegroundColor Red; exit 1 }

    foreach ($service in $Services) {
        $dockerfile = Join-Path $repoRoot $dockerfiles[$service]
        $image = "$AcrLoginServer/${service}:$ImageTag"
        Write-Host "`n🔨 Building $service ($($dockerfiles[$service])) -> $image [linux/amd64]" -ForegroundColor Cyan
        # `docker build` + `docker push` builds for the host's native platform, which is
        # wrong on an ARM64 dev machine (CLAUDE.md's documented gotcha) — Container Apps
        # requires linux/amd64 and silently has no runnable image otherwise (surfaced only
        # at `containerapp job create`/`update` time: "no child with platform linux/amd64
        # in index ..."). `buildx build --platform linux/amd64 --push` cross-builds under
        # QEMU emulation and publishes directly, without a local-load step that would lose
        # the target platform on push. --provenance=false keeps the pushed manifest a plain
        # single-platform image rather than an attestation-bearing index.
        docker buildx build --platform linux/amd64 --provenance=false -f $dockerfile -t $image --push $repoRoot
        if ($LASTEXITCODE -ne 0) { Write-Host "❌ Build/push failed for $service" -ForegroundColor Red; exit 1 }
    }
    Write-Host "`n✅ All images built and pushed (linux/amd64)" -ForegroundColor Green
} else {
    Write-Host "`n⏭️  Skipping build/push (-SkipBuild) — assuming tag $ImageTag already exists in ACR" -ForegroundColor Yellow
}

# ---- Migration job ---------------------------------------------------------------------

if (($Services -contains "migrate") -and -not $SkipMigration) {
    Write-Host "`n🗄️  Running database migrations..." -ForegroundColor Cyan
    $jobName = "cani-migrate-$jobSha"
    $migrateImage = "$AcrLoginServer/migrate:$ImageTag"

    # Check whether the job already exists first, rather than attempting `create` and
    # guessing from its exit code whether failure meant "already exists" (fine, fall back
    # to update) or something real (image/identity/permission error) — swallowing that
    # distinction is exactly what hid the linux/amd64 platform error the first time this
    # script ran.
    az containerapp job show --name $jobName --resource-group $ResourceGroup --output none 2>$null
    $jobExists = ($LASTEXITCODE -eq 0)

    if ($jobExists) {
        az containerapp job update `
            --name $jobName `
            --resource-group $ResourceGroup `
            --image $migrateImage
        if ($LASTEXITCODE -ne 0) { Write-Host "❌ Could not update migration job" -ForegroundColor Red; exit 1 }
    } else {
        az containerapp job create `
            --name $jobName `
            --resource-group $ResourceGroup `
            --environment $containerAppsEnv `
            --trigger-type Manual `
            --replica-timeout 300 `
            --replica-retry-limit 2 `
            --image $migrateImage `
            --registry-server $AcrLoginServer `
            --mi-user-assigned $ManagedIdentityId `
            --registry-identity $ManagedIdentityId `
            --cpu 0.5 --memory 1Gi `
            --secrets "postgres-password=keyvaultref:${keyVaultUri}secrets/POSTGRES-PASSWORD,identityref:$ManagedIdentityId" `
            --env-vars `
                "POSTGRES_HOST=$PostgresHostName" `
                "POSTGRES_PORT=5432" `
                "POSTGRES_DB=cani" `
                "POSTGRES_USER=caniadmin" `
                "POSTGRES_PASSWORD=secretref:postgres-password"
        if ($LASTEXITCODE -ne 0) { Write-Host "❌ Could not create migration job" -ForegroundColor Red; exit 1 }
    }

    $executionName = (az containerapp job start --name $jobName --resource-group $ResourceGroup --query name -o tsv).Trim()
    Write-Host "   Migration execution: $executionName" -ForegroundColor Gray

    $timeoutSeconds = 180
    $elapsed = 0
    $status = ""
    while ($elapsed -lt $timeoutSeconds) {
        $status = (az containerapp job execution show `
                --name $jobName `
                --job-execution-name $executionName `
                --resource-group $ResourceGroup `
                --query properties.status -o tsv).Trim()

        if ($status -eq "Succeeded") {
            Write-Host "✅ Migration completed successfully" -ForegroundColor Green
            break
        }
        if ($status -eq "Failed") {
            Write-Host "❌ Migration failed — logs:" -ForegroundColor Red
            az containerapp job logs show --name $jobName --execution $executionName --container $jobName --resource-group $ResourceGroup --format text
            exit 1
        }
        Write-Host "   Migration status: $status (${elapsed}s elapsed)" -ForegroundColor Gray
        Start-Sleep -Seconds 10
        $elapsed += 10
    }
    if ($elapsed -ge $timeoutSeconds) {
        Write-Host "❌ Migration timed out after ${timeoutSeconds}s" -ForegroundColor Red
        exit 1
    }
} elseif ($Services -contains "migrate") {
    Write-Host "`n⏭️  Skipping migration run (-SkipMigration)" -ForegroundColor Yellow
}

# ---- App updates ------------------------------------------------------------------------

$appServices = $Services | Where-Object { $_ -ne "migrate" }
foreach ($service in $appServices) {
    $image = "$AcrLoginServer/${service}:$ImageTag"
    Write-Host "`n🚢 Deploying $service -> $image" -ForegroundColor Cyan
    az containerapp update `
        --name $service `
        --resource-group $ResourceGroup `
        --image $image `
        --revision-suffix "sha-$revSha"
    if ($LASTEXITCODE -ne 0) { Write-Host "❌ Deploy failed for $service" -ForegroundColor Red; exit 1 }
}

# ---- Smoke checks -------------------------------------------------------------------------
# Same distinction as the workflow: hub-api/docs-api/retrieval-worker have internal ingress
# (curling them from outside the environment 404s at envoy, not the app), so revision
# healthState is the real signal; web has external ingress and gets a real HTTP check.

if (-not $SkipSmokeCheck) {
    $internalApps = @("hub-api", "docs-api", "retrieval-worker") | Where-Object { $appServices -contains $_ }
    foreach ($app in $internalApps) {
        Write-Host "`n🔍 Waiting for $app latest revision to be Healthy..." -ForegroundColor Yellow
        $deadline = (Get-Date).AddSeconds(180)
        while ($true) {
            $state = (az containerapp revision list `
                    --name $app `
                    --resource-group $ResourceGroup `
                    --query "[?properties.active] | [0].properties.healthState" -o tsv).Trim()
            if ($state -eq "Healthy") {
                Write-Host "✅ $app revision Healthy" -ForegroundColor Green
                break
            }
            if ((Get-Date) -ge $deadline) {
                Write-Host "❌ $app revision not Healthy after 180s (state: $state)" -ForegroundColor Red
                exit 1
            }
            Write-Host "   ${app}: $state, waiting..." -ForegroundColor Gray
            Start-Sleep -Seconds 10
        }
    }

    if ($appServices -contains "web") {
        $webFqdn = (az containerapp show --name web --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv).Trim()
        Write-Host "`n🔍 Checking web health (public ingress)..." -ForegroundColor Yellow
        # `-o $null` is a trap here: PowerShell passes $null to a native exe as an empty
        # string, so curl gets `-o ""` rather than a real null device, and the response
        # body ends up mixed into stdout instead of suppressed — which is exactly how the
        # first real deploy misreported a genuinely healthy 200 as a failure. Put the
        # status code on its own trailing line instead of trying to discard the body.
        $curlLines = (curl.exe -s -w "`n%{http_code}" "https://$webFqdn/api/health" 2>&1) -split "`n"
        $httpCode = $curlLines[-1].Trim()
        if ($httpCode -ne "200") {
            Write-Host "❌ web health check failed (HTTP $httpCode)" -ForegroundColor Red
            Write-Host "   Response: $($curlLines[0..($curlLines.Length - 2)] -join "`n")" -ForegroundColor Gray
            exit 1
        }
        Write-Host "✅ web healthy" -ForegroundColor Green
    }
    Write-Host "`n✅ All smoke checks passed" -ForegroundColor Green
} else {
    Write-Host "`n⏭️  Skipping smoke checks (-SkipSmokeCheck)" -ForegroundColor Yellow
}

Write-Host "`n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "✅ Deploy complete — tag $ImageTag" -ForegroundColor Green
