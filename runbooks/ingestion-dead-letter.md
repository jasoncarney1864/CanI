# Runbook: ingestion dead-letter jobs

Applies to `ingestion_jobs` rows with `status = 'failed'` (§8.10, §8.14).

## Triage

```sql
select ingestion_job_id, owner_user_id, error_code, error_detail, attempt_count, finished_at
from ingestion_jobs
where status = 'failed'
order by finished_at desc
limit 50;
```

- `PermanentJobFailure` (e.g. "no extractable text content") — not retryable as-is; the
  source document is likely blank, corrupted, or an unsupported scan quality. Confirm with
  the owner before any reprocessing.
- Anything else (transient extraction/embedding/Qdrant errors) — safe to requeue.

## Requeue a job

```sql
update ingestion_jobs
set status = 'retry_pending', attempt_count = 0, error_code = null, error_detail = null
where ingestion_job_id = '<id>';
```

ingestion-worker will pick it up on its next poll cycle (`SELECT ... FOR UPDATE SKIP
LOCKED`, `db/migrate.py`/`apps/ingestion-worker`). Reprocessing is idempotent for a given
`document_id` + artifact version (§8.10) — chunk manifests and vector points from the
prior attempt are not cleaned up automatically before a requeue; verify no duplicate
`chunk_manifests` rows accumulate if this becomes a frequent operation, and track
`cleanup of stale chunk rows on reprocess` as a backlog item (not implemented in this MVP
pass).

## Escalate

If failures cluster around one stage (extraction vs embedding vs indexing) across many
owners, check upstream dependency health first: Azure OpenAI / Document Intelligence
quota or outage, or Qdrant availability — not a per-job issue.
