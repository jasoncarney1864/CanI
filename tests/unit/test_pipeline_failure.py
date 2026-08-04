"""handle_job_failure must surface terminal failures on the document itself.

The regression these guard against: a dead-lettered job updated only ingestion_jobs,
so documents.current_status stayed 'queued' and the UI showed a permanently-failed
document as "Queued" forever (Sprint 3 closeout-gate finding, 2026-08-04).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from cani_shared.models import DocumentVersion, IngestionJob, IngestionStage
from ingestion_worker_app import pipeline
from ingestion_worker_app.pipeline import PermanentJobFailure, handle_job_failure


def _job(attempt_count: int = 1) -> IngestionJob:
    return IngestionJob(
        ingestion_job_id="job-1",
        document_version_id="ver-1",
        owner_user_id="owner-1",
        stage=IngestionStage.CHUNKING,
        status="processing",
        attempt_count=attempt_count,
    )


def _version() -> DocumentVersion:
    return DocumentVersion(
        document_version_id="ver-1",
        document_id="doc-1",
        owner_user_id="owner-1",
        blob_uri="https://blob/raw/doc-1",
    )


@pytest.fixture
def repo(monkeypatch):
    mocks = MagicMock()
    mocks.get_document_version.return_value = _version()
    monkeypatch.setattr(pipeline, "update_ingestion_job_stage", mocks.update_ingestion_job_stage)
    monkeypatch.setattr(pipeline, "get_document_version", mocks.get_document_version)
    monkeypatch.setattr(pipeline, "mark_document_status", mocks.mark_document_status)
    return mocks


def test_permanent_failure_marks_document_failed(repo):
    handle_job_failure(MagicMock(), _job(), PermanentJobFailure("no extractable text content"))

    repo.update_ingestion_job_stage.assert_called_once()
    assert repo.update_ingestion_job_stage.call_args.kwargs["status"] == "failed"
    repo.mark_document_status.assert_called_once()
    assert repo.mark_document_status.call_args.args[1:] == ("owner-1", "doc-1", IngestionStage.FAILED)


def test_exhausted_retries_marks_document_failed(repo):
    handle_job_failure(
        MagicMock(), _job(attempt_count=pipeline.MAX_INGESTION_ATTEMPTS), RuntimeError("transient")
    )

    assert repo.update_ingestion_job_stage.call_args.kwargs["status"] == "failed"
    repo.mark_document_status.assert_called_once()
    assert repo.mark_document_status.call_args.args[3] == IngestionStage.FAILED


def test_retry_pending_leaves_document_status_alone(repo):
    handle_job_failure(MagicMock(), _job(attempt_count=1), RuntimeError("transient blip"))

    assert repo.update_ingestion_job_stage.call_args.kwargs["status"] == "retry_pending"
    repo.mark_document_status.assert_not_called()


def test_missing_document_version_dead_letters_without_marking(repo):
    """The 'document_version not found' permanent failure has no document to mark —
    the job must still dead-letter cleanly instead of raising."""
    repo.get_document_version.return_value = None

    handle_job_failure(MagicMock(), _job(), PermanentJobFailure("document_version ver-1 not found"))

    assert repo.update_ingestion_job_stage.call_args.kwargs["status"] == "failed"
    repo.mark_document_status.assert_not_called()
