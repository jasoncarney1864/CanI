"""Domain models shared across services. Mirrors the schema in docs/09-data-model-and-storage.md.

Every model that represents user-scoped data carries owner_user_id — there is no
"generic" document/chunk model without it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class IngestionStage(StrEnum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    FAILED = "failed"


class Document(BaseModel):
    document_id: str
    owner_user_id: str
    title: str
    source_type: str
    current_status: IngestionStage
    checksum: str
    created_at: datetime
    updated_at: datetime


class DocumentVersion(BaseModel):
    document_version_id: str
    document_id: str
    owner_user_id: str
    blob_uri: str
    extractor_version: str | None = None
    extracted_at: datetime | None = None
    page_count: int | None = None
    classification_label: str | None = None
    classification_confidence: float | None = None


class IngestionJob(BaseModel):
    ingestion_job_id: str
    document_version_id: str
    owner_user_id: str
    stage: IngestionStage
    status: str
    attempt_count: int
    error_code: str | None = None
    error_detail: str | None = None


class ChunkManifest(BaseModel):
    chunk_id: str
    document_version_id: str
    owner_user_id: str
    document_id: str
    page_start: int
    page_end: int
    section_label: str | None
    chunk_index: int
    token_count: int
    embedding_version: str
    qdrant_point_id: str


class Citation(BaseModel):
    document_id: str
    document_title: str
    page_start: int
    page_end: int
    section_label: str | None
    chunk_id: str


class RetrievalAnswer(BaseModel):
    answer: str
    citations: list[Citation]
    insufficient_evidence: bool = False
