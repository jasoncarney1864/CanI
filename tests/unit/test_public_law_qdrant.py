from types import SimpleNamespace

import pytest
from cani_shared.vector.public_law_client import MissingJurisdictionFilterError, PublicLawQdrant
from cani_shared.vector.qdrant_client import VectorDimensionMismatchError
from qdrant_client.http import models as qmodels


@pytest.fixture
def qdrant():
    # Never actually contacts the URL for these tests — the empty-jurisdiction check raises
    # before any network call is issued.
    return PublicLawQdrant("http://localhost:1", "unit_test_law_collection")


def test_search_without_jurisdictions_raises(qdrant):
    with pytest.raises(MissingJurisdictionFilterError):
        qdrant.search(query_vector=[0.1, 0.2], jurisdictions=[])


def test_search_with_none_jurisdictions_raises(qdrant):
    with pytest.raises(MissingJurisdictionFilterError):
        qdrant.search(query_vector=[0.1, 0.2], jurisdictions=None)


class _Point:
    def __init__(self, id_, score, payload):
        self.id = id_
        self.score = score
        self.payload = payload


def test_search_reverifies_jurisdiction_on_returned_points(qdrant, monkeypatch):
    # Even if the server returned a point outside the requested jurisdictions (it should
    # not), the wrapper must drop it before it leaves the class.
    points = [
        _Point("a", 0.9, {"jurisdiction": "us-nv", "citation": "NRS 116.001"}),
        _Point("b", 0.5, {"jurisdiction": "us-ca", "citation": "CA Civ Code 1"}),
    ]
    monkeypatch.setattr(qdrant._client, "search", lambda **_: points)

    result = qdrant.search(query_vector=[0.1, 0.2], jurisdictions=["us-nv"])

    assert [c.point_id for c in result] == ["a"]


def test_search_passes_jurisdiction_filter(qdrant, monkeypatch):
    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(qdrant._client, "search", fake_search)

    qdrant.search(query_vector=[0.1, 0.2], jurisdictions=["us-nv", "us-nv-washoe"], limit=3)

    query_filter = captured["query_filter"]
    assert query_filter.must[0].key == "jurisdiction"
    assert query_filter.must[0].match.any == ["us-nv", "us-nv-washoe"]
    assert captured["limit"] == 3


def test_upsert_section_requires_no_owner_but_uses_given_point_id(qdrant, monkeypatch):
    captured = {}
    monkeypatch.setattr(qdrant._client, "upsert", lambda **kwargs: captured.update(kwargs))

    point_id = qdrant.upsert_section(
        vector=[0.1, 0.2], payload={"jurisdiction": "us-nv"}, point_id="fixed-id"
    )

    assert point_id == "fixed-id"
    assert captured["points"][0].id == "fixed-id"


def test_delete_points_noop_on_empty_list(qdrant, monkeypatch):
    called = []
    monkeypatch.setattr(qdrant._client, "delete", lambda **kwargs: called.append(kwargs))

    qdrant.delete_points([])

    assert called == []


def test_delete_points_calls_client_delete(qdrant, monkeypatch):
    captured = {}
    monkeypatch.setattr(qdrant._client, "delete", lambda **kwargs: captured.update(kwargs))

    qdrant.delete_points(["a", "b"])

    assert captured["points_selector"].points == ["a", "b"]


class _Named:
    def __init__(self, name):
        self.name = name


def _stub_existing_collection(qdrant, monkeypatch, size):
    monkeypatch.setattr(
        qdrant._client,
        "get_collections",
        lambda: SimpleNamespace(collections=[_Named("unit_test_law_collection")]),
    )
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
    _stub_existing_collection(qdrant, monkeypatch, size=32)

    with pytest.raises(VectorDimensionMismatchError):
        qdrant.ensure_collection(1536)


def test_ensure_collection_accepts_matching_dimension(qdrant, monkeypatch):
    _stub_existing_collection(qdrant, monkeypatch, size=1536)

    qdrant.ensure_collection(1536)  # no raise
