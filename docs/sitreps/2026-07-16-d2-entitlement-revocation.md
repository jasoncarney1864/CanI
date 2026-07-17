SITREP — CanI Platform
Date: 2026-07-16 | Branch: feat/d2-entitlement-revocation (PR #7 open) | Sprint 1, day 3 of 14

1. LAST COMPLETED
D2 (entitlement revocation invalidating live credentials) is code-complete and verified,
open for review as PR #7 (commits 450047d code, 2d3a0e8 docs). Revoking a user now kills
their already-issued session and access tokens on next use — no waiting out the 15-minute
or 12-hour TTL — via a per-user revocation epoch (users.auth_revoked_at, migration 0002)
plus an iat claim on every token, checked on each authenticated request in both spokes and
the hub. Revocation is an audited operator script (scripts/revoke_user_access.py) rather
than an unauthenticated admin endpoint, since admin RBAC does not exist yet. A row-factory
bug (KeyError on a pooled dict_row connection) surfaced during integration verification and
was fixed by pinning tuple_row. This retires the old incident-runbook workaround of rotating
the platform-wide signing secret for single-user containment.

2. WHERE WE ARE NOW
- D2 verified locally: full integration suite 3/3 green including the new test proving a
  live token AND session both die immediately after revocation
- PR #7 merged (7fcae62); all three checks were green before merge
- Deployed to dev AKS via app-cd-dev (green). Migration 0002 does NOT run in the CD
  pipeline, so it was applied separately via the real migrate.py inside a pod (also
  established schema_migrations tracking, previously absent on that DB)
- D2 verified live on AKS: whoami (which now queries auth_revoked_at) returns 200, and a
  full revoke cycle in-cluster confirmed a live session flips to 401 immediately after
  the revocation stamp
- Sprint 1 board: A1-A2, B1-B2, C1-C3, D1, D2 all complete; only the sprint closeout
  gate remains. Week 1 rollup 89% actual (50/56 boxes) vs 60% planned
- Dev AKS cluster healthy at last check; CD pipeline (app-cd-dev) runs unattended on merge
- Watch item: NetworkPolicies may be unenforced (no policy engine in the Pulumi cluster
  config) — still not verified

3. NEXT STEPS
1. New gap surfaced by this deploy: migrations do not run in app-cd-dev, so a schema
   change reaches the cluster only by a manual pod exec, and the smoke check would not
   catch a missing column (it only exercises healthz + dev-login). Add a migration Job
   or pre-deploy step to app-cd-dev before the next schema-bearing release.
2. Sprint 1 closeout gate: confirm CI green, infra-preview/apply and app-cd-dev all
   succeed, implementation-status reflects live-vs-scaffolded truth
3. Verify whether NetworkPolicies actually enforce; if not, enable a policy engine in
   infra/modules/compute_aks.py (node-pool-affecting change — plan it)
4. Phase 2 candidates once Sprint 1 closes: Application Insights/alerts (§13), backup and
   restore drills (§9.10), malware scanning on upload (§8.11)
