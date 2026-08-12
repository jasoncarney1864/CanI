# Qdrant Cloud cutover and re-ingest (2026-08-09 incident recovery)

Recovers from the 2026-08-09 corruption of self-hosted Qdrant
(docs/sitreps/2026-08-09-qdrant-corruption-and-missing-backups.md) by completing the
already-staged move to Qdrant Cloud. The corrupted store is unrecoverable and there is no
backup, so this is a rebuild: point the apps at the (empty, healthy) cloud cluster, then
re-embed every document from Postgres + Blob, which are both intact.

**Fixed values used throughout:**

| Thing | Value |
| --- | --- |
| Resource group | `cani-container-apps-dev` |
| Key Vault | `cani-platform-kv2e5cf1f6` |
| Qdrant Cloud cluster | `CanI`, free tier, AWS us-west-2 (URL already in `main.parameters.json`) |
| Collection | `cani_docs_dev_v2` |
| Snapshot target storage | `cani6ada34dffd`, container `qdrant-snapshots` |
| Orphaned self-hosted storage | `caniqdrthpizrvpqt7u` (file share `qdrant-data`) |
| Postgres | `cani-pgfd564d67` |

Everything up to step 6 is reversible with `git revert` plus a redeploy. Step 8
(decommission) and the AKS teardown in step 9 are not.

## 1. Commit and push

Working tree carries the incident-hardening changes (retrieval retry, `/readyz`, bicep
probe, CD smoke check). Review, commit, and push **from a local terminal** — and remember
`main` was already one commit ahead (`74e446f`, the sitrep) before these.

```bash
git add -p    # review: qdrant_client.py, retrieval main.py, main.bicep, cd workflow, test
git commit
git push
```

Wait for CI green before deploying — the deploy ships whatever images CD built last, and
you want the pipeline's view of main to match what you are about to run.

## 2. Deploy the Bicep (the actual cutover)

`deploy-with-secrets.ps1` reads six secrets from Key Vault *from this machine*, so the
public endpoint must be opened for the duration:

```bash
az keyvault update --name cani-platform-kv2e5cf1f6 --public-network-access Enabled
```

```powershell
pwsh infra/container-apps/deploy-with-secrets.ps1 -WhatIf
# Expect noise on all six secure params — the -WhatIf path passes dummies. That is an
# artifact, not a real change. Review everything else, especially QDRANT_URL flipping
# from the internal FQDN to the cloud URL on all four apps + the snapshot job.
pwsh infra/container-apps/deploy-with-secrets.ps1
```

```bash
az keyvault update --name cani-platform-kv2e5cf1f6 --public-network-access Disabled
```

This deploy also creates the `qdrant-snapshot` job for the first time — the template
defined it before the incident but it had never been applied, which is exactly why there
were no backups.

## 3. Verify connectivity before re-ingesting

```bash
# Startup log: expect "✅ Qdrant client created", and no 401 afterwards
az containerapp logs show -n retrieval-worker -g cani-container-apps-dev --tail 50

# Readiness now exercises Qdrant (new in this change) — 200 means the cluster is
# reachable with the real key from the real environment:
RETRIEVAL_FQDN=$(az containerapp show -n retrieval-worker -g cani-container-apps-dev \
  --query properties.configuration.ingress.fqdn -o tsv)
curl -i "https://$RETRIEVAL_FQDN/readyz"
```

A 401 here means the Key Vault secret and the cluster's current API key disagree
(remember the first key was rotated after the 2026-08-09 leak — see the preflight notes).

## 4. Re-ingest

Postgres `documents` / `document_versions` rows and the raw blobs are intact, so
re-ingest = enqueue a fresh ingestion job for every document version. The pipeline
re-runs extraction (Document Intelligence cost at ~77 documents is negligible) and
re-embeds into the empty cloud collection. Chunking is deterministic, so
`chunk_manifests` re-inserts are idempotent.

```sql
-- Enqueue one job per existing document version. Zip parents fan out children on their
-- own, but their extraction step is a no-op unpack, so including them is harmless.
INSERT INTO ingestion_jobs
    (ingestion_job_id, document_version_id, owner_user_id, stage, status, attempt_count, started_at)
SELECT gen_random_uuid(), dv.document_version_id, dv.owner_user_id, 'queued', 'queued', 0, now()
FROM document_versions dv;
```

Watch it drain:

```sql
SELECT status, count(*) FROM ingestion_jobs
WHERE started_at > now() - interval '1 hour' GROUP BY status;
```

```bash
az containerapp logs show -n ingestion-worker -g cani-container-apps-dev --follow
```

## 5. Reconcile (docs/09 §9.10)

Point count in Qdrant must equal the manifest count in Postgres:

```sql
SELECT count(*) FROM chunk_manifests;
```

```bash
curl -s -H "api-key: $QDRANT_API_KEY" \
  "$QDRANT_URL/collections/cani_docs_dev_v2" | jq .result.points_count
```

Then ask a real question through the app and confirm citations render. This is the
moment `/query` is back.

## 6. Prove the backup exists this time

The incident's core lesson was a documented-but-not-running control. Do not take the
job's existence on faith — run it and look at the artifact:

```bash
az containerapp job start -n qdrant-snapshot -g cani-container-apps-dev
az containerapp job execution list -n qdrant-snapshot -g cani-container-apps-dev -o table
az storage blob list --account-name cani6ada34dffd -c qdrant-snapshots -o table
```

A timestamped blob under `cani_docs_dev_v2/` = you have a backup for the first time
since the migration.

## 7. Update the incident sitrep

Mark the 2026-08-09 sitrep resolved with the recovery date and the points_count.

## 8. Decommission the corrupted self-hosted Qdrant

The incremental ARM deploy does not delete resources it no longer declares:

```bash
az containerapp delete -n qdrant -g cani-container-apps-dev --yes
az storage account delete -n caniqdrthpizrvpqt7u -g cani-container-apps-dev --yes
```

The corrupted collection data dies with the storage account; nothing of value is on it.

## 9. Check whether AKS is still billing

The consolidation plan ended with `pulumi up` on the workload stack destroying the AKS
cluster. Verify it actually happened:

```bash
az aks list -o table
```

If a cluster is still listed, finish the teardown (this is the irreversible step —
only run it with steps 3–6 verified):

```bash
cd infra/workload && pulumi up
```

## Rollback

Before step 8 there is nothing to roll back *to* — the self-hosted store is corrupt and
was already down. If the cloud cluster misbehaves, the failure mode is the same outage
already in progress, minus two structural faults. Fix forward.
