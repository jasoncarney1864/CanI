-- D2 (docs/07 §7.7): entitlement revocation must invalidate live sessions and tokens.
-- auth_revoked_at is a per-user revocation epoch: any session or access token whose
-- iat is at or before this instant is rejected, even if its signature and expiry are
-- otherwise valid. NULL = never revoked (the common fast path).
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_revoked_at TIMESTAMPTZ;
