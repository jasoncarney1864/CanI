"""OwnerScopedVectorStore (cani_shared.vector.store): the fail-closed owner filter, the SQL it
issues, the defense-in-depth re-verification, and the dimension tripwire — all without a
live Postgres. The store takes the caller's connection, so a tiny recording fake stands in
for psycopg here; the SQL itself runs for real in the integration suite.
"""

from __future__ import annotations

import pytest
from cani_shared.vector.store import (
    MissingOwnerFilterError,
    OwnerScopedVectorStore,
    VectorDimensionMismatchError,
    vector_literal,
)
from fake_pg import FakeConn


@pytest.fixture
def store():
    # No pool: every call in these tests passes an explicit connection, and the
    # empty-owner checks raise before any connection is touched at all.
    return OwnerScopedVectorStore()


def test_search_without_owner_raises(store):
    with pytest.raises(MissingOwnerFilterError):
        store.search(owner_user_id="", query_vector=[0.1, 0.2], conn=FakeConn())


def test_upsert_without_owner_raises(store):
    with pytest.raises(MissingOwnerFilterError):
        store.upsert_chunk(owner_user_id="", vector=[0.1, 0.2], payload={}, point_id="p", conn=FakeConn())


def test_chunks_for_document_without_owner_raises(store):
    with pytest.raises(MissingOwnerFilterError):
        store.chunks_for_document(owner_user_id="", document_id="doc-1", conn=FakeConn())


def test_chunks_for_document_without_document_raises(store):
    with pytest.raises(MissingOwnerFilterError):
        store.chunks_for_document(owner_user_id="owner-1", document_id="", conn=FakeConn())


def test_set_document_spoke_without_owner_raises(store):
    with pytest.raises(MissingOwnerFilterError):
        store.set_document_spoke(owner_user_id="", document_id="doc-1", spoke="Legal", conn=FakeConn())


def test_set_document_spoke_without_document_raises(store):
    with pytest.raises(MissingOwnerFilterError):
        store.set_document_spoke(owner_user_id="owner-1", document_id="", spoke="Legal", conn=FakeConn())


def test_delete_document_points_without_owner_raises(store):
    with pytest.raises(MissingOwnerFilterError):
        store.delete_document_points(owner_user_id="", document_id="doc-1", conn=FakeConn())


def test_delete_document_points_without_document_raises(store):
    with pytest.raises(MissingOwnerFilterError):
        store.delete_document_points(owner_user_id="owner-1", document_id="", conn=FakeConn())


def test_without_connection_or_pool_is_an_error_not_a_silent_noop(store):
    # A store built with no pool and called with no connection must fail loudly — never
    # pretend an upsert or delete happened.
    with pytest.raises(RuntimeError):
        store.delete_document_points(owner_user_id="owner-1", document_id="doc-1")


def test_search_filters_by_owner_and_spoke_in_sql(store):
    conn = FakeConn(results=[[]])
    store.search(owner_user_id="owner-1", query_vector=[0.5, 0.5], spoke="Legal", limit=3, conn=conn)

    sql, params = conn.calls[0]
    assert "WHERE owner_user_id = %s AND spoke = %s" in sql
    assert "ORDER BY (embedding::vector(2)) <=> %s::vector(2) LIMIT %s" in sql
    assert params == [vector_literal([0.5, 0.5]), "owner-1", "Legal", vector_literal([0.5, 0.5]), 3]


def test_search_reverifies_owner_on_returned_rows(store):
    # Even if the database returned a foreign-owner row (it cannot, given the WHERE
    # clause), the wrapper must drop it before it leaves the class.
    rows = [
        ("a", 0.9, {"owner_user_id": "owner-1", "chunk_id": "a"}),
        ("x", 0.8, {"owner_user_id": "intruder", "chunk_id": "x"}),
        ("b", 0.7, None),
    ]
    result = store.search(owner_user_id="owner-1", query_vector=[0.1, 0.2], conn=FakeConn(results=[rows]))

    assert [c.point_id for c in result] == ["a"]
    assert result[0].score == pytest.approx(0.9)


def test_upsert_writes_indexed_columns_and_full_payload(store):
    conn = FakeConn()
    store.upsert_chunk(
        owner_user_id="owner-1",
        vector=[0.25, 0.75],
        point_id="chunk-1",
        payload={
            "document_id": "doc-1",
            "spoke": "Legal",
            "origin": "upload",
            "chunk_index": 4,
            "chunk_text": "t",
        },
        conn=conn,
    )

    sql, params = conn.calls[0]
    assert sql.startswith("INSERT INTO chunk_embeddings")
    assert "ON CONFLICT (point_id) DO UPDATE" in sql
    assert params[:7] == ("chunk-1", "owner-1", "doc-1", "Legal", "upload", [], 4)
    assert params[7] == "[0.25,0.75]"
    assert params[8].obj == {
        "owner_user_id": "owner-1",
        "document_id": "doc-1",
        "spoke": "Legal",
        "origin": "upload",
        "chunk_index": 4,
        "chunk_text": "t",
    }


def test_set_document_spoke_updates_column_and_payload_for_owner_and_document(store):
    conn = FakeConn()
    store.set_document_spoke(owner_user_id="owner-1", document_id="doc-1", spoke="Legal", conn=conn)

    sql, params = conn.calls[0]
    assert sql.startswith("UPDATE chunk_embeddings SET spoke = %s, payload = payload || jsonb_build_object")
    assert "WHERE owner_user_id = %s AND document_id = %s" in sql
    assert params == ("Legal", "Legal", "owner-1", "doc-1")


def test_delete_document_points_filters_by_owner_and_document(store):
    conn = FakeConn()
    store.delete_document_points(owner_user_id="owner-1", document_id="doc-1", conn=conn)

    sql, params = conn.calls[0]
    assert sql == "DELETE FROM chunk_embeddings WHERE owner_user_id = %s AND document_id = %s"
    assert params == ("owner-1", "doc-1")


def test_chunks_for_document_reverifies_owner_and_orders(store):
    rows = [
        ({"owner_user_id": "owner-1", "chunk_id": "b", "chunk_index": 2, "chunk_text": "second"},),
        ({"owner_user_id": "owner-1", "chunk_id": "a", "chunk_index": 1, "chunk_text": "first"},),
        ({"owner_user_id": "intruder", "chunk_id": "x", "chunk_index": 0, "chunk_text": "leak"},),
    ]
    result = store.chunks_for_document(
        owner_user_id="owner-1", document_id="doc-1", conn=FakeConn(results=[rows])
    )

    assert [c["chunk_id"] for c in result] == ["a", "b"]  # ordered, intruder dropped
    assert all(c["owner_user_id"] == "owner-1" for c in result)


def test_ensure_collection_rejects_dimension_mismatch(store):
    # Rows written by the 32-dim fake embedder must not be silently reused once the real
    # 1536-dim Azure OpenAI embedder is configured.
    conn = FakeConn(results=[[(32,)]])
    with pytest.raises(VectorDimensionMismatchError):
        store.ensure_collection(1536, conn=conn)
    assert len(conn.calls) == 1  # never reached the CREATE INDEX


def test_ensure_collection_accepts_matching_dimension_and_builds_width_specific_index(store):
    conn = FakeConn(results=[[(1536,)]])
    store.ensure_collection(1536, conn=conn)

    sql, _ = conn.calls[1]
    assert sql == (
        "CREATE INDEX IF NOT EXISTS chunk_embeddings_hnsw_cos_1536 ON chunk_embeddings "
        "USING hnsw ((embedding::vector(1536)) vector_cosine_ops)"
    )
    assert conn.commits == 1


def test_ensure_collection_on_empty_table_only_builds_index(store):
    conn = FakeConn(results=[[]])
    store.ensure_collection(32, conn=conn)
    assert "chunk_embeddings_hnsw_cos_32" in conn.calls[1][0]


def test_ping_requires_the_pgvector_extension(store):
    with pytest.raises(RuntimeError):
        store.ping(conn=FakeConn(results=[[]]))
    store.ping(conn=FakeConn(results=[[(1,)]]))  # no raise


def test_vector_literal_is_pgvector_text_form():
    assert vector_literal([1, 0.5, -2.0]) == "[1.0,0.5,-2.0]"
