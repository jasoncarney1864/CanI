SITREP — CanI Platform
Date: 2026-07-15 | Branch: chore/validate-infra-preview | Sprint 1, day 2 of 14

1. LAST COMPLETED
Repaired the crashlooping KEDA operator and wired autoscaling end to end (9ca21ec).
Root cause was a partial KEDA install missing the ScaledJob CRD, not the suspected
missing TriggerAuthentication; fixed by server-side applying the complete v2.14.0 CRD
bundle. The ingestion-worker ScaledObject is now Ready and reading live queue depth
through a new least-privilege keda_scaler database role. Earlier today: full rotation
of all exposed dev secrets (195d4c2) after moving the plaintext bootstrap file out of
the repo and OneDrive (0590426), schema-apply script consolidated onto the real
migration runner (f44bf4b), and the implementation-status doc resynced with the live
B1/B2/C1 state (de06695).

2. WHERE WE ARE NOW
- Dev AKS cluster live and healthy: all four services Running, KEDA operator at
  0 restarts, ScaledObject Ready=True, HPA reading queue depth (verified 22:27 UTC)
- All exposed credentials rotated and verified (dev-login 200 = live DB write on the
  new password; blob access confirmed on the new key; old storage key1 burned)
- Local checks green: 29 unit tests, 2 integration tests, lint and format clean
- Working tree clean; 8 commits on this branch, none pushed
- Watch item: storage account IaC says public access disabled but the app uses an
  account-key connection string with no private endpoints - likely portal drift
- Watch item: NetworkPolicies may be unenforced (no network policy engine in the
  Pulumi cluster config) - not yet verified

3. NEXT STEPS
1. Fix the app-cd-dev.yml post-deploy smoke check - it curls dev.cani.internal, which
   can never resolve from a GitHub runner (blocks C3, app CD activation)
2. Verify whether NetworkPolicies actually enforce; if not, enable a policy engine in
   infra/modules/compute_aks.py
3. Complete C2: make the kustomize overlay apply the routine deploy path
4. Push and PR this branch (8 unpushed commits including security fixes)
