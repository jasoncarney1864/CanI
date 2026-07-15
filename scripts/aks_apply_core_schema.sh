#!/usr/bin/env bash
set -euo pipefail

POD=$(kubectl -n docs-platform get pod -l app=docs-api -o jsonpath='{.items[0].metadata.name}')

kubectl -n docs-platform exec -i "$POD" -- python - <<'PY'
import os
import psycopg

sql = """
CREATE TABLE IF NOT EXISTS users (
    user_id       UUID PRIMARY KEY,
    idp_subject   TEXT NOT NULL UNIQUE,
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS entitlements (
    user_id     UUID NOT NULL REFERENCES users(user_id),
    entitlement TEXT NOT NULL,
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at  TIMESTAMPTZ,
    PRIMARY KEY (user_id, entitlement)
);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_event_id UUID PRIMARY KEY,
    event_type     TEXT NOT NULL,
    actor_user_id  UUID,
    detail         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_events_actor ON audit_events (actor_user_id, created_at);

CREATE TABLE IF NOT EXISTS documents (
    document_id      UUID PRIMARY KEY,
    owner_user_id    UUID NOT NULL REFERENCES users(user_id),
    title            TEXT NOT NULL,
    source_type      TEXT NOT NULL,
    current_status   TEXT NOT NULL,
    checksum         TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_documents_owner ON documents (owner_user_id, document_id);
CREATE INDEX IF NOT EXISTS idx_documents_owner_checksum ON documents (owner_user_id, checksum);

CREATE TABLE IF NOT EXISTS document_versions (
    document_version_id     UUID PRIMARY KEY,
    document_id             UUID NOT NULL REFERENCES documents(document_id),
    owner_user_id           UUID NOT NULL REFERENCES users(user_id),
    blob_uri                TEXT NOT NULL,
    extractor_version       TEXT,
    extracted_at            TIMESTAMPTZ,
    page_count              INT,
    classification_label    TEXT,
    classification_confidence DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_document_versions_owner ON document_versions (owner_user_id, document_version_id);
CREATE INDEX IF NOT EXISTS idx_document_versions_document ON document_versions (owner_user_id, document_id);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    ingestion_job_id      UUID PRIMARY KEY,
    document_version_id   UUID NOT NULL REFERENCES document_versions(document_version_id),
    owner_user_id         UUID NOT NULL REFERENCES users(user_id),
    stage                 TEXT NOT NULL,
    status                TEXT NOT NULL,
    attempt_count         INT NOT NULL DEFAULT 0,
    error_code            TEXT,
    error_detail          TEXT,
    started_at            TIMESTAMPTZ,
    finished_at           TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_owner ON ingestion_jobs (owner_user_id, ingestion_job_id);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status ON ingestion_jobs (status, started_at);

CREATE TABLE IF NOT EXISTS chunk_manifests (
    chunk_id              UUID PRIMARY KEY,
    document_version_id   UUID NOT NULL REFERENCES document_versions(document_version_id),
    owner_user_id         UUID NOT NULL REFERENCES users(user_id),
    document_id           UUID NOT NULL REFERENCES documents(document_id),
    page_start            INT NOT NULL,
    page_end              INT NOT NULL,
    section_label         TEXT,
    chunk_index           INT NOT NULL,
    token_count           INT NOT NULL,
    embedding_version     TEXT NOT NULL,
    qdrant_point_id       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunk_manifests_owner ON chunk_manifests (owner_user_id, document_version_id);

CREATE TABLE IF NOT EXISTS query_audit (
    query_id              UUID PRIMARY KEY,
    owner_user_id         UUID NOT NULL REFERENCES users(user_id),
    question_hash         TEXT NOT NULL,
    model_id              TEXT NOT NULL,
    retrieved_chunk_ids   TEXT[] NOT NULL DEFAULT '{}',
    response_status       TEXT NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_query_audit_owner ON query_audit (owner_user_id, created_at);
"""

with psycopg.connect(
    host=os.environ["POSTGRES_HOST"],
    port=os.environ.get("POSTGRES_PORT", "5432"),
    dbname=os.environ["POSTGRES_DB"],
    user=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PASSWORD"],
) as conn:
    with conn.cursor() as cur:
        cur.execute(sql)

print("migration_applied")
PY
