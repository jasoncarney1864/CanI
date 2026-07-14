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


@dataclass
class ScoredChunk:
    point_id: str
    score: float
    payload: dict


class OwnerScopedQdrant:
    def __init__(self, url: str, collection: str):
        self._client = QdrantClient(url=url)
        self._collection = collection

    def ensure_collection(self, vector_size: int) -> None:
        """Every service (retrieval-worker, ingestion-worker) calls this at startup, so
        the check-then-create here is inherently racy across processes — Qdrant itself is
        the source of truth for "already exists", not our preceding GET, so a 409 from
        create_collection is treated as success rather than a fatal error."""
        existing = [c.name for c in self._client.get_collections().collections]
        if self._collection in existing:
            return
        try:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
            )
        except UnexpectedResponse as exc:
            if exc.status_code == 409:
                return
            raise

        for field_name in ("owner_user_id", "document_id", "taxonomy_tags"):
            try:
                self._client.create_payload_index(
                    collection_name=self._collection,
                    field_name=field_name,
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
            except UnexpectedResponse as exc:
                if exc.status_code != 409:
                    raise

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
    ) -> list[ScoredChunk]:
        if not owner_user_id:
            # Fail closed (§8.8, §9.6): never run a vector query without a mandatory owner filter.
            raise MissingOwnerFilterError("refusing to search without owner_user_id")

        must = [qmodels.FieldCondition(key="owner_user_id", match=qmodels.MatchValue(value=owner_user_id))]
        if taxonomy_tags:
            must.append(
                qmodels.FieldCondition(key="taxonomy_tags", match=qmodels.MatchAny(any=taxonomy_tags))
            )

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
