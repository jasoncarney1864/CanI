"""BlobStore.delete_prefix (docs/21 §1.6): the deletion pipeline's blob cleanup step must
delete everything under a prefix and treat an already-missing blob as success, not an
error — the pipeline can be re-run on a crash-and-reclaim retry (§1.7)."""

from unittest.mock import MagicMock

from azure.core.exceptions import ResourceNotFoundError
from cani_shared.blob import BlobStore

# The well-known Azurite emulator dev key (allowlisted in .gitleaks.toml, see CLAUDE.md) —
# never contacted over the network here; every call below is monkeypatched.
_FAKE_CONNECTION_STRING = (
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://azurite:10000/devstoreaccount1;"
)


class _Blob:
    def __init__(self, name):
        self.name = name


def _store_with_fake_client(blob_names: list[str]) -> tuple[BlobStore, MagicMock]:
    store = BlobStore(_FAKE_CONNECTION_STRING)
    container_client = MagicMock()
    container_client.list_blobs.return_value = [_Blob(n) for n in blob_names]
    store._client.get_container_client = MagicMock(return_value=container_client)
    return store, container_client


def test_delete_prefix_deletes_every_matching_blob():
    store, container_client = _store_with_fake_client(
        ["owner-1/doc-1/ver-1/original.pdf", "owner-1/doc-1/ver-1/extracted.txt"]
    )

    deleted = store.delete_prefix(container="raw-documents", prefix="owner-1/doc-1/")

    assert deleted == 2
    container_client.list_blobs.assert_called_once_with(name_starts_with="owner-1/doc-1/")
    assert container_client.delete_blob.call_count == 2


def test_delete_prefix_returns_zero_when_nothing_matches():
    store, container_client = _store_with_fake_client([])

    deleted = store.delete_prefix(container="raw-documents", prefix="owner-1/doc-1/")

    assert deleted == 0
    container_client.delete_blob.assert_not_called()


def test_delete_prefix_treats_already_missing_blob_as_success():
    store, container_client = _store_with_fake_client(["owner-1/doc-1/ver-1/original.pdf"])
    container_client.delete_blob.side_effect = ResourceNotFoundError("already gone")

    deleted = store.delete_prefix(container="raw-documents", prefix="owner-1/doc-1/")

    # Not counted as deleted (delete_blob never succeeded) but must not raise.
    assert deleted == 0
