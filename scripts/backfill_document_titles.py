#!/usr/bin/env python3
"""Backfill script to generate LLM titles for existing documents.

Finds documents with filename-based titles (e.g., ending in .pdf, .jpg) and replaces
them with LLM-generated descriptive titles by reading the document's chunk text from
the vector table, calling Azure OpenAI, and updating documents.title.

Usage:
    python scripts/backfill_document_titles.py [--limit N] [--dry-run]

Options:
    --limit N     Only process N documents (default: all)
    --dry-run     Show what would be changed without updating the database
"""

from __future__ import annotations

import argparse
import sys

from cani_shared.config import get_settings
from cani_shared.db.pool import get_pool
from cani_shared.db.repositories import update_document_title
from cani_shared.logging import configure_logging, get_logger
from cani_shared.vector.store import OwnerScopedVectorStore
from ingestion_worker_app.title_gen import generate_title
from psycopg import Connection

configure_logging("backfill-titles")
logger = get_logger(__name__)


def get_filename_titled_documents(conn: Connection, limit: int | None = None) -> list[dict]:
    """Find documents whose title looks like a filename (contains common file extensions)."""
    with conn.cursor() as cur:
        query = """
            SELECT d.owner_user_id, d.document_id, d.title
            FROM documents d
            WHERE d.title ~* '\\.(pdf|jpg|jpeg|png|gif|docx?|xlsx?|pptx?|txt)$'
            ORDER BY d.created_at DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        cur.execute(query)
        return [{"owner_user_id": row[0], "document_id": row[1], "title": row[2]} for row in cur.fetchall()]


def get_document_text(
    conn: Connection, vectors: OwnerScopedVectorStore, owner_user_id: str, document_id: str
) -> str:
    """All of a document's chunk text in document order — the same owner-scoped read the
    Document Viewer uses (cani_shared.vector.store), so this script never touches the
    embeddings table directly."""
    payloads = vectors.chunks_for_document(
        conn=conn, owner_user_id=str(owner_user_id), document_id=str(document_id)
    )
    return "\n".join(p.get("chunk_text", "") for p in payloads)


def backfill_titles(conn: Connection, settings, limit: int | None = None, dry_run: bool = False) -> None:
    """Backfill LLM-generated titles for documents with filename-based titles."""
    if not settings.azure_ai_providers_configured or not settings.azure_openai_chat_deployment:
        logger.error("Azure OpenAI not configured — cannot generate titles")
        sys.exit(1)

    docs = get_filename_titled_documents(conn, limit)
    vectors = OwnerScopedVectorStore()
    logger.info("backfill_started", document_count=len(docs), dry_run=dry_run)

    for i, doc in enumerate(docs, start=1):
        old_title = doc["title"]
        owner_user_id = doc["owner_user_id"]
        document_id = doc["document_id"]

        try:
            full_text = get_document_text(conn, vectors, owner_user_id, document_id)
            if not full_text.strip():
                logger.warning("no_chunks_found", document_id=document_id, title=old_title)
                continue

            new_title = generate_title(
                full_text,
                endpoint=settings.azure_openai_endpoint,
                api_key=settings.azure_openai_api_key,
                api_version=settings.azure_openai_api_version,
                deployment=settings.azure_openai_chat_deployment,
            )

            if dry_run:
                logger.info("would_update", document_id=document_id, old_title=old_title, new_title=new_title)
            else:
                update_document_title(conn, owner_user_id, document_id, new_title)
                logger.info(
                    "title_updated",
                    document_id=document_id,
                    old_title=old_title,
                    new_title=new_title,
                    progress=f"{i}/{len(docs)}",
                )

        except Exception as exc:  # noqa: BLE001
            logger.error("backfill_error", document_id=document_id, title=old_title, error=str(exc))
            continue

    logger.info("backfill_completed", document_count=len(docs))


def main():
    parser = argparse.ArgumentParser(description="Backfill LLM-generated document titles")
    parser.add_argument("--limit", type=int, help="Only process N documents")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without updating database")
    args = parser.parse_args()

    settings = get_settings()
    pool = get_pool(settings.postgres_dsn)

    with pool.connection() as conn:
        backfill_titles(conn, settings, limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
