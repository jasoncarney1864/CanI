# Container Apps Migration - Status Update

**Date:** August 5, 2026, 1:20 PM PT  
**Deployment:** container-apps-20260805-130557  
**Status:** 🔄 IN PROGRESS (13+ minutes elapsed)

## What's Been Completed

### ✅ Infrastructure Created
1. **Resource Group:** `cani-container-apps-dev`
2. **Log Analytics Workspace:** `cani-logs-dev`
3. **Storage Account:** `caniqdrthpizrvpqt7u`
4. **File Share:** `qdrant-data` (20 GiB)
5. **Container Apps Environment:** `cani-env-dev`

### 🔄 Currently Provisioning
- **Qdrant Container App:** Created but still in "InProgress" state
- **5 Other Apps:** Waiting (they reference Qdrant's FQDN, so must wait for Qdrant to complete)

## Expected Timeline
- **Total deployment time:** 15-20 minutes (typical for Container Apps with dependencies)
- **Current progress:** ~13 minutes  
- **Estimated completion:** 2-7 minutes remaining

## Next Steps (After Deployment Completes)

### 1. Build and Push Initial Images
```bash
# From repo root
export ACR_LOGIN_SERVER="canishared19088c8d54.azurecr.io"
export IMAGE_TAG="initial-$(git rev-parse --short HEAD)"

az acr login --name canishared19088c8d54

# Build all 6 images
docker build -f apps/hub-api/Dockerfile -t $ACR_LOGIN_SERVER/hub-api:$IMAGE_TAG .
docker build -f apps/docs-api/Dockerfile -t $ACR_LOGIN_SERVER/docs-api:$IMAGE_TAG .
docker build -f apps/web/Dockerfile -t $ACR_LOGIN_SERVER/web:$IMAGE_TAG .
docker build -f apps/ingestion-worker/Dockerfile -t $ACR_LOGIN_SERVER/ingestion-worker:$IMAGE_TAG .
docker build -f apps/retrieval-worker/Dockerfile -t $ACR_LOGIN_SERVER/retrieval-worker:$IMAGE_TAG .
docker build -f db/Dockerfile -t $ACR_LOGIN_SERVER/migrate:$IMAGE_TAG .

# Push all
for service in hub-api docs-api web ingestion-worker retrieval-worker migrate; do
  docker push $ACR_LOGIN_SERVER/$service:$IMAGE_TAG
done

# Update Container Apps to use the real images (replace :latest placeholders)
az containerapp update --name hub-api --resource-group cani-container-apps-dev --image $ACR_LOGIN_SERVER/hub-api:$IMAGE_TAG
az containerapp update --name docs-api --resource-group cani-container-apps-dev --image $ACR_LOGIN_SERVER/docs-api:$IMAGE_TAG
az containerapp update --name web --resource-group cani-container-apps-dev --image $ACR_LOGIN_SERVER/web:$IMAGE_TAG
az containerapp update --name ingestion-worker --resource-group cani-container-apps-dev --image $ACR_LOGIN_SERVER/ingestion-worker:$IMAGE_TAG
az containerapp update --name retrieval-worker --resource-group cani-container-apps-dev --image $ACR_LOGIN_SERVER/retrieval-worker:$IMAGE_TAG
```

### 2. Configure GitHub Actions
Add these **variables** to GitHub repo → Settings → Environments → `dev`:
- `CONTAINER_APPS_RESOURCE_GROUP` = `cani-container-apps-dev`
- `POSTGRES_HOST` = `cani-pg484bf91d.postgres.database.azure.com`
- `KEY_VAULT_URI` = `https://cani-platform-kv2e5cf1f6.vault.azure.net/`
- `MANAGED_IDENTITY_ID` = `/subscriptions/833d780f-03ed-4f6b-959e-f87d2a1435da/resourcegroups/cani-workload-core-canido-dev-eastus2-rgca86c588/providers/Microsoft.ManagedIdentity/userAssignedIdentities/cani-secrets-id94978007`

(ACR variables already exist from AKS workflow)

### 3. Test the New Workflow
```bash
gh workflow run container-apps-cd-dev.yml
```

### 4. DNS Cutover
Once Container Apps are validated (smoke tests passing), update DNS:
```bash
# Get Container Apps web FQDN
WEB_FQDN=$(az containerapp show --name web --resource-group cani-container-apps-dev --query properties.configuration.ingress.fqdn -o tsv)

# Add custom domain
az containerapp hostname add --name web --resource-group cani-container-apps-dev --hostname app.canido.co

# Update DNS CNAME record: app.canido.co → $WEB_FQDN
```

### 5. Parallel Run & Validation
- Run Container Apps and AKS in parallel for 7 days
- Monitor logs, performance, costs
- Validate full functionality

### 6. Decommission AKS (After 7 Days)
```bash
# Delete AKS cluster (THIS IS WHERE YOU SAVE MONEY!)
az aks delete --name cani-aks33874b17 --resource-group cani-workload-core-canido-dev-eastus2-rgca86c588 --yes
```

## Cost Impact

### Current Monthly Costs (AKS)
- **Node Pools:**
  - 1x Standard_D2s_v4 (system): ~$70/month
  - 2x Standard_D2s_v4 (apps): ~$140/month  
  - 1x Standard_D4s_v4 (data): ~$140/month
- **AKS Management:** ~$73/month
- **TOTAL:** ~$423/month (but showing as ~$103 in portal - possibly due to credits or partial month)

### Target Monthly Costs (Container Apps)
- **Consumption billing:** Pay per second of CPU/memory use
- **Estimated:** ~$30-50/month for this workload
- **Workers scale to zero:** No cost when idle

### Expected Savings
- **70-85% reduction** (~$350-370/month savings)
- **Break-even:** Immediate (no upfront costs)

## Monitoring Commands

```bash
# Check Container Apps status
az containerapp list --resource-group cani-container-apps-dev -o table

# View logs (live tail)
az containerapp logs show --name hub-api --resource-group cani-container-apps-dev --follow

# Check scaling
az containerapp replica list --name ingestion-worker --resource-group cani-container-apps-dev -o table
```

## Rollback Plan

If issues arise:
1. **DO NOT DELETE AKS** until Container Apps proven stable
2. Revert DNS to AKS ingress
3. Keep both environments running in parallel
4. Only decommission AKS after 7-day validation period

## References
- **Migration Guide:** [docs/container-apps-migration-guide.md](../container-apps-migration-guide.md)
- **Bicep Template:** [infra/container-apps/main.bicep](../../infra/container-apps/main.bicep)
- **GitHub Workflow:** [.github/workflows/container-apps-cd-dev.yml](../../.github/workflows/container-apps-cd-dev.yml)

---

**Next Check:** Deployment should complete in 2-7 minutes. Run `az deployment group show --resource-group cani-container-apps-dev --name container-apps-20260805-130557 --query properties.provisioningState -o tsv` to check status.
