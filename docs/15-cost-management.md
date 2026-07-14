# 15. Cost management

This section defines how CanI will budget, attribute, monitor, and optimize cloud spend while maintaining the security and reliability baselines defined in earlier sections.

## 15.1 Goals and constraints

Goals:
- Keep monthly spend predictable and within a solo-funded budget.
- Attribute cost clearly by environment and spoke.
- Reduce waste without compromising security and isolation controls.
- Build repeatable cost review and optimization habits.

Constraints:
- AKS is intentionally part of the architecture for learning value.
- PHI/PII-grade posture introduces baseline costs (private endpoints, logging, key management).
- Some services are partially always-on; full scale-to-zero is not realistic everywhere.

## 15.2 Cost governance model

Governance principles:
- Budget before build.
- Tag everything; untagged resources are policy violations.
- Prefer measurable optimization over ad-hoc cuts.
- Separate one-time migration/setup spend from recurring run-rate.

Owner model:
- Single owner is accountable for monthly review and corrective actions.
- Optimization actions are tracked as backlog items with expected savings.

## 15.3 Budget structure and guardrails

Budget layers:
- Subscription-level monthly budget (hard visibility boundary).
- Environment-level budget (`dev`, `prod`) with lower threshold for `dev`.
- Service-family budget buckets (compute, AI inference, storage, observability, networking).

Alert thresholds (starting point):
- 50% burn (early warning)
- 75% burn (investigation required)
- 90% burn (immediate mitigation actions)
- 100% burn (freeze non-critical changes until reviewed)

## 15.4 Cost allocation and tagging

Required tags (from Section 6 and cost extension):
- `environment`
- `owner`
- `spoke`
- `costCenter` (single value for now, extensible later)
- `workloadType` (api, batch, data, observability)

Allocation rules:
- Shared platform costs split separately from spoke-attributable costs.
- Cost reports must support views by `spoke` and by `environment`.
- Untagged or mis-tagged resources are corrected in the same sprint.

## 15.5 Baseline cost drivers for CanI

Major recurring drivers:
- AKS node pools and managed disks.
- Azure OpenAI/AI inference usage.
- PostgreSQL, Blob Storage, and Qdrant persistence/backup.
- Private networking components (private endpoints, NAT Gateway).
- Observability retention and ingestion volume.

Expected seasonal or burst drivers:
- Embedding/re-embedding jobs.
- OCR-heavy ingestion periods.
- Incident-driven logging surges.

## 15.6 Optimization strategy by layer

Compute optimization:
- Right-size AKS node pools with regular utilization review.
- Use Spot nodes for interruption-tolerant batch workers.
- Scale worker deployments aggressively during idle periods.

Storage and data optimization:
- Apply lifecycle policies to move stale artifacts to cool/archive tiers where appropriate.
- Keep only required hot retention for observability; archive long-tail logs.
- Compact or prune obsolete vector versions after controlled cutovers.

AI and retrieval optimization:
- Cap retrieval context/token budgets (Section 8 guardrails).
- Tune model selection and sampling defaults by workload type.
- Batch embedding workloads to reduce per-request overhead.

Network and platform optimization:
- Reassess need/tier of always-on edge components as traffic grows.
- Review private endpoint footprint for unused resources.

## 15.7 Autoscaling and schedule-based controls

- Maintain minimum production baseline for user-facing APIs.
- Use scheduled scale-down for non-critical dev workloads outside active hours.
- Pause non-essential batch jobs when budget thresholds are breached.
- Tie autoscaling defaults to SLO priorities from Section 13.

## 15.8 Cost visibility and reporting

Reporting cadence:
- Weekly quick review: anomalies, top movers, failed budget alerts.
- Monthly deep review: trend analysis, savings delivered vs planned.

Required report views:
- Cost by environment.
- Cost by spoke and workload type.
- Cost by service family (compute, storage, AI, networking, observability).
- Idle/underutilized resource candidates.

## 15.9 Cost anomaly response playbook

When anomaly is detected:
1. Identify top resource and service contributors.
2. Separate one-time event from sustained baseline shift.
3. Apply safe immediate mitigations (scale-down, pause non-critical jobs, tighten retention).
4. Validate no SLO/security regressions from mitigation.
5. Record root cause and prevention action.

## 15.10 Cost and security/reliability trade-off policy

- Security controls required by ADR-007 are not optional cost cuts.
- Reliability-critical capacity for core query path is protected from aggressive reductions.
- Cost optimization proposals must state expected savings and risk impact.
- Any trade-off that affects user isolation or data protection is rejected.

## 15.11 Tooling and automation

- Azure budget alerts and cost analysis views configured per subscription and environment.
- Scheduled reports exported for monthly review.
- CI/CD can include optional cost-impact checks for major infrastructure pull requests.
- Tag compliance and drift checks integrated with infrastructure workflows.

## 15.12 v1 implementation checklist

- Define monthly budget targets for `dev` and `prod`.
- Configure budget alerts at 50/75/90/100% thresholds.
- Enforce required cost tags across all resources.
- Build first cost dashboard/report set by environment and spoke.
- Implement scheduled dev scale-down and worker throttling policies.
- Add monthly cost review ritual and optimization backlog process.
- Document anomaly response runbook.

## 15.13 Open questions

1. What monthly budget cap is acceptable for v1 once production is live?
2. Should CanI reserve capacity for any baseline workloads or remain fully pay-as-you-go initially?
3. What retention period gives the best balance between observability value and log cost?

---

[← Security & compliance](14-security-and-compliance.md) | [Back to index](README.md) | Next: [Roadmap & phasing →](16-roadmap-and-phasing.md)