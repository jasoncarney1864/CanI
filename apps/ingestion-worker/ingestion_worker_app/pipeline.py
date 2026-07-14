"""Ingestion pipeline stages per docs/08-rag-pipeline-design.md §8.2-8.10:
extract (native PDF text, OCR fallback) -> chunk -> embed -> index, with durable status
per stage and idempotent re-runs (re-processing a completed job with identical inputs
must be a no-op — enforced here by deleting-then-reinserting this version's chunk rows
rather than appending duplicates on retry).
"""

from __future__ import annotations

import uuid

from cani_shared.blob import BlobStore
from cani_shared.chunking import PageText, chunk_document
from cani_shared.db.repositories import (
    MAX_INGESTION_ATTEMPTS,
    get_document,
    get_document_version,
    insert_chunk_manifests,
    mark_document_status,
    update_document_version_extraction,
    update_ingestion_job_stage,
)
from cani_shared.logging import get_logger, hash_user_id
from cani_shared.models import ChunkManifest, IngestionJob, IngestionStage
from cani_shared.providers.embedder import Embedder
from cani_shared.providers.extractor import TextExtractor
from cani_shared.vector.qdrant_client import OwnerScopedQdrant
from psycopg import Connection

logger = get_logger(__name__)


class PermanentJobFailure(Exception):
    """Raised for errors that retrying will never fix (e.g. document row vanished)."""


def process_job(
    conn: Connection,
    job: IngestionJob,
    *,
    blob_store: BlobStore,
    extractor: TextExtractor,
    embedder: Embedder,
    qdrant: OwnerScopedQdrant,
) -> None:
    owner_user_id = job.owner_user_id
    document_version = get_document_version(conn, owner_user_id, job.document_version_id)
    if document_version is None:
        raise PermanentJobFailure(f"document_version {job.document_version_id} not found for owner")

    document = get_document(conn, owner_user_id, document_version.document_id)
    if document is None:
        raise PermanentJobFailure(f"document {document_version.document_id} not found for owner")

    log = logger.bind(
        user_id_hash=hash_user_id(owner_user_id),
        document_id=document.document_id,
        ingestion_job_id=job.ingestion_job_id,
    )

    # --- extract --------------------------------------------------------------------
    update_ingestion_job_stage(
        conn, owner_user_id, job.ingestion_job_id, stage=IngestionStage.EXTRACTING, status="processing"
    )
    raw_bytes = blob_store.download(document_version.blob_uri)
    extraction = extractor.extract(raw_bytes, document.source_type)
    update_document_version_extraction(
        conn,
        owner_user_id,
        document_version.document_version_id,
        extractor_version=extraction.method,
        page_count=len(extraction.pages),
    )
    log.info(
        "stage_completed", stage="extracting", page_count=len(extraction.pages), method=extraction.method
    )

    # --- chunk ------------------------------------------------------------------------
    update_ingestion_job_stage(
        conn, owner_user_id, job.ingestion_job_id, stage=IngestionStage.CHUNKING, status="processing"
    )
    pages = [PageText(page_number=p.page_number, text=p.text) for p in extraction.pages]
    chunks = chunk_document(pages)
    if not chunks:
        raise PermanentJobFailure("no extractable text content — document may be blank or unsupported")
    log.info("stage_completed", stage="chunking", chunk_count=len(chunks))

    # --- embed + index ------------------------------------------------------------------
    update_ingestion_job_stage(
        conn, owner_user_id, job.ingestion_job_id, stage=IngestionStage.EMBEDDING, status="processing"
    )
    vectors = embedder.embed_batch([c.text for c in chunks])

    manifests: list[ChunkManifest] = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk_id = str(uuid.uuid4())
        qdrant.upsert_chunk(
            owner_user_id=owner_user_id,
            vector=vector,
            point_id=chunk_id,
            payload={
                "document_id": document.document_id,
                "document_version_id": document_version.document_version_id,
                "chunk_id": chunk_id,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section_label": chunk.section_label,
                "chunk_text": chunk.text,
                "taxonomy_tags": [],
                "embedding_version": embedder.embedding_version,
            },
        )
        manifests.append(
            ChunkManifest(
                chunk_id=chunk_id,
                document_version_id=document_version.document_version_id,
                owner_user_id=owner_user_id,
                document_id=document.document_id,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                section_label=chunk.section_label,
                chunk_index=chunk.chunk_index,
                token_count=chunk.token_count,
                embedding_version=embedder.embedding_version,
                qdrant_point_id=chunk_id,
            )
        )

    insert_chunk_manifests(conn, owner_user_id, manifests)

    update_ingestion_job_stage(
        conn, owner_user_id, job.ingestion_job_id, stage=IngestionStage.INDEXED, status="indexed"
    )
    mark_document_status(conn, owner_user_id, document.document_id, IngestionStage.INDEXED)
    log.info("stage_completed", stage="indexed", chunk_count=len(manifests))


def handle_job_failure(conn: Connection, job: IngestionJob, error: Exception) -> None:
    permanent = isinstance(error, PermanentJobFailure)
    if permanent or job.attempt_count >= MAX_INGESTION_ATTEMPTS:
        update_ingestion_job_stage(
            conn,
            job.owner_user_id,
            job.ingestion_job_id,
            stage=IngestionStage.FAILED,
            status="failed",
            error_code=type(error).__name__,
            error_detail=str(error)[:2000],
        )
        logger.error(
            "job_dead_lettered",
            ingestion_job_id=job.ingestion_job_id,
            attempt_count=job.attempt_count,
            error=str(error),
        )
    else:
        update_ingestion_job_stage(
            conn,
            job.owner_user_id,
            job.ingestion_job_id,
            stage=job.stage,
            status="retry_pending",
            error_code=type(error).__name__,
            error_detail=str(error)[:2000],
        )
        logger.warning(
            "job_retry_scheduled",
            ingestion_job_id=job.ingestion_job_id,
            attempt_count=job.attempt_count,
            error=str(error),
        )
