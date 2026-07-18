SITREP — CanI Platform
Date: 2026-07-17 | Branch: main | Sprint: Sprint 2 (Operational readiness)

1. LAST COMPLETED
Sprint 2 B1 is done, applied, and verified live. A $200/month subscription cost budget (cani-dev-monthly) is now in effect as infrastructure-as-code, with actual-cost alerts at 50, 75, 90, and 100 percent burn plus a forecasted-100-percent alert, all routing to the ops email (merged and applied via PR #23; closeout docs via PR #24). The amount is config-driven, so the cap moves without a code change, and it was grounded in live run-rate (month-to-date $103.63 on day 17, projecting ~$150-190/month). Verified against the subscription directly: budget active, all five notifications enabled and correctly targeted. Because month-to-date spend is already past 50 percent of $200, Azure's next evaluation will fire the first real budget email on its own, which serves as the natural end-to-end notification test (budget alerts cannot be force-fired like metric alerts).

2. WHERE WE ARE NOW
- All of Sprint 2 week-1's planned focus is complete, roughly two weeks early: A1 (observability wiring), A2 (alert baseline, fired and resolved in test), and B1 (budget alerts). Board is at 37 percent (15 of 41 boxes).
- Four Azure Monitor alerts (5xx, retrieval latency, dead-letter, node not-ready) are live and validated; App Insights and Container Insights both flowing; the subscription budget is live.
- Two unplanned fixes also landed and are verified: the dev OCR bug (unconfigured Document Intelligence now fails cleanly as a permanent error instead of a cryptic retry loop; then real DI credentials were delivered and OCR was confirmed end-to-end by reading text back from a scanned image-only PDF), and the Log Analytics daily cap was raised from 3 to 5 GB so a traffic burst cannot silently starve the alert telemetry.
- Production blockers #4 (cost budgets) and #5 (dev OCR) are both closed in implementation-status.
- Cluster and services are healthy; all work is merged to main; working tree clean. No known regressions.
- Watch item: the workspace daily cap can still pause telemetry ingestion if steady-state volume climbs toward 5 GB; budget alerts are deliberately independent of that pipeline, so cost visibility survives a telemetry pause.

3. NEXT STEPS
1. C1 — backup and restore validation drill: Postgres point-in-time recovery plus Qdrant snapshot-to-blob, with one full restore drill and recorded RTO/RPO. (Next sprint item.)
2. C2 — malware scanning before extraction in the upload/ingestion path, blocking on failed scans.
3. C3 — public-endpoint rate limiting (pairs with the still-deferred public ingress work).
4. D1 — complete the deferred Azure Policy set (required tags, allowed locations, TLS enforcement, deploy-if-not-exists diagnostics).
5. Optional: enable real OCR is already done; prod environment budget remains deferred until a prod subscription exists.
