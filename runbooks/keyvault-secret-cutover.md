# Runbook: Key Vault CSI secret cutover (D1)

How the CanI dev cluster moves from the manual `cani-secrets` Secret
(`scripts/apply_dev_secrets.sh`) to secrets sourced from Azure Key Vault via the Secrets
Store CSI driver + workload identity. Covers the elevated out-of-band steps (the CI service
principal is Contributor-only and can't do them) and the live cutover.

## What's already in place (IaC / applied)

- **Private endpoint + DNS** to the platform Key Vault (`cani-platform-kv6370c4cb`), and a
  **user-assigned identity** `cani-secrets-id9e0938f8` (client `4a790202-610f-499c-bb0b-2c64b2d42898`)
  with a federated credential per app service account — created by `infra/workload`
  (PR #52). The Key Vault is `public_network_access=Disabled`, so all data-plane access is
  via the private endpoint from inside the cluster.
- **k8s manifests** (`k8s/base/config.yaml`, `secret-provider-class.yaml`, the four wired
  deployments + service accounts) — committed, NOT yet applied.

## Step 1 — Elevated role grants (one-time, Owner)

The CI SP can't create these; an Owner does it via `az`:

```bash
KVID="/subscriptions/6591cee6-ee26-4155-ae71-3777bf7e9c73/resourceGroups/cani-platform-core-dev-eastus2-rg1227b5a0/providers/Microsoft.KeyVault/vaults/cani-platform-kv6370c4cb"
# UAMI can READ secrets (CSI driver):
az role assignment create --role "Key Vault Secrets User" \
  --assignee-object-id 9d752c78-7b4b-4940-8936-0b8406d49a50 \
  --assignee-principal-type ServicePrincipal --scope "$KVID"
# Operator can WRITE secret values (to populate/rotate):
az role assignment create --role "Key Vault Secrets Officer" \
  --assignee-object-id <your-user-object-id> --assignee-principal-type User --scope "$KVID"
```

(Both were applied 2026-07-20.)

## Step 2 — Populate Key Vault (ARM management plane, exposure-safe)

The vault's data plane is private, but the **ARM management plane** can write secrets and is
reachable from anywhere. Set each value with `az rest` PUT — **never echo secret values**;
source them from the operator's off-repo `~/.cani/dev-secrets.env`.

The eight KV secrets (kebab name → env key consumed by the app):

| KV secret name | env key | value source |
| --- | --- | --- |
| `cani-token-signing-secret` | `CANI_TOKEN_SIGNING_SECRET` | rotate: `openssl rand -base64 48` |
| `cani-session-secret` | `CANI_SESSION_SECRET` | rotate: `openssl rand -base64 48` |
| `postgres-password` | `POSTGRES_PASSWORD` | rotate with the server (Step 4) |
| `azure-storage-connection-string` | `AZURE_STORAGE_CONNECTION_STRING` | rotate storage key (Step 4) |
| `azure-documentintelligence-api-key` | `AZURE_DOCUMENTINTELLIGENCE_API_KEY` | current value (or rotate the DI key) |
| `applicationinsights-connection-string` | `APPLICATIONINSIGHTS_CONNECTION_STRING` | current value |
| `entra-oidc-client-secret` | `ENTRA_OIDC_CLIENT_SECRET` | rotate: `az ad app credential reset` (Step 4) |
| `keda-postgres-connection` | (`connection` in `cani-keda-postgres`) | rebuild after pg rotation |

Helper (reads a value into a shell var without printing, PUTs via ARM):

```bash
KV_MGMT="https://management.azure.com/subscriptions/6591cee6-ee26-4155-ae71-3777bf7e9c73/resourceGroups/cani-platform-core-dev-eastus2-rg1227b5a0/providers/Microsoft.KeyVault/vaults/cani-platform-kv6370c4cb/secrets"
kvset() {  # kvset <kv-secret-name> <env-var-holding-value>
  local name="$1" val="${!2}"
  az rest --method put --url "$KV_MGMT/${name}?api-version=2023-07-01" \
    --body "$(jq -nc --arg v "$val" '{properties:{value:$v}}')" >/dev/null \
    && echo "set $name"
}
set -a; source ~/.cani/dev-secrets.env; set +a
CANI_TOKEN_SIGNING_SECRET="$(openssl rand -base64 48)"   # rotate
CANI_SESSION_SECRET="$(openssl rand -base64 48)"         # rotate
kvset cani-token-signing-secret CANI_TOKEN_SIGNING_SECRET
kvset cani-session-secret CANI_SESSION_SECRET
kvset postgres-password POSTGRES_PASSWORD
kvset azure-storage-connection-string AZURE_STORAGE_CONNECTION_STRING
kvset azure-documentintelligence-api-key AZURE_DOCUMENTINTELLIGENCE_API_KEY
kvset applicationinsights-connection-string APPLICATIONINSIGHTS_CONNECTION_STRING
kvset entra-oidc-client-secret ENTRA_OIDC_CLIENT_SECRET
kvset keda-postgres-connection KEDA_POSTGRES_CONNECTION
```

Also delete the leftover `d1-connectivity-test` secret (from validation) once in-cluster
data-plane access exists.

## Step 3 — Cut over to CSI (source change only; lowest risk first)

Recommended: populate KV with the **current** values (except the trivially-rotated signing/
session), cut over, verify, THEN rotate the backing services (Step 4). This separates "where
secrets come from" from "changing them", so each is independently verifiable/reversible.

```bash
RG=cani-workload-core-dev-eastus2-rg9c8e66d0; CL=cani-aks64bdb7d1
# The CSI driver must own cani-secrets; delete the manually-applied one first so the driver
# recreates it on pod mount (it won't overwrite a Secret it doesn't own).
az aks command invoke -g $RG -n $CL --command "kubectl delete secret cani-secrets -n docs-platform --ignore-not-found; kubectl delete secret cani-secrets -n hub-system --ignore-not-found"
```

Then deploy the manifests — either trigger `app-cd-dev` (`workflow_dispatch`), or apply the
rendered overlay directly (matches how the ingress annotation was applied). Restart is
implicit (the deployment spec changes force new pods). Watch each rollout.

## Verify

- `kubectl describe pod` on each of docs-api / hub-api / retrieval-worker / ingestion-worker:
  the `secrets-store` CSI volume is mounted and the `azure.workload.identity/use` label is set.
- `kubectl get secret cani-secrets -n docs-platform` and `-n hub-system` exist and are
  **owned by the SecretProviderClass** (driver-created), with the expected keys.
- `kubectl get secret cani-keda-postgres -n docs-platform` exists (KEDA).
- Pods `Running`/`Ready`; the CD smoke check (hub dev-login + whoami) passes.
- End-to-end at `https://app.canido.co`: Entra sign-in → upload → query → cited answer.

## Step 4 — Rotate the backing services (after the app is on CSI)

Do one at a time; update the backing service AND the KV secret, then restart the affected
deployments so pods re-read via the CSI sync.

- **Postgres admin password**: `pulumi config set --secret postgresAdminPassword <new>` in
  `infra/workload` → merge/apply (updates the Flexible Server) → `kvset postgres-password …`
  → rebuild + `kvset keda-postgres-connection …` → restart docs-platform + hub-system pods.
- **Storage account key**: `az storage account keys renew --account-name cani9820b2c229 -g $RG --key key1`
  → build the new connection string → `kvset azure-storage-connection-string …` → restart.
- **Entra client secret**: `az ad app credential reset --id 1f0927a0-fe19-4661-93e0-019e94b05416`
  → `kvset entra-oidc-client-secret …` → also update the cluster `cani-hub-oidc` fallback if
  still present → restart hub-api.

## Rollback

If pods fail to mount / read secrets: re-apply the manual secret
(`CANI_DEV_SECRETS_FILE=~/.cani/dev-secrets.env scripts/apply_dev_secrets.sh` — keep it until
the cutover is confirmed) and `kubectl rollout undo` the four deployments. The CSI wiring is
inert without the driver-populated Secret, so the old path resumes.

## Step 5 — Cleanup

- Remove `scripts/apply_dev_secrets.sh`; point `runbooks/rotate-dev-secrets.md` at the KV
  (`kvset`) flow.
- Close D1 on `docs/19-sprint-3-reachability-board.md`.
