-- Add display_name column to users table
-- Migration 0003: User display names from IdP claims
-- Created: 2026-08-05

ALTER TABLE users 
ADD COLUMN IF NOT EXISTS display_name TEXT;

COMMENT ON COLUMN users.display_name IS 'User-friendly display name extracted from IdP claims (preferred_username, email, or name)';
