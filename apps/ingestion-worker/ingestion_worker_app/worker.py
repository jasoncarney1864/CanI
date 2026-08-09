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
from cani_shared.providers.factory import build_embedder, build_extractor, build_malware_scanner
from cani_shared.telemetry import configure_telemetry
from cani_shared.vector.qdrant_client import OwnerScopedQdrant

from ingestion_worker_app.pipeline import handle_job_failure, process_job

POLL_INTERVAL_SECONDS = 3

configure_logging("ingestion-worker")
logger = get_logger(__name__)

# Lazy initialization flag for Qdrant collection — postpone ensure_collection()
# until the first job is claimed instead of blocking startup.
_qdrant_initialized = False


def ensure_qdrant_ready(qdrant: OwnerScopedQdrant, vector_size: int) -> None:
    """Ensure Qdrant collection exists on first job processing (lazy init)."""
    global _qdrant_initialized  # noqa: PLW0603
    if not _qdrant_initialized:
        logger.info("lazy_qdrant_init_start")
        qdrant.ensure_collection(vector_size)
        _qdrant_initialized = True
        logger.info("lazy_qdrant_init_complete")


def run_forever() -> None:
    settings = get_settings()
    # No FastAPI app here (queue poller, no inbound server) — telemetry still captures
    # dependency calls and the stage events this worker emits.
    configure_telemetry("ingestion-worker", settings)
    pool = get_pool(settings.postgres_dsn)
    blob_store = BlobStore(settings.azure_storage_connection_string)
    blob_store.ensure_containers()
    scanner = build_malware_scanner(settings)
    extractor = build_extractor(settings)
    embedder = build_embedder(settings)
    qdrant = OwnerScopedQdrant(settings.qdrant_url, settings.qdrant_collection, settings.qdrant_api_key)
    # Postpone ensure_collection() until first job — avoids startup timeout

    logger.info("ingestion_worker_started")
    while True:
        with pool.connection() as conn:
            job = claim_next_ingestion_job(conn)
            if job is None:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            try:
                # Lazy init: ensure collection exists before processing first job. Kept
                # inside the same try/except as process_job — a transient Qdrant hiccup
                # here must not crash the whole worker process (it previously did,
                # causing a restart storm instead of a simple per-job retry).
                ensure_qdrant_ready(qdrant, embedder.vector_size)
                process_job(
                    conn,
                    job,
                    blob_store=blob_store,
                    scanner=scanner,
                    extractor=extractor,
                    embedder=embedder,
                    qdrant=qdrant,
                )
            except Exception as exc:  # noqa: BLE001 - top-level job loop must never crash the worker
                handle_job_failure(conn, job, exc)
                # Exponential backoff before this job becomes reclaimable again (§8.10) —
                # without a delay here, a persistently-failing job gets hammered in a tight
                # loop instead of spacing out retries.
                time.sleep(min(2**job.attempt_count, 30))


if __name__ == "__main__":
    run_forever()
