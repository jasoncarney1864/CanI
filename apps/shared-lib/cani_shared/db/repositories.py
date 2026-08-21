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

from cani_shared.models import (
    ChunkManifest,
    DeletionJob,
    Document,
    DocumentSpoke,
    DocumentVersion,
    IngestionJob,
    IngestionStage,
    LawChunkManifest,
    LawSource,
    LawSourceVersion,
)


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


def get_or_create_user(conn: Connection, idp_subject: str, display_name: str | None = None) -> dict[str, Any]:
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE idp_subject = %s", (idp_subject,))
        row = cur.fetchone()
        if row:
            # Update last_login_at and display_name on every login
            cur.execute(
                "UPDATE users SET last_login_at = now(), updated_at = now(), display_name = %s WHERE user_id = %s RETURNING *",
                (display_name, row["user_id"]),
            )
            updated = cur.fetchone()
            conn.commit()
            return updated

        user_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO users (user_id, idp_subject, display_name, status, created_at, updated_at, last_login_at)
            VALUES (%s, %s, %s, 'active', now(), now(), now())
            RETURNING *
            """,
            (user_id, idp_subject, display_name),
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
    conn: Connection,
    owner_user_id: str,
    *,
    title: str,
    source_type: str,
    checksum: str,
    spoke: DocumentSpoke = DocumentSpoke.GENERAL,
    origin: str = "uploaded",
    generated_from: dict[str, Any] | None = None,
) -> Document:
    _row_conn(conn)
    document_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (document_id, owner_user_id, title, source_type, current_status,
                                    checksum, spoke, origin, generated_from, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
            RETURNING *
            """,
            (
                document_id,
                owner_user_id,
                title,
                source_type,
                IngestionStage.QUEUED,
                checksum,
                spoke,
                origin,
                json.dumps(generated_from) if generated_from is not None else None,
            ),
        )
        row = cur.fetchone()
        conn.commit()
        return Document.model_validate(row)


def get_document(conn: Connection, owner_user_id: str, document_id: str) -> Document | None:
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM documents WHERE owner_user_id = %s AND document_id = %s AND deleted_at IS NULL",
            (owner_user_id, document_id),
        )
        row = cur.fetchone()
        return Document.model_validate(row) if row else None


def get_document_for_delete(conn: Connection, owner_user_id: str, document_id: str) -> Document | None:
    """Like get_document, but does NOT filter deleted_at (docs/21 §1.4 steps 1-2). The
    DELETE handler needs to tell "already tombstoned, cleanup pending" (idempotent 202)
    apart from "never existed / not owned / cleanup already finished" (404) — every other
    caller must keep going through get_document's deleted_at IS NULL filter."""
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM documents WHERE owner_user_id = %s AND document_id = %s",
            (owner_user_id, document_id),
        )
        row = cur.fetchone()
        return Document.model_validate(row) if row else None


def tombstone_document(conn: Connection, owner_user_id: str, document_id: str) -> None:
    """Synchronous half of delete (docs/21 §1.4 step 3): marks the document invisible to
    every deleted_at-filtered query immediately. The async deletion job does the actual
    row/vector/blob removal."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE documents SET deleted_at = now(), updated_at = now() "
            "WHERE owner_user_id = %s AND document_id = %s",
            (owner_user_id, document_id),
        )
        conn.commit()


def cancel_pending_ingestion_jobs(conn: Connection, owner_user_id: str, document_id: str) -> None:
    """Stops a not-yet-started ingestion job from processing a document that's being
    deleted out from under it (docs/21 §1.4 step 3). Only queued/retry_pending jobs are
    claimable (claim_next_ingestion_job's WHERE clause), so a cancelled job can never be
    picked up — a 'processing' job is left alone and handled by the deletion worker's
    single-worker-invariant guard instead (§1.7 step 1)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingestion_jobs
            SET status = 'cancelled'
            WHERE owner_user_id = %s AND status IN ('queued', 'retry_pending')
              AND document_version_id IN (
                  SELECT document_version_id FROM document_versions
                  WHERE owner_user_id = %s AND document_id = %s
              )
            """,
            (owner_user_id, owner_user_id, document_id),
        )
        conn.commit()


# Sort whitelist for list_documents (docs/21 §1.3): the only path user input can reach
# ORDER BY. "title" maps to a case-insensitive expression rather than the raw column so
# A-Z sort matches what the search box's case-insensitive `q` filter already implies.
_LIST_SORT_COLUMNS = {"created_at": "created_at", "updated_at": "updated_at", "title": "lower(title)"}


def list_documents(
    conn: Connection,
    owner_user_id: str,
    *,
    spoke: str | None = None,
    statuses: list[str] | None = None,
    origin: str | None = None,
    title_query: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Document], int]:
    """Filtered, sorted, paginated document listing (docs/21 §1.3). Returns (page items,
    total matching count) so the caller can render a pager without a second round trip.
    Secondary sort is always document_id in the same direction, for a stable order when
    the primary sort column ties (e.g. two documents uploaded in the same second)."""
    sort_column = _LIST_SORT_COLUMNS.get(sort)
    if sort_column is None:
        raise ValueError(f"invalid sort: {sort}")
    if order not in ("asc", "desc"):
        raise ValueError(f"invalid order: {order}")
    _row_conn(conn)

    predicates = ["owner_user_id = %s", "deleted_at IS NULL"]
    params: list[Any] = [owner_user_id]
    if spoke:
        predicates.append("spoke = %s")
        params.append(spoke)
    if statuses:
        predicates.append("current_status = ANY(%s)")
        params.append(statuses)
    if origin:
        predicates.append("origin = %s")
        params.append(origin)
    if title_query:
        # Escaped in Python and passed as an already-lowercased LIKE pattern, so the SQL
        # template never carries a bare literal '%' alongside %s placeholders.
        escaped = title_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        predicates.append("lower(title) LIKE %s ESCAPE '\\'")
        params.append(f"%{escaped.lower()}%")
    where_clause = " AND ".join(predicates)

    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) AS total FROM documents WHERE {where_clause}", params)
        total = cur.fetchone()["total"]

        cur.execute(
            f"""
            SELECT * FROM documents
            WHERE {where_clause}
            ORDER BY {sort_column} {order}, document_id {order}
            LIMIT %s OFFSET %s
            """,
            [*params, limit, offset],
        )
        items = [Document.model_validate(r) for r in cur.fetchall()]
    return items, total


def get_document_by_checksum(conn: Connection, owner_user_id: str, checksum: str) -> Document | None:
    """Supports idempotent re-upload (§8.3): a duplicate upload from the same owner
    returns the existing document instead of creating a redundant ingestion pipeline run."""
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM documents WHERE owner_user_id = %s AND checksum = %s AND deleted_at IS NULL",
            (owner_user_id, checksum),
        )
        row = cur.fetchone()
        return Document.model_validate(row) if row else None


def get_document_title(conn: Connection, owner_user_id: str, document_id: str) -> str | None:
    # tuple_row pinned for the same reason as get_auth_revoked_epoch: don't depend on
    # the pooled connection's inherited row_factory for positional access.
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT title FROM documents WHERE owner_user_id = %s AND document_id = %s AND deleted_at IS NULL",
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


def get_latest_document_version(
    conn: Connection, owner_user_id: str, document_id: str
) -> DocumentVersion | None:
    """Download endpoint's version lookup (docs/21 §2.2 step 2). Every existing document
    has exactly one version today, but ordering by created_at DESC (added by migration
    0006) rather than assuming a single row keeps this correct if re-ingestion ever adds
    a second version later."""
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM document_versions
            WHERE owner_user_id = %s AND document_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (owner_user_id, document_id),
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


def has_processing_ingestion_job(conn: Connection, owner_user_id: str, document_id: str) -> bool:
    """The deletion worker's single-worker-invariant guard (docs/21 §1.7 step 1): true if
    an ingestion job for this document is mid-flight right now. Deleting Qdrant points and
    blobs while a `processing` job is still chunking/embedding would let that job's late
    upserts land after the delete, resurrecting orphan vectors for a document the user
    already deleted — see the comment on process_deletion's guard for the full race and
    why it's only safe with a single worker replica."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            SELECT 1 FROM ingestion_jobs
            WHERE owner_user_id = %s AND status = 'processing'
              AND document_version_id IN (
                  SELECT document_version_id FROM document_versions
                  WHERE owner_user_id = %s AND document_id = %s
              )
            LIMIT 1
            """,
            (owner_user_id, owner_user_id, document_id),
        )
        return cur.fetchone() is not None


def delete_document_cascade(conn: Connection, owner_user_id: str, document_id: str) -> int:
    """Final step of the deletion pipeline (docs/21 §1.7 step 4), run only after the
    document's Qdrant points and blobs are already gone: removes its Postgres rows in
    FK-safe order. Returns the chunk_manifests row count for the audit event. No FK from
    deletion_jobs to documents (§4 migration) — the tombstone job row outliving the
    documents row it cleaned up is deliberate, it's this queue's own history, not
    document metadata."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "DELETE FROM chunk_manifests WHERE owner_user_id = %s AND document_id = %s",
            (owner_user_id, document_id),
        )
        chunks_deleted = cur.rowcount
        cur.execute(
            """
            DELETE FROM ingestion_jobs
            WHERE owner_user_id = %s AND document_version_id IN (
                SELECT document_version_id FROM document_versions
                WHERE owner_user_id = %s AND document_id = %s
            )
            """,
            (owner_user_id, owner_user_id, document_id),
        )
        cur.execute(
            "DELETE FROM document_versions WHERE owner_user_id = %s AND document_id = %s",
            (owner_user_id, document_id),
        )
        cur.execute(
            "DELETE FROM documents WHERE owner_user_id = %s AND document_id = %s",
            (owner_user_id, document_id),
        )
        conn.commit()
        return chunks_deleted


# --- Deletion job queue (docs/09 §9.9, docs/21 §1.7) -----------------------------------
# Second, independent SKIP LOCKED queue alongside ingestion_jobs — same claim discipline,
# same not-owner-scoped claim function for the same reason (a worker has no caller identity).

MAX_DELETION_ATTEMPTS = 5


def create_deletion_job(conn: Connection, owner_user_id: str, document_id: str) -> DeletionJob:
    _row_conn(conn)
    deletion_job_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO deletion_jobs (deletion_job_id, document_id, owner_user_id, status, attempt_count, created_at)
            VALUES (%s, %s, %s, 'queued', 0, now())
            RETURNING *
            """,
            (deletion_job_id, document_id, owner_user_id),
        )
        row = cur.fetchone()
        conn.commit()
        return DeletionJob.model_validate(row)


def claim_next_deletion_job(conn: Connection) -> DeletionJob | None:
    """Worker-internal queue claim, mirroring claim_next_ingestion_job: not owner-scoped by
    necessity, every row returned still carries its own owner_user_id for the caller to
    thread through subsequent scoped calls."""
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM deletion_jobs
            WHERE status = 'queued'
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            conn.commit()
            return None
        cur.execute(
            "UPDATE deletion_jobs SET status = 'processing', attempt_count = attempt_count + 1 "
            "WHERE deletion_job_id = %s RETURNING *",
            (row["deletion_job_id"],),
        )
        updated = cur.fetchone()
        conn.commit()
        return DeletionJob.model_validate(updated)


def finish_deletion_job(
    conn: Connection,
    owner_user_id: str,
    deletion_job_id: str,
    *,
    status: str,
    error_detail: str | None = None,
) -> None:
    """status='queued' puts a retryable failure back where claim_next_deletion_job will
    pick it up again; 'done'/'failed' are terminal and stamp finished_at."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE deletion_jobs
            SET status = %s, error_detail = %s,
                finished_at = CASE WHEN %s IN ('done', 'failed') THEN now() ELSE finished_at END
            WHERE owner_user_id = %s AND deletion_job_id = %s
            """,
            (status, error_detail, status, owner_user_id, deletion_job_id),
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


def update_document_spoke(conn: Connection, owner_user_id: str, document_id: str, spoke: str) -> None:
    """Moves a document to a different spoke (docs/21 follow-up — the Documents page had
    no way to fix a mis-filed upload). This row is what the Documents page reads and what
    an in-flight ingestion job re-reads before upserting a chunk (pipeline.py), so it's
    authoritative going forward; callers are also responsible for propagating the same
    value onto already-indexed Qdrant points via OwnerScopedQdrant.set_document_spoke,
    since retrieval filters on that payload copy, not this column."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE documents SET spoke = %s, updated_at = now() WHERE owner_user_id = %s AND document_id = %s",
            (spoke, owner_user_id, document_id),
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


# --- Public-law corpus (docs/20-public-law-corpus-design.md §20.4) --------------------
#
# Deliberately NOT owner-scoped — this is the first schema in the system that isn't. It's a
# shared registry and ledger, not user data, so none of these take owner_user_id.


def list_enabled_law_sources(conn: Connection) -> list[LawSource]:
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM law_sources WHERE enabled = TRUE ORDER BY source_key")
        return [LawSource.model_validate(r) for r in cur.fetchall()]


def get_latest_law_source_version(conn: Connection, law_source_id: str) -> LawSourceVersion | None:
    """The refresh job's diff baseline (§20.7 step 2): compare this version's checksum
    against a fresh fetch to decide whether the source changed at all."""
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM law_source_versions WHERE law_source_id = %s ORDER BY fetched_at DESC LIMIT 1",
            (law_source_id,),
        )
        row = cur.fetchone()
        return LawSourceVersion.model_validate(row) if row else None


def create_law_source_version(
    conn: Connection,
    law_source_id: str,
    *,
    blob_uri: str,
    checksum: str,
    section_count: int | None,
    status: str,
    law_source_version_id: str | None = None,
) -> LawSourceVersion:
    _row_conn(conn)
    law_source_version_id = law_source_version_id or str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO law_source_versions (law_source_version_id, law_source_id, fetched_at,
                                              blob_uri, checksum, section_count, status)
            VALUES (%s, %s, now(), %s, %s, %s, %s)
            RETURNING *
            """,
            (law_source_version_id, law_source_id, blob_uri, checksum, section_count, status),
        )
        row = cur.fetchone()
        conn.commit()
        return LawSourceVersion.model_validate(row)


def update_law_source_version_status(conn: Connection, law_source_version_id: str, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE law_source_versions SET status = %s WHERE law_source_version_id = %s",
            (status, law_source_version_id),
        )
        conn.commit()


def get_latest_law_chunk_manifests(conn: Connection, law_source_id: str) -> list[LawChunkManifest]:
    """Current manifest rows for a source — the diff baseline for the next refresh
    (§20.7 step 5). Rows are wholesale-replaced by replace_law_chunk_manifests on every
    refresh, so 'latest' here is simply every row currently on file for this source."""
    _row_conn(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM law_chunk_manifests WHERE law_source_id = %s ORDER BY chunk_index",
            (law_source_id,),
        )
        return [LawChunkManifest.model_validate(r) for r in cur.fetchall()]


def replace_law_chunk_manifests(conn: Connection, law_source_id: str, chunks: list[LawChunkManifest]) -> None:
    """Wholesale replace: delete every existing manifest row for this source and insert the
    caller's complete current-state list (§20.7 step 6). The caller is responsible for
    carrying forward unchanged rows (same chunk_id/qdrant_point_id) rather than minting new
    ones — this function doesn't diff, it just makes Postgres match what was passed."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM law_chunk_manifests WHERE law_source_id = %s", (law_source_id,))
        for c in chunks:
            cur.execute(
                """
                INSERT INTO law_chunk_manifests (chunk_id, law_source_version_id, law_source_id, citation,
                                                  heading, source_url, chunk_index, token_count,
                                                  content_sha256, embedding_version, qdrant_point_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    c.chunk_id,
                    c.law_source_version_id,
                    c.law_source_id,
                    c.citation,
                    c.heading,
                    c.source_url,
                    c.chunk_index,
                    c.token_count,
                    c.content_sha256,
                    c.embedding_version,
                    c.qdrant_point_id,
                ),
            )
        conn.commit()


def touch_law_source_checked(conn: Connection, law_source_id: str) -> None:
    """Stamped even when a fetch produced no change, so 'is the refresh job alive' is
    observable from SQL (§20.4) rather than inferable only from version-row timestamps."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE law_sources SET last_checked_at = now() WHERE law_source_id = %s",
            (law_source_id,),
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
