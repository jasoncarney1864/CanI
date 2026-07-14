# 16. Roadmap & phasing

This section converts the architecture into an execution plan, defining what ships in each phase, what gates promotion, and how risk is managed over time.

## 16.1 Planning principles

- Ship smallest useful scope first.
- Protect user-data isolation and security posture in every phase.
- Favor reversible changes and measurable milestones.
- Keep scope sized for a solo delivery cadence.

## 16.2 Phase definitions

Phase 0: Foundation and architecture completion (now)
- Outcome: architecture baselines documented and decisions captured.
- Status: complete through Sections 1-16 and accepted ADRs.

Phase 1: Core v1 MVP (CanI Docs first)
- Outcome: authenticated upload, ingestion, retrieval, and cited answers for user-owned docs.
- Target focus: correctness, isolation, and operational basics over feature breadth.

Phase 2: Reliability and operational hardening
- Outcome: stronger incident readiness, upgrade discipline, and performance consistency.
- Target focus: reduce operational risk and improve mean time to recovery.

Phase 3: Expansion and optimization
- Outcome: broaden spoke capabilities (Legal/Health depth), improve quality/cost ratio.
- Target focus: measured growth with sustainable run-rate.

## 16.3 Scope by phase

Phase 1 (v1) in-scope:
- Hub authentication and entitlement checks.
- CanI Docs ingestion pipeline (OCR/chunk/embed/index).
- Retrieval with strict owner filtering and citations.
- Single shared AKS cluster with baseline observability/security controls.
- CI/CD with dev/prod gates and OIDC identities.

Phase 1 out-of-scope:
- Multi-user sharing/households.
- Advanced agentic orchestration or autonomous workflows.
- Complex multi-region disaster recovery.

Phase 2 additions:
- Expanded alert/runbook coverage and incident drills.
- Upgrade automation maturity and rollback confidence improvements.
- More complete cost automation and anomaly response tuning.

Phase 3 additions:
- Deeper domain capabilities for Legal and Health spokes.
- Selective architecture decomposition if scale or risk requires it.
- Optional GitOps default and further platform optimization.

## 16.4 Milestones and exit criteria

Milestone A: v1 functional readiness
- Upload-to-answer path works end-to-end.
- Citation output is consistently present and traceable.
- No known cross-user access path in validation tests.

Milestone B: v1 operational readiness
- Critical alerts configured and tested.
- Backup/restore and deletion workflows validated.
- Basic security runbooks exercised once.

Milestone C: v1 production launch readiness
- Production environment passes deployment gates.
- Budget and anomaly guardrails configured.
- Known high-risk issues have explicit mitigations/acceptance.

## 16.5 Dependency map

Critical dependency chain:
1. Identity/access (Section 7)
2. RAG pipeline + data model (Sections 8-9)
3. AKS + IaC + CI/CD (Sections 10-12)
4. Observability + security + cost controls (Sections 13-15)
5. Launch decision gate (this section)

Execution implication:
- No production launch until all dependencies in chain are implemented and verified for v1 scope.

## 16.6 Risk register (delivery-level)

Top risks for near-term delivery:
- Scope creep from adding spoke features too early.
- Operational overload from platform complexity.
- Unexpected cloud cost growth during ingestion/model tuning.
- Security gaps from rushed integration changes.

Mitigation pattern:
- Timebox feature work.
- Keep release checklist strict and short.
- Trigger weekly risk review during pre-launch.

## 16.7 Release cadence and change windows

Suggested cadence:
- Weekly development increments to `dev`.
- Controlled promotion windows to `prod`.
- Immediate hotfix path with post-release review.

Change freeze triggers:
- Active unresolved P1 incident.
- Security control regression.
- Budget breach without mitigation plan.

## 16.8 Success metrics by phase

Phase 1 success indicators:
- End-to-end query success rate.
- Ingestion completion time for common docs.
- Security incident count and severity trend.

Phase 2 success indicators:
- Alert precision (signal/noise).
- Mean time to detect and recover.
- Upgrade success rate and rollback frequency.

Phase 3 success indicators:
- Cost per successful query trend.
- Spoke adoption and retention indicators.
- Feature delivery lead time stability.

## 16.9 Decision gates for next phase

Gate to move Phase 1 -> Phase 2:
- MVP stable in production-like use.
- Core SLOs and security controls demonstrably enforced.

Gate to move Phase 2 -> Phase 3:
- Operational toil reduced to sustainable level.
- Cost and reliability trends are predictable for at least one full review cycle.

## 16.10 v1 launch checklist summary

- Functional path validated: auth -> upload -> ingest -> retrieve -> cite.
- Security controls from Section 14 operationalized.
- Observability and alerting from Section 13 active and tuned.
- Cost guardrails from Section 15 configured.
- Incident, rollback, and recovery runbooks confirmed.

## 16.11 Open questions

1. What user cohort defines "launch" for initial v1 (personal-only vs limited external users)?
2. Which phase should include first meaningful Legal/Health spoke differentiation?
3. What objective threshold should trigger architecture split from shared AKS to multi-cluster?

---

[← Cost management](15-cost-management.md) | [Back to index](README.md) | Next: [Appendix A — Glossary →](appendix-a-glossary.md)