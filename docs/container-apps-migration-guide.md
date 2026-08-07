# Container Apps Migration Guide

## Overview
Migrating CanI from Azure Kubernetes Service (AKS) to Azure Container Apps for cost savings.

**Expected Cost Reduction:** ~50-70% (from ~$103/month to estimated $30-50/month)

**Why Container Apps?**
- Pay-per-second consumption billing (no idle node costs)
- Workers scale to zero when idle
- No cluster management fees
- Built-in HTTPS/load balancing
- Simpler operations (no kubectl/k9s needed)

---

## Prerequisites

1. **Existing Resources** (already deployed via Pulumi):
   - Azure Container Registry (ACR): `canishared19088c8d54`
   - Azure PostgreSQL: `cani-pg484bf91d.postgres.database.azure.com`
   - Azure OpenAI: `https://cani-openai.openai.azure.com/`
   - Key Vault: (need to identify - check Pulumi outputs)
   - Managed Identity: `984dbce5-2209-4df0-b904-41bdcce2596c`

2. **Required Access**:
   - Azure CLI logged in with subscription owner/contributor rights
   - GitHub repository write access (for workflow setup)

3. **Resource Group**:
   - Create new RG or reuse existing: `cani-container-apps-dev`

---

## Phase 1: Identify Current Resources

First, let's gather the exact resource names from the existing deployment:

```bash
# Login to Azure
az login

# Set subscription
az account set --subscription 833d780f-03ed-4f6b-959e-f87d2a1435da

# Find AKS resource group
az aks list --query "[].{name:name, resourceGroup:resourceGroup}" -o table

# Get Pulumi outputs (if available)
cd infra/workload
pulumi stack output --json

# Find Key Vault name
az keyvault list --query "[].{name:name, resourceGroup:resourceGroup}" -o table

# Verify managed identity
az identity show --ids "/subscriptions/833d780f-03ed-4f6b-959e-f87d2a1435da/resourceGroups/RESOURCE_GROUP/providers/Microsoft.ManagedIdentity/userAssignedIdentities/cani-workload-identity"
```

**ACTION REQUIRED:** Update `infra/container-apps/main.parameters.json` with actual values:
- `keyVaultName`
- `managedIdentityId` (full resource ID)
- Resource group name in `managedIdentityId` path

---

## Phase 2: Deploy Container Apps Infrastructure

```bash
# Navigate to infra directory
cd infra/container-apps

# Create resource group (if new)
az group create --name cani-container-apps-dev --location eastus

# Validate Bicep template
az deployment group validate \
  --resource-group cani-container-apps-dev \
  --template-file main.bicep \
  --parameters main.parameters.json

# Deploy infrastructure (dry-run with what-if)
az deployment group what-if \
  --resource-group cani-container-apps-dev \
  --template-file main.bicep \
  --parameters main.parameters.json

# Deploy for real
az deployment group create \
  --resource-group cani-container-apps-dev \
  --template-file main.bicep \
  --parameters main.parameters.json \
  --name container-apps-initial-$(date +%Y%m%d-%H%M%S)
```

**Expected Resources Created:**
- Container Apps Environment: `cani-env-dev`
- Log Analytics Workspace: `cani-logs-dev`
- Storage Account: `caniqd<unique>` (for Qdrant persistence)
- File Share: `qdrant-data`
- 6 Container Apps: hub-api, docs-api, web, ingestion-worker, retrieval-worker, qdrant

---

## Phase 3: Grant Managed Identity Permissions

The managed identity needs:
1. **ACR Pull** (to pull images)
2. **Key Vault Secrets Get** (to read database password)

```bash
# Get ACR resource ID
ACR_ID=$(az acr show --name canishared19088c8d54 --query id -o tsv)

# Grant AcrPull role to managed identity
az role assignment create \
  --assignee 984dbce5-2209-4df0-b904-41bdcce2596c \
  --role AcrPull \
  --scope $ACR_ID

# Grant Key Vault access (replace KEY_VAULT_NAME)
KEY_VAULT_NAME="cani-kv"  # UPDATE THIS
az keyvault set-policy \
  --name $KEY_VAULT_NAME \
  --object-id 984dbce5-2209-4df0-b904-41bdcce2596c \
  --secret-permissions get list
```

---

## Phase 4: Initial Container Deployment

The Bicep template deploys with `:latest` tags. We need to push initial images:

```bash
# Build and push images (from repo root)
export ACR_LOGIN_SERVER="canishared19088c8d54.azurecr.io"
export IMAGE_TAG="initial-$(git rev-parse --short HEAD)"

az acr login --name canishared19088c8d54

# Build all services
docker build -f apps/hub-api/Dockerfile -t $ACR_LOGIN_SERVER/hub-api:$IMAGE_TAG .
docker build -f apps/docs-api/Dockerfile -t $ACR_LOGIN_SERVER/docs-api:$IMAGE_TAG .
docker build -f apps/web/Dockerfile -t $ACR_LOGIN_SERVER/web:$IMAGE_TAG .
docker build -f apps/ingestion-worker/Dockerfile -t $ACR_LOGIN_SERVER/ingestion-worker:$IMAGE_TAG .
docker build -f apps/retrieval-worker/Dockerfile -t $ACR_LOGIN_SERVER/retrieval-worker:$IMAGE_TAG .
docker build -f db/Dockerfile -t $ACR_LOGIN_SERVER/migrate:$IMAGE_TAG .

# Push all
docker push $ACR_LOGIN_SERVER/hub-api:$IMAGE_TAG
docker push $ACR_LOGIN_SERVER/docs-api:$IMAGE_TAG
docker push $ACR_LOGIN_SERVER/web:$IMAGE_TAG
docker push $ACR_LOGIN_SERVER/ingestion-worker:$IMAGE_TAG
docker push $ACR_LOGIN_SERVER/retrieval-worker:$IMAGE_TAG
docker push $ACR_LOGIN_SERVER/migrate:$IMAGE_TAG

# Update Container Apps to use these images
az containerapp update --name hub-api --resource-group cani-container-apps-dev \
  --image $ACR_LOGIN_SERVER/hub-api:$IMAGE_TAG
az containerapp update --name docs-api --resource-group cani-container-apps-dev \
  --image $ACR_LOGIN_SERVER/docs-api:$IMAGE_TAG
az containerapp update --name web --resource-group cani-container-apps-dev \
  --image $ACR_LOGIN_SERVER/web:$IMAGE_TAG
az containerapp update --name ingestion-worker --resource-group cani-container-apps-dev \
  --image $ACR_LOGIN_SERVER/ingestion-worker:$IMAGE_TAG
az containerapp update --name retrieval-worker --resource-group cani-container-apps-dev \
  --image $ACR_LOGIN_SERVER/retrieval-worker:$IMAGE_TAG
```

---

## Phase 5: Configure GitHub Actions

### 5.1 Create GitHub Environment Variables

In GitHub repo settings → Environments → `dev`, add these variables:

```
CONTAINER_APPS_RESOURCE_GROUP = cani-container-apps-dev
ACR_NAME = canishared19088c8d54
ACR_LOGIN_SERVER = canishared19088c8d54.azurecr.io
POSTGRES_HOST = cani-pg484bf91d.postgres.database.azure.com
KEY_VAULT_URI = https://<KEY_VAULT_NAME>.vault.azure.net/
MANAGED_IDENTITY_ID = /subscriptions/833d780f-03ed-4f6b-959e-f87d2a1435da/resourceGroups/<RG>/providers/Microsoft.ManagedIdentity/userAssignedIdentities/cani-workload-identity
```

### 5.2 Verify Secrets

Ensure these secrets exist in GitHub (likely already configured for AKS):
- `AZURE_CLIENT_ID_WORKLOAD`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`

### 5.3 Test Workflow

```bash
# Trigger workflow manually
gh workflow run container-apps-cd-dev.yml

# Or push a change to trigger
git add .
git commit -m "test: trigger container apps deployment"
git push
```

---

## Phase 6: DNS Cutover

Once Container Apps are validated:

```bash
# Get Container Apps web FQDN
WEB_FQDN=$(az containerapp show --name web --resource-group cani-container-apps-dev \
  --query properties.configuration.ingress.fqdn -o tsv)

echo "Container Apps web FQDN: $WEB_FQDN"
```

**DNS Update:**
1. Add custom domain to Container Apps:
   ```bash
   # Add app.canido.co to web container app
   az containerapp hostname add \
     --name web \
     --resource-group cani-container-apps-dev \
     --hostname app.canido.co
   
   # Bind certificate (managed certificate)
   az containerapp hostname bind \
     --name web \
     --resource-group cani-container-apps-dev \
     --hostname app.canido.co \
     --environment cani-env-dev \
     --validation-method HTTP
   ```

2. Update DNS A record for `app.canido.co`:
   - Point to Container Apps environment's static IP
   - Or use CNAME to `$WEB_FQDN`

3. Wait for propagation (1-5 minutes)

4. Test: `curl https://app.canido.co/api/health`

---

## Phase 7: Validation & Smoke Testing

```bash
# Check all apps are running
az containerapp list --resource-group cani-container-apps-dev \
  --query "[].{name:name, status:properties.runningStatus, replicas:properties.template.scale.maxReplicas}" -o table

# Manual health checks
curl https://<HUB_FQDN>/healthz
curl https://<DOCS_FQDN>/healthz
curl https://<RETRIEVAL_FQDN>/healthz
curl https://app.canido.co/api/health

# Check logs
az containerapp logs show --name hub-api --resource-group cani-container-apps-dev --tail 50

# Test document upload flow
# (Manual testing via web UI at app.canido.co)
```

---

## Phase 8: Decommission AKS (After 1 Week Validation)

**WAIT 7 DAYS** after Container Apps cutover before decommissioning AKS.

```bash
# List AKS clusters
az aks list --query "[].{name:name, resourceGroup:resourceGroup}" -o table

# Delete AKS cluster (THIS SAVES THE MONEY!)
az aks delete \
  --name <AKS_CLUSTER_NAME> \
  --resource-group <AKS_RESOURCE_GROUP> \
  --yes --no-wait

# Optionally delete AKS resource group (if dedicated)
# WARNING: Only if no other resources!
az group delete --name <AKS_RESOURCE_GROUP> --yes --no-wait
```

**Expected Monthly Savings:**
- AKS cluster management: ~$73/month
- Node pools (2-3 VMs): ~$30/month
- **Total savings: ~$103 → $30-50** (50-70% reduction)

---

## Monitoring & Operations

### View Logs
```bash
# Live tail
az containerapp logs show --name hub-api --resource-group cani-container-apps-dev --follow

# Recent logs
az containerapp logs show --name docs-api --resource-group cani-container-apps-dev --tail 100
```

### Check Scaling
```bash
# View current replicas
az containerapp revision list --name ingestion-worker --resource-group cani-container-apps-dev \
  --query "[0].properties.replicas" -o tsv

# View scaling rules
az containerapp show --name ingestion-worker --resource-group cani-container-apps-dev \
  --query properties.template.scale -o json
```

### Cost Analysis
```bash
# Get current month costs
az consumption usage list \
  --start-date $(date -u +%Y-%m-01) \
  --end-date $(date -u +%Y-%m-%d) \
  --query "[?contains(instanceId, 'cani-container-apps-dev')].{name:instanceName, cost:pretaxCost}" \
  -o table
```

---

## Rollback Plan

If issues arise, rollback to AKS:

1. **DO NOT DELETE AKS** during initial cutover
2. Revert DNS to AKS ingress IP
3. Keep both environments running in parallel for 1 week
4. Only decommission AKS after Container Apps proven stable

---

## Troubleshooting

### Container not starting
```bash
az containerapp revision list --name <APP_NAME> --resource-group cani-container-apps-dev -o table
az containerapp logs show --name <APP_NAME> --resource-group cani-container-apps-dev --tail 200
```

### Secrets not loading
```bash
# Check Key Vault permissions
az keyvault show --name <KEY_VAULT_NAME> --query properties.accessPolicies
```

### Image pull failures
```bash
# Verify ACR role assignment
az role assignment list --assignee 984dbce5-2209-4df0-b904-41bdcce2596c --all
```

### Qdrant data persistence
```bash
# Check storage mount
az containerapp show --name qdrant --resource-group cani-container-apps-dev \
  --query properties.template.volumes -o json

# Verify file share
az storage share show --name qdrant-data --account-name <STORAGE_ACCOUNT> -o table
```

---

## Next Steps

1. ✅ Deploy Container Apps infrastructure (Phase 2)
2. ✅ Push initial images (Phase 4)
3. ✅ Configure GitHub Actions (Phase 5)
4. ⏳ Run parallel for 7 days (validation period)
5. ⏳ DNS cutover (Phase 6)
6. ⏳ Decommission AKS (Phase 8)
7. 📊 Monitor costs for 1 month to confirm savings

---

## Questions?

Check logs, review Container Apps docs, or open GitHub issue for migration-specific questions.
