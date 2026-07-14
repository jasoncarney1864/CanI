# Runbook: suspected cross-tenant data access

P1 per docs/14-security-and-compliance.md §14.11. Any confirmed instance is a hard stop —
§15.10: "Any trade-off that affects user isolation or data protection is rejected."

## 1. Detect / confirm

- Check `query_audit` for the affected `owner_user_id` and correlate `retrieved_chunk_ids`
  against `chunk_manifests.owner_user_id` for the same rows — every retrieved chunk must
  belong to the querying owner. A mismatch is a confirmed isolation failure.
- Check `audit_events` for the request's `trace_id` to see the full authn/authz path.
- The isolation guarantee in this codebase rests on two independent layers — check both:
  1. `cani_shared.auth.entitlements` — token/entitlement validation on every spoke call.
  2. `cani_shared.vector.qdrant_client.OwnerScopedQdrant` — mandatory owner payload filter,
     fails closed (`MissingOwnerFilterError`) if a caller ever omits it, and independently
     re-verifies `payload["owner_user_id"]` on every returned point before trusting Qdrant's
     server-side filter.
- If the leak is NOT explained by a code path bypassing one of the above, treat it as a
  possible data-layer compromise (Postgres/Qdrant access outside the app), not an app bug.

## 2. Contain

- Revoke the affected user(s)' entitlements immediately (`entitlements.revoked_at`) —
  forces re-auth and blocks further access (§7.7: "Existing sessions are revoked on
  critical entitlement removals" — session revocation on entitlement change is not yet
  implemented in this MVP pass; see the gap report. Until it is, also rotate
  `CANI_TOKEN_SIGNING_SECRET` to invalidate all outstanding access tokens platform-wide).
- If the cause is a code defect in ownership scoping, take the affected service out of
  rotation before deploying a fix.

## 3. Eradicate & recover

- Patch the scoping gap; add a regression test mirroring `tests/integration/test_isolation.py`
  for the exact scenario before closing.
- Re-run the full `tests/integration` suite against the fix.

## 4. Post-incident

- Record: affected owner(s), what was exposed, root cause, and the regression test added.
- This is a mandatory postmortem — not optional — per the P1 severity model in §14.11.
