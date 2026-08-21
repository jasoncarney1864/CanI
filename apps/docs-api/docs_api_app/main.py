"""CanI Docs API — upload gateway and query gateway (docs/08, docs/09).

This service is the only public-facing surface for CanI Docs. It validates the caller's
access token and entitlement on every request, then either handles the request directly
(upload/list) or delegates to retrieval-worker for the query path — re-minting a fresh
token so retrieval-worker performs its own independent entitlement check rather than
trusting network placement alone (§7.4: "Spokes must re-check entitlement and ownership
on every API call").
"""

from __future__ import annotations

import hashlib
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import quote

import httpx
from azure.core.exceptions import ResourceNotFoundError
from cani_shared.auth.entitlements import CAN_ACCESS_DOCS, make_principal_dependency, require_entitlement
from cani_shared.auth.tokens import RequestPrincipal, create_access_token
from cani_shared.blob import RAW_DOCUMENTS_CONTAINER, BlobStore
from cani_shared.config import get_settings
from cani_shared.db.pool import get_pool
from cani_shared.db.repositories import (
    cancel_pending_ingestion_jobs,
    create_deletion_job,
    create_document,
    create_document_version,
    create_ingestion_job,
    get_document,
    get_document_by_checksum,
    get_document_for_delete,
    get_latest_document_version,
    list_documents,
    record_audit_event,
    tombstone_document,
)
from cani_shared.logging import configure_logging, get_logger, hash_user_id
from cani_shared.middleware import RateLimitMiddleware, TraceIdMiddleware
from cani_shared.models import (
    Document,
    DocumentListResponse,
    DocumentSpoke,
    DocumentText,
    IngestionStage,
    RetrievalAnswer,
)
from cani_shared.telemetry import configure_telemetry, instrument_fastapi
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel

from docs_api_app.filenames import FALLBACK_FILENAME, sanitize_filename
from docs_api_app.generated_documents import (
    GeneratedDocumentValidationError,
    compose_generated_document,
    derive_title,
    validate_generated_document_request,
)
from docs_api_app.liveavatar import LiveAvatarError, create_session_token
from docs_api_app.uploads import UploadValidationError, validate_upload

GENERATED_SOURCE_TYPE = "text/markdown"

configure_logging("docs-api")
logger = get_logger(__name__)
settings = get_settings()
configure_telemetry("docs-api", settings)

get_principal = make_principal_dependency(
    token_signing_secret=settings.cani_token_signing_secret,
    postgres_dsn=settings.postgres_dsn,  # enables the D2 per-request revocation check
)
require_docs_entitlement = require_entitlement(CAN_ACCESS_DOCS, get_principal)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_pool(settings.postgres_dsn)
    blob_store = BlobStore(settings.azure_storage_connection_string)
    blob_store.ensure_containers()
    app.state.blob_store = blob_store
    yield


app = FastAPI(title="CanI Docs API", lifespan=lifespan)
app.add_middleware(TraceIdMiddleware)
instrument_fastapi(app)
# Added last -> outermost -> runs first, so a flood of upload/query requests is throttled
# before any downstream work or telemetry spend (§14.8).
if settings.rate_limit_enabled:
    app.add_middleware(
        RateLimitMiddleware,
        capacity=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )


class UploadResponse(BaseModel):
    document_id: str
    document_version_id: str
    status: str


class DeleteResponse(BaseModel):
    document_id: str
    status: str


class AvatarSessionTokenResponse(BaseModel):
    session_token: str


class QueryRequest(BaseModel):
    question: str
    spoke: str = "General"
    # Pass-through to retrieval-worker's RetrieveRequest (docs/20 §20.8). The Phase 3
    # state picker will populate jurisdictions from the browser; until then None on both
    # lets retrieval-worker apply its own spoke-based / config-based defaults.
    include_public_law: bool | None = None
    jurisdictions: list[str] | None = None


class ProvenanceCitation(BaseModel):
    chunk_id: str
    document_id: str | None = None
    document_title: str | None = None
    citation_ref: str | None = None  # law citations, e.g. "NRS 116.31065"


class Provenance(BaseModel):
    question: str
    model_id: str | None = None
    citations: list[ProvenanceCitation] = []


class GeneratedDocumentRequest(BaseModel):
    title: str | None = None
    spoke: str = "General"
    markdown: str
    provenance: Provenance


@app.post("/documents", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    spoke: str = Form("General"),
    principal: RequestPrincipal = Depends(get_principal),
    _: RequestPrincipal = Depends(require_docs_entitlement),
) -> UploadResponse:
    raw = await file.read()
    try:
        validated = validate_upload(
            content_type=file.content_type or "",
            size_bytes=len(raw),
            head_bytes=raw[:16],
        )
    except UploadValidationError as exc:
        logger.warning("upload_rejected", reason=str(exc), user_id_hash=hash_user_id(principal.user_id))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    # Validate spoke
    try:
        spoke_enum = DocumentSpoke(spoke)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid spoke: {spoke}") from e

    checksum = hashlib.sha256(raw).hexdigest()
    pool = get_pool(settings.postgres_dsn)

    with pool.connection() as conn:
        existing = get_document_by_checksum(conn, principal.user_id, checksum)
        if existing is not None:
            logger.info("upload_deduplicated", document_id=existing.document_id)
            return UploadResponse(
                document_id=existing.document_id, document_version_id="", status=existing.current_status
            )

        document = create_document(
            conn,
            principal.user_id,
            title=file.filename or "untitled",
            source_type=validated.content_type,
            checksum=checksum,
            spoke=spoke_enum,
        )

        blob_store: BlobStore = app.state.blob_store
        artifact_name = f"original.{validated.extension}"
        document_version_id = str(uuid.uuid4())
        blob_path = BlobStore.artifact_path(
            principal.user_id, document.document_id, document_version_id, artifact_name
        )
        blob_uri = blob_store.upload(container=RAW_DOCUMENTS_CONTAINER, path=blob_path, data=raw)

        document_version = create_document_version(
            conn,
            principal.user_id,
            document.document_id,
            blob_uri=blob_uri,
            document_version_id=document_version_id,
        )
        create_ingestion_job(conn, principal.user_id, document_version.document_version_id)

    logger.info(
        "document_uploaded",
        document_id=document.document_id,
        user_id_hash=hash_user_id(principal.user_id),
    )
    return UploadResponse(
        document_id=document.document_id,
        document_version_id=document_version.document_version_id,
        status="queued",
    )


@app.post("/documents/generated", response_model=UploadResponse)
def create_generated_document(
    payload: GeneratedDocumentRequest,
    principal: RequestPrincipal = Depends(get_principal),
    _: RequestPrincipal = Depends(require_docs_entitlement),
) -> UploadResponse:
    """Persist the current grounded answer as a first-class document (docs/21 §3). Mirrors
    upload_document deliberately: same per-owner checksum dedupe, same create_document ->
    create_document_version -> create_ingestion_job sequence, so a generated document
    flows through the ordinary ingestion pipeline exactly like an upload — chunked,
    embedded, indexed, and downloadable, with origin='generated' marking where it came
    from."""
    spoke_is_valid = payload.spoke in set(DocumentSpoke)
    try:
        validate_generated_document_request(
            title=payload.title,
            spoke_is_valid=spoke_is_valid,
            spoke=payload.spoke,
            markdown=payload.markdown,
            question=payload.provenance.question,
            citation_count=len(payload.provenance.citations),
        )
    except GeneratedDocumentValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    spoke_enum = DocumentSpoke(payload.spoke)

    title = derive_title(title=payload.title, question=payload.provenance.question)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    front_matter = compose_generated_document(
        title=title,
        generated_at=generated_at,
        question=payload.provenance.question,
        model_id=payload.provenance.model_id,
        citations=[
            {"chunk_id": c.chunk_id, "citation_ref": c.citation_ref} for c in payload.provenance.citations
        ],
    )
    # Blank line between front matter and body (docs/21 §3.3 step 2) — matches the
    # extractor's front-matter-stripping regex, which consumes the closing fence's own
    # newline and leaves this one as the first character of the extracted body.
    raw = (front_matter + "\n" + payload.markdown).encode("utf-8")
    checksum = hashlib.sha256(raw).hexdigest()

    pool = get_pool(settings.postgres_dsn)
    with pool.connection() as conn:
        existing = get_document_by_checksum(conn, principal.user_id, checksum)
        if existing is not None:
            logger.info("generated_document_deduplicated", document_id=existing.document_id)
            return UploadResponse(
                document_id=existing.document_id, document_version_id="", status=existing.current_status
            )

        document = create_document(
            conn,
            principal.user_id,
            title=title,
            source_type=GENERATED_SOURCE_TYPE,
            checksum=checksum,
            spoke=spoke_enum,
            origin="generated",
            generated_from=payload.provenance.model_dump(),
        )

        blob_store: BlobStore = app.state.blob_store
        document_version_id = str(uuid.uuid4())
        blob_path = BlobStore.artifact_path(
            principal.user_id, document.document_id, document_version_id, "original.md"
        )
        blob_uri = blob_store.upload(container=RAW_DOCUMENTS_CONTAINER, path=blob_path, data=raw)

        document_version = create_document_version(
            conn,
            principal.user_id,
            document.document_id,
            blob_uri=blob_uri,
            document_version_id=document_version_id,
        )
        create_ingestion_job(conn, principal.user_id, document_version.document_version_id)
        record_audit_event(
            conn,
            event_type="document_generated",
            actor_user_id=principal.user_id,
            detail={"document_id": document.document_id},
        )

    logger.info(
        "document_generated",
        document_id=document.document_id,
        user_id_hash=hash_user_id(principal.user_id),
    )
    return UploadResponse(
        document_id=document.document_id,
        document_version_id=document_version.document_version_id,
        status="queued",
    )


@app.get(
    "/documents",
    response_model=DocumentListResponse,
    # docs/21 §3.2: generated_from carries the full provenance blob (question, citations)
    # and is only useful on a single-document view — excluded from the list envelope to
    # keep the common "load the page" response lean.
    response_model_exclude={"items": {"__all__": {"generated_from"}}},
)
def list_my_documents(
    spoke: str | None = None,
    # Aliased so the local name doesn't shadow the fastapi `status` module used below.
    status_param: str | None = Query(
        default=None, alias="status", description="comma-separated IngestionStage values"
    ),
    origin: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    sort: str = "created_at",
    order: str = "desc",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: RequestPrincipal = Depends(get_principal),
    _: RequestPrincipal = Depends(require_docs_entitlement),
) -> DocumentListResponse:
    if spoke is not None:
        try:
            DocumentSpoke(spoke)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid spoke: {spoke}") from exc

    statuses: list[str] | None = None
    if status_param:
        statuses = [s.strip() for s in status_param.split(",") if s.strip()]
        for stage in statuses:
            try:
                IngestionStage(stage)
            except ValueError as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid status: {stage}") from exc

    if origin is not None and origin not in ("uploaded", "generated"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid origin: {origin}")

    pool = get_pool(settings.postgres_dsn)
    with pool.connection() as conn:
        try:
            items, total = list_documents(
                conn,
                principal.user_id,
                spoke=spoke,
                statuses=statuses,
                origin=origin,
                title_query=q,
                sort=sort,
                order=order,
                limit=limit,
                offset=offset,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    logger.info(
        "list_my_documents",
        user_id_hash=hash_user_id(principal.user_id),
        total=total,
        returned=len(items),
    )
    return DocumentListResponse(items=items, total=total, limit=limit, offset=offset)


@app.get("/documents/{document_id}", response_model=Document)
def get_my_document(
    document_id: str,
    principal: RequestPrincipal = Depends(get_principal),
    _: RequestPrincipal = Depends(require_docs_entitlement),
) -> Document:
    pool = get_pool(settings.postgres_dsn)
    with pool.connection() as conn:
        document = get_document(conn, principal.user_id, document_id)
    if document is None:
        # Same response whether the doc belongs to someone else or doesn't exist at all —
        # never leak cross-owner existence via a differentiated error (§9.8).
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return document


@app.delete("/documents/{document_id}", response_model=DeleteResponse, status_code=status.HTTP_202_ACCEPTED)
def delete_my_document(
    document_id: str,
    principal: RequestPrincipal = Depends(get_principal),
    _: RequestPrincipal = Depends(require_docs_entitlement),
) -> DeleteResponse:
    """Tombstone + enqueue async cleanup (docs/09 §9.9, docs/21 §1.4). The response is 202
    because the document only *looks* gone immediately (deleted_at excludes it from every
    other query); vectors, blobs, and the row itself are removed by the deletion worker."""
    pool = get_pool(settings.postgres_dsn)
    with pool.connection() as conn:
        document = get_document_for_delete(conn, principal.user_id, document_id)
        if document is None:
            # Not owned, never existed, or the deletion worker already finished cleaning
            # it up — same 404 either way, no cross-owner existence leak (§9.8).
            raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
        if document.deleted_at is not None:
            # Already tombstoned, cleanup pending — idempotent, don't enqueue a second job.
            return DeleteResponse(document_id=document_id, status="delete_pending")

        tombstone_document(conn, principal.user_id, document_id)
        cancel_pending_ingestion_jobs(conn, principal.user_id, document_id)
        create_deletion_job(conn, principal.user_id, document_id)
        record_audit_event(
            conn,
            event_type="document_delete_requested",
            actor_user_id=principal.user_id,
            detail={"document_id": document_id},
        )

    logger.info(
        "document_delete_requested",
        document_id=document_id,
        user_id_hash=hash_user_id(principal.user_id),
    )
    return DeleteResponse(document_id=document_id, status="delete_pending")


@app.post("/query", response_model=RetrievalAnswer)
async def query(
    payload: QueryRequest,
    principal: RequestPrincipal = Depends(get_principal),
    _: RequestPrincipal = Depends(require_docs_entitlement),
) -> RetrievalAnswer:
    internal_token = create_access_token(
        user_id=principal.user_id,
        entitlements=principal.entitlements,
        secret=settings.cani_token_signing_secret,
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.retrieval_worker_url}/retrieve",
            json={
                "question": payload.question,
                "spoke": payload.spoke,
                "include_public_law": payload.include_public_law,
                "jurisdictions": payload.jurisdictions,
            },
            headers={"Authorization": f"Bearer {internal_token}"},
        )
    if response.status_code != 200:
        logger.error("retrieval_upstream_error", status_code=response.status_code)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "retrieval service error")
    return RetrievalAnswer.model_validate(response.json())


@app.get("/documents/{document_id}/text", response_model=DocumentText)
async def get_document_text(
    document_id: str,
    principal: RequestPrincipal = Depends(get_principal),
    _: RequestPrincipal = Depends(require_docs_entitlement),
) -> DocumentText:
    """The document's source text (ordered chunks) for the Document Viewer. Confirms the
    caller owns the document here (404 otherwise, no cross-owner existence leak, §9.8),
    then proxies to the retrieval-worker — the only tier with Qdrant network access — the
    same way /query proxies to /retrieve."""
    pool = get_pool(settings.postgres_dsn)
    with pool.connection() as conn:
        if get_document(conn, principal.user_id, document_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")

    internal_token = create_access_token(
        user_id=principal.user_id,
        entitlements=principal.entitlements,
        secret=settings.cani_token_signing_secret,
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{settings.retrieval_worker_url}/documents/{document_id}/chunks",
            headers={"Authorization": f"Bearer {internal_token}"},
        )
    if response.status_code != 200:
        logger.error("document_text_upstream_error", status_code=response.status_code)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "retrieval service error")
    return DocumentText.model_validate(response.json())


@app.get("/documents/{document_id}/original")
def get_document_original(
    document_id: str,
    principal: RequestPrincipal = Depends(get_principal),
    _: RequestPrincipal = Depends(require_docs_entitlement),
) -> Response:
    """Download the document's original bytes exactly as uploaded (docs/21 §2.2). Same
    ownership/tombstone check as every other document route (get_document already filters
    deleted_at); a missing blob (out-of-band deletion, or a stale blob_uri) is a clean 404,
    not a 500 — BlobStore.download re-raises ResourceNotFoundError immediately instead of
    retrying it three times before giving up."""
    pool = get_pool(settings.postgres_dsn)
    with pool.connection() as conn:
        document = get_document(conn, principal.user_id, document_id)
        if document is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
        version = get_latest_document_version(conn, principal.user_id, document_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")

    blob_store: BlobStore = app.state.blob_store
    try:
        raw = blob_store.download(version.blob_uri)
    except ResourceNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "original file is no longer available") from exc

    # blob_uri is "{container}/{owner}/{document_id}/{version_id}/original.{ext}" —
    # the extension always comes from the stored artifact name, not from source_type,
    # so it matches what was actually written to blob storage.
    ext = PurePosixPath(version.blob_uri).suffix.lstrip(".") or "bin"
    stem = sanitize_filename(document.title)
    filename = f"{stem}.{ext}"
    # RFC 6266/5987: filename= is the ASCII fallback for older clients, filename*= carries
    # the real (possibly non-ASCII) name percent-encoded. Both point at the same file.
    ascii_stem = stem.encode("ascii", "ignore").decode("ascii").strip() or FALLBACK_FILENAME
    ascii_filename = f"{ascii_stem}.{ext}"
    disposition = f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quote(filename)}"

    logger.info(
        "document_original_downloaded",
        document_id=document_id,
        user_id_hash=hash_user_id(principal.user_id),
    )
    return Response(
        content=raw,
        media_type=document.source_type,
        headers={"Content-Disposition": disposition},
    )


@app.post("/avatar/session-token", response_model=AvatarSessionTokenResponse)
async def create_avatar_session_token(
    principal: RequestPrincipal = Depends(get_principal),
    _: RequestPrincipal = Depends(require_docs_entitlement),
) -> AvatarSessionTokenResponse:
    """Mints a short-lived LiveAvatar (HeyGen) session token server-side so
    LIVEAVATAR_API_KEY never reaches the browser. The frontend uses the returned token to
    open the WebRTC avatar session directly with LiveAvatar — that embed wiring doesn't
    exist yet, this endpoint only covers the token exchange."""
    if not settings.liveavatar_configured:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "avatar voicing is not configured on this deployment"
        )
    try:
        token = await create_session_token(
            api_key=settings.liveavatar_api_key, avatar_id=settings.liveavatar_avatar_id
        )
    except LiveAvatarError as exc:
        logger.error(
            "liveavatar_session_token_failed", error=str(exc), user_id_hash=hash_user_id(principal.user_id)
        )
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "avatar service error") from exc
    return AvatarSessionTokenResponse(session_token=token)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
