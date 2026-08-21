"""Async tombstone-cleanup pipeline (docs/09 §9.9, docs/21 §1.7). Runs in the same worker
process as the ingestion pipeline (worker.py drains both queues in one loop) — deliberately
not a separate deployable, for the same "the jobs table is the queue" rationale as
ingestion. Removes Qdrant points, blobs, and Postgres rows for a document already
tombstoned by docs-api's DELETE /documents/{id}.
"""

from __future__ import annotations

from cani_shared.blob import (
    EXTRACTED_TEXT_CONTAINER,
    INGESTION_ARTIFACTS_CONTAINER,
    RAW_DOCUMENTS_CONTAINER,
    BlobStore,
)
from cani_shared.db.repositories import (
    MAX_DELETION_ATTEMPTS,
    delete_document_cascade,
    finish_deletion_job,
    has_processing_ingestion_job,
    record_audit_event,
)
from cani_shared.logging import get_logger, hash_user_id
from cani_shared.models import DeletionJob
from cani_shared.vector.qdrant_client import OwnerScopedQdrant
from psycopg import Connection

logger = get_logger(__name__)

_ARTIFACT_CONTAINERS = (RAW_DOCUMENTS_CONTAINER, EXTRACTED_TEXT_CONTAINER, INGESTION_ARTIFACTS_CONTAINER)


class RetryableDeletionError(Exception):
    """Raised when the deletion job should go back to `queued` and be tried again later,
    rather than dead-lettering — currently only the in-flight-ingestion guard below."""


def process_deletion(
    conn: Connection, job: DeletionJob, *, blob_store: BlobStore, qdrant: OwnerScopedQdrant
) -> None:
    owner_user_id = job.owner_user_id
    document_id = job.document_id
    log = logger.bind(
        user_id_hash=hash_user_id(owner_user_id), document_id=document_id, deletion_job_id=job.deletion_job_id
    )

    # SINGLE-WORKER INVARIANT — do not remove this guard or weaken it without reading this
    # comment (docs/21 §1.7). This check-then-act ("no ingestion job is currently
    # processing for this document") is only race-free because exactly one worker process
    # drains both the ingestion and deletion queues in a single loop (worker.py): an
    # ingestion job cannot start for this document while we're in process_deletion, and
    # vice versa, because claim_next_ingestion_job and claim_next_deletion_job are never
    # called concurrently with each other for the same document. If this worker is ever
    # scaled to multiple replicas, this becomes a TOCTOU race: replica A can pass this
    # check while replica B concurrently claims an ingestion job for the same document, and
    # B's late chunk upserts land in Qdrant AFTER A's delete_document_points call below —
    # resurrecting orphan vectors for a document the user already deleted. The fix, when
    # multi-replica is needed: take a per-document advisory lock
    # (pg_advisory_xact_lock(hashtext(document_id::text))) in both process_job and
    # process_deletion before this check, so the two can never interleave.
    if has_processing_ingestion_job(conn, owner_user_id, document_id):
        raise RetryableDeletionError(
            f"document {document_id} has an ingestion job in flight; retrying after it completes"
        )

    qdrant.delete_document_points(owner_user_id=owner_user_id, document_id=document_id)
    log.info("stage_completed", stage="vectors_deleted")

    blobs_deleted = 0
    prefix = f"{owner_user_id}/{document_id}/"
    for container in _ARTIFACT_CONTAINERS:
        blobs_deleted += blob_store.delete_prefix(container=container, prefix=prefix)
    log.info("stage_completed", stage="blobs_deleted", blobs_deleted=blobs_deleted)

    chunks_deleted = delete_document_cascade(conn, owner_user_id, document_id)

    finish_deletion_job(conn, owner_user_id, job.deletion_job_id, status="done")
    record_audit_event(
        conn,
        event_type="document_deleted",
        actor_user_id=owner_user_id,
        detail={"document_id": document_id, "chunks_deleted": chunks_deleted, "blobs_deleted": blobs_deleted},
    )
    log.info("document_deleted", chunks_deleted=chunks_deleted, blobs_deleted=blobs_deleted)


def handle_deletion_failure(conn: Connection, job: DeletionJob, error: Exception) -> None:
    """Mirrors ingestion_worker_app.pipeline.handle_job_failure: a retryable failure under
    the attempt cap goes back to `queued`; anything else (or attempts exhausted) dead-letters
    with an audit event. The document stays tombstoned either way — a failed cleanup is an
    ops concern (see runbooks/deletion-dead-letter.md), not something the user sees."""
    retryable = isinstance(error, RetryableDeletionError)
    if retryable and job.attempt_count < MAX_DELETION_ATTEMPTS:
        finish_deletion_job(
            conn, job.owner_user_id, job.deletion_job_id, status="queued", error_detail=str(error)[:2000]
        )
        logger.warning(
            "deletion_retry_scheduled",
            deletion_job_id=job.deletion_job_id,
            attempt_count=job.attempt_count,
            error=str(error),
        )
        return

    finish_deletion_job(
        conn, job.owner_user_id, job.deletion_job_id, status="failed", error_detail=str(error)[:2000]
    )
    record_audit_event(
        conn,
        event_type="document_delete_failed",
        actor_user_id=job.owner_user_id,
        detail={
            "document_id": job.document_id,
            "deletion_job_id": job.deletion_job_id,
            "error": str(error)[:500],
        },
    )
    logger.error(
        "deletion_job_dead_lettered",
        deletion_job_id=job.deletion_job_id,
        attempt_count=job.attempt_count,
        error=str(error),
    )
