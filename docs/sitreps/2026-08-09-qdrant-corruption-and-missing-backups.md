# Sitrep 2026-08-09 — Qdrant store corrupted, no backups existed

**Status:** live incident, mitigated but not resolved. Query path down since ~Aug 7.
**Impact:** every `/query` returns 500. Upload/ingest also affected (same dependency).
Auth, document listing and the web app are unaffected.

## What users saw

`Upstream query failed (500).` on every question. The web app degraded cleanly — the
error rendered in the conversation pane and the mic stayed usable — so the failure looked
cosmetic from the outside while retrieval was entirely dead.

## Chain

1. `docs-api /query` proxies to `retrieval-worker`, which calls `ensure_qdrant_ready()`
   on **every** request (`retrieval_worker_app/main.py:102`).
2. That calls `get_collections()` against `QDRANT_URL`.
3. Qdrant is unreachable, so the call raises and becomes a 500.

Qdrant itself is crash-looping on startup:

```
Panic occurred in .../shards/replica_set/mod.rs:275:
Failed to load local shard "./storage/collections/cani_docs_dev_v2/0":
RocksDB open error: IO error: No such file or directory: while unlink() file:
  .../segments/30ff9a71-b778-410b-a73d-ef27f3abfa1f/LOG.old.1786122894878678
```

## Root cause

Two contributing faults, both structural:

**Two active revisions sharing one RocksDB store.** At time of diagnosis:

| Revision | Created | Active | Replicas | Traffic | State |
|---|---|---|---|---|---|
| `qdrant--587kiiz` | Aug 5 | yes | 1 | 0% | Healthy |
| `qdrant--0000001` | Aug 7 | yes | 1 | 100% | **Failed** |

Both mounted the same `qdrant-data` Azure Files share. RocksDB is single-writer and does
not tolerate two processes opening one store. All traffic pointed at the failed revision.

**RocksDB on Azure Files (SMB).** SMB does not provide the `unlink()`-on-open-file and
locking semantics RocksDB assumes — and `unlink()` is the exact syscall in the panic.
Two writers made corruption near-certain, but one writer on SMB is still unsound.

## The backup that wasn't

`runbooks/backup-restore-drill.md` documents a validated Qdrant backup: nightly snapshot
job at 02:00 UTC to the `qdrant-snapshots` blob container, RPO 24 h, restore measured at
0.9 s during the 2026-07-17 drill. That drill was real — but it ran against the AKS
deployment, and the migration did not carry the mechanism over.

Verified 2026-08-09:

- `qdrant-snapshots` container on `cani6ada34dffd` exists and holds **0 blobs**.
- `az containerapp job list -g cani-container-apps-dev` returns **no jobs at all**;
  `qdrant-snapshot` is `ResourceNotFound`.

`infra/container-apps/main.bicep` defines `qdrantSnapshotJob`, so the template is correct
and was simply never applied. Recovery is therefore a **rebuild, not a restore**.

This is the same shape as the August fake-providers incident: a control that is written
down, believed, and not actually running. In both cases nothing errored.

## Actions taken

- Deactivated `qdrant--587kiiz` to stop the second writer.
- Set the `qdrant` app to single-revision mode so multi-revision cannot recreate one.

Neither repairs the corruption; they stop it recurring while we work.

## Remaining

1. Delete `collections/cani_docs_dev_v2` from the `qdrant-data` share so Qdrant can boot.
   The data is corrupt and unrecoverable, so nothing is lost by deleting it.
2. Let `ensure_collection` recreate the collection at the embedder's dimension.
3. Re-ingest from the `extracted-text` container — OCR and Document Intelligence can be
   skipped, since extraction output is already persisted.
4. Reconcile restored point count against `chunk_manifests` (docs/09 §9.10).

## Follow-ups this exposed

- **Deploy the snapshot job.** Highest priority. There are currently no backups.
- **Finish moving to Qdrant Cloud.** `main.parameters.json` already sets `qdrantUrl` to a
  Qdrant Cloud cluster while production runs self-hosted on the file share. Applying the
  Bicep as-is would silently repoint Qdrant at a different, empty corpus. Deployed state
  and IaC disagree, and the IaC is the intended destination.
- **`/healthz` does not reflect readiness.** It returned 200 throughout, because it never
  touches Qdrant. The CD smoke check greenlights a service that cannot answer a query. A
  readiness probe that exercises the dependency would have caught this at deploy time.
- **No retry on the query path.** One transient Qdrant failure is a user-visible 500.
  `d7f716d` already hardened ingestion-worker against exactly this; retrieval never got
  the same treatment.
- **`ensure_qdrant_ready()` runs per request** rather than being cached after first
  success, widening the window for the above.
