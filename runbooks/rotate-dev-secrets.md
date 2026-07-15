# Runbook: dev secrets — storage, apply, and rotation

Covers the `cani-secrets` Kubernetes Secret consumed by all four services in dev
(`hub-system` and `docs-platform` namespaces).

## Where secret values live

- **Canonical location:** `~/.cani/dev-secrets.env` on the operator's machine —
  deliberately **outside** the repo (so it can't be committed) and **outside OneDrive**
  (so it never syncs to a cloud account). Plain `KEY=VALUE` lines, no quotes needed.
- **Never** store secret values anywhere under the repo tree. `.gitignore` blocks
  `*secrets-bootstrap*.yaml` as a backstop, but the rule is: the file shouldn't exist
  there in the first place.
- The Postgres admin password additionally lives, encrypted, in Pulumi stack config
  (`infra/workload`, key `postgresAdminPassword`) — Pulumi is the source of truth for
  what the *server* accepts; the env file must be kept in sync with it.

Required keys (all seven are required by `cani_shared.config.Settings` in every service,
even where a service doesn't functionally use them):

```
CANI_TOKEN_SIGNING_SECRET=   # >=32 chars
CANI_SESSION_SECRET=         # >=32 chars
POSTGRES_PASSWORD=
POSTGRES_HOST=               # Postgres Flexible Server FQDN
QDRANT_URL=
QDRANT_COLLECTION=
AZURE_STORAGE_CONNECTION_STRING=
```

## Applying to the cluster

```bash
bash scripts/apply_dev_secrets.sh
```

The script reads `~/.cani/dev-secrets.env` (override with `CANI_DEV_SECRETS_FILE`),
validates all keys are present and the signing secrets meet the app's 32-char minimum,
and streams the Secret manifests to `kubectl apply` over stdin — nothing is written to
disk. Then restart the workloads (the script prints the exact commands).

## One-time migration note (2026-07-15)

Dev secrets previously sat in a plaintext manifest inside the repo working tree
(`k8s/overlays/dev/cani-secrets-bootstrap.yaml` — untracked but not gitignored, and
synced to OneDrive by virtue of the repo's location). That file has been moved to
`~/.cani/cani-secrets-bootstrap.yaml`. **Treat every value in it as exposed** to the
OneDrive account and rotate all of them (procedure below), then delete the moved file
once `~/.cani/dev-secrets.env` is populated and applied.

## Rotation procedures

### 1. Token signing + session secrets (`CANI_TOKEN_SIGNING_SECRET`, `CANI_SESSION_SECRET`)

Rotating these invalidates **all** outstanding access tokens and sessions — that is the
point (it's also the documented containment step in
`suspected-cross-tenant-access.md`). Users just re-login; no server-side state to update.

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"   # run twice, one per key
# update both values in ~/.cani/dev-secrets.env
bash scripts/apply_dev_secrets.sh
kubectl -n hub-system rollout restart deployment/hub-api
kubectl -n docs-platform rollout restart deployment/docs-api deployment/retrieval-worker deployment/ingestion-worker
```

### 2. Postgres admin password (`POSTGRES_PASSWORD`)

Pulumi owns the server-side password — change it there first, then update the env file:

```bash
cd infra/workload
pulumi config set --secret postgresAdminPassword   # prompts; paste the new value
pulumi up                                          # applies the server-side change
# update POSTGRES_PASSWORD in ~/.cani/dev-secrets.env to the same value
bash scripts/apply_dev_secrets.sh
# restart all four deployments (commands printed by the script)
```

Expect a brief window where running pods hold the old password; restart promptly after
`pulumi up` completes.

### 3. Storage connection string (`AZURE_STORAGE_CONNECTION_STRING`)

Storage accounts have two keys, so rotate without downtime by switching keys:

```bash
# If currently on key1, first point the app at key2:
az storage account show-connection-string \
  --name <storage-account-name> -g <workload-rg> --key secondary -o tsv
# update AZURE_STORAGE_CONNECTION_STRING in ~/.cani/dev-secrets.env, apply, restart

# Then invalidate the exposed key:
az storage account keys renew --account-name <storage-account-name> -g <workload-rg> --key key1
```

(Longer term this key goes away entirely — workload identity + Key Vault CSI is the
target state per `k8s/base/secret-provider-class.yaml`; account-key auth is a dev
stopgap.)

### 4. Verify after any rotation

```bash
kubectl -n hub-system get pods && kubectl -n docs-platform get pods   # all Running
# then exercise the real path: dev-login -> token -> upload -> poll indexed -> query
# (see README.md "Walk the core loop by hand")
```

A failed rotation shows up as CrashLoopBackOff with a `ValidationError` from
`cani_shared.config` (missing/short values) or auth failures in logs (stale password) —
`kubectl logs` on the failing pod says which.
