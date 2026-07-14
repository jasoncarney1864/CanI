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
