"""Qdrant snapshot export (docs/09 §9.10). Verifies the create -> download -> upload ->
cleanup sequence without a live Qdrant or Blob account."""

from __future__ import annotations

import cani_shared.backup as backup


class _FakeResponse:
    def __init__(self, *, json_data=None, content=b""):
        self._json = json_data
        self.content = content

    def json(self):
        return self._json

    def raise_for_status(self):
        return None


class _FakeClient:
    def __init__(self, calls):
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url):
        self._calls.append(("post", url))
        return _FakeResponse(json_data={"result": {"name": "snap-123.snapshot"}})

    def get(self, url):
        self._calls.append(("get", url))
        return _FakeResponse(content=b"SNAPSHOT-BYTES")

    def delete(self, url):
        self._calls.append(("delete", url))
        return _FakeResponse()


class _FakeBlobStore:
    last = {}

    def __init__(self, connection_string):
        pass

    def upload(self, *, container, path, data, overwrite=False):
        _FakeBlobStore.last = {"container": container, "path": path, "data": data, "overwrite": overwrite}
        return f"{container}/{path}"


class _Settings:
    qdrant_url = "http://qdrant:6333"
    qdrant_collection = "cani_docs_dev"
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
    assert _FakeBlobStore.last["data"] == b"SNAPSHOT-BYTES"
    # overwrite=False so an existing snapshot path is never clobbered.
    assert _FakeBlobStore.last["overwrite"] is False
    # The on-disk snapshot is deleted afterward (PVC hygiene).
    assert ("delete", "http://qdrant:6333/collections/cani_docs_dev/snapshots/snap-123.snapshot") in calls


def test_snapshot_deletes_even_if_upload_fails(monkeypatch):
    calls: list = []
    monkeypatch.setattr(backup.httpx, "Client", lambda *a, **k: _FakeClient(calls))

    class _BoomStore:
        def __init__(self, *_a, **_k):
            pass

        def upload(self, **_k):
            raise RuntimeError("blob down")

    monkeypatch.setattr(backup, "BlobStore", _BoomStore)

    try:
        backup.snapshot_qdrant_to_blob(_Settings())
    except RuntimeError:
        pass
    # Cleanup still ran despite the upload failure.
    assert any(c[0] == "delete" for c in calls)
