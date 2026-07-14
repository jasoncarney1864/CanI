# 12. CI/CD strategy

This section defines the delivery pipeline for CanI applications and infrastructure using GitHub Actions, protected environments, and OIDC federation.

## 12.1 Goals and constraints

Goals:
- Keep delivery repeatable, observable, and safe for a solo operator.
- Separate validation from deployment and enforce promotion gates.
- Avoid long-lived cloud credentials in CI/CD.
- Support independent deployment cadence for platform and workload layers.

Constraints:
- Source control and automation platform is GitHub.
- Azure auth from pipelines must use OIDC federation.
- IaC is Pulumi Python and aligns with Section 11 project/stack structure.

## 12.2 Pipeline architecture overview

Pipeline families:
- Infrastructure pipeline for `infra/platform` and `infra/workload`.
- Application pipeline for `apps/*` services and manifests.
- Operational pipeline for drift checks, backups, and policy verification jobs.

Execution model:
1. Pull request: lint/test/preview only.
2. Merge to main: deploy to `dev` automatically.
3. Promotion to `prod`: explicit approval gate through protected environment.

## 12.3 Branching and release model

**Decision (v1): trunk-based development with protected `main`.**

Rules:
- Short-lived feature branches only.
- Pull request required before merge.
- Required checks must pass before merge.
- Direct push to `main` disabled.

Release handling:
- Tag releases from `main` for production promotion traceability.
- Rollback references previous known-good tag/artifact.

## 12.4 GitHub Actions workflow set

Core workflows:
- `infra-preview.yml`
  - Trigger: pull requests touching `infra/**`
  - Actions: dependency install, policy checks, `pulumi preview`
- `infra-apply-dev.yml`
  - Trigger: push to `main` touching `infra/**`
  - Actions: `pulumi up` to `dev` stacks
- `infra-apply-prod.yml`
  - Trigger: manual dispatch or release tag
  - Actions: `pulumi up` to `prod` stacks after approval
- `app-ci.yml`
  - Trigger: pull requests touching `apps/**`
  - Actions: build, unit tests, container image build/scan
- `app-cd-dev.yml`
  - Trigger: push to `main` touching `apps/**`
  - Actions: publish image, deploy to dev AKS namespaces
- `app-cd-prod.yml`
  - Trigger: manual dispatch or release tag
  - Actions: deploy approved image/tag to prod namespaces
- `ops-drift-detection.yml`
  - Trigger: scheduled + manual
  - Actions: refresh previews, drift report artifact, alert on unexpected changes

## 12.5 Environment model and protections

GitHub environments:
- `dev`
- `prod`

Protection policies:
- `dev`: low-friction deploy, still audited.
- `prod`: required reviewers, wait timer (optional), and restricted secret access.

Separation rules:
- Infra and app workflows both target these environments but keep independent approval events.
- Platform infrastructure production changes require stronger reviewer policy than workload app rollout.

## 12.6 OIDC federation and Azure identity mapping

Identity mapping:
- Platform pipeline uses Platform federated identity (Section 6).
- Workload/app pipeline uses Workload federated identity.

Security controls:
- Restrict federated credential subject claims to specific repo, branch/tag, and workflow contexts.
- No client secret or certificate stored in GitHub for Azure login.
- Least-privilege role assignments by environment and scope.

## 12.7 Artifact and image flow

Build flow:
1. Build container images from application changes.
2. Scan image for vulnerabilities and fail on defined severity threshold.
3. Push signed/tagged image to ACR.
4. Deploy immutable image tag (no `latest`) to target environment.

Promotion policy:
- `prod` consumes previously built and validated artifact from `dev` lineage.
- No rebuild on production promotion unless explicitly required.

## 12.8 Deployment strategy for AKS workloads

Rollout approach:
- Use rolling updates with readiness/liveness gates.
- One namespace/environment at a time for controlled blast radius.
- Include post-deploy smoke checks for hub auth, retrieval path, and citation endpoint.

Failure response:
- Automatic rollback if health gates fail.
- Emit deployment event and incident signal to monitoring channel.

## 12.9 GitOps adoption plan (optional)

**Decision (v1): hybrid CI/CD first, GitOps later.**

Phase 1 (v1):
- GitHub Actions performs deployments directly with audited workflows and approvals.

Phase 2 (later):
- Add GitOps controller for continuous reconciliation of Kubernetes manifests.
- CI pipeline publishes signed manifests/charts; controller applies desired state.

Reasoning:
- Reduces initial complexity while preserving a clear migration path.

## 12.10 Security and compliance controls in pipelines

- Required dependency and container vulnerability scanning.
- Secret scanning on pull requests and push events.
- Prevent unreviewed workflow changes from triggering privileged deploy jobs.
- Signed commits/tags preferred for production promotion events.
- Full audit trail: actor, commit SHA, artifact digest, deployment target.

## 12.11 Observability and operational metrics for CI/CD

Required metrics:
- Workflow success/failure rate by pipeline family.
- Mean lead time from merge to dev deployment.
- Mean time from prod deploy failure to rollback.
- Deployment frequency by service and environment.

Operational outputs:
- Persist preview/apply logs and drift reports as artifacts.
- Emit deployment annotations into application telemetry for correlation.

## 12.12 v1 implementation checklist

- Create GitHub environments (`dev`, `prod`) with branch rules and reviewers.
- Configure OIDC federated credentials for platform and workload identities.
- Implement infra preview/apply workflows aligned to Section 11 stacks.
- Implement app CI and dev/prod deployment workflows with immutable tags.
- Add vulnerability scan and policy gates to PR and deploy workflows.
- Add drift detection schedule and alert routing.
- Document rollback runbooks for infra and app failures.

## 12.13 Open questions

1. Should production app deployment be fully manual approval or time-windowed auto-promotion after stability checks?
2. Which policy engine should gate workflow and IaC changes (native checks only vs additional policy-as-code)?
3. At what maturity point should GitOps reconciliation move from optional to default?

---

[← IaC strategy](11-iac-strategy.md) | [Back to index](README.md) | Next: [Observability →](13-observability.md)