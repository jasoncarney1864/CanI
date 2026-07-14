# 10. AKS cluster design

This section defines the AKS topology for CanI workloads, including node pools, networking, workload identity, ingress, autoscaling, and operational guardrails.

## 10.1 Goals and constraints

Goals:
- Run hub/spoke platform workloads on AKS with strong tenant isolation controls.
- Support both stateless APIs and stateful vector workload needs.
- Keep reliability reasonable for v1 while preserving cost control.
- Maximize hands-on AKS learning value (explicit project goal from Section 1).

Constraints:
- Solo-operated platform with modest early traffic.
- PHI/PII-grade posture by default (ADR-007).
- Workload landing zone network and private endpoint strategy from Section 6.

## 10.2 Cluster topology decision

**Decision (v1): one shared AKS cluster with per-spoke namespaces.**

Namespace model:
- `hub-system` (hub APIs and auth/routing services)
- `docs-platform` (ingestion, retrieval, citation services)
- `legal-spoke` (domain adapters/policies)
- `health-spoke` (domain adapters/policies)
- `platform-observability` (agents/exporters)

Rationale:
- Lower fixed cost than multiple clusters.
- Keeps operational surface area manageable for one person.
- Still enables isolation through namespace RBAC, network policy, and workload identity boundaries.

## 10.3 AKS SKU, control plane, and baseline settings

- AKS Standard tier for full control of networking and add-ons.
- Private cluster enabled (private API server).
- Availability zones enabled for production node pools where region supports zones.
- Kubernetes RBAC with Microsoft Entra integration enabled.
- Azure Policy for Kubernetes enabled for baseline policy enforcement.

## 10.4 Networking design

Cluster networking:
- Azure CNI Overlay for pod networking to keep VNet IP pressure low.
- Nodes deployed in workload VNet subnets defined in Section 6.
- API server access private only from trusted admin paths.

Traffic flow:
- East-west traffic controlled by Kubernetes network policies.
- North-south ingress controlled by dedicated ingress namespace and policy.
- Egress routed through NAT Gateway (Section 6), with deterministic outbound IP.

Private dependency access:
- Private endpoints used for Storage, Key Vault, ACR, Azure OpenAI.
- Private DNS zone linkage from hub/workload design in Section 6 remains required.

## 10.5 Node pool strategy

Pool layout for v1:

1. `systempool`
   - Mode: system
   - Purpose: core cluster components only
   - Size: small but zone-aware where possible
2. `appspool`
   - Mode: user
   - Purpose: hub/docs/legal/health stateless services
   - Autoscaling: enabled with min/max bounds
3. `datapool`
   - Mode: user
   - Purpose: Qdrant and stateful supporting components
   - Taints/tolerations: dedicated scheduling boundary for stateful workloads
4. `batchpool` (optional in v1, recommended soon after)
   - Mode: user
   - Purpose: ingestion and embedding workers
   - Can include Spot nodes for interruption-tolerant jobs

Scheduling guardrails:
- Use node affinity and tolerations so stateful workloads do not drift to generic pools.
- Define PodDisruptionBudgets for critical services.

## 10.6 Workload identity and secrets

- Microsoft Entra Workload Identity for pod-to-Azure auth (no static cloud credentials in pods).
- Separate managed identity per major service boundary (hub, docs API, ingestion worker, retrieval service).
- Key Vault CSI driver for secret material mounted at runtime.
- Least-privilege role assignments scoped to required resources only.

## 10.7 Ingress and service exposure

Ingress model:
- Single ingress controller deployment in dedicated namespace.
- Public entry exposed only for user-facing endpoints that must be internet reachable.
- Internal services use ClusterIP/Internal Load Balancer and are not publicly exposed.

TLS and edge controls:
- TLS termination at ingress with managed certificate lifecycle.
- WAF-capable edge layer is a planned enhancement once usage justifies cost.

## 10.8 Autoscaling strategy

Cluster and workload scaling:
- Cluster Autoscaler enabled on user pools with explicit min/max per pool.
- Horizontal Pod Autoscaler for API services driven by CPU/memory and custom metrics where useful.
- KEDA for queue-based ingestion/embedding workers to scale with backlog.

Capacity controls:
- Keep reserved baseline capacity for latency-sensitive query path.
- Allow aggressive scale-down for asynchronous workers outside peak use.

## 10.9 Stateful workload pattern (Qdrant)

- Deploy Qdrant as StatefulSet on `datapool` only.
- Use managed disks with zone-aware placement where available.
- Persist snapshots to Blob Storage on schedule (aligns with Section 9 backup model).
- Restrict network access to Qdrant from approved CanI Docs services only.

## 10.10 Security baseline for AKS

- Pod Security Standards enforced (baseline/restricted as appropriate per namespace).
- NetworkPolicy deny-by-default posture, then explicit allow rules.
- Admission/policy checks for privileged containers, hostPath, and unsafe capabilities.
- ACR pull permissions scoped per workload identity.
- Audit logging and Kubernetes control plane logs forwarded to central Log Analytics.

## 10.11 Observability and operations

Required telemetry:
- Node/pod CPU and memory saturation.
- Pod restart/crashloop rates by namespace.
- Ingress latency/error rates.
- Queue lag and worker throughput for async pipeline.

Operational practices:
- Runbook for node pool scale events, failed upgrades, and private DNS failures.
- SLO-aligned alerts for query latency and ingestion backlog.

## 10.12 Upgrade and maintenance strategy

- Stay within AKS supported Kubernetes version window (N and N-1).
- Upgrade non-production first, then production with maintenance windows.
- Use surge settings and rolling node replacement to reduce disruption.
- Test rollback path for ingress and critical service deployments before each minor upgrade.

## 10.13 Cost controls

- Separate pool sizing for stateless vs stateful vs batch workloads.
- Spot node usage only for interruption-safe worker jobs.
- Idle-time scale-down policies for worker deployments.
- Review per-namespace cost signals monthly to detect spoke drift.

## 10.14 v1 implementation checklist

- Provision private AKS cluster with Entra-integrated RBAC.
- Create namespace, network policy, and workload identity baseline manifests.
- Create `systempool`, `appspool`, and `datapool` with autoscaler bounds.
- Deploy ingress controller and enforce public/internal service exposure policy.
- Configure HPA/KEDA for API and worker paths.
- Deploy Qdrant StatefulSet with backups and network restrictions.
- Enable Container Insights and AKS control plane diagnostics.
- Validate upgrade runbook in a non-production environment.

## 10.15 Open questions

1. Should CanI Hub remain in this cluster long term, or move to a separate runtime for blast-radius reduction?
2. At what load threshold should CanI move from shared cluster to spoke-specific clusters?
3. Is an explicit egress firewall phase required before public launch, or can NAT + policy controls carry v1?

---

[← Data model & storage](09-data-model-and-storage.md) | [Back to index](README.md) | Next: [IaC strategy →](11-iac-strategy.md)