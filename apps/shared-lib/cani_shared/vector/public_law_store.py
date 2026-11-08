"""Read/write access to the shared public-law vectors (docs/20-public-law-corpus-design.md
§20.3). Sibling to store.py rather than a class inside it, per that doc section.

No owner filter — the corpus is public by definition — but search REQUIRES a non-empty
jurisdiction filter, enforced the same fail-closed way OwnerScopedVectorStore enforces
owner: there is no method that searches the whole corpus unscoped.
"""

from __future__ import annotations

from psycopg import Connection
from psycopg.types.json import Jsonb

from cani_shared.vector.store import ScoredChunk, _PgStoreBase, vector_literal


class MissingJurisdictionFilterError(Exception):
    """Raised instead of ever issuing an unscoped public-law search."""


class PublicLawVectorStore(_PgStoreBase):
    table = "law_chunk_embeddings"

    def upsert_section(
        self, *, vector: list[float], payload: dict, point_id: str, conn: Connection | None = None
    ) -> str:
        """point_id is mandatory: the refresh job always passes a deterministic uuid5 derived
        from (source_key, citation, part) so re-upserts of an unchanged section replace the
        same row in place instead of accumulating duplicates (§20.7)."""
        with self._conn(conn) as c:
            c.execute(
                """
                INSERT INTO law_chunk_embeddings
                    (point_id, jurisdiction, source_kind, law_source_id, embedding, payload)
                VALUES (%s, %s, %s, %s, %s::vector, %s)
                ON CONFLICT (point_id) DO UPDATE SET
                    jurisdiction = EXCLUDED.jurisdiction,
                    source_kind = EXCLUDED.source_kind,
                    law_source_id = EXCLUDED.law_source_id,
                    embedding = EXCLUDED.embedding,
                    payload = EXCLUDED.payload
                """,
                (
                    point_id,
                    str(payload.get("jurisdiction", "")),
                    payload.get("source_kind"),
                    payload.get("law_source_id"),
                    vector_literal(vector),
                    Jsonb(payload),
                ),
            )
        return point_id

    def delete_points(self, point_ids: list[str], conn: Connection | None = None) -> None:
        """For repealed/removed sections (§20.7 step 5) — a citation present in the previous
        manifest but absent from the latest fetch is gone from the law, not just unchanged."""
        if not point_ids:
            return
        with self._conn(conn) as c:
            c.execute("DELETE FROM law_chunk_embeddings WHERE point_id = ANY(%s)", (list(point_ids),))

    def search(
        self,
        *,
        query_vector: list[float],
        jurisdictions: list[str],
        limit: int = 8,
        conn: Connection | None = None,
    ) -> list[ScoredChunk]:
        if not jurisdictions:
            # Fail closed, mirroring OwnerScopedVectorStore.search: never run a vector query
            # without a mandatory jurisdiction filter — there is no "search everything".
            raise MissingJurisdictionFilterError(
                "refusing to search public law without a jurisdiction filter"
            )

        width = len(query_vector)
        sql = (
            f"SELECT point_id, 1 - ((embedding::vector({width})) <=> %s::vector({width})) AS score, payload "
            f"FROM law_chunk_embeddings WHERE jurisdiction = ANY(%s) "
            f"ORDER BY (embedding::vector({width})) <=> %s::vector({width}) LIMIT %s"
        )
        literal = vector_literal(query_vector)
        with self._conn(conn) as c:
            rows = c.execute(sql, [literal, list(jurisdictions), literal, limit]).fetchall()

        # Defense in depth, same discipline as OwnerScopedVectorStore.search: re-verify the
        # filter on every returned row rather than trusting the WHERE clause alone.
        return [
            ScoredChunk(point_id=str(point_id), score=float(score), payload=payload or {})
            for point_id, score, payload in rows
            if payload and payload.get("jurisdiction") in jurisdictions
        ]
