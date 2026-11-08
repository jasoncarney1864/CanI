-- 0009: vectors move into Postgres (pgvector), replacing the external Qdrant store.
--
-- Why: the 2026-08-09 incident (docs/sitreps/2026-08-09-qdrant-corruption-and-missing-backups.md)
-- was a second datastore with its own backup job that was defined but never applied, and a
-- reconciliation (Qdrant point count vs chunk_manifests) that could never be closed. With the
-- embeddings in the same database as the manifests, a chunk and its vector are written in
-- one transaction, deletion is a cascade in the same transaction, and the Postgres backup
-- covers both. It also removes the only paid-or-free-tier external dependency from the
-- 2026-11 low-cost rebuild (docs/adr/adr-008-vector-store-pgvector.md).
--
-- Azure Database for PostgreSQL Flexible Server must allow-list the extension first
-- (server parameter `azure.extensions` must include VECTOR) or CREATE EXTENSION fails.
-- The local docker-compose image is pgvector/pgvector:pg16, which ships it.

CREATE EXTENSION IF NOT EXISTS vector;

-- The embedding column is deliberately untyped (`vector`, no fixed dimension). The width is
-- decided by the configured embedder at runtime (32 for the deterministic fake, 1536 for
-- text-embedding-3-small), and the store's ensure_collection() builds a dimension-specific
-- expression index and refuses to run against rows of a different width — the same
-- fakes-in-prod tripwire the Qdrant wrapper had (CLAUDE.md "Fake providers fail open").

CREATE TABLE IF NOT EXISTS chunk_embeddings (
    point_id        TEXT PRIMARY KEY,
    owner_user_id   TEXT NOT NULL,
    document_id     TEXT NOT NULL,
    spoke           TEXT,
    origin          TEXT,
    taxonomy_tags   TEXT[] NOT NULL DEFAULT '{}',
    chunk_index     INT,
    embedding       vector NOT NULL,
    -- The full chunk payload (chunk_text, page_start/end, section_label, ...) exactly as
    -- retrieval and the Document Viewer consume it. The indexed columns above are copies
    -- of the filterable fields; the payload is the record.
    payload         JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_owner_document ON chunk_embeddings (owner_user_id, document_id);
CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_owner_spoke ON chunk_embeddings (owner_user_id, spoke);

-- Public-law corpus (docs/20 §20.3): no owner, mandatory jurisdiction filter instead.
CREATE TABLE IF NOT EXISTS law_chunk_embeddings (
    point_id        TEXT PRIMARY KEY,
    jurisdiction    TEXT NOT NULL,
    source_kind     TEXT,
    law_source_id   TEXT,
    embedding       vector NOT NULL,
    payload         JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_law_chunk_embeddings_jurisdiction ON law_chunk_embeddings (jurisdiction);

-- The manifest ledgers keep pointing at the vector row by id; only the name loses its
-- vendor prefix.
ALTER TABLE chunk_manifests RENAME COLUMN qdrant_point_id TO point_id;
ALTER TABLE law_chunk_manifests RENAME COLUMN qdrant_point_id TO point_id;
