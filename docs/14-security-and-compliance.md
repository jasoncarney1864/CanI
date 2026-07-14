# 14. Security & compliance

This section defines the security model, threat posture, and compliance-oriented controls for CanI, building on the PHI/PII-default decision in ADR-007.

## 14.1 Goals and constraints

Goals:
- Protect sensitive user legal/health data end to end.
- Reduce likelihood and impact of unauthorized access or data leakage.
- Make controls auditable and operationally practical for one operator.
- Align technical safeguards with a PHI/PII-grade data posture.

Constraints:
- CanI is not a HIPAA-covered entity, but adopts PHI-grade controls by design.
- Platform is Azure-first with AKS and private network architecture from Sections 6 and 10.
- Identity, data, and observability controls from Sections 7, 9, and 13 are foundational inputs.

## 14.2 Security principles

- Deny by default.
- Least privilege for humans, workloads, and pipelines.
- Defense in depth across identity, network, data, and runtime controls.
- Explicit ownership scoping for every user data access path.
- Secure-by-default configurations, with exceptions documented and time-bounded.

## 14.3 Threat model (v1)

Primary threat scenarios:
- Unauthorized cross-user data access via API, query, or retrieval path.
- Credential theft or token replay against hub/spoke endpoints.
- Data exfiltration from misconfigured storage, vector store, or logs.
- Supply-chain risk from vulnerable images/dependencies or compromised CI/CD paths.
- Insider or operator misuse of elevated privileges.

Trust boundaries:
- Public client boundary at user-facing ingress.
- Service boundary between hub and spoke workloads.
- Data boundary around Blob Storage, PostgreSQL, and Qdrant.
- Administrative boundary for break-glass and deployment identities.

## 14.4 Data classification and handling model

Classification baseline:
- All uploaded document content is treated as sensitive PHI/PII-equivalent.
- Derived artifacts (chunks, embeddings metadata, citations, query history) are also sensitive.

Handling rules:
- No raw sensitive payloads in logs, traces, or error messages.
- Minimize data copies between systems and environments.
- Use data retention limits and deletion workflows from Section 9.

## 14.5 Identity and access security controls

- Entra External ID for user authentication and modern token flows (Section 7).
- Short-lived tokens, secure session handling, and high-risk action re-authentication.
- Workload identities for pod-to-Azure access; no static cloud credentials in workloads.
- Mandatory entitlement and ownership checks at hub, API, and data access layers.
- Administrative actions fully audited with actor and reason.

## 14.6 Network security controls

- Private cluster AKS posture and private endpoints for data services.
- NetworkPolicy deny-by-default in Kubernetes namespaces.
- Restricted east-west service communication with explicit allow rules.
- Deterministic egress through NAT Gateway, with future firewall phase as needed.
- No public exposure for Qdrant or internal data-path services.

## 14.7 Encryption and key management

- Encryption in transit using TLS 1.2+ for all service and data paths.
- Encryption at rest across Blob Storage, PostgreSQL, and persistent volumes.
- Key Vault as the source of truth for application secrets and keys.
- Customer-managed keys where supported and operationally justified.
- Key rotation schedule defined and tested with non-disruptive rollout procedure.

## 14.8 Application and API security

- Input validation and strict file-type/size checks on upload endpoints.
- Prompt-injection-aware retrieval guardrails (ignore policy-override instructions in documents).
- CSRF protections and secure cookie settings for browser sessions.
- Rate limiting and abuse protection on externally reachable APIs.
- Secure defaults for error handling that avoid sensitive data leakage.

## 14.9 Runtime and platform hardening

- Pod Security Standards and admission controls enforced in AKS.
- Restrict privileged containers and unsafe host-level capabilities.
- Vulnerability scanning for container images and dependency manifests.
- Signed and immutable deployment artifacts promoted through environments.
- Baseline hardening checks included in CI/CD gate criteria.

## 14.10 Secrets management and exposure prevention

- No secrets in source code, pull requests, or plain-text pipeline variables.
- Secret scanning enabled for repository and CI events.
- Runtime secret retrieval from Key Vault with least-privilege identity binding.
- Break-glass secret access time-limited and audit-logged.

## 14.11 Incident response and recovery

Incident lifecycle:
1. Detect and triage from security alerts (Section 13).
2. Contain impacted identity/workload/data path.
3. Eradicate root cause and rotate potentially exposed credentials.
4. Recover service and validate integrity.
5. Publish post-incident review with corrective actions.

Preparedness requirements:
- Runbooks for suspected cross-tenant access, credential compromise, and data exposure.
- Clear severity model and escalation path for P1 security incidents.

## 14.12 Compliance posture and auditability

Compliance intent:
- Security controls are mapped to recognized privacy/security practices even without formal HIPAA scope.
- Evidence collection supports future compliance review or external audit needs.

Audit evidence sources:
- Identity and authorization event logs.
- Deployment and change history from CI/CD workflows.
- Security scan results and remediation tracking.
- Access reviews for privileged roles and break-glass usage.

## 14.13 Security testing and validation

- Dependency and container vulnerability scanning in CI.
- Periodic configuration review for AKS, storage, and identity settings.
- Targeted penetration-style tests for authz bypass and tenant isolation flaws.
- Disaster recovery and backup restore drills for critical data paths.

## 14.14 v1 implementation checklist

- Publish v1 threat model with owners and review cadence.
- Enforce ownership-scoped authorization checks on all data read paths.
- Enable repository and pipeline secret scanning and dependency scanning.
- Confirm private endpoint and public-access-deny posture for data services.
- Finalize key rotation and break-glass procedures.
- Define security incident runbooks and escalation contacts.
- Establish evidence retention process for security/compliance reviews.

## 14.15 Open questions

1. Which external security benchmark should CanI formally align to first (for example, CIS controls profile)?
2. What cadence is realistic for recurring threat model and access review sessions?
3. Which controls must be mandatory before public launch versus phased post-launch hardening?

---

[← Observability](13-observability.md) | [Back to index](README.md) | Next: [Cost management →](15-cost-management.md)