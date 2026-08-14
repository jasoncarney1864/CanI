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
from cani_shared.models import DocumentChunk, DocumentText, RetrievalAnswer, Verdict
from cani_shared.providers.factory import build_chat_grounder, build_embedder
from cani_shared.telemetry import configure_telemetry, instrument_fastapi
from cani_shared.vector.public_law_client import PublicLawQdrant
from cani_shared.vector.qdrant_client import OwnerScopedQdrant, ScoredChunk, retry_transient
from fastapi import Depends, FastAPI, Response
from pydantic import BaseModel

from retrieval_worker_app.assembly import (
    LAW_CONTEXT_TOP_K,
    USER_CONTEXT_TOP_K,
    build_citations,
    build_context_chunks,
    legal_disclaimer,
    parse_jurisdictions,
    suppress_verdict_if_law_cited,
    top_k,
)

CANDIDATE_POOL_SIZE = 8
LAW_CANDIDATE_POOL_SIZE = 8

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

    # Public-law corpus (docs/20 §20.9): empty collection name means the feature ships
    # dark — no PublicLawQdrant is constructed, and retrieve() never searches a second
    # corpus. No readiness tripwire (Q5, on hold): an empty/unreachable law collection
    # degrades retrieval to document-only rather than failing startup or the query.
    app.state.law_qdrant = None
    app.state._law_qdrant_initialized = False
    if settings.law_qdrant_collection:
        logger.info(f"🔌 Creating public-law Qdrant client for collection: {settings.law_qdrant_collection}")
        app.state.law_qdrant = PublicLawQdrant(
            settings.qdrant_url, settings.law_qdrant_collection, settings.qdrant_api_key
        )

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


def ensure_law_qdrant_ready():
    """Same lazy-init pattern as ensure_qdrant_ready(), for the public-law collection.
    No-op when the feature is off (app.state.law_qdrant is None)."""
    import logging

    logger = logging.getLogger(__name__)

    if app.state.law_qdrant is None:
        return
    if not getattr(app.state, "_law_qdrant_initialized", False):
        logger.info(
            f"🔄 Ensuring public-law Qdrant collection on first use: {settings.law_qdrant_collection}"
        )
        try:
            app.state.law_qdrant.ensure_collection(embedder.vector_size)
            app.state._law_qdrant_initialized = True
            logger.info(f"✅ Public-law Qdrant collection ready: {settings.law_qdrant_collection}")
        except Exception as e:
            logger.error(f"❌ Failed to ensure public-law Qdrant collection: {type(e).__name__}: {str(e)}")
            raise


class RetrieveRequest(BaseModel):
    question: str
    spoke: str = "General"
    # None -> defaults to (spoke == "Legal"). Explicit True/False overrides the default
    # (docs/20 §20.8) — the Phase 3 state picker will always pass jurisdictions explicitly,
    # but a bare spoke="Legal" request already gets dual-corpus retrieval today.
    include_public_law: bool | None = None
    jurisdictions: list[str] | None = None


@app.post("/retrieve", response_model=RetrievalAnswer)
def retrieve(
    payload: RetrieveRequest,
    principal: RequestPrincipal = Depends(get_principal),
    _: RequestPrincipal = Depends(require_docs_entitlement),
) -> RetrievalAnswer:
    qdrant: OwnerScopedQdrant = app.state.qdrant
    query_vector = embedder.embed_batch([payload.question])[0]

    # Owner filter is mandatory and enforced inside OwnerScopedQdrant.search — it raises
    # rather than silently searching unscoped, so there is no way to reach this line
    # having queried across owners.
    def _search_user():
        ensure_qdrant_ready()  # Lazy-initialize on first request
        return qdrant.search(
            owner_user_id=principal.user_id,
            query_vector=query_vector,
            limit=CANDIDATE_POOL_SIZE,
            spoke=payload.spoke,
        )

    # Retry wraps init + search together: on a transient failure the readiness flag is
    # still unset, so the retry re-runs the collection check too (2026-08-09 sitrep —
    # ingestion got this hardening in d7f716d; retrieval never did).
    candidates = retry_transient(_search_user)
    top_user = top_k(candidates, USER_CONTEXT_TOP_K)

    # Public-law corpus (docs/20 §20.8): searched only when in play for this request, and
    # only if the feature is configured at all (app.state.law_qdrant is None otherwise —
    # the collection name shipped empty, ships-dark default). A law-search failure degrades
    # to document-only rather than 500ing the query — the user's own document is the
    # primary corpus and its availability must not depend on the secondary one. Likewise an
    # empty law collection just returns no candidates; no readiness tripwire (Q5, on hold).
    include_law = (
        payload.include_public_law if payload.include_public_law is not None else payload.spoke == "Legal"
    )
    top_law: list[ScoredChunk] = []
    if include_law and app.state.law_qdrant is not None:
        jurisdictions = payload.jurisdictions or parse_jurisdictions(settings.law_default_jurisdictions)
        law_qdrant: PublicLawQdrant = app.state.law_qdrant

        def _search_law():
            ensure_law_qdrant_ready()
            return law_qdrant.search(
                query_vector=query_vector, jurisdictions=jurisdictions, limit=LAW_CANDIDATE_POOL_SIZE
            )

        try:
            law_candidates = retry_transient(_search_law)
            top_law = top_k(law_candidates, LAW_CONTEXT_TOP_K)
        except Exception as exc:  # noqa: BLE001 - any law-search fault degrades to document-only
            logger.warning("law_search_degraded", error=f"{type(exc).__name__}: {exc}")
            top_law = []

    pool = get_pool(settings.postgres_dsn)
    with pool.connection() as conn:
        titles = {
            document_id: get_document_title(conn, principal.user_id, document_id) or "Untitled document"
            for document_id in {c.payload["document_id"] for c in top_user}
        }

        context_chunks = build_context_chunks(top_user, top_law, titles)
        grounded = grounder.ground(question=payload.question, context_chunks=context_chunks)
        citations = build_citations(grounded.used_chunk_indices, top_user, top_law, titles)

        record_query_audit(
            conn,
            principal.user_id,
            question_hash=hashlib.sha256(payload.question.encode("utf-8")).hexdigest(),
            model_id=grounder.model_id,
            retrieved_chunk_ids=[c.payload["chunk_id"] for c in top_user],
            response_status="insufficient_evidence" if grounded.insufficient_evidence else "ok",
        )

    logger.info(
        "query_completed",
        user_id_hash=hash_user_id(principal.user_id),
        candidate_count=len(candidates),
        law_candidate_count=len(top_law),
        citation_count=len(citations),
        insufficient_evidence=grounded.insufficient_evidence,
    )

    verdict = Verdict.from_kind(grounded.verdict) if grounded.verdict else None
    # Q4 (decided, docs/20 §20.8/§20.12): suppress only the badge when any cited chunk is
    # law-sourced — the citation, quote, and plain-language answer still render in full.
    verdict = suppress_verdict_if_law_cited(verdict, citations)

    # Add spoke-specific disclaimer (extends when law citations are present, §20.8).
    answer_text = grounded.answer_text
    if payload.spoke == "Legal":
        answer_text = legal_disclaimer(citations) + "\n\n" + answer_text

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
    payloads = retry_transient(
        lambda: qdrant.chunks_for_document(owner_user_id=principal.user_id, document_id=document_id)
    )

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
    """Liveness only: is the process up. Deliberately does NOT touch Qdrant — a dead
    dependency should fail /readyz (stop routing traffic), not /healthz (restart the
    container, which cannot fix Qdrant and would just add a restart loop on top)."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz(response: Response) -> dict:
    """Readiness that exercises the dependency. During the 2026-08-09 outage /healthz
    returned 200 for ~2 days of total query failure because nothing on the health path
    touched Qdrant; the CD smoke check greenlit a deploy that could not answer a single
    query. This is the probe that would have caught it."""
    try:
        app.state.qdrant.ping()
    except Exception as exc:  # noqa: BLE001 - any failure here means "not ready"
        logger.warning("readyz_qdrant_unreachable", error=f"{type(exc).__name__}: {exc}")
        response.status_code = 503
        return {"status": "unready", "qdrant": "unreachable"}
    return {"status": "ready", "qdrant": "ok"}
