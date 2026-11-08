"""Owner-filtered vector access on Postgres + pgvector. Per docs/08-rag-pipeline-design.md
§8.8 and docs/09-data-model-and-storage.md §9.6: "Retrieval path fails closed if owner
filter is missing." This wrapper makes that structurally true — there is no search method
that accepts an empty/missing owner_user_id; it raises before issuing the query.

Replaced the Qdrant wrapper in 2026-11 (docs/adr/adr-008-vector-store-pgvector.md). The
public surface is unchanged on purpose: the ingestion pipeline, deletion pipeline,
retrieval-worker and docs-api call the same seven methods they called on Qdrant, so the
swap is a storage change and not a behaviour change. What did change: every method takes
the caller's open connection, so a chunk's vector and its chunk_manifests row commit in the
same transaction, and delete_document_points runs inside the deletion job's transaction.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
import psycopg_pool
from psycopg import Connection
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


class MissingOwnerFilterError(Exception):
    """Raised instead of ever issuing an unscoped vector query."""


class VectorDimensionMismatchError(Exception):
    """Raised when already-stored vectors have a different width than the embedder produces.

    This is fatal on purpose. Silently mixing widths turns every upsert into a per-document
    runtime failure far away from the real cause, and — worse — leaves any already-indexed
    vectors semantically meaningless while the system still reports success. This is the
    tripwire for the fakes-in-prod incident class (CLAUDE.md): the 32-wide fake embedder
    and the 1536-wide Azure OpenAI embedder can never share a table unnoticed.
    """


@dataclass
class ScoredChunk:
    point_id: str
    score: float
    payload: dict


def _is_transient(exc: Exception) -> bool:
    """Transient = worth retrying: connection-level failures and pool exhaustion. Anything
    else (SQL errors, integrity violations, owner-filter violations) is a contract problem
    and retrying it just delays the real error."""
    return isinstance(exc, psycopg.OperationalError | psycopg_pool.PoolTimeout)


def retry_transient[T](
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.25,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run ``fn``, retrying transient database failures with exponential backoff.

    Exists because of the 2026-08-09 outage (docs/sitreps/2026-08-09-*): one transient
    vector-store failure on the retrieval path was a user-visible 500 on every /query,
    while ingestion had already been hardened against exactly this class of fault.
    Bounded and short (0.25s/0.5s/1s worst case ≈ 1.75s added latency) because this sits
    on an interactive request path — it absorbs blips, not outages. Non-transient errors
    re-raise immediately.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - classified immediately below
            if not _is_transient(exc):
                raise
            last = exc
            if attempt < attempts - 1:
                sleep(base_delay * (2**attempt))
    assert last is not None  # attempts >= 1, so we only get here via the except path
    raise last


def vector_literal(vector: list[float]) -> str:
    """pgvector's text input form. Passed as a string and cast with ``::vector`` so no
    client-side adapter package is needed — vectors are never read back out."""
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


def _order_by_chunk_index(payload: dict) -> int:
    # chunk_index gives document order; fall back to page_start for chunks indexed
    # before chunk_index was added to the payload.
    return payload.get("chunk_index", payload.get("page_start", 0))


class _PgStoreBase:
    """Shared connection handling and the dimension tripwire for both stores."""

    table: str

    def __init__(self, pool: ConnectionPool | None = None):
        self._pool = pool

    @contextmanager
    def _conn(self, conn: Connection | None) -> Iterator[Connection]:
        """Use the caller's connection (joining its transaction) when given; otherwise
        borrow one from the pool. The pool branch commits on clean exit, same as every
        other ``with pool.connection()`` in the codebase."""
        if conn is not None:
            yield conn
            return
        if self._pool is None:
            raise RuntimeError(f"{type(self).__name__} needs a connection or a pool")
        with self._pool.connection() as pooled:
            yield pooled

    def ping(self, conn: Connection | None = None) -> None:
        """Cheap live check — raises if Postgres is unreachable or pgvector is missing.

        Used by the retrieval-worker's /readyz. Deliberately NOT cached: during the
        2026-08-09 outage /healthz answered 200 for two days while the vector store
        crash-looped, because nothing on the health path ever touched the dependency."""
        with self._conn(conn) as c:
            row = c.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone()
        if row is None:
            raise RuntimeError("pgvector extension is not installed (migration 0009 not applied?)")

    def ensure_collection(self, vector_size: int, conn: Connection | None = None) -> None:
        """Every service (retrieval-worker, ingestion-worker) calls this before first use.

        Two jobs: assert any already-stored vectors match the embedder's width (see
        VectorDimensionMismatchError), then make sure the HNSW index for that width exists.
        The embedding column is untyped so the width lives in an expression index — the
        documented pgvector pattern for a column whose dimension is decided at runtime —
        and search() must use the identical ``(embedding::vector(N))`` expression for the
        planner to pick it up. ``IF NOT EXISTS`` makes the concurrent-startup race across
        services a no-op rather than an error."""
        with self._conn(conn) as c:
            self._assert_vector_size(c, vector_size)
            c.execute(
                f"CREATE INDEX IF NOT EXISTS {self.table}_hnsw_cos_{vector_size} "
                f"ON {self.table} USING hnsw ((embedding::vector({vector_size})) vector_cosine_ops)"
            )
            c.commit()

    def _assert_vector_size(self, conn: Connection, expected: int) -> None:
        row = conn.execute(f"SELECT vector_dims(embedding) FROM {self.table} LIMIT 1").fetchone()
        if row is None:
            return
        actual = row[0]
        if actual != expected:
            raise VectorDimensionMismatchError(
                f"table {self.table!r} holds vectors of width {actual} but the configured "
                f"embedder produces {expected}. Switching embedders requires re-ingesting into "
                f"an empty table; reusing these rows would corrupt retrieval."
            )


class OwnerScopedVectorStore(_PgStoreBase):
    table = "chunk_embeddings"

    def upsert_chunk(
        self,
        *,
        owner_user_id: str,
        vector: list[float],
        payload: dict,
        point_id: str,
        conn: Connection | None = None,
    ) -> str:
        if not owner_user_id:
            raise MissingOwnerFilterError("refusing to index a vector without owner_user_id")
        full_payload = {"owner_user_id": owner_user_id, **payload}
        with self._conn(conn) as c:
            c.execute(
                """
                INSERT INTO chunk_embeddings
                    (point_id, owner_user_id, document_id, spoke, origin, taxonomy_tags, chunk_index,
                     embedding, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s)
                ON CONFLICT (point_id) DO UPDATE SET
                    owner_user_id = EXCLUDED.owner_user_id,
                    document_id = EXCLUDED.document_id,
                    spoke = EXCLUDED.spoke,
                    origin = EXCLUDED.origin,
                    taxonomy_tags = EXCLUDED.taxonomy_tags,
                    chunk_index = EXCLUDED.chunk_index,
                    embedding = EXCLUDED.embedding,
                    payload = EXCLUDED.payload
                """,
                (
                    point_id,
                    owner_user_id,
                    str(payload.get("document_id", "")),
                    payload.get("spoke"),
                    payload.get("origin"),
                    list(payload.get("taxonomy_tags") or []),
                    payload.get("chunk_index"),
                    vector_literal(vector),
                    Jsonb(full_payload),
                ),
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
        conn: Connection | None = None,
    ) -> list[ScoredChunk]:
        if not owner_user_id:
            # Fail closed (§8.8, §9.6): never run a vector query without a mandatory owner filter.
            raise MissingOwnerFilterError("refusing to search without owner_user_id")

        width = len(query_vector)
        where = ["owner_user_id = %s"]
        params: list[object] = [owner_user_id]
        if taxonomy_tags:
            where.append("taxonomy_tags && %s")
            params.append(list(taxonomy_tags))
        if spoke:
            where.append("spoke = %s")
            params.append(spoke)

        # Cosine distance (<=>) is 0 for identical direction; report 1 - distance so callers
        # keep Qdrant's "higher is better" similarity contract (assembly.top_k sorts desc).
        # The cast expression must match ensure_collection's index expression exactly.
        sql = (
            f"SELECT point_id, 1 - ((embedding::vector({width})) <=> %s::vector({width})) AS score, payload "
            f"FROM chunk_embeddings WHERE {' AND '.join(where)} "
            f"ORDER BY (embedding::vector({width})) <=> %s::vector({width}) LIMIT %s"
        )
        literal = vector_literal(query_vector)
        with self._conn(conn) as c:
            rows = c.execute(sql, [literal, *params, literal, limit]).fetchall()

        # Defense in depth: even though the WHERE clause guarantees this, never trust a
        # single control point for tenant isolation — verify the payload on every returned
        # row before it leaves this wrapper.
        return [
            ScoredChunk(point_id=str(point_id), score=float(score), payload=payload or {})
            for point_id, score, payload in rows
            if payload and payload.get("owner_user_id") == owner_user_id
        ]

    def chunks_for_document(
        self, *, owner_user_id: str, document_id: str, conn: Connection | None = None
    ) -> list[dict]:
        """All of one document's chunk payloads, owner-scoped, for the Document Viewer.
        A metadata read, not a similarity query — but the same mandatory-owner-filter +
        re-verify discipline as search()."""
        if not owner_user_id:
            raise MissingOwnerFilterError("refusing to read chunks without owner_user_id")
        if not document_id:
            raise MissingOwnerFilterError("refusing to read chunks without a document_id")

        with self._conn(conn) as c:
            rows = c.execute(
                "SELECT payload FROM chunk_embeddings WHERE owner_user_id = %s AND document_id = %s",
                (owner_user_id, document_id),
            ).fetchall()
        payloads = [row[0] for row in rows if row[0] and row[0].get("owner_user_id") == owner_user_id]
        payloads.sort(key=_order_by_chunk_index)
        return payloads

    def set_document_spoke(
        self, *, owner_user_id: str, document_id: str, spoke: str, conn: Connection | None = None
    ) -> None:
        """Updates the spoke on every already-indexed row for a document, without
        re-embedding (docs/21 follow-up: moving a mis-filed document between spokes).
        Idempotent and safe for a document with no indexed rows yet — it matches zero rows
        and succeeds as a no-op. Both the indexed column (what search filters on) and the
        payload copy (what the Document Viewer and citations read) are updated together."""
        if not owner_user_id:
            raise MissingOwnerFilterError("refusing to update vectors without owner_user_id")
        if not document_id:
            raise MissingOwnerFilterError("refusing to update vectors without a document_id")
        with self._conn(conn) as c:
            c.execute(
                """
                UPDATE chunk_embeddings
                SET spoke = %s, payload = payload || jsonb_build_object('spoke', %s::text)
                WHERE owner_user_id = %s AND document_id = %s
                """,
                (spoke, spoke, owner_user_id, document_id),
            )

    def delete_document_points(
        self, *, owner_user_id: str, document_id: str, conn: Connection | None = None
    ) -> None:
        """Deletion pipeline step (docs/21 §1.5/§1.7 step 2). Deleting zero rows (e.g. a
        document whose ingestion failed before any chunk was indexed) succeeds, which is
        what makes a crash-and-reclaim of the deletion job safe."""
        if not owner_user_id:
            raise MissingOwnerFilterError("refusing to delete vectors without owner_user_id")
        if not document_id:
            raise MissingOwnerFilterError("refusing to delete vectors without a document_id")
        with self._conn(conn) as c:
            c.execute(
                "DELETE FROM chunk_embeddings WHERE owner_user_id = %s AND document_id = %s",
                (owner_user_id, document_id),
            )
