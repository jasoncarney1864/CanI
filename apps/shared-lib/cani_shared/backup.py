"""Qdrant snapshot export to Blob Storage (docs/09 §9.10, Sprint 2 C1).

Runs as a scheduled Kubernetes CronJob (k8s/base/qdrant/snapshot-cronjob.yaml) on the
ingestion-worker image, which already carries httpx + the blob SDK. It asks Qdrant to
create a snapshot over its REST API, streams that snapshot into the qdrant-snapshots
container under a timestamped path, then deletes the on-disk snapshot so exports don't
accumulate on the 20Gi PVC.

Restore (drill / recovery) is the reverse and is documented in
runbooks/backup-restore-drill.md — it is a deliberate operator action, not automated.
"""

from __future__ import annotations

import datetime

import httpx

from cani_shared.blob import BlobStore
from cani_shared.config import Settings, get_settings
from cani_shared.logging import configure_logging, get_logger

QDRANT_SNAPSHOTS_CONTAINER = "qdrant-snapshots"

logger = get_logger(__name__)


def snapshot_qdrant_to_blob(settings: Settings) -> str:
    """Create a Qdrant snapshot and upload it to Blob Storage. Returns the blob URI
    (``container/path``). Raises on any failure so the CronJob is marked failed and the
    failure alert path (§13.8) can see it."""
    base = settings.qdrant_url.rstrip("/")
    collection = settings.qdrant_collection

    # Generous timeout: snapshotting scales with collection size, and the download streams
    # the whole file back over HTTP.
    with httpx.Client(timeout=httpx.Timeout(600.0)) as client:
        created = client.post(f"{base}/collections/{collection}/snapshots")
        created.raise_for_status()
        snapshot_name = created.json()["result"]["name"]
        logger.info("qdrant_snapshot_created", snapshot=snapshot_name, collection=collection)

        try:
            download = client.get(f"{base}/collections/{collection}/snapshots/{snapshot_name}")
            download.raise_for_status()
            data = download.content

            timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
            path = f"{collection}/{timestamp}_{snapshot_name}"
            BlobStore(settings.azure_storage_connection_string).upload(
                container=QDRANT_SNAPSHOTS_CONTAINER, path=path, data=data, overwrite=False
            )
            blob_uri = f"{QDRANT_SNAPSHOTS_CONTAINER}/{path}"
            logger.info("qdrant_snapshot_uploaded", blob_uri=blob_uri, size_bytes=len(data))
            return blob_uri
        finally:
            # Always free the PVC copy — the durable copy is the blob. Best-effort: a
            # failed delete must not mask a successful (or failing) upload above.
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
