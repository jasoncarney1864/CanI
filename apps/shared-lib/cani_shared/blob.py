"""Blob storage access per docs/09-data-model-and-storage.md §9.5.

Container strategy: raw-documents (originals), extracted-text (canonical text
artifacts), ingestion-artifacts (OCR/layout/debug bundles). Path convention:
owner_user_id/document_id/document_version_id/<artifact>. Artifacts are immutable —
never overwrite an existing blob path in place.
"""

from __future__ import annotations

import time
from collections.abc import Iterable

from azure.storage.blob import BlobServiceClient

RAW_DOCUMENTS_CONTAINER = "raw-documents"
EXTRACTED_TEXT_CONTAINER = "extracted-text"
INGESTION_ARTIFACTS_CONTAINER = "ingestion-artifacts"

_ALL_CONTAINERS = (RAW_DOCUMENTS_CONTAINER, EXTRACTED_TEXT_CONTAINER, INGESTION_ARTIFACTS_CONTAINER)


class BlobStore:
    def __init__(self, connection_string: str):
        self._connection_string = connection_string
        self._client = BlobServiceClient.from_connection_string(connection_string)

    def ensure_containers(self) -> None:
        existing = {c["name"] for c in self._client.list_containers()}
        for name in _ALL_CONTAINERS:
            if name not in existing:
                self._client.create_container(name)

    @staticmethod
    def artifact_path(
        owner_user_id: str, document_id: str, document_version_id: str, artifact_name: str
    ) -> str:
        return f"{owner_user_id}/{document_id}/{document_version_id}/{artifact_name}"

    def upload(self, *, container: str, path: str, data: bytes, overwrite: bool = False) -> str:
        client = self._client.get_blob_client(container=container, blob=path)
        client.upload_blob(data, overwrite=overwrite)
        return f"{container}/{path}"

    def upload_stream(
        self,
        *,
        container: str,
        path: str,
        stream: Iterable[bytes],
        overwrite: bool = False,
        length: int | None = None,
    ) -> str:
        """Upload without materialising the payload in memory.

        ``upload`` takes ``bytes``, which means the caller has already paid for the whole
        object in RAM. That is fine for document artifacts, which are bounded by the upload
        limit, and wrong for anything that grows with the size of the corpus — Qdrant
        snapshots above all. Pass an iterator of chunks here instead and let the SDK
        block-upload them.

        ``max_concurrency=1`` is required, not tuning: a generator is not seekable, so the
        SDK cannot hand overlapping ranges of it to parallel writers.
        """
        client = self._client.get_blob_client(container=container, blob=path)
        client.upload_blob(stream, overwrite=overwrite, length=length, max_concurrency=1)
        return f"{container}/{path}"

    def download(self, blob_uri: str, *, max_attempts: int = 3) -> bytes:
        """Retries transient network failures with backoff per §8.10 — this is the
        ingestion pipeline's blob read, so a flaky connection here should not
        dead-letter a job that would have succeeded on a second attempt."""
        container, _, path = blob_uri.partition("/")

        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                client = self._client.get_blob_client(container=container, blob=path)
                return client.download_blob().readall()
            except Exception as exc:  # noqa: BLE001 - retried below; re-raised after final attempt
                last_error = exc
                if attempt == max_attempts:
                    break
                time.sleep(0.5 * attempt)
        raise last_error
