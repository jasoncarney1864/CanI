"""Polling entrypoint. Uses the ingestion_jobs table itself as the durable work queue
(`SELECT ... FOR UPDATE SKIP LOCKED`) instead of standing up Service Bus/Redis for a
solo-dev MVP (§8.10) — safe for concurrent worker replicas, swappable later if queue
depth ever needs a dedicated broker.
"""

from __future__ import annotations

import time

from cani_shared.blob import BlobStore
from cani_shared.config import get_settings
from cani_shared.db.pool import get_pool
from cani_shared.db.repositories import claim_next_ingestion_job
from cani_shared.logging import configure_logging, get_logger
from cani_shared.providers.factory import build_embedder, build_extractor
from cani_shared.vector.qdrant_client import OwnerScopedQdrant

from ingestion_worker_app.pipeline import handle_job_failure, process_job

POLL_INTERVAL_SECONDS = 3

configure_logging("ingestion-worker")
logger = get_logger(__name__)


def run_forever() -> None:
    settings = get_settings()
    pool = get_pool(settings.postgres_dsn)
    blob_store = BlobStore(settings.azure_storage_connection_string)
    blob_store.ensure_containers()
    extractor = build_extractor(settings)
    embedder = build_embedder(settings)
    qdrant = OwnerScopedQdrant(settings.qdrant_url, settings.qdrant_collection)
    qdrant.ensure_collection(embedder.vector_size)

    logger.info("ingestion_worker_started")
    while True:
        with pool.connection() as conn:
            job = claim_next_ingestion_job(conn)
            if job is None:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            try:
                process_job(
                    conn, job, blob_store=blob_store, extractor=extractor, embedder=embedder, qdrant=qdrant
                )
            except Exception as exc:  # noqa: BLE001 - top-level job loop must never crash the worker
                handle_job_failure(conn, job, exc)
                # Exponential backoff before this job becomes reclaimable again (§8.10) —
                # without a delay here, a persistently-failing job gets hammered in a tight
                # loop instead of spacing out retries.
                time.sleep(min(2**job.attempt_count, 30))


if __name__ == "__main__":
    run_forever()
