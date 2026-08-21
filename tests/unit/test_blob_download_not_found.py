"""BlobStore.download's not-found fast path (docs/21 §2.2 step 3): a missing blob must
fail immediately, not after the usual 3-attempt retry-with-backoff loop meant for
transient network faults — the download endpoint's 404 shouldn't cost the caller ~1.5s
of pointless retries for an error that will never succeed."""

import time
from unittest.mock import MagicMock

import pytest
from azure.core.exceptions import ResourceNotFoundError
from cani_shared.blob import BlobStore

_FAKE_CONNECTION_STRING = (
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://azurite:10000/devstoreaccount1;"
)


def _store_with_fake_blob_client(side_effect) -> tuple[BlobStore, MagicMock]:
    store = BlobStore(_FAKE_CONNECTION_STRING)
    blob_client = MagicMock()
    blob_client.download_blob.side_effect = side_effect
    store._client.get_blob_client = MagicMock(return_value=blob_client)
    return store, blob_client


def test_download_reraises_not_found_without_retrying(monkeypatch):
    store, blob_client = _store_with_fake_blob_client(ResourceNotFoundError("gone"))
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    with pytest.raises(ResourceNotFoundError):
        store.download("raw-documents/owner-1/doc-1/ver-1/original.pdf")

    assert blob_client.download_blob.call_count == 1
    assert sleeps == []


def test_download_still_retries_transient_errors(monkeypatch):
    store, blob_client = _store_with_fake_blob_client(
        [ConnectionError("blip"), ConnectionError("blip"), MagicMock(readall=lambda: b"ok")]
    )
    monkeypatch.setattr(time, "sleep", lambda s: None)

    result = store.download("raw-documents/owner-1/doc-1/ver-1/original.pdf")

    assert result == b"ok"
    assert blob_client.download_blob.call_count == 3
