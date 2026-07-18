# Backup and restore drill (docs/09 §9.10, Sprint 2 C1)

How CanI's three data stores are backed up, how to restore each, and the results of the
2026-07-17 validation drill. Recovery objectives are summarized first, then the
per-store procedures.

## Recovery objectives (dev, measured/estimated 2026-07-17)

| Store | Mechanism | RTO | RPO |
| --- | --- | --- | --- |
| Postgres | Flexible Server point-in-time restore (7-day retention) | Provisioning time of a new server — Azure-typical ~10-30 min for a Burstable B2s (readiness-validated, not executed this drill) | Continuous WAL archiving; restore to any point in the 7-day window, last-restorable-time lag ~5 min |
| Qdrant | Scheduled snapshot exported to Blob (daily CronJob) | ~1 s to restore a snapshot into a collection (measured); ~13 s to take + upload a fresh snapshot | Snapshot interval = 24 h; take an on-demand snapshot before risky ops to drive RPO toward 0 |
| Blob Storage | Versioning + soft delete (7-day) | Immediate (list versions / undelete) | Versioning captures every overwrite (RPO ~0 for overwrites); 7-day recovery window for deletes |

## 2026-07-17 drill results

- **Qdrant — full drill executed and passed.** Seeded one real document (1 chunk),
  triggered the snapshot CronJob (completed in 13 s, ~64 MB snapshot landed in the
  `qdrant-snapshots` container), then restored that snapshot from Blob into a scratch
  collection (`cani_docs_dev_restore_drill`) in 0.9 s and reconciled: restored point
  count (1) == `chunk_manifests` row count (1), the §9.10 reconciliation. Scratch
  collection deleted afterward; live data untouched.
- **Postgres — readiness-validated (restore not executed).** PITR is enabled on
  `cani-pgfd564d67` (Ready, Standard_B2s Burstable), 7-day retention, earliest restore
  point 2026-07-15T05:02:43Z. The restore procedure below is documented and its
  parameters confirmed against the CLI; an actual restore-to-temp-server was deferred to
  avoid the (small) cost, per the C1 decision.
- **Blob — enabled and verified live.** Versioning = true, blob soft delete = true
  (7 days), container soft delete = true (7 days).

## Postgres: point-in-time restore

PITR creates a **new** server from the source server's continuous backups; it never
mutates the source. Restore to a new name, validate, then repoint the app (or rename)
during a real recovery.

```bash
RG=cani-workload-core-dev-eastus2-rg9c8e66d0
SRC=cani-pgfd564d67
# Pick a time within the retention window (see earliestRestoreDate):
az postgres flexible-server show -g "$RG" -n "$SRC" \
  --query "backup.earliestRestoreDate" -o tsv

# Restore to a new server at a chosen UTC timestamp:
az postgres flexible-server restore \
  -g "$RG" \
  --name cani-pg-restore-drill \
  --source-server "$SRC" \
  --restore-time "2026-07-17T12:00:00Z"
```

Validation after the restore completes (connect to the restored server and check the
source-of-truth tables):

```sql
SELECT count(*) FROM documents;
SELECT count(*) FROM chunk_manifests;
SELECT count(*) FROM users;
```

Teardown (drills only — a real recovery keeps the restored server):

```bash
az postgres flexible-server delete -g "$RG" -n cani-pg-restore-drill --yes
```

Notes:
- Geo-redundant backup is Disabled in dev (single-region). A region loss is out of scope
  for the dev RPO; revisit for prod.
- RTO is dominated by new-server provisioning, not data volume, at this scale.

## Qdrant: snapshot and restore

**Backup** is automated: the `qdrant-snapshot` CronJob (`k8s/base/qdrant/snapshot-cronjob.yaml`,
daily 02:00 UTC) runs `python -m cani_shared.backup`, which snapshots the collection via
Qdrant's REST API, uploads it to the `qdrant-snapshots` blob container under a
timestamped path, then deletes the on-disk copy. Run it on demand with:

```bash
kubectl -n docs-platform create job --from=cronjob/qdrant-snapshot qdrant-snap-adhoc
kubectl -n docs-platform wait --for=condition=complete job/qdrant-snap-adhoc --timeout=300s
kubectl -n docs-platform logs job/qdrant-snap-adhoc | grep qdrant_snapshot_uploaded  # -> blob_uri
```

**Restore** downloads a snapshot from Blob and recovers it into a collection. Restore
into a *scratch* collection first to validate (as the drill did), or into the live
collection name for a real recovery. From a pod carrying `cani_shared` + Blob egress
(e.g. `deploy/ingestion-worker`):

```python
import httpx
from cani_shared.config import get_settings
from cani_shared.blob import BlobStore

s = get_settings()
base = s.qdrant_url.rstrip("/")
blob_uri = "qdrant-snapshots/<collection>/<timestamp>_<snapshot>.snapshot"  # from the CronJob log
target = "cani_docs_dev"  # or a scratch name for a drill

data = BlobStore(s.azure_storage_connection_string).download(blob_uri)
httpx.post(
    f"{base}/collections/{target}/snapshots/upload?priority=snapshot",
    files={"snapshot": ("snap.snapshot", data)}, timeout=600,
).raise_for_status()
```

**Reconciliation** (§9.10, metadata is source of truth): after restore, the collection's
`points_count` must equal the owner-scoped `chunk_manifests` row count. A shortfall means
points are missing (re-ingest the affected documents); an excess means orphaned points
(safe to leave or prune). The drill confirmed an exact match.

## Blob Storage: accidental-deletion recovery

Versioning and soft delete are enabled on the workload storage account (7-day window).

- **Overwritten blob** — list versions and copy the prior version back:
  `az storage blob list --include v ...` then promote/copy the wanted `versionId`.
- **Deleted blob** — undelete within the window:
  `az storage blob undelete --account-name <acct> -c <container> -n <path>`.
- **Deleted container** — restore within the window:
  `az storage container restore --account-name <acct> --name <container> --deleted-version <ver>`.
