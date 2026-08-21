"""Domain models shared across services. Mirrors the schema in docs/09-data-model-and-storage.md.

Every model that represents user-scoped data carries owner_user_id — there is no
"generic" document/chunk model without it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class IngestionStage(StrEnum):
    QUEUED = "queued"
    UNPACKING = "unpacking"  # zip archive fan-out: entries become their own documents
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    UNPACKED = "unpacked"  # terminal state for an archive whose entries were fanned out
    FAILED = "failed"


class DocumentSpoke(StrEnum):
    GENERAL = "General"
    LEGAL = "Legal"
    HEALTH = "Health"
    FINANCE = "Finance"


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
    spoke: DocumentSpoke = DocumentSpoke.GENERAL
    origin: str = "uploaded"
    # Tombstone timestamp (docs/21 §1.4/§4). None everywhere except the one delete-flow
    # lookup that deliberately bypasses the `deleted_at IS NULL` filter every other query
    # applies — see get_document_for_delete.
    deleted_at: datetime | None = None
    # Provenance for origin="generated" documents (docs/21 §3.2); always None for uploads.
    # Deliberately excluded from GET /documents' list envelope via response_model_exclude
    # (docs/21 §3.2 "keeps pages lean") — present only on the single-document GET.
    generated_from: dict[str, Any] | None = None


class DocumentListResponse(BaseModel):
    """Envelope for GET /documents (docs/21 §1.2) — replaces the old bare array so the
    client can page without a separate count query."""

    items: list[Document]
    total: int
    limit: int
    offset: int


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
    # Added by migration 0006 for "latest version" ordering (docs/21 §2.2). Defaulted so
    # any DocumentVersion constructed in code before the column existed still validates.
    created_at: datetime | None = None


class IngestionJob(BaseModel):
    ingestion_job_id: str
    document_version_id: str
    owner_user_id: str
    stage: IngestionStage
    status: str
    attempt_count: int
    error_code: str | None = None
    error_detail: str | None = None


class DeletionJob(BaseModel):
    """Async tombstone-cleanup queue row (docs/09 §9.9, docs/21 §1.7). Mirrors the
    ingestion job queue's SKIP LOCKED claim pattern, but as a second, independent queue."""

    deletion_job_id: str
    document_id: str
    owner_user_id: str
    status: str
    attempt_count: int
    error_detail: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


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
    # Discriminator (docs/20-public-law-corpus-design.md §20.8). Defaults to
    # "user_document" so every payload built before this field existed still validates.
    source_kind: str = "user_document"
    # User-document fields. Optional (rather than the original hard-required) because a
    # law citation carries none of them — a statute has no owning document or page range.
    document_id: str | None = None
    document_title: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    section_label: str | None = None
    chunk_id: str
    # Verbatim text of the cited chunk, so the client Document Viewer can render the
    # source passage and spotlight it (docs/13 §5 "Spotlight" layout). Optional: absent
    # when a chunk payload predates snippet capture. This can never contain another
    # owner's content — citations are built only from the caller's own owner-filtered
    # chunks (see retrieval-worker OwnerScopedQdrant enforcement). For a law citation this
    # snippet IS the verbatim quoted statute text (§20.1 principle 1).
    snippet: str | None = None
    # Law-corpus fields (absent on user-document citations).
    citation_ref: str | None = None  # 'NRS 116.31065'
    source_url: str | None = None
    law_fetched_at: datetime | None = None  # honesty about currency: "text as of <date>"


class Verdict(BaseModel):
    """Structured yes/no answer for permissibility questions, surfaced as the client's
    verdict badge (docs/13 §5). Absent for open-ended Q&A."""

    kind: VerdictKind
    label: str

    @classmethod
    def from_kind(cls, kind: VerdictKind | str) -> Verdict:
        resolved = VerdictKind(kind)
        return cls(kind=resolved, label=_VERDICT_LABELS[resolved])


class RetrievalAnswer(BaseModel):
    answer: str
    citations: list[Citation]
    insufficient_evidence: bool = False
    verdict: Verdict | None = None


class DocumentChunk(BaseModel):
    """One indexed chunk of a document's source text, for the Document Viewer pane.
    `chunk_id` matches Citation.chunk_id, so the UI can spotlight the cited chunk in
    context (docs/13 §5)."""

    chunk_id: str
    text: str
    page_start: int
    page_end: int
    section_label: str | None
    chunk_index: int


class DocumentText(BaseModel):
    """A document's full source text as its ordered chunks (GET /documents/{id}/text).
    Owner-scoped end to end — only the owner's own chunks are ever assembled here."""

    document_id: str
    title: str
    chunks: list[DocumentChunk]


class LawSourceKind(StrEnum):
    STATE_STATUTE = "state_statute"
    COUNTY_CODE = "county_code"
    FEDERAL_STATUTE = "federal_statute"
    FEDERAL_REGULATION = "federal_regulation"


class LawSource(BaseModel):
    """Registry row for a fetchable public-law source (docs/20 §20.4). Deliberately not
    owner-scoped — this is a shared registry, not user data."""

    law_source_id: str
    source_key: str
    display_name: str
    source_kind: LawSourceKind
    jurisdiction: str
    citation_prefix: str
    fetch_url: str
    license_note: str
    enabled: bool
    last_checked_at: datetime | None = None
    created_at: datetime


class LawSourceVersion(BaseModel):
    """One successful fetch snapshot of a LawSource (docs/20 §20.4)."""

    law_source_version_id: str
    law_source_id: str
    fetched_at: datetime
    blob_uri: str
    checksum: str
    section_count: int | None = None
    status: str


class LawChunkManifest(BaseModel):
    """Law-corpus analogue of ChunkManifest (docs/20 §20.4) — the Postgres ledger of what is
    currently in the public-law Qdrant collection, keyed by citation rather than page range."""

    chunk_id: str
    law_source_version_id: str
    law_source_id: str
    citation: str
    heading: str | None = None
    source_url: str
    chunk_index: int
    token_count: int
    content_sha256: str
    embedding_version: str
    qdrant_point_id: str
