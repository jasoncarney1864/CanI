SITREP — CanI Platform
Date: 2026-07-17 | Branch: main | Sprint: Sprint 2 (Operational readiness)

1. LAST COMPLETED
Two security controls landed and were both live-validated in the dev cluster: C2 (malware scanning before extraction) and C3 (per-client rate limiting on public APIs). C2 adds a MalwareScanner gate in the ingestion pipeline right before extraction, behind an interface with a ClamAV backend for production and an EICAR-test-file scanner for dev and CI; a positive result permanently fails the job and blocks extraction, logging the signature and owner hash for traceability but never the file bytes. It was proven by uploading a real EICAR file disguised with PDF magic bytes: the worker flagged it at the scanning stage and dead-lettered it on the first attempt, with nothing extracted or indexed. C3 adds a token-bucket rate limiter as the outermost middleware on hub-api and docs-api (default 60 requests per 60 seconds per client, health checks exempt, over-limit returns 429 with Retry-After). It was proven by a 70-request burst from one client that returned exactly 60 allowed plus 10 rejections, while health checks stayed healthy and a second client was unaffected.

2. WHERE WE ARE NOW
- Sprint 2 is 68 percent complete (28 of 41 board items) and well ahead of schedule: A1, A2, B1, C1, C2 and C3 are all done. Only D1 (the deferred Azure Policy set) remains before the sprint closeout gate.
- All security controls are live and app-level end to end: owner-scoped access, CSRF, upload validation, malware scanning, rate limiting, plus the observability and cost guardrails from earlier today.
- Everything is merged to main; cluster and services healthy; no known regressions. Two untracked sitrep files remain in the working tree, left uncommitted per the sitrep convention.
- Honest limitations recorded for both: C2 dev uses the EICAR-only backend (full AV needs a clamd deployment, not stood up because the cluster is at its 10-core vCPU ceiling); C3 is service-layer not gateway (public ingress deferred) with per-pod buckets (a strict global limit would need Redis). Both gates themselves are real and identical regardless of backend.

3. NEXT STEPS
1. D1 — complete the deferred Azure Policy set in the security module: required-tags, allowed-locations, TLS enforcement, and deploy-if-not-exists diagnostics coverage, then validate the assignments and compliance results. This is the last Sprint 2 workstream item.
2. Sprint 2 closeout gate — confirm observability, budget alerts, backup/restore, malware scanning, rate limiting and the policy baseline are all in place, and mark the sprint complete.
3. Deferred and noted for later: stand up a clamd deployment for full AV and a Redis-backed global rate limit once past the vCPU ceiling / when a prod environment exists; run an actual Postgres PITR restore drill if a fuller proof is wanted; prod environment budget.
