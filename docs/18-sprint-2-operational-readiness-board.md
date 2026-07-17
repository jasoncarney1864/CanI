# 18. Sprint 2 operational readiness board

Execution board for Sprint 2, pre-seeded from the Sprint 2 items in
implementation-status.

## Board metadata

- Sprint: Sprint 2 - Operational readiness
- Owner: Jason
- Start date: 2026-07-17 (pulled forward — Sprint 1 closed 12 days early)
- Target end date: 2026-08-12
- Last updated: 2026-07-17
- Overall status: In progress — A1 done (observability wiring verified end to end); A2 next

## Status legend

- [ ] Not started
- [-] In progress
- [x] Done
- [!] Blocked

## Weekly status rollup

| Week | Date range | Planned focus | Planned complete (%) | Actual complete (%) | Delta (pp) | Key blocker | Notes |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| Week 1 | 2026-07-17 to 2026-08-04 | Observability wiring, alert baseline, budget thresholds | 55 | 12 | -43 | None | In progress. A1 done 2026-07-17 (14 days early). Range start corrected from 07-29 to the real pulled-forward start date. |
| Week 2 | 2026-08-05 to 2026-08-12 | Backup or restore drill, malware scanning, rate limiting, policy baseline closeout | 100 | 0 | -100 | TBD | Fill at week close |

Formula: Actual complete (%) = round((number of checked boxes [x] in sprint checklist items / total sprint checklist boxes) x 100).

## Entry criteria

- [x] Sprint 1 closeout gate is complete. (Closed 2026-07-16.)
- [x] Dev AKS environment is stable enough for operational hardening work. (Healthy, Calico enforcing.)

## Workstream A - Observability and alerting

### A1. Application Insights and Container Insights wiring (P1)

- Owner: Jason
- Due: 2026-07-31
- Status: [x] Done (2026-07-17, 14 days early)
- Dependencies: Sprint 1 closeout
- Checklist:
  - [x] Wire Application Insights for application telemetry. (`ApplicationInsights` module, workspace-based, PR #14.)
  - [x] Wire Container Insights for AKS cluster telemetry. (`omsagent` addon with `useAADAuth`; 5 `ama-logs` pods Running.)
  - [x] Ensure logs and metrics correlate with trace identifiers. (Azure Monitor OTel Distro propagates W3C `traceparent`; verified below.)
  - [x] Verify telemetry ingestion from hub-api, docs-api, ingestion-worker, retrieval-worker. (All four emitting; verified below.)
- Done criteria:
  - [x] End-to-end telemetry visible for app and cluster layers.

Verification evidence (2026-07-17, live dev, real traffic through the deployed stack):

Telemetry landed in App Insights `cani-central-appied0b6605` from all four services:

| `cloud_RoleName` | requests | dependencies |
| --- | ---: | ---: |
| cani.hub-api | 4 | 14 |
| cani.docs-api | 2 | 14 |
| cani.retrieval-worker | 1 | 6 |
| cani.ingestion-worker | — (queue poller, no inbound server) | 4 |

Cross-service correlation (the section 13.5 "distributed tracing across hub, docs
services, and workers" requirement) — one `operation_Id`
(`0dbe9ad199291d94d5618520eb36ee74`), 12 spans, two services:

```text
docs-api  POST /query                 207ms   server span
  |- HTTP POST /retrieve               49ms   httpx carries traceparent across the boundary
       retrieval-worker POST /retrieve 34ms   same trace, different service
         |- HTTP POST /collections/... 13ms   Qdrant vector search, latency attributed
```

Known gap (accepted, not blocking): **Postgres calls emit no dependency spans.** We
instrument FastAPI + httpx only; Qdrant appears because qdrant-client uses httpx
underneath, but psycopg is not instrumented. DB latency is therefore *not* visible in
App Insights dependency data — it is only inside the enclosing server span. Adding
`opentelemetry-instrumentation-psycopg` would close this. Not required by A2's four
alerts (5xx, retrieval latency, dead-letter growth, node not-ready), so deferred rather
than done now; recorded so we do not later assume DB latency is observable when it is not.

Cost note: health probes are excluded from tracing (`excluded_urls="healthz"`) — they
fire every few seconds and are pure ingestion cost with no diagnostic signal.
`TELEMETRY_SAMPLING_RATIO` defaults to 1.0 in dev (full visibility) and is the lever to
trim ingestion cost as traffic grows (section 15).

### A2. P1 or P2 alert baseline from section 13.8 (P1)

- Owner: Jason
- Due: 2026-08-01
- Status: [ ] Not started — unblocked (A1 done 2026-07-17)
- Dependencies: A1 (met)
- Checklist:
  - [ ] Create elevated 5xx rate alert.
  - [ ] Create retrieval latency SLO breach alert.
  - [ ] Create ingestion dead-letter growth alert.
  - [ ] Create node not-ready alert.
  - [ ] Validate alert routing and runbook references.
- Done criteria:
  - [ ] All target alerts fire in test scenarios and resolve cleanly.

## Workstream B - Cost controls

### B1. Budget alerts at 50, 75, 90, and 100 percent (P1)

- Owner: Jason
- Due: 2026-08-02
- Status: [ ] Not started
- Dependencies: Sprint 1 closeout
- Checklist:
  - [ ] Configure budget thresholds at 50 percent, 75 percent, 90 percent, and 100 percent.
  - [ ] Confirm recipients and notification channels.
  - [ ] Validate test notifications.
- Done criteria:
  - [ ] Budget alert policy is active and notifications are confirmed.

## Workstream C - Resilience and data protection

### C1. Backup and restore validation drill (P1)

- Owner: Jason
- Due: 2026-08-05
- Status: [ ] Not started
- Dependencies: Sprint 1 closeout
- Checklist:
  - [ ] Validate Postgres point-in-time recovery procedure.
  - [ ] Validate Qdrant snapshot to blob storage process.
  - [ ] Run one full restore drill in a controlled environment.
  - [ ] Record RTO and RPO outcomes.
- Done criteria:
  - [ ] One documented restore drill completed with acceptable recovery outcomes.

### C2. Malware scanning before extraction (P2)

- Owner: Jason
- Due: 2026-08-07
- Status: [ ] Not started
- Dependencies: Sprint 1 closeout
- Checklist:
  - [ ] Add malware scanning step in upload or ingestion path before extraction.
  - [ ] Ensure failed scans block downstream processing.
  - [ ] Add tests for clean and malicious file paths.
- Done criteria:
  - [ ] Untrusted file is blocked before extraction and logged with traceability.

### C3. Public endpoint rate limiting (P2)

- Owner: Jason
- Due: 2026-08-08
- Status: [ ] Not started
- Dependencies: Sprint 1 closeout
- Checklist:
  - [ ] Define rate-limit policy for exposed endpoints.
  - [ ] Implement rate limiting at gateway or service layer.
  - [ ] Add tests for limit exceeded and normal traffic behavior.
- Done criteria:
  - [ ] Rate limiting enforces expected thresholds without breaking normal traffic.

## Workstream D - Policy baseline completion

### D1. Complete deferred policy set in security module (P2)

- Owner: Jason
- Due: 2026-08-09
- Status: [ ] Not started
- Dependencies: Sprint 1 closeout
- Checklist:
  - [ ] Add required tags policy coverage.
  - [ ] Add allowed locations policy coverage.
  - [ ] Add TLS enforcement policy coverage.
  - [ ] Add deploy-if-not-exists diagnostics policy coverage.
  - [ ] Validate policy assignments and compliance results.
- Done criteria:
  - [ ] Deferred baseline policies are implemented and assigned.

## Sprint closeout gate

- Owner: Jason
- Due: 2026-08-12
- Status: [ ] Not started
- Checklist:
  - [ ] Observability wiring and core alerts are active.
  - [ ] Budget threshold alerts are active.
  - [ ] Backup and restore drill is completed and documented.
  - [ ] Malware scanning and rate limiting controls are in place.
  - [ ] Deferred baseline policies are implemented.
  - [ ] Implementation status document updated with Sprint 2 outcomes.
- Done criteria:
  - [ ] Sprint 2 marked complete with operational readiness baseline established.

## Daily standup log

Use one line per day.

- 2026-07-14: Board created and pre-seeded from implementation-status Sprint 2 list.
- 2026-07-17: A1 done. IaC (App Insights + Container Insights) applied via PR #14; app
  instrumentation via PR #15 (shared `cani_shared.telemetry`, all four services, opt-in on
  connection string). Verified against live dev with real traffic: telemetry from all four
  services, and docs-api -> retrieval-worker -> Qdrant confirmed as a single 12-span
  distributed trace. Logged the psycopg-spans gap rather than implying DB latency is
  visible. A2 (alert baseline) now unblocked.
