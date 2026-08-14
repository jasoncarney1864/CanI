"""Scheduled batch refresh for the public-law corpus (docs/20-public-law-corpus-design.md
§20.7). Entrypoint: `python -m ingestion_worker_app.law_refresh`.

Lives in ingestion-worker rather than a new package because it shares every dependency
ingestion already has (blob, embedder, Qdrant, repositories, chunk budget), and a sixth
installable package is overhead a solo-dev monorepo doesn't need. Not woven into the poll
loop either: this is scheduled batch work (a weekly Container Apps Job in prod), not
queue-driven per-user work, and mixing them would couple a scraper's failure modes into the
user ingestion path.

Per-source flow is diff-based and idempotent (§20.7): unchanged sections are never
re-embedded, changed/new sections get a deterministic uuid5 point id so re-upserts replace
in place, and removed (repealed) sections get deleted. One source's failure — a fetch error,
a markup change, anything — is caught by the per-source loop below and logged as
`law_source_failed`; it must never block the other sources, and because
replace_law_chunk_manifests only runs after a source's fetch+embed+upsert all succeed, a
failed refresh leaves that source's previous good version live in Qdrant. A failed scrape
degrades to slightly-stale law, never to no law.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from cani_shared.blob import PUBLIC_LAW_SNAPSHOTS_CONTAINER, BlobStore
from cani_shared.config import Settings, get_settings
from cani_shared.db.pool import get_pool
from cani_shared.db.repositories import (
    create_law_source_version,
    get_latest_law_chunk_manifests,
    get_latest_law_source_version,
    list_enabled_law_sources,
    replace_law_chunk_manifests,
    touch_law_source_checked,
    update_law_source_version_status,
)
from cani_shared.law.fetcher import LawSourceFetcher
from cani_shared.law.sectioner import LawChunk, chunk_sections
from cani_shared.logging import configure_logging, get_logger
from cani_shared.models import LawChunkManifest, LawSource
from cani_shared.providers.embedder import Embedder
from cani_shared.providers.factory import build_embedder, build_law_fetchers
from cani_shared.telemetry import configure_telemetry
from cani_shared.vector.public_law_client import PublicLawQdrant
from psycopg import Connection

configure_logging("ingestion-worker")
logger = get_logger(__name__)

# Fixed, deterministic namespace for point ids — derived once from a stable URL rather than
# a random literal, so its provenance is obvious to a future reader.
LAW_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://canido.co/law-corpus")

_EXTENSION_BY_CONTENT_TYPE = {"text/html": "html", "text/plain": "txt"}


def _point_id(source_key: str, citation: str, part: int) -> str:
    """Deterministic per (source, citation, part) — this IS the identity that survives
    across refreshes (§20.7): an unchanged section produces the same id every run, so
    upserting it again is a no-op replace rather than a new point."""
    return str(uuid.uuid5(LAW_NS, f"{source_key}:{citation}:{part}"))


def _extension_for_content_type(content_type: str) -> str:
    return _EXTENSION_BY_CONTENT_TYPE.get(content_type, "bin")


def _manifest(
    chunk: LawChunk,
    point_id: str,
    version_id: str,
    source: LawSource,
    content_hash: str,
    embedding_version: str,
) -> LawChunkManifest:
    # chunk_id deliberately equals qdrant_point_id here, unlike ChunkManifest (user docs)
    # where chunk_id is a fresh uuid4 independent of the point id. Both being the same
    # deterministic value is what makes "unchanged section -> same row every refresh" true
    # without any extra bookkeeping to look up a prior chunk_id by citation.
    return LawChunkManifest(
        chunk_id=point_id,
        law_source_version_id=version_id,
        law_source_id=source.law_source_id,
        citation=chunk.citation,
        heading=chunk.heading,
        source_url=chunk.source_url,
        chunk_index=chunk.chunk_index,
        token_count=chunk.token_count,
        content_sha256=content_hash,
        embedding_version=embedding_version,
        qdrant_point_id=point_id,
    )


def refresh_source(
    conn: Connection,
    source: LawSource,
    *,
    fetcher: LawSourceFetcher,
    blob_store: BlobStore,
    embedder: Embedder,
    qdrant: PublicLawQdrant,
    fetcher_kind: str,
) -> None:
    log = logger.bind(
        source_key=source.source_key, jurisdiction=source.jurisdiction, fetcher_kind=fetcher_kind
    )

    document = fetcher.fetch()
    checksum = hashlib.sha256(document.raw_bytes).hexdigest()

    previous_version = get_latest_law_source_version(conn, source.law_source_id)
    if previous_version is not None and previous_version.checksum == checksum:
        touch_law_source_checked(conn, source.law_source_id)
        log.info("law_refresh_completed", result="unchanged")
        return

    version_id = str(uuid.uuid4())
    blob_path = f"{source.source_key}/{version_id}/raw.{_extension_for_content_type(document.content_type)}"
    blob_uri = blob_store.upload(
        container=PUBLIC_LAW_SNAPSHOTS_CONTAINER, path=blob_path, data=document.raw_bytes
    )

    chunks = chunk_sections(document.sections)
    previous_by_point_id = {
        m.qdrant_point_id: m for m in get_latest_law_chunk_manifests(conn, source.law_source_id)
    }
    fetched_at = datetime.now(UTC).isoformat()

    new_manifests: list[LawChunkManifest] = []
    new_point_ids: set[str] = set()
    embedded_count = 0
    for chunk in chunks:
        point_id = _point_id(source.source_key, chunk.citation, chunk.part)
        new_point_ids.add(point_id)
        content_hash = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()

        previous = previous_by_point_id.get(point_id)
        # Re-embed unless BOTH the text and the embedding space are unchanged — a
        # content-hash match alone isn't enough if the embedder itself changed (e.g. fake ->
        # real) since the previous vector would silently be from a different embedding space.
        if previous is not None and previous.content_sha256 == content_hash:
            if previous.embedding_version == embedder.embedding_version:
                new_manifests.append(
                    _manifest(chunk, point_id, version_id, source, content_hash, previous.embedding_version)
                )
                continue

        vector = embedder.embed_batch([chunk.text])[0]
        display_heading = f"{chunk.citation}  {chunk.heading}" if chunk.heading else chunk.citation
        qdrant.upsert_section(
            vector=vector,
            point_id=point_id,
            payload={
                "chunk_id": point_id,
                "chunk_text": chunk.text,
                "source_kind": source.source_kind,
                "jurisdiction": source.jurisdiction,
                "law_source_id": source.law_source_id,
                "citation": chunk.citation,
                "heading": display_heading,
                "source_url": chunk.source_url,
                "chunk_index": chunk.chunk_index,
                "fetched_at": fetched_at,
                "content_sha256": content_hash,
                "embedding_version": embedder.embedding_version,
            },
        )
        embedded_count += 1
        new_manifests.append(
            _manifest(chunk, point_id, version_id, source, content_hash, embedder.embedding_version)
        )

    removed_point_ids = set(previous_by_point_id) - new_point_ids
    if removed_point_ids:
        qdrant.delete_points(list(removed_point_ids))

    create_law_source_version(
        conn,
        source.law_source_id,
        law_source_version_id=version_id,
        blob_uri=blob_uri,
        checksum=checksum,
        section_count=len(document.sections),
        status="fetched",
    )
    # Manifest replace is the last write, deliberately: everything above this line can fail
    # without corrupting state (nothing has been swapped in as "current" yet).
    replace_law_chunk_manifests(conn, source.law_source_id, new_manifests)
    update_law_source_version_status(conn, version_id, "indexed")
    touch_law_source_checked(conn, source.law_source_id)
    log.info(
        "law_refresh_completed",
        result="indexed",
        section_count=len(document.sections),
        chunk_count=len(new_manifests),
        embedded_count=embedded_count,
        removed_count=len(removed_point_ids),
    )


def run_refresh(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    configure_telemetry("ingestion-worker", settings)

    if not settings.law_qdrant_collection:
        logger.warning("law_refresh_skipped", reason="CANI_LAW_QDRANT_COLLECTION not configured")
        return

    pool = get_pool(settings.postgres_dsn)
    blob_store = BlobStore(settings.azure_storage_connection_string)
    blob_store.ensure_containers()
    embedder = build_embedder(settings)
    fetchers = build_law_fetchers(settings)
    fetcher_kind = "real" if settings.law_fetch_enabled else "fake"

    qdrant = PublicLawQdrant(settings.qdrant_url, settings.law_qdrant_collection, settings.qdrant_api_key)
    qdrant.ensure_collection(embedder.vector_size)

    logger.info("law_refresh_started", fetcher_kind=fetcher_kind)
    with pool.connection() as conn:
        sources = list_enabled_law_sources(conn)
        for source in sources:
            fetcher = fetchers.get(source.source_key)
            if fetcher is None:
                logger.warning(
                    "law_source_skipped", source_key=source.source_key, reason="no fetcher registered"
                )
                continue
            try:
                refresh_source(
                    conn,
                    source,
                    fetcher=fetcher,
                    blob_store=blob_store,
                    embedder=embedder,
                    qdrant=qdrant,
                    fetcher_kind=fetcher_kind,
                )
            except Exception as exc:  # noqa: BLE001 - one source's failure must never block the others (§20.7)
                conn.rollback()
                logger.error("law_source_failed", source_key=source.source_key, error=str(exc))

    logger.info("law_refresh_finished", source_count=len(sources))


if __name__ == "__main__":
    run_refresh()
