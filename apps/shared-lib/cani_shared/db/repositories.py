"""Ownership-scoped data access. Deliberate design constraint (§9.3/§9.11): every function
that reads or writes user-scoped rows takes `owner_user_id` as its mandatory first
parameter after the connection. There is no generic/unscoped "get_document(id)" — callers
cannot accidentally bypass the ownership predicate because the function signature won't
let them.

The one exception is `claim_next_ingestion_job`, which is an internal worker queue-claim
operation across all owners by necessity (a worker has no single caller identity); every
row it returns still carries its own owner_user_id, which callers must thread through to
every subsequent scoped call.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row, tuple_row

from cani_shared.models import ChunkManifest, Document, DocumentVersion, IngestionJob, IngestionStage


def _stringify_uuid_dict_row(cursor):
    """dict_row, but UUID columns come back as str. psycopg3 adapts uuid columns to
    uuid.UUID objects natively, which pydantic v2 refuses to coerce into `str` fields —
    every model in cani_shared.models declares ID fields as str, so this normalizes at
    the query boundary instead of duplicating the conversion at every call site."""
    inner_make_row = dict_row(cursor)

    def make_row(values):
        row = inner_make_row(values)
        return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in row.items()}

    return make_row


def _row_conn(conn: Connection) -> Connection:
    conn.row_factory = _stringify_uuid_dict_row
    return conn


# --- Users & entitlements -------------------------------------------------------------


def get_or_create_user(conn: Connection, idp_subject: str) -> dict[str, Any]:
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE idp_subject = %s", (idp_subject,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE users SET last_login_at = now(), updated_at = now() WHERE user_id = %s RETURNING *",
                (row["user_id"],),
            )
            updated = cur.fetchone()
            conn.commit()
            return updated

        user_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO users (user_id, idp_subject, status, created_at, updated_at, last_login_at)
            VALUES (%s, %s, 'active', now(), now(), now())
            RETURNING *
            """,
            (user_id, idp_subject),
        )
        created = cur.fetchone()
        # Default entitlement set on first sign-in (§7.7): docs access only.
        cur.execute(
            "INSERT INTO entitlements (user_id, entitlement, granted_at) VALUES (%s, 'can_access_docs', now())",
            (user_id,),
        )
        conn.commit()
        return created


def get_user(conn: Connection, user_id: str) -> dict[str, Any]:
    """Fetch a user by user_id."""
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"User {user_id} not found")
        return row


def get_entitlements(conn: Connection, owner_user_id: str) -> list[str]:
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT entitlement FROM entitlements WHERE user_id = %s AND revoked_at IS NULL",
            (owner_user_id,),
        )
        return [r["entitlement"] for r in cur.fetchall()]


def get_auth_revoked_epoch(conn: Connection, user_id: str) -> int | None:
    """Per-user revocation epoch (unix seconds) for D2 (§7.7), or None if never revoked.
    Checked on every authenticated request: any token/session with iat <= this epoch is
    dead regardless of its own expiry.

    Pins tuple_row on its own cursor: pooled connections retain whatever row_factory a
    prior call set (e.g. _row_conn's dict_row), so positional access here would otherwise
    break depending on call order within the connection's lifetime."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT EXTRACT(EPOCH FROM auth_revoked_at)::bigint FROM users WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        if row is None:
            # Unknown user: treat as revoked-from-the-beginning (fail closed).
            return 2**53
        value = row[0]
        return int(value) if value is not None else None


def revoke_entitlement(
    conn: Connection,
    user_id: str,
    entitlement: str,
    *,
    revoke_sessions: bool,
    actor: str,
    reason: str,
) -> None:
    """Marks the entitlement revoked; when revoke_sessions is set (§7.7 'critical
    entitlement removals'), also stamps the user's revocation epoch so every
    previously issued session and access token dies immediately."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE entitlements SET revoked_at = now() "
            "WHERE user_id = %s AND entitlement = %s AND revoked_at IS NULL",
            (user_id, entitlement),
        )
        if revoke_sessions:
            cur.execute(
                "UPDATE users SET auth_revoked_at = now(), updated_at = now() WHERE user_id = %s", (user_id,)
            )
        cur.execute(
            "INSERT INTO audit_events (audit_event_id, event_type, actor_user_id, detail, created_at) "
            "VALUES (%s, %s, NULL, %s, now())",
            (
                str(uuid.uuid4()),
                "entitlement_revoked",
                json.dumps(
                    {
                        "target_user_id": user_id,
                        "entitlement": entitlement,
                        "sessions_revoked": revoke_sessions,
                        "actor": actor,
                        "reason": reason,
                    }
                ),
            ),
        )
        conn.commit()


def revoke_all_user_auth(conn: Connection, user_id: str, *, actor: str, reason: str) -> None:
    """Kills every live session and access token for the user without touching
    entitlements — the runbook containment action for credential compromise."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET auth_revoked_at = now(), updated_at = now() WHERE user_id = %s", (user_id,)
        )
        cur.execute(
            "INSERT INTO audit_events (audit_event_id, event_type, actor_user_id, detail, created_at) "
            "VALUES (%s, %s, NULL, %s, now())",
            (
                str(uuid.uuid4()),
                "user_auth_revoked",
                json.dumps({"target_user_id": user_id, "actor": actor, "reason": reason}),
            ),
        )
        conn.commit()


def record_audit_event(
    conn: Connection, *, event_type: str, actor_user_id: str, detail: dict[str, Any]
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_events (audit_event_id, event_type, actor_user_id, detail, created_at) "
            "VALUES (%s, %s, %s, %s, now())",
            (str(uuid.uuid4()), event_type, actor_user_id, json.dumps(detail)),
        )
        conn.commit()


# --- Documents & ingestion lifecycle ----------------------------------------------------


def create_document(
    conn: Connection, owner_user_id: str, *, title: str, source_type: str, checksum: str
) -> Document:
    _row_conn(conn)
    document_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (document_id, owner_user_id, title, source_type, current_status,
                                    checksum, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, now(), now())
            RETURNING *
            """,
            (document_id, owner_user_id, title, source_type, IngestionStage.QUEUED, checksum),
        )
        row = cur.fetchone()
        conn.commit()
        return Document.model_validate(row)


def get_document(conn: Connection, owner_user_id: str, document_id: str) -> Document | None:
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM documents WHERE owner_user_id = %s AND document_id = %s",
            (owner_user_id, document_id),
        )
        row = cur.fetchone()
        return Document.model_validate(row) if row else None


def list_documents(conn: Connection, owner_user_id: str) -> list[Document]:
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM documents WHERE owner_user_id = %s ORDER BY created_at DESC",
            (owner_user_id,),
        )
        return [Document.model_validate(r) for r in cur.fetchall()]


def get_document_by_checksum(conn: Connection, owner_user_id: str, checksum: str) -> Document | None:
    """Supports idempotent re-upload (§8.3): a duplicate upload from the same owner
    returns the existing document instead of creating a redundant ingestion pipeline run."""
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM documents WHERE owner_user_id = %s AND checksum = %s",
            (owner_user_id, checksum),
        )
        row = cur.fetchone()
        return Document.model_validate(row) if row else None


def get_document_title(conn: Connection, owner_user_id: str, document_id: str) -> str | None:
    # tuple_row pinned for the same reason as get_auth_revoked_epoch: don't depend on
    # the pooled connection's inherited row_factory for positional access.
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT title FROM documents WHERE owner_user_id = %s AND document_id = %s",
            (owner_user_id, document_id),
        )
        row = cur.fetchone()
        return row[0] if row else None


def create_document_version(
    conn: Connection,
    owner_user_id: str,
    document_id: str,
    *,
    blob_uri: str,
    document_version_id: str | None = None,
) -> DocumentVersion:
    _row_conn(conn)
    document_version_id = document_version_id or str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO document_versions (document_version_id, document_id, owner_user_id, blob_uri)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (document_version_id, document_id, owner_user_id, blob_uri),
        )
        row = cur.fetchone()
        conn.commit()
        return DocumentVersion.model_validate(row)


def get_document_version(
    conn: Connection, owner_user_id: str, document_version_id: str
) -> DocumentVersion | None:
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM document_versions WHERE owner_user_id = %s AND document_version_id = %s",
            (owner_user_id, document_version_id),
        )
        row = cur.fetchone()
        return DocumentVersion.model_validate(row) if row else None


def update_document_version_extraction(
    conn: Connection,
    owner_user_id: str,
    document_version_id: str,
    *,
    extractor_version: str,
    page_count: int,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE document_versions
            SET extractor_version = %s, extracted_at = now(), page_count = %s
            WHERE owner_user_id = %s AND document_version_id = %s
            """,
            (extractor_version, page_count, owner_user_id, document_version_id),
        )
        conn.commit()


def create_ingestion_job(conn: Connection, owner_user_id: str, document_version_id: str) -> IngestionJob:
    _row_conn(conn)
    job_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_jobs (ingestion_job_id, document_version_id, owner_user_id,
                                         stage, status, attempt_count, started_at)
            VALUES (%s, %s, %s, %s, 'queued', 0, now())
            RETURNING *
            """,
            (job_id, document_version_id, owner_user_id, IngestionStage.QUEUED),
        )
        row = cur.fetchone()
        conn.commit()
        return IngestionJob.model_validate(row)


def claim_next_ingestion_job(conn: Connection) -> IngestionJob | None:
    """Worker-internal queue claim. Not owner-scoped by design: a background worker has
    no caller identity and must be able to process jobs for every owner. `SELECT ... FOR
    UPDATE SKIP LOCKED` gives us at-least-once delivery with safe concurrent workers
    without standing up a separate broker (§8.10)."""
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM ingestion_jobs
            WHERE status IN ('queued', 'retry_pending')
            ORDER BY started_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            conn.commit()
            return None
        cur.execute(
            "UPDATE ingestion_jobs SET status = 'processing', attempt_count = attempt_count + 1 "
            "WHERE ingestion_job_id = %s RETURNING *",
            (row["ingestion_job_id"],),
        )
        updated = cur.fetchone()
        conn.commit()
        return IngestionJob.model_validate(updated)


MAX_INGESTION_ATTEMPTS = 5


def update_ingestion_job_stage(
    conn: Connection,
    owner_user_id: str,
    ingestion_job_id: str,
    *,
    stage: IngestionStage,
    status: str,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingestion_jobs
            SET stage = %s, status = %s, error_code = %s, error_detail = %s,
                finished_at = CASE WHEN %s IN ('indexed', 'unpacked', 'failed') THEN now() ELSE finished_at END
            WHERE owner_user_id = %s AND ingestion_job_id = %s
            """,
            (stage, status, error_code, error_detail, status, owner_user_id, ingestion_job_id),
        )
        conn.commit()


def mark_document_status(
    conn: Connection, owner_user_id: str, document_id: str, status: IngestionStage
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE documents SET current_status = %s, updated_at = now() WHERE owner_user_id = %s AND document_id = %s",
            (status, owner_user_id, document_id),
        )
        conn.commit()


def update_document_title(conn: Connection, owner_user_id: str, document_id: str, title: str) -> None:
    """Update a document's title (e.g. after LLM generation from extracted text)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE documents SET title = %s, updated_at = now() WHERE owner_user_id = %s AND document_id = %s",
            (title, owner_user_id, document_id),
        )
        conn.commit()


def insert_chunk_manifests(conn: Connection, owner_user_id: str, chunks: list[ChunkManifest]) -> None:
    with conn.cursor() as cur:
        for c in chunks:
            cur.execute(
                """
                INSERT INTO chunk_manifests (chunk_id, document_version_id, owner_user_id, document_id,
                                              page_start, page_end, section_label, chunk_index,
                                              token_count, embedding_version, qdrant_point_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    c.chunk_id,
                    c.document_version_id,
                    owner_user_id,
                    c.document_id,
                    c.page_start,
                    c.page_end,
                    c.section_label,
                    c.chunk_index,
                    c.token_count,
                    c.embedding_version,
                    c.qdrant_point_id,
                ),
            )
        conn.commit()


def record_query_audit(
    conn: Connection,
    owner_user_id: str,
    *,
    question_hash: str,
    model_id: str,
    retrieved_chunk_ids: list[str],
    response_status: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO query_audit (query_id, owner_user_id, question_hash, model_id,
                                      retrieved_chunk_ids, response_status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, now())
            """,
            (str(uuid.uuid4()), owner_user_id, question_hash, model_id, retrieved_chunk_ids, response_status),
        )
        conn.commit()
