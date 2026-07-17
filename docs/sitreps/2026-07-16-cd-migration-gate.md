SITREP — CanI Platform
Date: 2026-07-16 (late) | Branch: main | Sprint 1, day 3 of 14

1. LAST COMPLETED
Closed the follow-up gap that D2's deploy exposed: app-cd-dev now runs database
migrations as a gating Kubernetes Job before the app rollout, so a schema change can
never reach the cluster behind the code that depends on it (PR #9, merged 216aa80). The
migrate image (db/Dockerfile) is built in the pipeline; the deploy blocks on the Job's
completion; the trigger now includes db/**; and the smoke check additionally calls whoami,
which queries the revocation column, so the exact class of bug that shipped silently with
D2 would now fail the deploy. Verified end to end via a workflow_dispatch run: the Job
(cani-migrate-216aa804433d) created, condition met, migrate.py reported both migrations
already-applied (idempotent), and the dev-login + whoami smoke passed green.

2. WHERE WE ARE NOW
- Sprint 1 functionally complete: A1-A2, B1-B2, C1-C3, D1, D2 all done and verified live
- CD hardened and proven: unattended deploy with a migration gate + a smoke check that
  now catches schema/code drift; full app-cd-dev run green in real CI
- Dev AKS cluster healthy; D2 (entitlement revocation) verified live earlier today
- Working tree clean; main synced; no open PRs
- Only the Sprint 1 closeout gate remains open on the board
- Watch item: NetworkPolicies may be unenforced — no policy engine set in the Pulumi
  cluster config; deny-by-default rules likely decorative, still not verified

3. NEXT STEPS
1. Sprint 1 closeout gate: confirm CI/infra-preview/infra-apply/app-cd-dev all green and
   implementation-status reflects live-vs-scaffolded truth, then mark Sprint 1 complete
2. Verify whether NetworkPolicies actually enforce; if not, enable a policy engine in
   infra/modules/compute_aks.py (node-pool-affecting change — plan it)
3. Phase 2 openers once Sprint 1 closes: Application Insights + alerts (§13), backup and
   restore drills (§9.10), malware scanning on upload (§8.11)
4. Smaller hygiene: apply the cani-hub-oidc secret to AKS so real OIDC login works there
   (dev-login covers it today; localhost redirect until ingress exists)
