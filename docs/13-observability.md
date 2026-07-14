# 13. Observability

This section defines the monitoring, logging, tracing, and alerting model for CanI using Azure Monitor, Log Analytics, Container Insights, and Application Insights.

## 13.1 Goals and constraints

Goals:
- Detect failures quickly across hub, spokes, ingestion, and retrieval paths.
- Correlate signals end-to-end from user request to infrastructure resources.
- Provide actionable alerts that reduce mean time to detect and recover.
- Keep operational complexity sustainable for a solo operator.

Constraints:
- Central Log Analytics workspace already defined in Section 6.
- AKS is the workload runtime (Section 10).
- CI/CD and deployment events are emitted from GitHub Actions (Section 12).

## 13.2 Observability architecture overview

Telemetry layers:
- Infrastructure telemetry via Azure Monitor and Container Insights.
- Application telemetry via Application Insights and OpenTelemetry-friendly instrumentation.
- Centralized logs and KQL analytics in Log Analytics.
- Action groups and alert rules for proactive notification.

Flow model:
1. Apps/services emit logs, traces, and metrics.
2. AKS platform data and diagnostics feed central workspace.
3. Azure Monitor rules evaluate thresholds/anomalies.
4. Alerts route to operational channels with runbook context.

## 13.3 Log strategy

Log categories:
- Application logs (structured JSON preferred)
- Audit/security logs (authn/authz, admin actions)
- AKS control plane and node/pod logs
- Pipeline/deployment logs linked from CI/CD workflows

Log design rules:
- Include consistent correlation fields: `trace_id`, `user_id` (hashed/redacted where required), `document_id`, `spoke`, `environment`.
- Avoid logging raw sensitive document content.
- Use explicit severity levels and event types.

Retention model (initial):
- Hot investigative window in central workspace.
- Longer retention/export path for audit records as policy requires.

## 13.4 Metrics strategy

Golden signals by service:
- Latency
- Traffic/request volume
- Error rate
- Saturation (CPU, memory, queue depth)

Key platform metrics:
- AKS node and pod resource saturation.
- Ingestion queue backlog and processing throughput.
- Retrieval latency and citation coverage success rate.
- Authentication success/failure and token validation errors.

## 13.5 Tracing and correlation

Trace requirements:
- Distributed tracing across hub, docs services, and workers.
- Trace propagation through asynchronous stages (ingestion jobs).
- Include deployment/release annotations so regressions can be tied to rollouts.

Correlation practices:
- Single request correlation ID generated at ingress and propagated downstream.
- Map Application Insights operation IDs to Log Analytics entries for fast drill-down.

## 13.6 AKS observability baseline

- Enable Container Insights for cluster health and workload visibility.
- Send AKS control plane diagnostics to central Log Analytics.
- Monitor namespace-level health for `hub-system`, `docs-platform`, `legal-spoke`, `health-spoke`, and `platform-observability`.
- Track restart spikes, pending pods, and node pressure conditions.

## 13.7 Application Insights design

Instrumentation scope:
- Hub API and spoke-facing APIs.
- Ingestion and retrieval services.
- Background workers (OCR/chunk/embed/index).

Data model guidance:
- Custom dimensions for `spoke`, `stage`, `owner_scope`, and `model_id` where relevant.
- Sample high-volume success traces when needed; keep error traces unsampled.

## 13.8 Alerting and incident model

Alert classes:
- P1: user-visible outage or severe data-path failure.
- P2: degradation with workaround or partial outage.
- P3: early warning and capacity risk.

Initial alert set:
- Elevated 5xx rate on hub/docs APIs.
- Retrieval latency SLO breach sustained over window.
- Ingestion queue depth and dead-letter growth.
- AKS node not ready or sustained pod crashloop.
- Missing diagnostics/telemetry ingestion from critical services.

Routing and response:
- Use Azure Monitor action groups for notifications.
- Include runbook link and owning service tag in each alert.

## 13.9 Dashboards and operational views

Required dashboards:
- Executive health view: availability, latency, errors by spoke.
- RAG pipeline view: queue depth, stage durations, failure hotspots.
- AKS operations view: node/pod health, resource saturation, deployment events.
- Security/audit view: auth failures, policy denials, break-glass actions.

Dashboard principles:
- Prefer a small number of high-signal dashboards over many fragmented views.
- Keep environment filters (`dev`, `prod`) explicit.

## 13.10 SLOs and error budget (v1)

Initial SLO candidates:
- Query API availability objective.
- Query latency target aligned with Section 8 performance goals.
- Ingestion time-to-index objective for common document sizes.

Error budget usage:
- Repeated SLO burn pauses non-critical feature rollout until stabilized.
- Link incident postmortems to SLO burn periods.

## 13.11 Data protection in telemetry

- Redact or hash user identifiers when full value is not operationally required.
- Never log raw uploaded document text or secrets.
- Restrict observability data access by role and environment.
- Apply retention and purge handling consistent with security/compliance policy.

## 13.12 CI/CD and observability integration

- Emit deployment markers from Section 12 workflows into telemetry.
- Gate production promotion on core health checks where feasible.
- Publish drift/preview artifacts and link them from incident records when relevant.

## 13.13 v1 implementation checklist

- Enable Application Insights for all core services.
- Enable Container Insights and AKS diagnostics to Log Analytics.
- Standardize structured logging schema and correlation IDs.
- Define initial alert rules and action groups for P1/P2 signals.
- Build baseline dashboards for platform, pipeline, and AKS health.
- Document on-call/runbook workflow for top alert scenarios.
- Validate alert noise and tune thresholds after initial launch period.

## 13.14 Open questions

1. Which notification channels are mandatory for P1 alerts at launch?
2. What telemetry retention period balances audit needs against cost targets?
3. Should synthetic probes be introduced in v1 or delayed until traffic stabilizes?

---

[← CI/CD strategy](12-cicd-strategy.md) | [Back to index](README.md) | Next: [Security & compliance →](14-security-and-compliance.md)