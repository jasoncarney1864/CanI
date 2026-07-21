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

> **CRITICAL — the CSI driver does NOT auto-propagate Key Vault changes.** Secret rotation
> (`Rotation` / `--enable-secret-rotation`) is **off** on this cluster, so writing a new value
> to Key Vault does **nothing** on its own: the driver only re-reads a secret when a pod
> mounts the SPC volume, and it will **not** overwrite the existing `cani-secrets`/
> `cani-keda-postgres` k8s Secret it already created. A plain `kubectl rollout restart` reuses
> the stale k8s Secret — pods come back on the OLD value and look "fine". This misled us once
> (a self-consistent old signing secret read as "rotation verified"). **You must delete the
> synced k8s Secret so the driver rebuilds it from Key Vault on the next mount.**

**Corrected rotation procedure (every secret):**

1. Set the new value in Key Vault via ARM PUT (`kvset`, Step 2) — never echo the value.
2. **Delete the synced Secret in BOTH namespaces** so the driver re-syncs from KV:

   ```bash
   RG=cani-workload-core-dev-eastus2-rg9c8e66d0; CL=cani-aks64bdb7d1
   az aks command invoke -g $RG -n $CL --command \
     "kubectl delete secret cani-secrets -n docs-platform -n hub-system --ignore-not-found"
   # if rotating the KEDA connection, also: kubectl delete secret cani-keda-postgres -n docs-platform --ignore-not-found
   ```

3. **Restart ALL consuming services together** (not just the "affected" one). Shared secrets
   like the signing/session key live in every namespace; refreshing only one side leaves
   hub-api and docs-api on different values and breaks cross-service token validation.

   ```bash
   az aks command invoke -g $RG -n $CL --command \
     "kubectl -n hub-system rollout restart deploy/hub-api; \
      kubectl -n docs-platform rollout restart deploy/docs-api deploy/retrieval-worker deploy/ingestion-worker"
   ```

4. Verify per the **Verify** section above (pods Ready, CD smoke check, live sign-in).

Per-secret specifics (each still follows the four steps above):

- **Postgres admin password**: `pulumi config set --secret postgresAdminPassword <new>` in
  `infra/workload` → merge/apply on `main` (CI updates the Flexible Server) → `kvset
  postgres-password …` → rebuild the KEDA connection string + `kvset keda-postgres-connection …`
  → delete `cani-secrets` (both ns) **and** `cani-keda-postgres` → restart all. Highest risk;
  watch the DB.
- **Storage account key**: `az storage account keys renew --account-name cani9820b2c229 -g $RG --key key1`,
  then **build the connection string in Python from `az storage account keys list -o json`**
  (the `--key secondary` / `show-connection-string` CLI forms returned empty on Windows) and
  **TEST it authenticates before writing to KV** — `az storage container list --connection-string "<new>"`
  must succeed — then `kvset azure-storage-connection-string …` → refresh. A previous attempt
  wrote an unverified key2 string and crashlooped docs-api; the test-first guard prevents that.
- **Entra client secret**: cross-tenant — the `cani-hub` app is in the caniauth CIAM tenant,
  not your default `az` session. `az login --tenant 43189f5e-8c1b-4e3f-9cf7-d17babc03e36 --allow-no-subscriptions`,
  then `az ad app credential reset --id 1f0927a0-fe19-4661-93e0-019e94b05416` → switch the CLI
  back → `kvset entra-oidc-client-secret …` → refresh (only hub-system carries this secret, but
  still delete `cani-secrets` there and restart hub-api).

## Rollback

> The cutover is **confirmed complete** (2026-07-20) and `scripts/apply_dev_secrets.sh` has
> been removed, so the original script-based rollback no longer applies.

If pods fail to mount / read secrets after a change, recover within the CSI model: check the
SecretProviderClass + `SecretProviderClassPodStatus` and the CSI driver logs, confirm the
workload identity can reach the vault, and if a rotation produced a bad value re-run the
corrected rotation procedure (Step 4) with a known-good value — delete `cani-secrets` in both
namespaces and restart all services so the driver re-syncs from Key Vault. Values can be
re-created locally from `~/.cani/dev-secrets.env` if the vault needs re-populating (ARM PUT via
`kvset`), since ARM cannot read secret values back.

## Step 5 — Cleanup (2026-07-20)

- [x] Removed `scripts/apply_dev_secrets.sh`; `runbooks/rotate-dev-secrets.md` rewritten to
  the KV (`kvset`) delete-secret rotation flow.
- [x] Closed D1 on `docs/19-sprint-3-reachability-board.md` (cutover done; storage/Entra/
  Postgres rotation tracked as a follow-up).
- [ ] Delete the leftover `d1-connectivity-test` validation secret. **Blocked from a laptop:**
  ARM management-plane PUT can create/update secrets but the resource type does **not** support
  DELETE (`DeleteNotSupported`); deletion is a **data-plane** op, and the vault has
  `public_network_access=Disabled`, so it's unreachable from outside the vnet. The value is a
  throwaway connectivity probe (no real material), so this is tidiness, not exposure. Delete it
  from inside the vnet with a principal holding **Key Vault Secrets Officer** (the CI/operator
  UAMI has only *Secrets User*), e.g. a short-lived pod:
  `az aks command invoke -g cani-workload-core-dev-eastus2-rg9c8e66d0 -n cani-aks64bdb7d1 --command "kubectl run kvdel --rm -i --restart=Never --image=mcr.microsoft.com/azure-cli -- az keyvault secret delete --vault-name cani-platform-kv6370c4cb --name d1-connectivity-test"`
  (the pod needs a workload-identity binding to a Secrets Officer identity). Deferred with the
  other rotation follow-ups.
