SITREP — CanI Platform
Date: 2026-07-15 (night) | Branch: chore/validate-infra-preview (merged to main as d18a855) | Sprint 1, day 2 of 14

1. LAST COMPLETED
C3 is activated: PR #2 (12 commits - secret handling, KEDA repair, private-cluster CD,
IaC drift fix) merged to main as d18a855 after all seven checks went green, and the
full CD pipeline executed end to end for the first time. The first run exposed exactly
one gap: the GitHub dev environment changes the OIDC token subject to environment:dev,
and neither app registration had a federated credential for it - only pull_request and
ref:refs/heads/main. Fixed by adding cani-env-dev credentials to both apps (plus a
pre-merge grant of AKS RBAC Cluster Admin, cluster-scoped, to the workload identity).
On rerun everything passed: four images built and pushed with the merge SHA, both
pulumi applies were pure no-ops (23 and 17 unchanged - the drift fix held), 31 objects
applied via command invoke, all four rollouts green, and every smoke check passed
including the dev-login probe that proves a live Postgres write.

2. WHERE WE ARE NOW
- Continuous deployment to dev is real: any apps/** push to main now builds, deploys,
  and functionally verifies automatically (rollout gates + in-cluster smoke checks)
- Cluster runs immutable SHA-tagged images from the pipeline, replacing the
  hand-pushed :dev tags
- Dev cluster healthy at last verification (post-deploy smoke checks, ~23:55 UTC)
- Pulumi state matches live Azure on both stacks; merge-triggered applies confirmed
  no-op in CI
- Working tree: one uncommitted sitrep file; feature branch fully merged - local
  checkout still on it, main not yet pulled locally
- Watch item: NetworkPolicies likely unenforced (no policy engine in cluster config) -
  still not verified
- Watch item: sprint board C2/C3 items still show "not started" - board lags reality

3. NEXT STEPS
1. Update sprint board: C2 exercised in substance, C3 done criteria met (owner: Jason)
2. Verify NetworkPolicy enforcement; if unenforced, enable a policy engine in
   infra/modules/compute_aks.py (would be a node-pool-affecting change - plan it)
3. Local housekeeping: switch to main, pull, delete merged feature branch, commit the
   outstanding sitrep file
4. Next sprint item: Entra External ID tenant + real OIDC swap in hub-api (D1)
