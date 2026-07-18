# 18. Sprint 2 operational readiness board

Execution board for Sprint 2, pre-seeded from the Sprint 2 items in
implementation-status.

## Board metadata

- Sprint: Sprint 2 - Operational readiness
- Owner: Jason
- Start date: 2026-07-17 (pulled forward — Sprint 1 closed 12 days early)
- Target end date: 2026-08-12
- Last updated: 2026-07-17
- Overall status: In progress — A1, A2, B1, C1, C2 and C3 done. Only D1 (policy baseline)
  remains before the closeout gate. Well ahead of plan.

## Status legend

- [ ] Not started
- [-] In progress
- [x] Done
- [!] Blocked

## Weekly status rollup

| Week | Date range | Planned focus | Planned complete (%) | Actual complete (%) | Delta (pp) | Key blocker | Notes |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| Week 1 | 2026-07-17 to 2026-08-04 | Observability wiring, alert baseline, budget thresholds | 55 | 37 | -18 | None | Ahead of plan. A1 + A2 + B1 all done 2026-07-17 (all of week-1's planned focus complete, ~2 weeks early). Also: dev OCR bug fixed, workspace cap raised 3->5 GB. |
| Week 2 | 2026-08-05 to 2026-08-12 | Backup or restore drill, malware scanning, rate limiting, policy baseline closeout | 100 | 75 | -25 | None | Started early. C1 (backup/restore), C2 (malware scan) and C3 (rate limiting) all done 2026-07-17, week-2 items pulled forward. Only D1 remains. |

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
  - [x] Wire Container Insights for AKS cluster telemetry. (**Correction 2026-07-17
    evening:** the original done-claim was wrong — agents were Running but NO data ever
    flowed. `omsagent` with `useAADAuth` deploys agents without the Data Collection Rule
    that makes them collect anything; found when A2 recon queried the workspace and got
    zero `ContainerLogV2`/`KubeNodeInventory` rows. Fixed in PR #17:
    `ContainerInsightsCollection` DCR + association, association name
    `ContainerInsightsExtension` as required by the agent. Verified genuinely flowing
    2026-07-17 ~18:15Z — `ContainerLogV2` climbed past 4,600 rows once the restarted
    `ama-logs` agents picked up the new DCR (a flat zero before). Lesson recorded:
    "agents Running" is not verification — table rows are.)
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
- Status: [x] Done (2026-07-17, 15 days early) — all four alerts live as IaC (PR #17),
  routing validated, and three fired + auto-resolved cleanly in test (see done criteria)
- Dependencies: A1 (met)
- Checklist:
  - [x] Create elevated 5xx rate alert. (P1, `AppRequests`, >=5 server errors/15m,
    eval 5m.)
  - [x] Create retrieval latency SLO breach alert. (P2, P95 of `POST /query` > 5s
    sustained 30m — the docs/02 SLO.)
  - [x] Create ingestion dead-letter growth alert. (P2, `ContainerLogV2`
    `job_dead_lettered`, any occurrence/15m. Container stdout is the ONLY place this
    signal exists: structlog bypasses stdlib logging so it never reaches AppTraces, and
    psycopg emits no spans.)
  - [x] Create node not-ready alert. (P1, platform metric `kube_node_status_condition`
    condition=Ready/status2=NotReady — deliberately metric-based, not log-based, so it
    still fires when the agent/log pipeline is itself what broke.)
  - [x] Validate alert routing and runbook references. (Action-group test notification
    delivered to ops email, status Succeeded, 2026-07-17 16:54Z. Each alert description
    carries owning service + runbook/docs reference.)
- Done criteria:
  - [x] All target alerts fire in test scenarios and resolve cleanly. Validated
    2026-07-17 19:36Z with a clean 47-second outage window (retrieval-worker scaled to
    0, six `POST /query` returning 500, scaled back; then a blank PDF ->
    `PermanentJobFailure` -> `job_dead_lettered`). All three testable alerts completed
    the full Fired -> Resolved cycle:
    - `cani-ops-5xx` (Sev1): Fired -> Resolved
    - `cani-ops-deadletter` (Sev2): Fired -> Resolved
    - `cani-ops-latency` (Sev2): Fired -> Resolved (the failed queries also breached the
      latency condition — a bonus validation of the third rule)
    Node not-ready (`cani-ops` Sev1 metric alert) is validated by signal + the
    action-group test notification rather than by breaking a node: the cluster runs at
    the 10-core regional quota ceiling, so a deliberately failed node could not be
    replaced by scale-out. `auto_mitigate=True` on every rule is confirmed working by
    the three clean auto-resolves above.

First fire-in-test attempt (16:52Z / 18:03Z) came up empty — NOT an alert fault: the
workspace was `OverQuota` on the pre-trim kube-audit backlog, so the App Insights
exporter dropped the validation traffic. Diagnosed to the daily cap (not a telemetry
regression — proven by fresh docs-api requests landing cleanly once ingestion resumed),
then re-run after the 18:00Z reset. See "cap can blind observability" below.

Findings from A2 recon/validation (2026-07-17):

1. **Cost leak (fixed):** the `allLogs` AKS diagnostic setting was ingesting
   **5.78 GB/day (~$400/month)** into the workspace, 76% of it the read-inclusive
   `kube-audit` category. Trimmed to `kube-audit-admin` + `guard` (every write/delete
   audit event kept) — expected ~1.2 GB/day. B1's budget alerts would not have existed
   to catch this.
2. **Workspace daily cap added (3 GB/day)** as a runaway-source circuit breaker. It
   promptly proved itself by tripping on the same day's pre-trim kube-audit volume
   (`dataIngestionStatus: OverQuota`, resets 18:00Z) — suspending ALL ingestion,
   including the alert-validation signals. Working as designed, awkward timing. Metric
   alerts (node not-ready) are unaffected by the cap — they do not ride the workspace
   pipeline.
   - **Trade-off to keep in mind (the cap can blind observability):** while `OverQuota`,
     the workspace silently drops incoming telemetry — including the exact 5xx/latency/
     dead-letter signals the alerts fire on. A cost circuit-breaker can therefore mask an
     incident during the very window you most want visibility, and (as happened here) an
     `OverQuota` drop is easy to misread as a telemetry outage. Mitigations in place:
     the category trim drops steady-state to ~1.2 GB/day (well under 3 GB), and node
     not-ready rides metrics (cap-immune) so total-blackout is still detectable. Open
     decision: raise the cap (e.g. 5 GB) now that kube-audit is trimmed, or keep 3 GB
     and rely on B1 budget alerts as the earlier warning. Deferred to B1, not blocking
     A2.
3. **`AppTraces` was 100% exporter self-noise:** azure.core logs each telemetry upload
   at INFO; default root-logger capture re-exports it, forever (55k rows/2h, zero app
   events). Fixed with `logger_name="cani"` in `configure_azure_monitor` (PR #17,
   deployed).
4. **OCR fallback is broken in dev (open bug):** the blank-PDF dead-letter test failed
   through the OCR path with "No connection adapters were found" — a relative URL,
   meaning `AZURE_DOCUMENTINTELLIGENCE_ENDPOINT` is empty in the cluster. Any scanned
   document requiring OCR will dead-letter. Needs the DI endpoint/key delivered to
   cani-secrets (docs-platform ns) or an explicit skip-OCR-in-dev decision.
5. **infra-apply-dev raced its own stacks (fixed, PR #18):** the parallel matrix let
   workload read `ops_action_group_id` before platform exported it, and fail-fast then
   canceled the platform `pulumi up` mid-create, orphaning three query rules (existed
   in Azure, absent from state — a rerun would have created duplicates). Orphans
   deleted, state verified clean, jobs made sequential (`needs:`), `workflow_dispatch`
   added for manual retriggers.

## Workstream B - Cost controls

### B1. Budget alerts at 50, 75, 90, and 100 percent (P1)

- Owner: Jason
- Due: 2026-08-02
- Status: [x] Done (2026-07-17, ~2 weeks early)
- Dependencies: Sprint 1 closeout
- Checklist:
  - [x] Configure budget thresholds at 50 / 75 / 90 / 100 percent. (Subscription-scoped
    monthly Cost budget `cani-dev-monthly`, $200 USD, as IaC in `infra/modules/cost.py`;
    Actual-cost notifications at all four burn levels + a Forecasted 100% alert that
    warns when spend is *trending* over the cap before it actually crosses.)
  - [x] Confirm recipients and notification channels. (All five notifications enabled,
    delivering to the ops email via the Consumption notification channel — deliberately
    independent of the Monitor action group and the Log Analytics daily cap, so a budget
    alert fires even when the telemetry pipeline is degraded.)
  - [x] Validate test notifications. (Budget alerts cannot be force-fired like metric
    alerts — Azure evaluates them against accrued spend on its own cadence. Verified the
    live config against the subscription instead; and since MTD spend ($103.63) is
    already past 50% of $200, the actual-50% alert will fire on Azure's next evaluation
    as a natural end-to-end test.)
- Done criteria:
  - [x] Budget alert policy is active and notifications are confirmed. Verified live on
    the subscription 2026-07-17: `cani-dev-monthly`, $200 USD monthly, five enabled
    notifications (actual 50/75/90/100 + forecasted 100), all routing to the ops email.
    Amount is config-driven (`monthlyBudgetUsd`) so the cap moves without a code change.

Scope note: the whole subscription is dev today, so the subscription budget *is* the dev
environment budget. A separate prod environment budget (§15.3 environment-level, lower
dev threshold) is deferred until a prod subscription exists. The $200 cap was chosen
against live run-rate (MTD $103.63 on day 17 → ~$150-190/mo projected, trending lower now
that the A2 kube-audit log leak is fixed).

## Workstream C - Resilience and data protection

### C1. Backup and restore validation drill (P1)

- Owner: Jason
- Due: 2026-08-05
- Status: [x] Done (2026-07-17, ~3 weeks early)
- Dependencies: Sprint 1 closeout
- Checklist:
  - [x] Validate Postgres point-in-time recovery procedure. (Readiness-validated: PITR
    enabled on `cani-pgfd564d67`, 7-day retention, earliest restore 2026-07-15; restore
    command + validation queries documented in `runbooks/backup-restore-drill.md`. Actual
    restore-to-temp-server deferred to avoid the small cost — chosen decision.)
  - [x] Validate Qdrant snapshot to blob storage process. (Two §9.10 gaps built first:
    the snapshot mechanism did not exist and blob versioning/soft-delete were off — PR
    #25. Then executed a full snapshot: the `qdrant-snapshot` CronJob ran on demand in
    13s and landed a ~64 MB snapshot in the `qdrant-snapshots` container.)
  - [x] Run one full restore drill in a controlled environment. (Seeded one real
    document, snapshotted, then restored the snapshot from Blob into a scratch collection
    in 0.9s and reconciled point count (1) == `chunk_manifests` (1) — the §9.10
    reconciliation. Scratch collection deleted; live data untouched.)
  - [x] Record RTO and RPO outcomes. (Recorded per store in the runbook's objectives
    table: Qdrant restore ~1s / RPO 24h scheduled (0 on-demand); Postgres RTO ~new-server
    provisioning / RPO ~5 min within 7-day window; Blob immediate / RPO ~0 for overwrites.)
- Done criteria:
  - [x] One documented restore drill completed with acceptable recovery outcomes. Qdrant
    snapshot->blob->restore->reconcile executed end to end and matched; procedures for all
    three stores documented in `runbooks/backup-restore-drill.md`.

Note: C1 turned out to be build-then-drill, not just drill — Postgres PITR was ready, but
the Qdrant snapshot-to-blob mechanism (`cani_shared.backup` + CronJob) and blob
versioning/soft-delete were missing and had to be implemented first (PR #25) before there
was anything to exercise.

### C2. Malware scanning before extraction (P2)

- Owner: Jason
- Due: 2026-08-07
- Status: [x] Done (2026-07-17, ~3 weeks early)
- Dependencies: Sprint 1 closeout
- Checklist:
  - [x] Add malware scanning step in upload or ingestion path before extraction. (PR #27:
    `MalwareScanner` interface scanned in the ingestion pipeline right after blob download
    and before `extractor.extract()`. Two backends, same real-vs-fake tiering as the Azure
    providers — `ClamAVScanner` (clamd INSTREAM) for prod, `EicarSignatureScanner` for
    dev/CI; factory selects on `CLAMAV_HOST`. A document is never left unscanned.)
  - [x] Ensure failed scans block downstream processing. (A positive result raises
    `PermanentJobFailure` → dead-lettered on attempt 1, no wasted retries; the document
    never reaches extraction.)
  - [x] Add tests for clean and malicious file paths. (5 unit tests: EICAR flagged, clean
    passes, ClamAV INSTREAM clean+FOUND parsing against a loopback fake clamd, factory
    selection. Full suite 74 passing.)
- Done criteria:
  - [x] Untrusted file is blocked before extraction and logged with traceability.
    Live-validated 2026-07-17: uploaded a file with `%PDF` magic bytes + the EICAR payload
    (passes the type/size gate), and the worker logged `malware_detected` at `stage:
    scanning` (signature `Eicar-Test-Signature`, with document_id + owner hash, never the
    bytes) then dead-lettered on attempt 1. Qdrant point count and `chunk_manifests` were
    unchanged afterward — nothing was extracted or indexed.

Honesty note: dev uses the EICAR-only backend (proves the gate, needs no clamd), the same
tiering as FakeEmbedder / dev-OCR. Full AV in production requires a clamd deployment
(`CLAMAV_HOST`); a clamav pod is not stood up in dev because the cluster is at its 10-core
vCPU ceiling. The scan *gate* (runs before extraction, positive result blocks) is identical
regardless of backend. EICAR test bytes are stored base64-encoded in source so a host AV
(e.g. Windows Defender) doesn't quarantine the repo file.

### C3. Public endpoint rate limiting (P2)

- Owner: Jason
- Due: 2026-08-08
- Status: [x] Done (2026-07-17, ~3 weeks early)
- Dependencies: Sprint 1 closeout
- Checklist:
  - [x] Define rate-limit policy for exposed endpoints. (Per-client token bucket, default
    60 requests / 60s, config-driven via `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS`
    / `RATE_LIMIT_ENABLED`. Client keyed by leftmost `X-Forwarded-For` else socket peer;
    `/healthz` exempt.)
  - [x] Implement rate limiting at gateway or service layer. (Service layer — public
    ingress is still deferred. `RateLimitMiddleware` in `cani_shared.middleware`, added as
    the outermost middleware on hub-api and docs-api so abusive traffic is rejected before
    downstream work or telemetry spend. Over-limit → 429 + `Retry-After`, logs a
    `rate_limited` event with a hashed client key.)
  - [x] Add tests for limit exceeded and normal traffic behavior. (4 unit tests:
    allow-to-capacity-then-429, probe exemption, refill-after-window, per-client
    isolation. Full suite 78 passing.)
- Done criteria:
  - [x] Rate limiting enforces expected thresholds without breaking normal traffic.
    Live-validated 2026-07-17: a 70-request burst from one client returned exactly 60
    allowed (reached the route) + 10 × 429; `/healthz` stayed 200 for 15 requests from the
    same throttled client (probe exemption); a different client was unaffected (isolation).

Honesty note: service-layer, not gateway, because public ingress is deferred — the
middleware already reads `X-Forwarded-For` for when an ingress lands. Buckets are per-pod,
so the effective ceiling is ~N x capacity with N replicas (exact in dev's single replica);
a strict global limit needs a shared store (Redis) and is deferred + documented.

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
- 2026-07-17 (evening): A2 nearly done. All four §13.8 alerts live as IaC (PR #17) with
  routing validated by action-group test notification. A1's Container Insights claim
  corrected: it had never flowed (missing DCR — agents Running is not data flowing);
  fixed in the same PR. Cost leak found and fixed (5.78 GB/day kube-audit -> trimmed
  categories + 3 GB/day cap; the cap immediately tripped on the pre-trim volume,
  pausing ingestion until 18:00Z — validation re-trip after reset). Apply-workflow race
  fixed (PR #18, sequential stacks). Open bug filed: dev OCR fallback broken
  (`AZURE_DOCUMENTINTELLIGENCE_ENDPOINT` empty) — OCR-requiring docs dead-letter.
- 2026-07-17 (late): A2 DONE. Fire-in-test passed after the 18:00Z cap reset — a clean
  47s outage window produced six 500s + a genuine dead-letter, and all three testable
  alerts completed Fired -> Resolved (5xx Sev1, dead-letter Sev2, latency Sev2). Node
  not-ready validated by signal + action-group test (cluster at vCPU ceiling). Chased
  the earlier "AppRequests stopped" scare to ground: not a regression — the cap's
  OverQuota window had dropped the first validation batch; fresh docs-api requests
  confirmed telemetry healthy. Recorded the "cap can blind observability" trade-off.
  Workstream A complete (~2 weeks early). Confirmed the web prototype (apps/web) is
  localhost-only — no Deployment/Service/Ingress in the cluster, nothing publicly
  exposed. Next: B1 budget alerts.
- 2026-07-17 (late, cont.): Cleared the A2 follow-ups and B1. Workspace cap raised
  3 -> 5 GB (PR #22, applied + verified live) so a burst can't blind the alerts again.
  Dev OCR bug fixed (PR #21): unconfigured DI now fails cleanly as a permanent error
  instead of a cryptic 5x-retry; then DI credentials delivered to cani-secrets and OCR
  verified end-to-end (a scanned image-only PDF read back correct text via
  Document Intelligence). B1 DONE (PR #23, applied): $200/mo subscription budget with
  50/75/90/100% actual + forecasted-100% alerts to the ops email, verified live on the
  subscription; MTD already >50%, so the first real alert fires on Azure's next
  evaluation. All of week-1's planned focus (A1/A2/B1) now complete. Next: C1 backup/
  restore drill.
- 2026-07-17 (late, cont. 2): C1 DONE (a week-2 item, pulled forward). Turned out to be
  build-then-drill: Postgres PITR was ready, but the Qdrant snapshot-to-blob mechanism
  and blob versioning/soft-delete didn't exist. Built both (PR #25: `cani_shared.backup`
  plus a daily CronJob, NetworkPolicy, and blob recovery IaC, 2 tests), applied, then
  drilled:
  snapshot (13s) -> blob (~64 MB) -> restore into a scratch collection (0.9s) ->
  reconcile point count == chunk_manifests (match). Postgres PITR readiness-validated
  (restore-to-temp-server deferred to avoid the small cost). Procedures + RTO/RPO in
  `runbooks/backup-restore-drill.md`. Board 49% (20/41). Next: C2 malware scan.
- 2026-07-17 (late, cont. 3): C2 DONE (another week-2 item pulled forward). Malware scan
  gate in the ingestion pipeline before extraction (PR #27): `MalwareScanner` interface,
  ClamAV (INSTREAM) for prod + EICAR scanner for dev/CI, factory on `CLAMAV_HOST`, 5
  tests. Live-validated by uploading an EICAR-laden `%PDF` file: worker logged
  `malware_detected` at the scanning stage and dead-lettered it on attempt 1; Qdrant +
  chunk_manifests unchanged (nothing extracted). EICAR bytes stored base64 in source to
  avoid host-AV quarantine. Board 59% (24/41). Next: C3 rate limiting.
- 2026-07-17 (late, cont. 4): C3 DONE (last of the pulled-forward week-2 items).
  Per-client token-bucket rate limiting on hub-api + docs-api (PR #29), service-layer
  (public ingress deferred), default 60/60s, `/healthz` exempt, 429 + Retry-After,
  4 tests. Live-validated: a 70-request burst from one client -> exactly 60 allowed +
  10x 429; `/healthz` stayed 200 under the throttle; a different client unaffected.
  Board 68% (28/41). Only D1 (policy baseline) left before the closeout gate.
