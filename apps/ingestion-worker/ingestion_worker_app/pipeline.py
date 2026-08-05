"""Ingestion pipeline stages per docs/08-rag-pipeline-design.md §8.2-8.10:
extract (native PDF text, OCR fallback) -> chunk -> embed -> index, with durable status
per stage and idempotent re-runs (re-processing a completed job with identical inputs
must be a no-op — enforced here by deleting-then-reinserting this version's chunk rows
rather than appending duplicates on retry).

Zip archives take a different path: scan -> unpack -> fan out. Each supported entry is
registered as its own document (blob + version + ingestion job), and those child jobs
then flow through the ordinary pipeline above — including their own malware scan. The
archive document itself ends in the terminal `unpacked` state; it is never chunked or
indexed. Fan-out is idempotent: on retry, entries that already exist (per-owner
checksum dedupe) are skipped instead of duplicated.
"""

from __future__ import annotations

import hashlib
import uuid

from cani_shared.archive import ZIP_CONTENT_TYPE, ArchiveValidationError, extract_archive
from cani_shared.blob import RAW_DOCUMENTS_CONTAINER, BlobStore
from cani_shared.chunking import PageText, chunk_document
from cani_shared.config import get_settings
from cani_shared.db.repositories import (
    MAX_INGESTION_ATTEMPTS,
    create_document,
    create_document_version,
    create_ingestion_job,
    get_document,
    get_document_by_checksum,
    get_document_version,
    insert_chunk_manifests,
    mark_document_status,
    update_document_title,
    update_document_version_extraction,
    update_ingestion_job_stage,
)
from cani_shared.logging import get_logger, hash_user_id
from cani_shared.models import ChunkManifest, IngestionJob, IngestionStage
from cani_shared.providers.embedder import Embedder
from cani_shared.providers.extractor import OcrUnavailableError, TextExtractor
from cani_shared.providers.scanner import MalwareScanner
from cani_shared.vector.qdrant_client import OwnerScopedQdrant
from psycopg import Connection

from ingestion_worker_app.title_gen import generate_title

logger = get_logger(__name__)


class PermanentJobFailure(Exception):
    """Raised for errors that retrying will never fix (e.g. document row vanished)."""


def process_job(
    conn: Connection,
    job: IngestionJob,
    *,
    blob_store: BlobStore,
    scanner: MalwareScanner,
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

    # §8.11: scan for malware BEFORE extraction. A positive result is a permanent
    # failure — the document never reaches the extractor, and we log the signature (never
    # the file bytes) with the owner hash + document id for traceability.
    scan = scanner.scan(raw_bytes)
    if not scan.is_clean:
        log.warning("malware_detected", signature=scan.signature, stage="scanning")
        raise PermanentJobFailure(f"malware scan blocked document (signature={scan.signature})")
    log.info("stage_completed", stage="scanning", result="clean")

    # Zip archives fan out into per-entry documents instead of being extracted/indexed
    # themselves. Child jobs re-enter this function as ordinary single-document jobs.
    if document.source_type == ZIP_CONTENT_TYPE:
        _unpack_archive_job(
            conn, job, raw_bytes, document_id=document.document_id, blob_store=blob_store, log=log
        )
        return

    try:
        extraction = extractor.extract(raw_bytes, document.source_type)
    except OcrUnavailableError as exc:
        # OCR credentials aren't configured — retrying can't fix that. Fail permanently
        # with the clear message rather than dead-lettering after five wasted attempts.
        raise PermanentJobFailure(str(exc)) from exc
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

    # --- generate title -------------------------------------------------------------------
    # Generate a human-readable title from extracted text (replaces the raw filename).
    # This runs after extraction so we have the document content, but before chunking so
    # we don't waste tokens if this document turns out to be blank. Title generation
    # failures are non-fatal — we fall back to "Untitled Document" rather than blocking
    # the entire ingestion job (the document is still searchable, just poorly named).
    settings = get_settings()
    if settings.azure_ai_providers_configured and settings.azure_openai_chat_deployment:
        full_text = "\n".join(p.text for p in extraction.pages)
        title = generate_title(
            full_text,
            endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            deployment=settings.azure_openai_chat_deployment,
        )
        update_document_title(conn, owner_user_id, document.document_id, title)
        log.info("title_generated", title=title)

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
                "chunk_index": chunk.chunk_index,  # document order, for the Document Viewer
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


def _unpack_archive_job(
    conn: Connection,
    job: IngestionJob,
    raw_bytes: bytes,
    *,
    document_id: str,
    blob_store: BlobStore,
    log,
) -> None:
    """Unpack a scanned zip archive and register each supported entry as its own
    document + version + ingestion job. Per-owner checksum dedupe makes retries
    idempotent — already-registered entries are counted, not duplicated."""
    owner_user_id = job.owner_user_id
    update_ingestion_job_stage(
        conn, owner_user_id, job.ingestion_job_id, stage=IngestionStage.UNPACKING, status="processing"
    )
    mark_document_status(conn, owner_user_id, document_id, IngestionStage.UNPACKING)

    try:
        entries, skipped = extract_archive(raw_bytes)
    except ArchiveValidationError as exc:
        raise PermanentJobFailure(str(exc)) from exc

    created = 0
    deduplicated = 0
    for entry in entries:
        checksum = hashlib.sha256(entry.data).hexdigest()
        if get_document_by_checksum(conn, owner_user_id, checksum) is not None:
            deduplicated += 1
            continue

        child = create_document(
            conn,
            owner_user_id,
            title=entry.filename,
            source_type=entry.content_type,
            checksum=checksum,
        )
        child_version_id = str(uuid.uuid4())
        blob_path = BlobStore.artifact_path(
            owner_user_id, child.document_id, child_version_id, f"original.{entry.extension}"
        )
        blob_uri = blob_store.upload(container=RAW_DOCUMENTS_CONTAINER, path=blob_path, data=entry.data)
        child_version = create_document_version(
            conn, owner_user_id, child.document_id, blob_uri=blob_uri, document_version_id=child_version_id
        )
        create_ingestion_job(conn, owner_user_id, child_version.document_version_id)
        created += 1

    if created == 0 and deduplicated == 0:
        reasons = "; ".join(f"{s.filename}: {s.reason}" for s in skipped[:10])
        raise PermanentJobFailure(f"archive contains no supported documents ({reasons})")

    update_ingestion_job_stage(
        conn, owner_user_id, job.ingestion_job_id, stage=IngestionStage.UNPACKED, status="unpacked"
    )
    mark_document_status(conn, owner_user_id, document_id, IngestionStage.UNPACKED)
    log.info(
        "stage_completed",
        stage="unpacked",
        entries_created=created,
        entries_deduplicated=deduplicated,
        entries_skipped=len(skipped),
        skip_reasons=[f"{s.filename}: {s.reason}" for s in skipped],
    )


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
        # The UI reads documents.current_status, which only the happy path updated —
        # without this, a dead-lettered document shows "Queued" forever.
        version = get_document_version(conn, job.owner_user_id, job.document_version_id)
        if version is not None:
            mark_document_status(conn, job.owner_user_id, version.document_id, IngestionStage.FAILED)
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
