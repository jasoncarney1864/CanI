SITREP — CanI Platform
Date: 2026-07-17 | Branch: main | Sprint 1: CLOSED

1. LAST COMPLETED
Sprint 1 is closed (a37d187), 12 days ahead of the 07-28 target. The final piece was
NetworkPolicy enforcement (PR #10): the cluster had been running networkPolicy=none, so
the deny-by-default policies were inert (proven — docs-api reached Qdrant freely). Rewrote
the policies to the real topology (external Postgres and Azure AI via ipBlock/443, worker
egress, DNS, node-subnet probe ingress; the old set would have caused an outage if
enforced), enabled Calico in-place, and verified enforcement live (docs-api to Qdrant now
blocked; retrieval-worker to Qdrant and all auth/DNS/Postgres paths intact). Two latent
defects were fixed on the way: the Qdrant PDB (maxUnavailable 0) that blocked all node
drains, and the maxed regional vCPU quota (user node pools now roll in-place). IaC and
Pulumi state were reconciled, and the post-merge infra-apply-dev on main was confirmed an
in-place update, not a destructive replace. The closeout gate then passed on all four
items and the board was marked complete (PR #12).

2. WHERE WE ARE NOW
- Sprint 1 complete: all workstreams (A access/identity, B infra apply, C AKS+CD, D auth
  hardening) plus NetworkPolicy enforcement done and verified against the live cluster
- Dev platform is live end to end: real Entra login, full auth->upload->ingest->retrieve
  ->cite on AKS, unattended CD with a gating DB migration and in-cluster smoke checks,
  per-request entitlement/credential revocation, and enforced network isolation
- Cluster healthy: networkPolicy=calico, provisioningState Succeeded, all pods running
- CI green (lint, format, 52 unit, integration); working tree clean; main synced; no open PRs
- Constraint to remember: regional vCPU quota is at its 10-core ceiling (cluster fully
  consumes it), which is why node pools roll in-place rather than by surge

3. NEXT STEPS (Phase 2 / operational readiness — none are Sprint 1 blockers)
1. Observability first (§13): Application Insights + Container Insights + the P1/P2 alert
   set. Highest leverage — wanted before real traffic, not after.
2. Resilience: backup/restore drills — Postgres PITR, Qdrant snapshot-to-blob (§9.10).
3. Secrets: cut over from the operator script to Key Vault CSI (secret-provider-class).
4. Edge/app hardening: public ingress + non-localhost OIDC redirect; upload malware scan
   (§8.11); rate limiting (§14.8).
5. Capacity: request a regional vCPU quota increase if the cluster needs to grow or wants
   surge-based upgrades back.
