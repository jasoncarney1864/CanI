import pytest
from cani_shared.vector.qdrant_client import MissingOwnerFilterError, OwnerScopedQdrant


@pytest.fixture
def qdrant():
    # Never actually contacts the URL for these tests — the empty-owner check raises
    # before any network call is issued.
    return OwnerScopedQdrant("http://localhost:1", "unit_test_collection")


def test_search_without_owner_raises(qdrant):
    with pytest.raises(MissingOwnerFilterError):
        qdrant.search(owner_user_id="", query_vector=[0.1, 0.2])


def test_upsert_without_owner_raises(qdrant):
    with pytest.raises(MissingOwnerFilterError):
        qdrant.upsert_chunk(owner_user_id="", vector=[0.1, 0.2], payload={})


def test_chunks_for_document_without_owner_raises(qdrant):
    with pytest.raises(MissingOwnerFilterError):
        qdrant.chunks_for_document(owner_user_id="", document_id="doc-1")


def test_chunks_for_document_without_document_raises(qdrant):
    with pytest.raises(MissingOwnerFilterError):
        qdrant.chunks_for_document(owner_user_id="owner-1", document_id="")


class _Point:
    def __init__(self, payload):
        self.payload = payload


def test_chunks_for_document_reverifies_owner_and_orders(qdrant, monkeypatch):
    # Even if the server returned a foreign-owner point (it should not), the wrapper must
    # drop it; results must come back ordered by chunk_index.
    points = [
        _Point({"owner_user_id": "owner-1", "chunk_id": "b", "chunk_index": 2, "chunk_text": "second"}),
        _Point({"owner_user_id": "owner-1", "chunk_id": "a", "chunk_index": 1, "chunk_text": "first"}),
        _Point({"owner_user_id": "intruder", "chunk_id": "x", "chunk_index": 0, "chunk_text": "leak"}),
    ]
    monkeypatch.setattr(qdrant._client, "scroll", lambda **_: (points, None))

    result = qdrant.chunks_for_document(owner_user_id="owner-1", document_id="doc-1")

    assert [c["chunk_id"] for c in result] == ["a", "b"]  # ordered, intruder dropped
    assert all(c["owner_user_id"] == "owner-1" for c in result)
