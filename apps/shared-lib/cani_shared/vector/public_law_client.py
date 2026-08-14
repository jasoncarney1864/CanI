"""Read/write access to the shared public-law collection (docs/20-public-law-corpus-design.md
§20.3). Sibling to qdrant_client.py rather than a class inside it, per that doc section.

No owner filter — the corpus is public by definition — but search REQUIRES a non-empty
jurisdiction filter, enforced the same fail-closed way OwnerScopedQdrant enforces owner:
there is no method that searches the whole corpus unscoped.
"""

from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from cani_shared.vector.qdrant_client import ScoredChunk, VectorDimensionMismatchError


class MissingJurisdictionFilterError(Exception):
    """Raised instead of ever issuing an unscoped public-law search."""


class PublicLawQdrant:
    def __init__(self, url: str, collection: str, api_key: str | None = None):
        self._client = QdrantClient(url=url, api_key=api_key or None, timeout=60.0)
        self._collection = collection

    def ensure_collection(self, vector_size: int) -> None:
        """Same 409-tolerant check-then-create + dimension-assert pattern as
        OwnerScopedQdrant.ensure_collection — this is the tripwire that catches the
        fakes-in-prod incident class (CLAUDE.md), and the law collection needs it for the
        same reason: it shares the embedder with the user collection."""
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

        for field_name in ("jurisdiction", "source_kind", "law_source_id"):
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
        params = self._client.get_collection(self._collection).config.params.vectors
        actual = params.size if isinstance(params, qmodels.VectorParams) else None
        if actual is not None and actual != expected:
            raise VectorDimensionMismatchError(
                f"collection {self._collection!r} has vector size {actual} but the configured "
                f"embedder produces {expected}. Point CANI_LAW_QDRANT_COLLECTION at a new "
                f"collection or delete the existing one; reusing it would corrupt retrieval."
            )

    def upsert_section(self, *, vector: list[float], payload: dict, point_id: str) -> str:
        """point_id is mandatory (unlike OwnerScopedQdrant.upsert_chunk, which mints a fresh
        uuid4 by default): the refresh job always passes a deterministic uuid5 derived from
        (source_key, citation, part) so re-upserts of an unchanged section replace the same
        point in place instead of accumulating duplicates (§20.7)."""
        self._client.upsert(
            collection_name=self._collection,
            points=[qmodels.PointStruct(id=point_id, vector=vector, payload=payload)],
        )
        return point_id

    def delete_points(self, point_ids: list[str]) -> None:
        """For repealed/removed sections (§20.7 step 5) — a citation present in the previous
        manifest but absent from the latest fetch is gone from the law, not just unchanged."""
        if not point_ids:
            return
        self._client.delete(
            collection_name=self._collection,
            points_selector=qmodels.PointIdsList(points=point_ids),
        )

    def search(
        self, *, query_vector: list[float], jurisdictions: list[str], limit: int = 8
    ) -> list[ScoredChunk]:
        if not jurisdictions:
            # Fail closed, mirroring OwnerScopedQdrant.search: never run a vector query
            # without a mandatory jurisdiction filter — there is no "search everything".
            raise MissingJurisdictionFilterError(
                "refusing to search public law without a jurisdiction filter"
            )

        must = [qmodels.FieldCondition(key="jurisdiction", match=qmodels.MatchAny(any=jurisdictions))]
        results = self._client.search(
            collection_name=self._collection,
            query_vector=query_vector,
            query_filter=qmodels.Filter(must=must),
            limit=limit,
        )

        # Defense in depth, same discipline as OwnerScopedQdrant.search: re-verify the filter
        # on every returned point rather than trusting the server-side filter alone.
        verified = [r for r in results if r.payload and r.payload.get("jurisdiction") in jurisdictions]
        return [ScoredChunk(point_id=str(r.id), score=r.score, payload=r.payload or {}) for r in verified]
