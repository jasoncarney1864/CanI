"""ingestion_worker_app.deletion: the single-worker-invariant guard (docs/21 §1.7 step 1)
and handle_deletion_failure's retry/dead-letter split, mirroring test_pipeline_failure.py's
coverage of the ingestion side of the same worker.
"""

from __future__ import annotations

from unittest.mock import ANY, MagicMock

import pytest
from cani_shared.models import DeletionJob
from ingestion_worker_app import deletion
from ingestion_worker_app.deletion import RetryableDeletionError, handle_deletion_failure, process_deletion


def _job(attempt_count: int = 1) -> DeletionJob:
    return DeletionJob(
        deletion_job_id="del-1",
        document_id="doc-1",
        owner_user_id="owner-1",
        status="processing",
        attempt_count=attempt_count,
        created_at="2026-08-18T00:00:00Z",
    )


@pytest.fixture
def repo(monkeypatch):
    mocks = MagicMock()
    mocks.has_processing_ingestion_job.return_value = False
    mocks.delete_document_cascade.return_value = 3
    monkeypatch.setattr(deletion, "has_processing_ingestion_job", mocks.has_processing_ingestion_job)
    monkeypatch.setattr(deletion, "delete_document_cascade", mocks.delete_document_cascade)
    monkeypatch.setattr(deletion, "finish_deletion_job", mocks.finish_deletion_job)
    monkeypatch.setattr(deletion, "record_audit_event", mocks.record_audit_event)
    return mocks


def test_process_deletion_raises_retryable_when_ingestion_in_flight(repo):
    """The single-worker-invariant guard: never delete vectors/blobs while an ingestion
    job for the same document is still processing — see the long comment in deletion.py
    for why this is only race-free with one worker replica."""
    repo.has_processing_ingestion_job.return_value = True
    qdrant = MagicMock()
    blob_store = MagicMock()

    with pytest.raises(RetryableDeletionError):
        process_deletion(MagicMock(), _job(), blob_store=blob_store, qdrant=qdrant)

    qdrant.delete_document_points.assert_not_called()
    blob_store.delete_prefix.assert_not_called()


def test_process_deletion_happy_path_deletes_vectors_blobs_and_rows(repo):
    qdrant = MagicMock()
    blob_store = MagicMock()
    blob_store.delete_prefix.return_value = 1

    process_deletion(MagicMock(), _job(), blob_store=blob_store, qdrant=qdrant)

    qdrant.delete_document_points.assert_called_once_with(owner_user_id="owner-1", document_id="doc-1")
    assert blob_store.delete_prefix.call_count == 3  # raw-documents, extracted-text, ingestion-artifacts
    repo.delete_document_cascade.assert_called_once_with(ANY, "owner-1", "doc-1")
    repo.finish_deletion_job.assert_called_once()
    assert repo.finish_deletion_job.call_args.kwargs["status"] == "done"
    repo.record_audit_event.assert_called_once()
    assert repo.record_audit_event.call_args.kwargs["event_type"] == "document_deleted"
    assert repo.record_audit_event.call_args.kwargs["detail"]["chunks_deleted"] == 3
    assert repo.record_audit_event.call_args.kwargs["detail"]["blobs_deleted"] == 3


def test_retryable_failure_under_attempt_cap_requeues(repo):
    handle_deletion_failure(MagicMock(), _job(attempt_count=1), RetryableDeletionError("ingestion in flight"))

    repo.finish_deletion_job.assert_called_once()
    assert repo.finish_deletion_job.call_args.kwargs["status"] == "queued"
    repo.record_audit_event.assert_not_called()


def test_retryable_failure_at_attempt_cap_dead_letters(repo):
    handle_deletion_failure(
        MagicMock(),
        _job(attempt_count=deletion.MAX_DELETION_ATTEMPTS),
        RetryableDeletionError("ingestion in flight"),
    )

    assert repo.finish_deletion_job.call_args.kwargs["status"] == "failed"
    repo.record_audit_event.assert_called_once()
    assert repo.record_audit_event.call_args.kwargs["event_type"] == "document_delete_failed"


def test_non_retryable_failure_dead_letters_immediately(repo):
    handle_deletion_failure(MagicMock(), _job(attempt_count=1), RuntimeError("qdrant unreachable"))

    assert repo.finish_deletion_job.call_args.kwargs["status"] == "failed"
    repo.record_audit_event.assert_called_once()
    assert repo.record_audit_event.call_args.kwargs["event_type"] == "document_delete_failed"
