"""Qdrant snapshot export to Blob Storage (docs/09 §9.10, Sprint 2 C1).

Runs as a scheduled Container Apps Job (`qdrant-snapshot` in
infra/container-apps/main.bicep) on the ingestion-worker image, which already carries
httpx + the blob SDK. Qdrant Cloud's free tier takes no backups of its own, so this is
the only copy. It asks Qdrant to create a snapshot over its REST API, streams that
snapshot into the qdrant-snapshots container under a timestamped path, then deletes the
snapshot from the cluster so exports don't accumulate against its disk quota.

Two sizing constraints are worth knowing, because both fail late and quietly:

* The snapshot is streamed chunk by chunk and is never held whole in memory. The job runs
  under a 1Gi cap, which a materialised multi-hundred-MB snapshot would blow.
* Qdrant builds the snapshot on the cluster's own disk before we can download it, so a
  collection larger than roughly half the cluster's disk quota cannot be snapshotted at
  all. On the free tier that quota is 4 GB. That failure arrives here as an HTTP error
  from the create call, not as anything obviously disk-related.

Restore (drill / recovery) is the reverse and is documented in
runbooks/backup-restore-drill.md — it is a deliberate operator action, not automated.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator

import httpx

from cani_shared.blob import BlobStore
from cani_shared.config import Settings, get_settings
from cani_shared.logging import configure_logging, get_logger

QDRANT_SNAPSHOTS_CONTAINER = "qdrant-snapshots"

# Block size for the streamed upload: large enough that a multi-hundred-MB snapshot is not
# thousands of round trips, small enough that peak memory stays trivial against the 1Gi cap.
_CHUNK_BYTES = 4 * 1024 * 1024

logger = get_logger(__name__)


def _counted(chunks: Iterator[bytes], counter: list[int]) -> Iterator[bytes]:
    """Pass chunks through untouched while recording the running total, so the upload can
    be logged with its real size without ever holding the payload."""
    for chunk in chunks:
        counter[0] += len(chunk)
        yield chunk


def snapshot_qdrant_to_blob(settings: Settings) -> str:
    """Create a Qdrant snapshot and stream it to Blob Storage. Returns the blob URI
    (``container/path``). Raises on any failure so the Job is marked failed and the
    failure alert path (§13.8) can see it."""
    base = settings.qdrant_url.rstrip("/")
    collection = settings.qdrant_collection
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}

    # Generous timeout: snapshotting scales with collection size, and the download streams
    # the whole file back over HTTP.
    with httpx.Client(timeout=httpx.Timeout(600.0), headers=headers) as client:
        created = client.post(f"{base}/collections/{collection}/snapshots")
        created.raise_for_status()
        snapshot_name = created.json()["result"]["name"]
        logger.info("qdrant_snapshot_created", snapshot=snapshot_name, collection=collection)

        try:
            timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
            path = f"{collection}/{timestamp}_{snapshot_name}"
            counter = [0]

            snapshot_url = f"{base}/collections/{collection}/snapshots/{snapshot_name}"
            with client.stream("GET", snapshot_url) as download:
                download.raise_for_status()
                # Qdrant sends Content-Length. Passing it through lets the SDK size its
                # blocks instead of guessing; if it's absent or unparseable, a chunked
                # upload of unknown length still works.
                try:
                    length: int | None = int(download.headers["content-length"])
                except (KeyError, TypeError, ValueError):
                    length = None

                BlobStore(settings.azure_storage_connection_string).upload_stream(
                    container=QDRANT_SNAPSHOTS_CONTAINER,
                    path=path,
                    stream=_counted(download.iter_bytes(_CHUNK_BYTES), counter),
                    overwrite=False,
                    length=length,
                )

            blob_uri = f"{QDRANT_SNAPSHOTS_CONTAINER}/{path}"
            logger.info("qdrant_snapshot_uploaded", blob_uri=blob_uri, size_bytes=counter[0])
            return blob_uri
        finally:
            # Always free the cluster-side copy — the durable copy is the blob, and the
            # snapshot competes with live data for the cluster's disk quota. Best-effort:
            # a failed delete must not mask a successful (or failing) upload above.
            try:
                client.delete(f"{base}/collections/{collection}/snapshots/{snapshot_name}")
            except Exception as exc:  # noqa: BLE001 - cleanup only
                logger.warning("qdrant_snapshot_cleanup_failed", snapshot=snapshot_name, error=str(exc))


def main() -> None:
    configure_logging("qdrant-snapshot")
    blob_uri = snapshot_qdrant_to_blob(get_settings())
    logger.info("qdrant_snapshot_done", blob_uri=blob_uri)


if __name__ == "__main__":
    main()
