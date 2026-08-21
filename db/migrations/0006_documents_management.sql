-- Documents page management (docs/21): origin/provenance for generated docs,
-- tombstone delete per docs/09 §9.9, deletion job queue, version ordering.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'uploaded',
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS generated_from JSONB;

-- Partial indexes: every live-document query filters deleted_at IS NULL.
CREATE INDEX IF NOT EXISTS idx_documents_owner_live_created
    ON documents (owner_user_id, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_documents_owner_live_updated
    ON documents (owner_user_id, updated_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_documents_owner_live_title
    ON documents (owner_user_id, lower(title)) WHERE deleted_at IS NULL;

-- Version ordering for "latest version" (download endpoint). Existing rows take now();
-- harmless because every existing document has exactly one version.
ALTER TABLE document_versions
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Async deletion queue (docs/09 §9.9 "tombstone job"). No FK to documents on purpose:
-- the job's final step deletes the documents row.
CREATE TABLE IF NOT EXISTS deletion_jobs (
    deletion_job_id UUID PRIMARY KEY,
    document_id     UUID NOT NULL,
    owner_user_id   UUID NOT NULL REFERENCES users(user_id),
    status          TEXT NOT NULL DEFAULT 'queued',   -- queued|processing|done|failed
    attempt_count   INT NOT NULL DEFAULT 0,
    error_detail    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_deletion_jobs_claim ON deletion_jobs (status, created_at);
