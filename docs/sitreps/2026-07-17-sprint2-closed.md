SITREP — CanI Platform
Date: 2026-07-17 | Branch: main | Sprint: Sprint 2 (Operational readiness) — CLOSED

1. LAST COMPLETED
Sprint 2 is complete. All seven workstream items are done and live-validated where testable, and the closeout gate is met — roughly four weeks ahead of the 2026-08-12 target. The final item, D1 (governance policy baseline), assigned the deferred policy set at management-group scope: allowed locations (Deny), required tags (Audit, via a custom definition, for environment/owner/spoke), storage TLS (Audit), and Key Vault diagnostics (deploy-if-not-exists). Closing D1 surfaced a real access-control gap: the CI deploy identity had no role at the management-group scope at all, which is why the earlier deny policies had been bootstrapped by hand. With approval, the CI identity was granted Resource Policy Contributor at that scope — policy-write only, no role-assignment power — so management-group policy is now proper CI-managed infrastructure-as-code. The diagnostics policy, whose managed identity and role grants Azure only permits an Owner to create, was applied as a documented one-time elevated step.

2. WHERE WE ARE NOW
- Every Sprint 2 item is done: A1 (observability wiring), A2 (alert baseline), B1 (budget alerts), C1 (backup/restore drill), C2 (malware scanning), C3 (rate limiting), D1 (policy baseline). Board is 100 percent (34 of 34 workstream items) with the closeout gate marked complete.
- The dev platform now has an operational-readiness baseline: App Insights and Container Insights flowing; four alerts that fire and auto-resolve; a $200/month budget with burn alerts; backup and restore for all three data stores with a drilled Qdrant path; malware scanning before extraction; per-client rate limiting; and a governance policy baseline.
- Everything is merged to main and main's infra apply is green. Cluster and services healthy, no known regressions.
- Several sitrep files remain untracked in the working tree, left uncommitted per the sitrep convention.

3. NEXT STEPS
1. Decide the next sprint focus. Natural candidates: public ingress + non-localhost OIDC redirect (unblocks real external access and pairs with the deferred gateway-layer rate limit), and Key Vault CSI secret cutover (removes the manual secret-delivery stopgap).
2. Clear the documented deferrals when their blockers lift: a clamd deployment for full antivirus (needs headroom past the 10-core vCPU ceiling), a Redis-backed strict global rate limit, an actual Postgres point-in-time restore drill, a prod-environment budget, and App Insights dashboards (section 13.9).
3. Optional housekeeping: commit the accumulated sitrep files if you want them in history, and consider a short Sprint 2 retro capturing the recurring theme this sprint — several controls were "build-then-validate" because the mechanism did not exist yet (Container Insights DCR, Qdrant snapshots, the policy set), and least-privilege CI repeatedly required a deliberate, scoped elevation.
