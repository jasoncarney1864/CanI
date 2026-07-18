SITREP — CanI Platform
Date: 2026-07-17 | Branch: main | Sprint: Sprint 2 (Operational readiness)

1. LAST COMPLETED
Sprint 2 C1 (backup and restore validation) is done, and it turned out to be build-then-drill rather than just a drill. Postgres point-in-time restore was already available, but two of the three data-protection mechanisms Section 9.10 requires did not exist yet: the Qdrant snapshot-to-blob process, and blob versioning plus soft delete. Both were built as code and applied (PR #25): a cani_shared.backup module that snapshots Qdrant over its REST API and uploads to a dedicated qdrant-snapshots container, a daily Kubernetes CronJob to run it, a matching NetworkPolicy under deny-all, and the blob recovery settings in infrastructure. Then the drill was executed end to end (PR #26 documents it): one real document was ingested so reconciliation would be meaningful, the snapshot job ran in 13 seconds and landed a ~64 MB snapshot in Blob, and that snapshot was restored from Blob into a scratch collection in under a second, with the restored point count reconciling exactly against the chunk_manifests row count (the Section 9.10 check). The scratch collection was deleted afterward; live data was never touched.

2. WHERE WE ARE NOW
- Sprint 2 is about half complete (49 percent, 20 of 41 board items) and well ahead of schedule: A1, A2, B1 (all of week one) plus C1 (a week-two item) are done.
- All three data stores now have backup and a documented restore path: Postgres PITR (7-day retention), blob versioning and soft delete (7-day window), and scheduled Qdrant snapshots to Blob. A new runbook (runbooks/backup-restore-drill.md) holds the procedures and an RTO/RPO table.
- Postgres PITR was readiness-validated only, by choice, to avoid the small cost of spinning up a temporary restore server; the restore command and validation queries are documented so a real restore is follow-the-steps.
- Everything is merged to main; cluster and services healthy; no known regressions. One untracked sitrep file remains in the working tree (this and the prior one), left uncommitted per the sitrep convention.
- Measured recovery: Qdrant snapshot ~13s, restore ~1s; Postgres RTO is dominated by new-server provisioning (Azure-typical tens of minutes); blob recovery is immediate.

3. NEXT STEPS
1. C2 — malware scanning before extraction: add a scan step in the upload or ingestion path that blocks downstream processing on a failed scan, with tests for clean and malicious files.
2. C3 — public-endpoint rate limiting (pairs with the still-deferred public ingress work).
3. D1 — complete the deferred Azure Policy set (required tags, allowed locations, TLS enforcement, deploy-if-not-exists diagnostics).
4. Optional hardening already noted: run an actual Postgres PITR restore drill later if a fuller proof is wanted; add a prod environment budget once a prod subscription exists.
