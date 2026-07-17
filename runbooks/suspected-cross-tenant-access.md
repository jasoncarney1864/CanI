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

- Kill the affected user's live credentials immediately (D2, §7.7). This invalidates
  every already-issued session and access token on its next use — no waiting out the
  token TTL, and no platform-wide signing-secret rotation:

  ```bash
  python scripts/revoke_user_access.py --user-id <uuid> --all-auth \
      --actor <you> --reason "suspected cross-tenant access, incident <id>"
  ```

  On the private AKS cluster the script runs inside a pod that already has the DB env
  and psycopg — copy it in and exec it (same shape as `scripts/aks_apply_core_schema.sh`):

  ```bash
  POD=$(kubectl -n docs-platform get pod -l app=docs-api -o jsonpath='{.items[0].metadata.name}')
  kubectl -n docs-platform cp scripts/revoke_user_access.py "$POD":/tmp/revoke.py
  kubectl -n docs-platform exec "$POD" -- python /tmp/revoke.py --user-id <uuid> --all-auth \
      --actor <you> --reason "incident <id>"
  ```

  `--all-auth` stamps `users.auth_revoked_at` without touching entitlements; use
  `--entitlement <name> --revoke-sessions` instead if you also want to strip a specific
  spoke grant. Both emit an audit event.
- If the cause is a code defect in ownership scoping, take the affected service out of
  rotation before deploying a fix.
- Platform-wide `CANI_TOKEN_SIGNING_SECRET` rotation (per `rotate-dev-secrets.md`) is no
  longer required for single-user containment — reserve it for signing-key compromise,
  where every user's tokens must die at once.

## 3. Eradicate & recover

- Patch the scoping gap; add a regression test mirroring `tests/integration/test_isolation.py`
  for the exact scenario before closing.
- Re-run the full `tests/integration` suite against the fix.

## 4. Post-incident

- Record: affected owner(s), what was exposed, root cause, and the regression test added.
- This is a mandatory postmortem — not optional — per the P1 severity model in §14.11.
