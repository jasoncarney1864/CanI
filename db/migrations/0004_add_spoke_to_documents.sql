-- Add spoke categorization to documents (Legal, Health, Finance, General)
-- Supports multi-spoke architecture for specialized knowledge domains.

DO $$ BEGIN
    CREATE TYPE document_spoke AS ENUM ('General', 'Legal', 'Health', 'Finance');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

ALTER TABLE documents 
ADD COLUMN IF NOT EXISTS spoke document_spoke NOT NULL DEFAULT 'General';

-- Add index for spoke-based queries
CREATE INDEX IF NOT EXISTS idx_documents_owner_spoke ON documents (owner_user_id, spoke);

-- Backfill: all existing documents default to 'General'
-- (column default handles this automatically)
