SITREP — CanI Platform
Date: 2026-07-15 (late) | Branch: chore/validate-infra-preview | Sprint 1, day 2 of 14

1. LAST COMPLETED
Made app-cd-dev.yml genuinely deployable against the private cluster (3771fef): the
deploy job now renders the kustomize overlay on the runner and applies it via az aks
command invoke (direct kubectl can never reach the private API server from a GitHub
runner), and the dead dev.cani.internal curl is replaced with in-cluster smoke checks -
healthz on all three APIs plus a dev-login POST that proves token minting and a live
Postgres write on every deploy. The same investigation surfaced and defused a merge
landmine (2ff7002): live ACR and storage had been flipped to public access in the
portal while the IaC said Disabled, so the auto-triggered pulumi up on merge would
have reverted both and broken image pulls and blob access. Public access is now an
explicit per-stack flag (dev=true as a documented stopgap, Disabled remains the
default); both stacks previewed, gated, and applied as verified server-side no-ops.

2. WHERE WE ARE NOW
- Dev AKS cluster healthy: all four services Running, KEDA operator stable,
  ScaledObject Ready=True on live queue depth
- Pulumi state now matches live Azure for both stacks - no reverting diffs pending;
  merging this branch no longer risks an outage
- app CD workflow is believed correct end to end but has never executed for real
  (C3 not activated); remaining prerequisite is confirming the workload OIDC
  identity holds runCommand rights on the cluster
- Local checks green: 29 unit tests, 2 integration tests, lint and format clean
- Working tree clean; 10 commits ahead of last-fetched origin, none pushed
- Watch item: NetworkPolicies may be unenforced (no policy engine in the Pulumi
  cluster config) - still not verified

3. NEXT STEPS
1. Push this branch and open the PR - 10 commits including security fixes, and the
   drift fix must land before anything else merges touching infra
2. Activate C3: merge, watch the first real app-cd-dev run, verify runCommand rights
3. Verify whether NetworkPolicies actually enforce; if not, enable a policy engine
   in infra/modules/compute_aks.py
4. Complete C2: make the kustomize overlay apply the routine deploy path
