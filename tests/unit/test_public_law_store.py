"""PublicLawVectorStore (docs/20 §20.3): mandatory jurisdiction filter, deterministic
point-id replace-in-place, and the shared dimension tripwire. Same recording-fake approach
as test_vector_store_owner_filter.py; the SQL runs for real in the integration suite."""

from __future__ import annotations

import pytest
from cani_shared.vector.public_law_store import MissingJurisdictionFilterError, PublicLawVectorStore
from cani_shared.vector.store import VectorDimensionMismatchError, vector_literal
from fake_pg import FakeConn


@pytest.fixture
def store():
    return PublicLawVectorStore()


def test_search_without_jurisdictions_raises(store):
    with pytest.raises(MissingJurisdictionFilterError):
        store.search(query_vector=[0.1, 0.2], jurisdictions=[], conn=FakeConn())


def test_search_with_none_jurisdictions_raises(store):
    with pytest.raises(MissingJurisdictionFilterError):
        store.search(query_vector=[0.1, 0.2], jurisdictions=None, conn=FakeConn())


def test_search_reverifies_jurisdiction_on_returned_rows(store):
    rows = [
        ("a", 0.9, {"jurisdiction": "us-nv", "citation": "NRS 116.001"}),
        ("b", 0.5, {"jurisdiction": "us-ca", "citation": "CA Civ Code 1"}),
    ]
    result = store.search(query_vector=[0.1, 0.2], jurisdictions=["us-nv"], conn=FakeConn(results=[rows]))

    assert [c.point_id for c in result] == ["a"]


def test_search_passes_jurisdiction_filter(store):
    conn = FakeConn(results=[[]])
    store.search(query_vector=[0.1, 0.2], jurisdictions=["us-nv", "us-nv-washoe"], limit=3, conn=conn)

    sql, params = conn.calls[0]
    assert "FROM law_chunk_embeddings WHERE jurisdiction = ANY(%s)" in sql
    assert params == [vector_literal([0.1, 0.2]), ["us-nv", "us-nv-washoe"], vector_literal([0.1, 0.2]), 3]


def test_upsert_section_requires_no_owner_but_uses_given_point_id(store):
    conn = FakeConn()
    point_id = store.upsert_section(
        vector=[0.1, 0.2], payload={"jurisdiction": "us-nv"}, point_id="fixed-id", conn=conn
    )

    assert point_id == "fixed-id"
    sql, params = conn.calls[0]
    assert "ON CONFLICT (point_id) DO UPDATE" in sql
    assert params[0] == "fixed-id"
    assert params[1] == "us-nv"


def test_delete_points_noop_on_empty_list(store):
    conn = FakeConn()
    store.delete_points([], conn=conn)
    assert conn.calls == []


def test_delete_points_deletes_by_id_list(store):
    conn = FakeConn()
    store.delete_points(["a", "b"], conn=conn)

    sql, params = conn.calls[0]
    assert sql == "DELETE FROM law_chunk_embeddings WHERE point_id = ANY(%s)"
    assert params == (["a", "b"],)


def test_ensure_collection_rejects_dimension_mismatch(store):
    with pytest.raises(VectorDimensionMismatchError):
        store.ensure_collection(1536, conn=FakeConn(results=[[(32,)]]))


def test_ensure_collection_accepts_matching_dimension(store):
    conn = FakeConn(results=[[(1536,)]])
    store.ensure_collection(1536, conn=conn)  # no raise
    assert "law_chunk_embeddings_hnsw_cos_1536" in conn.calls[1][0]
