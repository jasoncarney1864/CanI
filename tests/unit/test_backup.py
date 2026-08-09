"""Qdrant snapshot export (docs/09 §9.10). Verifies the create -> stream -> upload ->
cleanup sequence without a live Qdrant or Blob account.

The snapshot is the one thing here that grows without bound, and the job that runs this
has a 1Gi memory cap, so these tests also assert that the payload is never materialised
whole — see ``_FakeStreamResponse.content``."""

from __future__ import annotations

import pytest

import cani_shared.backup as backup


class _FakeResponse:
    def __init__(self, *, json_data=None):
        self._json = json_data

    def json(self):
        return self._json

    def raise_for_status(self):
        return None


class _FakeStreamResponse:
    """Stands in for ``httpx.Client.stream(...)``'s context manager."""

    def __init__(self, chunks, headers=None):
        self._chunks = chunks
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    def iter_bytes(self, chunk_size=None):
        yield from self._chunks

    @property
    def content(self):
        raise AssertionError(
            "backup must stream the snapshot; reading .content buffers the whole file "
            "into a job capped at 1Gi"
        )


class _FakeClient:
    def __init__(self, calls, *, chunks=(b"SNAPSHOT-", b"BYTES"), headers=None):
        self._calls = calls
        self._chunks = chunks
        self._headers = {"content-length": "14"} if headers is None else headers

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url):
        self._calls.append(("post", url))
        return _FakeResponse(json_data={"result": {"name": "snap-123.snapshot"}})

    def stream(self, method, url):
        self._calls.append((method.lower(), url))
        return _FakeStreamResponse(self._chunks, self._headers)

    def delete(self, url):
        self._calls.append(("delete", url))
        return _FakeResponse()


class _FakeBlobStore:
    last: dict = {}

    def __init__(self, connection_string):
        pass

    def upload_stream(self, *, container, path, stream, overwrite=False, length=None):
        # Draining the iterator here is what the real SDK does; joining is a test-only
        # convenience so assertions can look at the bytes.
        data = b"".join(stream)
        _FakeBlobStore.last = {
            "container": container,
            "path": path,
            "data": data,
            "overwrite": overwrite,
            "length": length,
        }
        return f"{container}/{path}"


class _Settings:
    qdrant_url = "http://qdrant:6333"
    qdrant_collection = "cani_docs_dev"
    qdrant_api_key = ""
    azure_storage_connection_string = "fake-connection-string"


def test_snapshot_uploads_and_cleans_up(monkeypatch):
    calls: list = []
    monkeypatch.setattr(backup.httpx, "Client", lambda *a, **k: _FakeClient(calls))
    monkeypatch.setattr(backup, "BlobStore", _FakeBlobStore)

    blob_uri = backup.snapshot_qdrant_to_blob(_Settings())

    # Uploaded to the snapshots container, under the collection prefix, with the snapshot name.
    assert blob_uri.startswith(f"{backup.QDRANT_SNAPSHOTS_CONTAINER}/cani_docs_dev/")
    assert blob_uri.endswith("snap-123.snapshot")
    assert _FakeBlobStore.last["container"] == backup.QDRANT_SNAPSHOTS_CONTAINER
    # Chunks arrive reassembled and in order.
    assert _FakeBlobStore.last["data"] == b"SNAPSHOT-BYTES"
    # overwrite=False so an existing snapshot path is never clobbered.
    assert _FakeBlobStore.last["overwrite"] is False
    # Content-Length is forwarded so the SDK can size its blocks.
    assert _FakeBlobStore.last["length"] == 14
    # The cluster-side snapshot is deleted afterward — it competes with live data for disk.
    assert ("delete", "http://qdrant:6333/collections/cani_docs_dev/snapshots/snap-123.snapshot") in calls


def test_snapshot_download_is_streamed_not_buffered(monkeypatch):
    """Regression guard for the 1Gi cap: a full-buffer download would raise here."""
    calls: list = []
    monkeypatch.setattr(backup.httpx, "Client", lambda *a, **k: _FakeClient(calls))
    monkeypatch.setattr(backup, "BlobStore", _FakeBlobStore)

    backup.snapshot_qdrant_to_blob(_Settings())

    assert ("get", "http://qdrant:6333/collections/cani_docs_dev/snapshots/snap-123.snapshot") in calls


def test_missing_content_length_still_uploads(monkeypatch):
    """Unknown length is legal — the SDK falls back to a chunked upload."""
    calls: list = []
    monkeypatch.setattr(backup.httpx, "Client", lambda *a, **k: _FakeClient(calls, headers={}))
    monkeypatch.setattr(backup, "BlobStore", _FakeBlobStore)

    backup.snapshot_qdrant_to_blob(_Settings())

    assert _FakeBlobStore.last["length"] is None
    assert _FakeBlobStore.last["data"] == b"SNAPSHOT-BYTES"


def test_snapshot_deletes_even_if_upload_fails(monkeypatch):
    calls: list = []
    monkeypatch.setattr(backup.httpx, "Client", lambda *a, **k: _FakeClient(calls))

    class _BoomStore:
        def __init__(self, *_a, **_k):
            pass

        def upload_stream(self, **_k):
            raise RuntimeError("blob down")

    monkeypatch.setattr(backup, "BlobStore", _BoomStore)

    with pytest.raises(RuntimeError):
        backup.snapshot_qdrant_to_blob(_Settings())

    # Cleanup still ran despite the upload failure.
    assert any(c[0] == "delete" for c in calls)
