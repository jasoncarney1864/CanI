"""CanI Docs retrieval service (docs/08 §8.8-8.9) — internal-only, called by docs-api.

Query-time flow: verify caller identity/entitlement -> mandatory owner-filtered vector
search -> lightweight score-based rerank -> grounded answer from top chunks only ->
citations scoped to the caller's own chunk IDs. Every step fails closed: the Qdrant
wrapper itself refuses to run without an owner filter (cani_shared.vector.qdrant_client),
so there is no code path here that can return another user's content even by mistake.
"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager

from cani_shared.auth.entitlements import CAN_ACCESS_DOCS, make_principal_dependency, require_entitlement
from cani_shared.auth.tokens import RequestPrincipal
from cani_shared.config import get_settings
from cani_shared.db.pool import get_pool
from cani_shared.db.repositories import get_document_title, record_query_audit
from cani_shared.logging import configure_logging, get_logger, hash_user_id
from cani_shared.middleware import TraceIdMiddleware
from cani_shared.models import Citation, DocumentChunk, DocumentText, RetrievalAnswer, Verdict
from cani_shared.providers.factory import build_chat_grounder, build_embedder
from cani_shared.telemetry import configure_telemetry, instrument_fastapi
from cani_shared.vector.qdrant_client import OwnerScopedQdrant
from fastapi import Depends, FastAPI
from pydantic import BaseModel

CANDIDATE_POOL_SIZE = 8
CONTEXT_TOP_K = 4  # bounded context/token budget per §8.8

configure_logging("retrieval-worker")
logger = get_logger(__name__)
settings = get_settings()
configure_telemetry("retrieval-worker", settings)

get_principal = make_principal_dependency(
    token_signing_secret=settings.cani_token_signing_secret,
    postgres_dsn=settings.postgres_dsn,  # enables the D2 per-request revocation check
)
require_docs_entitlement = require_entitlement(CAN_ACCESS_DOCS, get_principal)

embedder = build_embedder(settings)
grounder = build_chat_grounder(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging

    logger = logging.getLogger(__name__)

    logger.info("🔌 Connecting to PostgreSQL...")
    get_pool(settings.postgres_dsn)
    logger.info("✅ PostgreSQL connected")

    logger.info(f"🔌 Creating Qdrant client for: {settings.qdrant_url}")
    try:
        qdrant = OwnerScopedQdrant(settings.qdrant_url, settings.qdrant_collection, settings.qdrant_api_key)
        logger.info("✅ Qdrant client created (collection will be ensured on first use)")
        app.state.qdrant = qdrant
        app.state._qdrant_initialized = False  # Track initialization state
    except Exception as e:
        logger.error(f"❌ Failed to create Qdrant client: {type(e).__name__}: {str(e)}")
        raise

    logger.info("🚀 Retrieval worker startup complete!")
    yield


app = FastAPI(title="CanI Retrieval Worker", lifespan=lifespan)
app.add_middleware(TraceIdMiddleware)
instrument_fastapi(app)


def ensure_qdrant_ready():
    """Lazy-initialize Qdrant collection on first use to avoid blocking startup."""
    import logging

    logger = logging.getLogger(__name__)

    if not getattr(app.state, "_qdrant_initialized", False):
        logger.info(f"🔄 Ensuring Qdrant collection on first use: {settings.qdrant_collection}")
        try:
            app.state.qdrant.ensure_collection(embedder.vector_size)
            app.state._qdrant_initialized = True
            logger.info(f"✅ Qdrant collection ready: {settings.qdrant_collection}")
        except Exception as e:
            logger.error(f"❌ Failed to ensure Qdrant collection: {type(e).__name__}: {str(e)}")
            raise


class RetrieveRequest(BaseModel):
    question: str
    spoke: str = "General"


@app.post("/retrieve", response_model=RetrievalAnswer)
def retrieve(
    payload: RetrieveRequest,
    principal: RequestPrincipal = Depends(get_principal),
    _: RequestPrincipal = Depends(require_docs_entitlement),
) -> RetrievalAnswer:
    ensure_qdrant_ready()  # Lazy-initialize on first request
    qdrant: OwnerScopedQdrant = app.state.qdrant
    query_vector = embedder.embed_batch([payload.question])[0]

    # Owner filter is mandatory and enforced inside OwnerScopedQdrant.search — it raises
    # rather than silently searching unscoped, so there is no way to reach this line
    # having queried across owners.
    candidates = qdrant.search(
        owner_user_id=principal.user_id,
        query_vector=query_vector,
        limit=CANDIDATE_POOL_SIZE,
        spoke=payload.spoke,
    )

    # Lightweight rerank (§8.8, §8.15 open question): candidates already come back score
    # sorted from Qdrant; truncate to the bounded context window rather than running a
    # separate ML reranker for v1.
    top = sorted(candidates, key=lambda c: c.score, reverse=True)[:CONTEXT_TOP_K]

    context_chunks = [c.payload.get("chunk_text", "") for c in top]
    grounded = grounder.ground(question=payload.question, context_chunks=context_chunks)

    pool = get_pool(settings.postgres_dsn)
    citations: list[Citation] = []
    with pool.connection() as conn:
        for idx in grounded.used_chunk_indices:
            if idx >= len(top):
                continue
            chunk = top[idx]
            document_id = chunk.payload["document_id"]
            title = get_document_title(conn, principal.user_id, document_id) or "Untitled document"
            citations.append(
                Citation(
                    document_id=document_id,
                    document_title=title,
                    page_start=chunk.payload["page_start"],
                    page_end=chunk.payload["page_end"],
                    section_label=chunk.payload.get("section_label"),
                    chunk_id=chunk.payload["chunk_id"],
                    # Same owner-filtered chunk the grounder cited — safe to surface verbatim
                    # so the client can render and spotlight the source passage.
                    snippet=chunk.payload.get("chunk_text"),
                )
            )

        record_query_audit(
            conn,
            principal.user_id,
            question_hash=hashlib.sha256(payload.question.encode("utf-8")).hexdigest(),
            model_id=grounder.model_id,
            retrieved_chunk_ids=[c.payload["chunk_id"] for c in top],
            response_status="insufficient_evidence" if grounded.insufficient_evidence else "ok",
        )

    logger.info(
        "query_completed",
        user_id_hash=hash_user_id(principal.user_id),
        candidate_count=len(candidates),
        citation_count=len(citations),
        insufficient_evidence=grounded.insufficient_evidence,
    )

    verdict = Verdict.from_kind(grounded.verdict) if grounded.verdict else None

    # Add spoke-specific disclaimer
    answer_text = grounded.answer_text
    if payload.spoke == "Legal":
        answer_text = (
            "⚖️ Legal Disclaimer: This is not legal advice. Consult a qualified attorney for your specific situation.\n\n"
            + answer_text
        )

    return RetrievalAnswer(
        answer=answer_text,
        citations=citations,
        insufficient_evidence=grounded.insufficient_evidence,
        verdict=verdict,
    )


@app.get("/documents/{document_id}/chunks", response_model=DocumentText)
def document_chunks(
    document_id: str,
    principal: RequestPrincipal = Depends(get_principal),
    _: RequestPrincipal = Depends(require_docs_entitlement),
) -> DocumentText:
    """A document's source text as its ordered chunks, for the Document Viewer. Internal —
    called by docs-api. Owner-scoped: the Qdrant read filters on the caller's own id and
    re-verifies it, so it cannot assemble another owner's document even if asked."""
    qdrant: OwnerScopedQdrant = app.state.qdrant
    payloads = qdrant.chunks_for_document(owner_user_id=principal.user_id, document_id=document_id)

    pool = get_pool(settings.postgres_dsn)
    with pool.connection() as conn:
        title = get_document_title(conn, principal.user_id, document_id) or "Untitled document"

    chunks = [
        DocumentChunk(
            chunk_id=p["chunk_id"],
            text=p.get("chunk_text", ""),
            page_start=p["page_start"],
            page_end=p["page_end"],
            section_label=p.get("section_label"),
            chunk_index=p.get("chunk_index", 0),
        )
        for p in payloads
    ]
    logger.info(
        "document_chunks_served",
        user_id_hash=hash_user_id(principal.user_id),
        chunk_count=len(chunks),
    )
    return DocumentText(document_id=document_id, title=title, chunks=chunks)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
