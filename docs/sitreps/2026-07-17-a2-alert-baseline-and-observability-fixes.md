SITREP — CanI Platform
Date: 2026-07-17 | Branch: docs/sprint2-a2-closeout | Sprint: Sprint 2 (Operational readiness), A2

1. LAST COMPLETED
The Sprint 2 A2 alert baseline was built and deployed as infrastructure-as-code (PR #17, merged): an email action group plus the four Section 13.8 alerts — P1 elevated 5xx, P2 retrieval-latency SLO, P2 ingestion dead-letter, and P1 node not-ready. Building it required querying the live workspace first, which surfaced three real problems that were fixed in the same change: Container Insights had never actually flowed (the AKS agent addon deploys agents but no Data Collection Rule — agents were "Running" for days with zero rows), a diagnostic setting was leaking 5.78 GB/day of kube-audit into the workspace (about 400 dollars/month), and the App Insights exporter was logging its own uploads in a feedback loop. A follow-up fix made the infra-apply workflow apply the platform stack before the workload stack (PR #18, merged), after the original parallel version raced its own cross-stack dependency and left three orphaned alert rules in Azure (cleaned up, state verified). Routing is validated: an action-group test notification was delivered successfully to the ops email. Container Insights is now confirmed genuinely flowing (ContainerLogV2 climbed past 5,900 rows once the restarted agents picked up the new rule).

2. WHERE WE ARE NOW
- All four alert rules are live in Azure and tracked in Pulumi state; email routing is proven.
- Container Insights fix is verified end to end — cluster/pod logs (docs-api, hub-api, both workers, calico) are flowing to the workspace.
- Cost controls applied: AKS diagnostics trimmed to write-audit + auth events, plus a 3 GB/day workspace hard cap (which promptly tripped on the day's pre-trim volume and paused ingestion until the 18:00Z daily reset — working as designed, awkward timing).
- A2 SIGN-OFF: DONE. The earlier "App Insights request telemetry has stopped" watch item was NOT a telemetry regression — it was the 3 GB/day workspace daily cap pausing ingestion (tripped ~16:36Z on the pre-trim kube-audit backlog) combined with near-zero traffic. Once the cap reset (18:00Z) and real traffic resumed, AppRequests flowed normally. The empty AppTraces table is by design (the telemetry exporter restricts stdlib-log capture to the unused "cani" logger namespace; app logs go via structlog -> stdout -> Container Insights ContainerLogV2, not App Insights AppTraces). Cap state is now RespectQuota (healthy).
- END-TO-END VALIDATION (2026-07-17): re-tripped the failure scenarios against the live private cluster and confirmed all three testable alerts completed the full Fired -> Resolved lifecycle (auto_mitigate working):
  - `cani-ops-5xx` (Sev1): Fired 19:25:25Z -> Resolved 20:06:26Z. Trigger: retrieval-worker scaled to 0, six concurrent `POST /query` returned 500 (7 rows >= 500 in AppRequests, threshold >= 5), then scaled back to 1.
  - `cani-ops-deadletter` (Sev2): Fired 19:22:43Z -> Resolved 20:38:55Z. Trigger: blank/no-text PDF upload -> OCR fallback failed -> `job_dead_lettered` (attempt 5) at 19:21:48Z in ContainerLogV2 (threshold > 0).
  - `cani-ops-latency` (Sev2): Fired 19:38:51Z -> Resolved 20:54:51Z — a bonus: the 30s upstream-timeout durations on the failed queries breached the p95 > 5000ms latency SLO, validating the third rule for free.
  - Node not-ready (Sev1 metric alert) remains validated by signal + action-group test rather than by breaking a node (cluster sits at the 10-core regional quota ceiling, so a downed node cannot be replaced by scale-out).
- Open bug found during testing: the dev OCR fallback is misconfigured (Document Intelligence endpoint is empty), so any document needing OCR dead-letters. Filed as a production blocker (only remaining A2 follow-up).
- Docs live on branch docs/sprint2-a2-closeout (PR #20, docs-only); this sitrep and the Sprint 2 board now record A2 as DONE with the Fired -> Resolved evidence above. Ready to merge.

3. NEXT STEPS
1. DONE — AppRequests "stopped" was diagnosed to the daily-cap pause + low traffic (not a telemetry regression); data path confirmed healthy.
2. DONE — re-tripped the 5xx, dead-letter, and (incidentally) latency scenarios; all three reached Fired and auto-resolved cleanly. A2 done-criteria met.
3. OPEN (production blocker, tracked separately) — fix the dev OCR configuration: the Document Intelligence endpoint is empty, so any document needing OCR dead-letters (`No connection adapters were found for '/documentintelligence/...'`). Deliver the DI endpoint/key to cani-secrets, or make an explicit skip-OCR-in-dev decision.
4. Merge PR #20 (docs) — A2 validation is complete; this sitrep + board now reflect the final Fired -> Resolved state.
5. Proceed to Sprint 2 B1 (subscription budget alerts at 50/75/90/100 percent).
