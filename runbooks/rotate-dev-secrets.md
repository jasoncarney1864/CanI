# Runbook: dev secrets — where they live and how to rotate them

As of D1 (2026-07-20) the dev cluster sources every runtime secret from **Azure Key Vault**
via the Secrets Store CSI driver + workload identity. The manual `cani-secrets` script
(`scripts/apply_dev_secrets.sh`) is **retired** — Key Vault is the source of truth for what
the cluster runs on. This runbook covers where the values live now and the correct rotation
procedure. The one-time cutover itself is documented in
[`keyvault-secret-cutover.md`](keyvault-secret-cutover.md).

## Where secret values live

- **Cluster (canonical): Azure Key Vault `cani-platform-kv6370c4cb`.** The CSI driver syncs
  the KV secrets into the `cani-secrets` k8s Secret (both `docs-platform` and `hub-system`)
  plus `cani-keda-postgres` (KEDA connection), on pod mount. See
  [`k8s/base/secret-provider-class.yaml`](../k8s/base/secret-provider-class.yaml) for the
  KV-name → env-key mapping.
- **The vault is private** (`public_network_access=Disabled`, RBAC auth). Its **data plane**
  is reachable only via the private endpoint from inside the cluster — you can't read/write
  values with a plain `az keyvault secret` command from a laptop. Writes go through the **ARM
  management plane** (`az rest ... PUT`, the `kvset` helper below), which is reachable from
  anywhere; note ARM **cannot read** secret values back (GET returns metadata only).
- **Local docker-compose only:** `~/.cani/dev-secrets.env` on the operator's machine —
  outside the repo and outside OneDrive. This is now *only* for running the stack locally; it
  is **not** applied to the cluster anymore. Keep it in sync with KV when you rotate.
- The Postgres admin password additionally lives, encrypted, in Pulumi stack config
  (`infra/workload`, key `postgresAdminPassword`) — Pulumi is the source of truth for what the
  *server* accepts; KV + the env file must match it.

KV secret name → env key consumed by the app:

| KV secret name | env key |
| --- | --- |
| `cani-token-signing-secret` | `CANI_TOKEN_SIGNING_SECRET` (>=32 chars) |
| `cani-session-secret` | `CANI_SESSION_SECRET` (>=32 chars) |
| `postgres-password` | `POSTGRES_PASSWORD` |
| `azure-storage-connection-string` | `AZURE_STORAGE_CONNECTION_STRING` |
| `azure-documentintelligence-api-key` | `AZURE_DOCUMENTINTELLIGENCE_API_KEY` |
| `applicationinsights-connection-string` | `APPLICATIONINSIGHTS_CONNECTION_STRING` |
| `entra-oidc-client-secret` | `ENTRA_OIDC_CLIENT_SECRET` |
| `keda-postgres-connection` | `connection` in `cani-keda-postgres` |

Non-secret config (`POSTGRES_HOST`, `QDRANT_URL`, `QDRANT_COLLECTION`,
`AZURE_DOCUMENTINTELLIGENCE_ENDPOINT`, `ENTRA_OIDC_*` except the client secret) now lives in
the `cani-config` ConfigMap ([`k8s/base/config.yaml`](../k8s/base/config.yaml)), not in any
secret.

## The one rule that matters: the CSI driver does NOT auto-propagate KV changes

Secret rotation is **off** on this cluster (the default). Writing a new value to Key Vault
does **nothing** on its own, and a plain `kubectl rollout restart` reuses the **stale**
`cani-secrets` k8s Secret — pods come back on the OLD value and appear healthy. (This bit us
during D1: a self-consistent old signing secret read as "rotation verified".) The driver only
rebuilds the k8s Secret from KV when a pod mounts the SPC volume **and** the k8s Secret does
not already exist — so you must delete it.

## Rotation procedure (all secrets)

```bash
# --- setup: management-plane PUT helper (never echoes values) ---
KV_MGMT="https://management.azure.com/subscriptions/6591cee6-ee26-4155-ae71-3777bf7e9c73/resourceGroups/cani-platform-core-dev-eastus2-rg1227b5a0/providers/Microsoft.KeyVault/vaults/cani-platform-kv6370c4cb/secrets"
kvset() {  # kvset <kv-secret-name> <env-var-holding-value>
  local name="$1" val="${!2}"
  az rest --method put --url "$KV_MGMT/${name}?api-version=2023-07-01" \
    --body "$(jq -nc --arg v "$val" '{properties:{value:$v}}')" >/dev/null && echo "set $name"
}
RG=cani-workload-core-dev-eastus2-rg9c8e66d0; CL=cani-aks64bdb7d1
```

1. **Set the new value in KV** with `kvset` (never `echo` the value; source it from a shell
   var or `~/.cani/dev-secrets.env`).
2. **Delete the synced k8s Secret in BOTH namespaces** so the driver re-syncs from KV:

   ```bash
   az aks command invoke -g $RG -n $CL --command \
     "kubectl delete secret cani-secrets -n docs-platform -n hub-system --ignore-not-found"
   # KEDA connection too, when rotating it:
   # az aks command invoke -g $RG -n $CL --command "kubectl delete secret cani-keda-postgres -n docs-platform --ignore-not-found"
   ```

3. **Restart ALL services together** — shared secrets (signing/session) exist in both
   namespaces; refreshing one side leaves hub-api and docs-api on different values and breaks
   cross-service token validation:

   ```bash
   az aks command invoke -g $RG -n $CL --command \
     "kubectl -n hub-system rollout restart deploy/hub-api; \
      kubectl -n docs-platform rollout restart deploy/docs-api deploy/retrieval-worker deploy/ingestion-worker"
   ```

4. **Verify** (see section at the end). Also update `~/.cani/dev-secrets.env` to the new value
   so local compose stays in sync.

## Per-secret specifics

### 1. Token signing + session secrets (`cani-token-signing-secret`, `cani-session-secret`)

Rotating these invalidates **all** outstanding access tokens and sessions — that is the point
(also the containment step in `suspected-cross-tenant-access.md`). Users just re-login.

```bash
CANI_TOKEN_SIGNING_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
CANI_SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
kvset cani-token-signing-secret CANI_TOKEN_SIGNING_SECRET
kvset cani-session-secret CANI_SESSION_SECRET
# then: delete cani-secrets (both ns) -> restart all -> verify
```

### 2. Storage connection string (`azure-storage-connection-string`)

Storage accounts have two keys, so rotate without downtime by renewing one, but **build and
TEST the connection string before writing it to KV** — a previous rotation wrote an unverified
key2 string and crashlooped docs-api. The `--key secondary` / `show-connection-string` CLI
forms returned empty on Windows; build it in Python from the key list instead:

```bash
ACCT=cani9820b2c229
az storage account keys renew --account-name $ACCT -g $RG --key key1 >/dev/null
KEY="$(az storage account keys list --account-name $ACCT -g $RG -o json \
  | python -c 'import json,sys; print([k["value"] for k in json.load(sys.stdin) if k["keyName"]=="key1"][0])')"
AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=$ACCT;AccountKey=$KEY;EndpointSuffix=core.windows.net"
# TEST it authenticates BEFORE writing to KV:
az storage container list --connection-string "$AZURE_STORAGE_CONNECTION_STRING" -o none && echo "auth OK"
kvset azure-storage-connection-string AZURE_STORAGE_CONNECTION_STRING
# then: delete cani-secrets (both ns) -> restart all -> verify
```

(Longer term this key goes away entirely — the target is a storage RBAC role on the workload
identity, no account key. Account-key auth is the current dev stopgap.)

### 3. Postgres admin password (`postgres-password`) + KEDA connection (`keda-postgres-connection`)

Highest risk — changing the server password breaks in-flight connections until pods restart.
Pulumi owns the server-side password; change it there first so server + KV stay in sync:

```bash
cd infra/workload
pulumi config set --secret postgresAdminPassword   # prompts; paste the new value
# merge/apply on main (CI runs infra-apply-dev) — this updates the Flexible Server
```

Then mirror it into KV, rebuild the KEDA connection (dedicated `keda_scaler` role — LOGIN +
SELECT on `ingestion_jobs` only, never the admin credential), and refresh:

```bash
POSTGRES_PASSWORD="<same value>"
kvset postgres-password POSTGRES_PASSWORD
KEDA_POSTGRES_CONNECTION="postgresql://keda_scaler:<keda-pass>@cani-pgfd564d67.postgres.database.azure.com:5432/cani?sslmode=require"
kvset keda-postgres-connection KEDA_POSTGRES_CONNECTION
# delete cani-secrets (both ns) AND cani-keda-postgres -> restart all -> verify -> watch the DB
az aks command invoke -g $RG -n $CL --command \
  "kubectl -n docs-platform annotate scaledobject ingestion-worker cani.io/reconcile-nudge=$(date +%s) --overwrite"
```

`kubectl get scaledobject -n docs-platform` — READY must return to `True`.

### 4. Entra OIDC client secret (`entra-oidc-client-secret`)

Cross-tenant: the `cani-hub` app registration lives in the `caniauth` CIAM tenant
(43189f5e-8c1b-4e3f-9cf7-d17babc03e36), not your default `az` session — authenticate there
first:

```bash
az login --tenant 43189f5e-8c1b-4e3f-9cf7-d17babc03e36 --allow-no-subscriptions
NEW="$(az ad app credential reset --id 1f0927a0-fe19-4661-93e0-019e94b05416 \
  --display-name hub-api-dev --years 1 --query password -o tsv)"
az account set --subscription 6591cee6-ee26-4155-ae71-3777bf7e9c73   # switch CLI back
ENTRA_OIDC_CLIENT_SECRET="$NEW"; unset NEW
kvset entra-oidc-client-secret ENTRA_OIDC_CLIENT_SECRET
# only hub-system carries this, but still: delete cani-secrets (both ns) -> restart all -> verify a live sign-in
```

`credential reset` replaces ALL existing secrets on the app by default; in-flight hub-api pods
keep working until restart (token exchange only happens at login), but refresh promptly and
confirm a fresh incognito sign-in works.

## Verify after any rotation

```bash
az aks command invoke -g $RG -n $CL --command \
  "kubectl -n hub-system get pods; kubectl -n docs-platform get pods"   # all Running/Ready
```

Then exercise the real path end-to-end at `https://app.canido.co` (a fresh **incognito**
sign-in — Entra SSO will silently re-login an existing browser session, masking a broken
secret): Entra login → upload → query → cited answer. A failed rotation shows up as
CrashLoopBackOff with a `ValidationError` from `cani_shared.config` (missing/short values) or
auth failures in logs (stale password/secret) — `kubectl logs` on the failing pod says which.
