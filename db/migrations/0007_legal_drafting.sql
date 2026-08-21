-- Legal-drafting assistant (Sprint 4): conversational template-based drafting on top of
-- the existing dual-source retrieval (OwnerScopedQdrant for the owner's own Legal-spoke
-- documents, PublicLawQdrant for statute reference — docs/20-public-law-corpus-design.md).
-- No new reference-document schema: NRS 162A is seeded below as another law_sources row,
-- the same pattern NRS 116 already uses, so it rides the existing fetch/chunk/embed/refresh
-- pipeline with zero new pipeline code.

CREATE TABLE IF NOT EXISTS legal_templates (
    legal_template_id UUID PRIMARY KEY,
    slug              TEXT NOT NULL,
    version           INT NOT NULL DEFAULT 1,
    title             TEXT NOT NULL,
    category          TEXT NOT NULL,
    jurisdiction_note TEXT NOT NULL,
    schema_json       JSONB NOT NULL,   -- field defs: type/label/required/help
    body_template     TEXT NOT NULL,
    disclaimer_text   TEXT NOT NULL,
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (slug, version)
);
-- The picker's "current version of this template" lookup: one partial-unique row per
-- active slug, so a template can be revised (new version, old row deactivated) without a
-- window where two versions are simultaneously offered to users.
CREATE UNIQUE INDEX IF NOT EXISTS idx_legal_templates_active_slug
    ON legal_templates (slug) WHERE is_active;

CREATE TABLE IF NOT EXISTS legal_drafts (
    legal_draft_id    UUID PRIMARY KEY,
    owner_user_id     UUID NOT NULL REFERENCES users(user_id),
    legal_template_id UUID NOT NULL REFERENCES legal_templates(legal_template_id),
    template_version  INT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'draft',  -- draft|finalized|archived
    field_values_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Set once, on finalize. Doubles as the finalize-idempotency check: a draft with
    -- document_id already set means "already finalized," so a duplicate finalize call
    -- returns the existing document instead of creating a second one/blob.
    document_id       UUID REFERENCES documents(document_id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_legal_drafts_owner ON legal_drafts (owner_user_id, updated_at DESC);

-- Seed: NRS Chapter 162A (Uniform Power of Attorney Act), the statutory basis for the v1
-- durable financial POA template — registered exactly like NRS 116 was (docs/20 §20.11).
INSERT INTO law_sources (
    law_source_id, source_key, display_name, source_kind, jurisdiction,
    citation_prefix, fetch_url, license_note, enabled
) VALUES (
    'b3f8b6b0-6f1a-4b8a-9b0e-1a2b3c4d5e01',
    'nrs-162a',
    'Nevada Revised Statutes, Chapter 162A (Uniform Power of Attorney Act)',
    'state_statute',
    'us-nv',
    'NRS 162A',
    'https://www.leg.state.nv.us/NRS/NRS-162A.html',
    'Public record; scraped from the Nevada Legislature website.',
    TRUE
) ON CONFLICT (source_key) DO NOTHING;
