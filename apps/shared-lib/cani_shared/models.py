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


class VerdictKind(StrEnum):
    YES = "yes"
    YES_WITH_CONDITIONS = "yes_with_conditions"
    NO = "no"
    INSUFFICIENT = "insufficient"


_VERDICT_LABELS = {
    VerdictKind.YES: "Yes",
    VerdictKind.YES_WITH_CONDITIONS: "Yes, with conditions",
    VerdictKind.NO: "No",
    VerdictKind.INSUFFICIENT: "Insufficient evidence",
}


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
    # Verbatim text of the cited chunk, so the client Document Viewer can render the
    # source passage and spotlight it (docs/13 §5 "Spotlight" layout). Optional: absent
    # when a chunk payload predates snippet capture. This can never contain another
    # owner's content — citations are built only from the caller's own owner-filtered
    # chunks (see retrieval-worker OwnerScopedQdrant enforcement).
    snippet: str | None = None


class Verdict(BaseModel):
    """Structured yes/no answer for permissibility questions, surfaced as the client's
    verdict badge (docs/13 §5). Absent for open-ended Q&A."""

    kind: VerdictKind
    label: str

    @classmethod
    def from_kind(cls, kind: VerdictKind | str) -> "Verdict":
        resolved = VerdictKind(kind)
        return cls(kind=resolved, label=_VERDICT_LABELS[resolved])


class RetrievalAnswer(BaseModel):
    answer: str
    citations: list[Citation]
    insufficient_evidence: bool = False
    verdict: Verdict | None = None
