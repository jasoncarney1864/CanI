# 11. IaC strategy

This section defines how infrastructure is represented, organized, promoted, and governed using Pulumi (Python) for the CanI platform.

## 11.1 Goals and constraints

Goals:
- Keep all Azure infrastructure reproducible and reviewable as code.
- Separate slow-moving platform foundation from fast-moving workload changes.
- Make day-to-day operations manageable for one developer.
- Keep future team scaling possible without re-architecting IaC.

Constraints:
- IaC tool is Pulumi with Python (hard requirement from Section 2).
- Landing zone model from Section 6 already defines platform/workload split.
- CI/CD uses GitHub Actions with OIDC identities.

## 11.2 Repository strategy decision

**Decision (v1): monorepo with clear boundaries.**

Rationale:
- Lower coordination overhead for a solo developer.
- Easier cross-section refactors when app, infra, and docs evolve together.
- Simplifies shared standards for naming, tagging, and environments.

Expected trade-off:
- CI runs can grow as the repository grows; mitigated by path-based workflow triggers.

## 11.3 Proposed repository layout

High-level structure:
- `docs/` architecture and ADR material.
- `infra/platform/` Pulumi project for management groups, policy, hub network, shared services.
- `infra/workload/` Pulumi project for AKS, data services, and workload-connected resources.
- `infra/modules/` reusable Pulumi component resources shared by platform/workload.
- `apps/` application services (hub/docs/legal/health) and deployment manifests.
- `.github/workflows/` pipeline definitions for preview/apply/deploy stages.

Layout principle:
- Infrastructure composition lives in `infra/platform` and `infra/workload`; reusable logic goes to `infra/modules` only when reused in at least two places.

## 11.4 Pulumi project and stack model

Projects:
- `cani-platform` (platform landing zone layer)
- `cani-workload` (workload landing zone layer)

Stacks (v1):
- `dev`
- `prod`

Stack naming convention:
- `<project>/<environment>` (for example: `cani-platform/dev`, `cani-workload/prod`)

Ownership boundaries:
- Platform stack changes are infrequent, high-impact, approval-gated.
- Workload stack changes are frequent, delivery-oriented, still policy-gated.

## 11.5 State and secrets strategy

State:
- Use remote Pulumi state backend with access via federated identity.
- Enable storage-level protection controls (soft delete/versioning where supported) and restricted network access.

Secrets:
- No plain secrets in repository or pipeline variables.
- Application/runtime secrets live in Azure Key Vault and are referenced at deploy/runtime.
- Pulumi config secrets must use encrypted secret handling only.

## 11.6 Cross-stack contract and dependencies

`cani-workload` consumes outputs from `cani-platform` via `StackReference`.

Platform outputs expected by workload:
- Hub/shared network identifiers (VNet/subnet IDs as needed)
- Central Log Analytics workspace identifiers
- Shared ACR and Key Vault resource identifiers
- Policy or diagnostic destination identifiers needed by workload resources

Contract rules:
- Output keys are versioned and treated as stable interfaces.
- Breaking output changes require coordinated update in both projects.

## 11.7 Module design and coding standards

Module guidance:
- Favor small Pulumi ComponentResources with clear inputs/outputs.
- Avoid circular dependencies between modules.
- Keep Azure resource naming and tags centralized in helper utilities.

Recommended module families:
- `modules/networking`
- `modules/security`
- `modules/observability`
- `modules/compute-aks`
- `modules/data-services`

Coding standards:
- Type hints and dataclass-style config objects for component inputs.
- Deterministic defaults over implicit environment behavior.
- Minimal side effects in module constructors.

## 11.8 Environment promotion and change flow

Promotion model:
1. Pull request runs `pulumi preview` for impacted project/stack.
2. Merge to main applies to `dev` with OIDC identity.
3. Production apply is manual approval gate with separate environment protection.

Safety controls:
- Require preview artifact review before apply.
- Block destructive replacements in production unless explicitly approved.
- Keep platform applies separate from workload applies.

## 11.9 Drift management and brownfield changes

Drift strategy:
- Run scheduled drift detection (`pulumi preview --refresh`) for both projects.
- Investigate and reconcile drift before unrelated changes are applied.

Brownfield/import strategy:
- Import existing resources explicitly rather than recreate.
- Document import commands and resulting state assumptions in runbooks.

## 11.10 Naming, tagging, and policy alignment

Tag baseline (from Section 6 policy):
- `environment`
- `owner`
- `spoke`

Naming convention:
- `<project>-<layer>-<env>-<region>-<suffix>` where practical.
- Keep naming logic in one shared helper module to avoid drift.

## 11.11 v1 implementation checklist

- Create monorepo directories for `infra/platform`, `infra/workload`, and shared modules.
- Initialize Pulumi Python projects and baseline stack configs (`dev`, `prod`).
- Implement `StackReference` contract from platform to workload.
- Add shared naming/tagging helpers and enforce use across modules.
- Configure state backend access through federated identities.
- Implement preview/apply GitHub workflows with environment approvals.
- Add drift detection workflow and operational runbook.

## 11.12 Open questions

1. At what scale threshold should CanI split infra into a dedicated repository?
2. Should policy-as-code (for example, Pulumi CrossGuard) be added in v1 or deferred to the security/compliance phase?
3. Is a separate `stage` environment needed before `prod`, or is `dev` plus approval gates sufficient initially?

---

[← AKS cluster design](10-aks-cluster-design.md) | [Back to index](README.md) | Next: [CI/CD strategy →](12-cicd-strategy.md)