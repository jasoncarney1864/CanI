-- Public-law corpus registry, snapshots, and chunk ledger (docs/20-public-law-corpus-design.md
-- §20.4). None of these three tables carry owner_user_id — this is deliberate and is the
-- first schema in the system that is NOT user-scoped: the corpus is a single shared
-- collection of public statute text, not user content (§20.3).

CREATE TABLE IF NOT EXISTS law_sources (
    law_source_id   UUID PRIMARY KEY,
    source_key      TEXT NOT NULL UNIQUE,   -- stable machine key, e.g. 'nrs-116', 'washoe-county-code'
    display_name    TEXT NOT NULL,          -- 'Nevada Revised Statutes, Chapter 116'
    source_kind     TEXT NOT NULL,          -- state_statute | county_code | federal_statute | federal_regulation
    jurisdiction    TEXT NOT NULL,          -- 'us-nv', 'us-nv-washoe', 'us'
    citation_prefix TEXT NOT NULL,          -- 'NRS 116', 'WCC'
    fetch_url       TEXT NOT NULL,
    license_note    TEXT NOT NULL,          -- provenance/terms note, e.g. 'public record; scraped from NV Legislature site'
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    last_checked_at TIMESTAMPTZ,            -- updated on every refresh pass, even unchanged
                                             -- fetches, so "is the refresh job alive" is
                                             -- observable from SQL
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per successful fetch that produced new content. blob_uri points at the raw
-- snapshot (audit trail + re-chunk without re-fetch). checksum is over the raw bytes: an
-- unchanged fetch records last_checked_at on law_sources but inserts no version row.
CREATE TABLE IF NOT EXISTS law_source_versions (
    law_source_version_id UUID PRIMARY KEY,
    law_source_id         UUID NOT NULL REFERENCES law_sources(law_source_id),
    fetched_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    blob_uri              TEXT NOT NULL,
    checksum              TEXT NOT NULL,
    section_count         INT,
    status                TEXT NOT NULL   -- fetched | chunked | indexed | failed
);
CREATE INDEX IF NOT EXISTS idx_law_source_versions_source
    ON law_source_versions (law_source_id, fetched_at DESC);

-- Law-corpus analogue of chunk_manifests: Postgres is the ledger of what is in Qdrant, keyed
-- the same way, so drift between the two stores is detectable and repairable. Rows are
-- wholesale-replaced on every refresh (§20.7 step 6) rather than accumulated across
-- versions — qdrant_point_id is deterministic (uuid5 of source_key:citation:part), so an
-- unchanged section keeps the same row/point across refreshes and a changed or removed
-- section's old row is simply not reinserted.
CREATE TABLE IF NOT EXISTS law_chunk_manifests (
    chunk_id              UUID PRIMARY KEY,
    law_source_version_id UUID NOT NULL REFERENCES law_source_versions(law_source_version_id),
    law_source_id         UUID NOT NULL REFERENCES law_sources(law_source_id),
    citation              TEXT NOT NULL,
    heading               TEXT,
    source_url            TEXT NOT NULL,
    chunk_index           INT NOT NULL,
    token_count           INT NOT NULL,
    content_sha256        TEXT NOT NULL,
    embedding_version     TEXT NOT NULL,
    qdrant_point_id       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_law_chunk_manifests_source
    ON law_chunk_manifests (law_source_id, citation);

-- Seed the v1 registry: NRS Chapter 116 is the only source built in Phase 1 (§20.11).
-- County code (Washoe/Municode) stays on hold per §20.12 Q1 — no row for it here.
INSERT INTO law_sources (
    law_source_id, source_key, display_name, source_kind, jurisdiction,
    citation_prefix, fetch_url, license_note, enabled
) VALUES (
    '9a9a2b6e-3b0e-4f5b-8a0e-5e6c2c9b0a01',
    'nrs-116',
    'Nevada Revised Statutes, Chapter 116 (Common-Interest Ownership)',
    'state_statute',
    'us-nv',
    'NRS 116',
    'https://www.leg.state.nv.us/NRS/NRS-116.html',
    'Public record; scraped from the Nevada Legislature website.',
    TRUE
) ON CONFLICT (source_key) DO NOTHING;
