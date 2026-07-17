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
from cani_shared.models import Citation, RetrievalAnswer
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
    get_pool(settings.postgres_dsn)
    qdrant = OwnerScopedQdrant(settings.qdrant_url, settings.qdrant_collection)
    qdrant.ensure_collection(embedder.vector_size)
    app.state.qdrant = qdrant
    yield


app = FastAPI(title="CanI Retrieval Worker", lifespan=lifespan)
app.add_middleware(TraceIdMiddleware)
instrument_fastapi(app)


class RetrieveRequest(BaseModel):
    question: str


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
    candidates = qdrant.search(
        owner_user_id=principal.user_id, query_vector=query_vector, limit=CANDIDATE_POOL_SIZE
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

    return RetrievalAnswer(
        answer=grounded.answer_text,
        citations=citations,
        insufficient_evidence=grounded.insufficient_evidence,
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
