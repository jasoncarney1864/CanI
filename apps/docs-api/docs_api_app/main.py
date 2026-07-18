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

import httpx
from cani_shared.auth.entitlements import CAN_ACCESS_DOCS, make_principal_dependency, require_entitlement
from cani_shared.auth.tokens import RequestPrincipal, create_access_token
from cani_shared.blob import RAW_DOCUMENTS_CONTAINER, BlobStore
from cani_shared.config import get_settings
from cani_shared.db.pool import get_pool
from cani_shared.db.repositories import (
    create_document,
    create_document_version,
    create_ingestion_job,
    get_document,
    get_document_by_checksum,
    list_documents,
)
from cani_shared.logging import configure_logging, get_logger, hash_user_id
from cani_shared.middleware import RateLimitMiddleware, TraceIdMiddleware
from cani_shared.models import Document, RetrievalAnswer
from cani_shared.telemetry import configure_telemetry, instrument_fastapi
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from docs_api_app.uploads import UploadValidationError, validate_upload

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


class QueryRequest(BaseModel):
    question: str


@app.post("/documents", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
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


@app.get("/documents", response_model=list[Document])
def list_my_documents(
    principal: RequestPrincipal = Depends(get_principal),
    _: RequestPrincipal = Depends(require_docs_entitlement),
) -> list[Document]:
    pool = get_pool(settings.postgres_dsn)
    with pool.connection() as conn:
        return list_documents(conn, principal.user_id)


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
            json={"question": payload.question},
            headers={"Authorization": f"Bearer {internal_token}"},
        )
    if response.status_code != 200:
        logger.error("retrieval_upstream_error", status_code=response.status_code)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "retrieval service error")
    return RetrievalAnswer.model_validate(response.json())


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
