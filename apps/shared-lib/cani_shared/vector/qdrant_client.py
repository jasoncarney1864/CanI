"""Owner-filtered Qdrant access. Per docs/08-rag-pipeline-design.md §8.8 and
docs/09-data-model-and-storage.md §9.6: "Retrieval path fails closed if owner filter is
missing." This wrapper makes that structurally true — there is no search method that
accepts an empty/missing owner_user_id; it raises before issuing the query.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse


class MissingOwnerFilterError(Exception):
    """Raised instead of ever issuing an unscoped vector query."""


class VectorDimensionMismatchError(Exception):
    """Raised when an existing collection's dimensionality does not match the embedder.

    This is fatal on purpose. Silently reusing a collection built by a different embedder
    turns every upsert into a per-document runtime failure far away from the real cause,
    and — worse — leaves any already-indexed vectors semantically meaningless while the
    system still reports success.
    """


@dataclass
class ScoredChunk:
    point_id: str
    score: float
    payload: dict


class OwnerScopedQdrant:
    def __init__(self, url: str, collection: str, api_key: str | None = None):
        self._client = QdrantClient(url=url, api_key=api_key or None, timeout=60.0)
        self._collection = collection

    def ensure_collection(self, vector_size: int) -> None:
        """Every service (retrieval-worker, ingestion-worker) calls this at startup, so
        the check-then-create here is inherently racy across processes — Qdrant itself is
        the source of truth for "already exists", not our preceding GET, so a 409 from
        create_collection is treated as success rather than a fatal error."""
        existing = [c.name for c in self._client.get_collections().collections]
        if self._collection in existing:
            self._assert_vector_size(vector_size)
            return
        try:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
            )
        except UnexpectedResponse as exc:
            if exc.status_code == 409:
                self._assert_vector_size(vector_size)
                return
            raise

        for field_name in ("owner_user_id", "document_id", "taxonomy_tags", "spoke"):
            try:
                self._client.create_payload_index(
                    collection_name=self._collection,
                    field_name=field_name,
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
            except UnexpectedResponse as exc:
                if exc.status_code != 409:
                    raise

    def _assert_vector_size(self, expected: int) -> None:
        """Fail loudly when an existing collection was built for a different embedder.

        Switching embedders (e.g. the fake fallback -> Azure OpenAI) changes the vector
        width. Without this check the mismatch only surfaces later as a per-upsert
        "Wrong input: Vector dimension error" inside the ingestion worker's retry loop,
        which reads like a transient fault rather than a configuration error.
        """
        params = self._client.get_collection(self._collection).config.params.vectors
        actual = params.size if isinstance(params, qmodels.VectorParams) else None
        if actual is not None and actual != expected:
            raise VectorDimensionMismatchError(
                f"collection {self._collection!r} has vector size {actual} but the configured "
                f"embedder produces {expected}. Point QDRANT_COLLECTION at a new collection "
                f"or delete the existing one; reusing it would corrupt retrieval."
            )

    def upsert_chunk(
        self, *, owner_user_id: str, vector: list[float], payload: dict, point_id: str | None = None
    ) -> str:
        if not owner_user_id:
            raise MissingOwnerFilterError("refusing to index a vector without owner_user_id")
        point_id = point_id or str(uuid.uuid4())
        full_payload = {"owner_user_id": owner_user_id, **payload}
        self._client.upsert(
            collection_name=self._collection,
            points=[qmodels.PointStruct(id=point_id, vector=vector, payload=full_payload)],
        )
        return point_id

    def search(
        self,
        *,
        owner_user_id: str,
        query_vector: list[float],
        limit: int = 8,
        taxonomy_tags: list[str] | None = None,
        spoke: str | None = None,
    ) -> list[ScoredChunk]:
        if not owner_user_id:
            # Fail closed (§8.8, §9.6): never run a vector query without a mandatory owner filter.
            raise MissingOwnerFilterError("refusing to search without owner_user_id")

        must = [qmodels.FieldCondition(key="owner_user_id", match=qmodels.MatchValue(value=owner_user_id))]
        if taxonomy_tags:
            must.append(
                qmodels.FieldCondition(key="taxonomy_tags", match=qmodels.MatchAny(any=taxonomy_tags))
            )
        if spoke:
            must.append(qmodels.FieldCondition(key="spoke", match=qmodels.MatchValue(value=spoke)))

        # `search()` (not the newer `query_points()` Query API) — pinned qdrant-client
        # 1.9.x to match the qdrant/qdrant:v1.9.7 server image, and query_points() isn't
        # available until client 1.10+.
        results = self._client.search(
            collection_name=self._collection,
            query_vector=query_vector,
            query_filter=qmodels.Filter(must=must),
            limit=limit,
        )

        # Defense in depth: even though the server-side filter should guarantee this,
        # never trust a single control point for tenant isolation — verify the payload
        # on every returned point before it leaves this wrapper.
        verified = [r for r in results if r.payload and r.payload.get("owner_user_id") == owner_user_id]
        return [ScoredChunk(point_id=str(r.id), score=r.score, payload=r.payload or {}) for r in verified]

    def chunks_for_document(self, *, owner_user_id: str, document_id: str) -> list[dict]:
        """All of one document's chunk payloads, owner-scoped, for the Document Viewer.
        Uses scroll (not vector search) — this is a metadata read, not a similarity query —
        but keeps the same mandatory-owner-filter + re-verify discipline as search()."""
        if not owner_user_id:
            raise MissingOwnerFilterError("refusing to read chunks without owner_user_id")
        if not document_id:
            raise MissingOwnerFilterError("refusing to read chunks without a document_id")

        scroll_filter = qmodels.Filter(
            must=[
                qmodels.FieldCondition(key="owner_user_id", match=qmodels.MatchValue(value=owner_user_id)),
                qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=document_id)),
            ]
        )
        payloads: list[dict] = []
        offset = None
        while True:
            points, offset = self._client.scroll(
                collection_name=self._collection,
                scroll_filter=scroll_filter,
                with_payload=True,
                with_vectors=False,
                limit=256,
                offset=offset,
            )
            # Re-verify owner on every point before it leaves the wrapper (as in search()).
            payloads.extend(
                p.payload for p in points if p.payload and p.payload.get("owner_user_id") == owner_user_id
            )
            if offset is None:
                break
        # chunk_index gives document order; fall back to page_start for chunks indexed
        # before chunk_index was added to the payload.
        payloads.sort(key=lambda p: p.get("chunk_index", p.get("page_start", 0)))
        return payloads
