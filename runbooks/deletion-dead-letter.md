# Runbook: deletion dead-letter jobs

Applies to `deletion_jobs` rows with `status = 'failed'` (docs/09 §9.9, docs/21 §1.7).

The document stays tombstoned (`documents.deleted_at` set) regardless of cleanup status —
it's already invisible to the owner in list/get/text/download/dedupe. A failed deletion
job means the async cleanup (Qdrant points, blobs, Postgres rows) didn't finish; it is not
user-visible and is not urgent in the way a stuck upload is.

## Triage

```sql
select deletion_job_id, document_id, owner_user_id, error_detail, attempt_count, finished_at
from deletion_jobs
where status = 'failed'
order by finished_at desc
limit 50;
```

- A `RetryableDeletionError` in `error_detail` that still ended up `failed` means the
  document had an ingestion job stuck `processing` for all 5 attempts — check
  `ingestion_jobs` for that document_id; if the ingestion job is itself dead (crashed
  worker, never finished), see `runbooks/ingestion-dead-letter.md` first, then requeue the
  deletion job below once it clears.
- Anything else (Qdrant/blob transient errors, unexpected exceptions) — safe to requeue;
  steps 2-4 of `ingestion_worker_app/deletion.py::process_deletion` are each idempotent.

## Requeue a job

```sql
update deletion_jobs
set status = 'queued', attempt_count = 0, error_detail = null
where deletion_job_id = '<id>';
```

ingestion-worker picks it up on its next poll cycle (`SELECT ... FOR UPDATE SKIP LOCKED`,
same as ingestion jobs — see `apps/ingestion-worker/ingestion_worker_app/worker.py`).

## Escalate

If failures cluster across many owners, check Qdrant and blob storage availability first
— not a per-job issue. If a document has been stuck `failed` for an extended period and
its ingestion job is *not* the blocker, capture the `error_detail` and open an issue; do
not manually delete `chunk_manifests`/`document_versions`/`documents` rows by hand —
`delete_document_cascade` deletes them in FK-safe order for a reason.
