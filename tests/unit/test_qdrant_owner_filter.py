from types import SimpleNamespace

import pytest
from cani_shared.vector.qdrant_client import (
    MissingOwnerFilterError,
    OwnerScopedQdrant,
    VectorDimensionMismatchError,
)
from qdrant_client.http import models as qmodels


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


def test_delete_document_points_without_owner_raises(qdrant):
    with pytest.raises(MissingOwnerFilterError):
        qdrant.delete_document_points(owner_user_id="", document_id="doc-1")


def test_delete_document_points_without_document_raises(qdrant):
    with pytest.raises(MissingOwnerFilterError):
        qdrant.delete_document_points(owner_user_id="owner-1", document_id="")


def test_delete_document_points_filters_by_owner_and_document(qdrant, monkeypatch):
    captured = {}

    def fake_delete(*, collection_name, points_selector):
        captured["collection_name"] = collection_name
        captured["points_selector"] = points_selector

    monkeypatch.setattr(qdrant._client, "delete", fake_delete)

    qdrant.delete_document_points(owner_user_id="owner-1", document_id="doc-1")

    conditions = {c.key: c.match.value for c in captured["points_selector"].filter.must}
    assert conditions == {"owner_user_id": "owner-1", "document_id": "doc-1"}


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


class _Named:
    def __init__(self, name):
        self.name = name


def _stub_existing_collection(qdrant, monkeypatch, size, *, index_calls=None):
    monkeypatch.setattr(
        qdrant._client,
        "get_collections",
        lambda: SimpleNamespace(collections=[_Named("unit_test_collection")]),
    )
    # docs/21 §3.4: create_payload_index now runs on the already-exists path too, so it
    # must be stubbed here too, not just on the create-collection path — otherwise these
    # tests would attempt a real network call to http://localhost:1 and hang/fail.
    if index_calls is not None:
        monkeypatch.setattr(
            qdrant._client,
            "create_payload_index",
            lambda **kwargs: index_calls.append(kwargs["field_name"]),
        )
    else:
        monkeypatch.setattr(qdrant._client, "create_payload_index", lambda **_: None)
    monkeypatch.setattr(
        qdrant._client,
        "get_collection",
        lambda _name: SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors=qmodels.VectorParams(size=size, distance=qmodels.Distance.COSINE)
                )
            )
        ),
    )


def test_ensure_collection_rejects_dimension_mismatch(qdrant, monkeypatch):
    # A collection built by the 32-dim fake embedder must not be silently reused once the
    # real 1536-dim Azure OpenAI embedder is configured.
    _stub_existing_collection(qdrant, monkeypatch, size=32)

    with pytest.raises(VectorDimensionMismatchError):
        qdrant.ensure_collection(1536)


def test_ensure_collection_accepts_matching_dimension(qdrant, monkeypatch):
    _stub_existing_collection(qdrant, monkeypatch, size=1536)

    qdrant.ensure_collection(1536)  # no raise


def test_ensure_collection_creates_payload_indexes_on_the_already_exists_path(qdrant, monkeypatch):
    # docs/21 §3.4: a field added after the collection already exists in production (e.g.
    # "origin") must still get indexed — this only happens if index creation runs every
    # call, not just the just-created branch.
    index_calls: list[str] = []
    _stub_existing_collection(qdrant, monkeypatch, size=1536, index_calls=index_calls)

    qdrant.ensure_collection(1536)

    assert set(index_calls) == {"owner_user_id", "document_id", "taxonomy_tags", "spoke", "origin"}
