# 17. Sprint 1 execution board

Execution board for Sprint 1 from the current v1 checkpoint. This turns the plan in
implementation-status into a trackable run sheet with owners, dates, status, and
explicit acceptance checks.

## Board metadata

- Sprint: Sprint 1 - Live infrastructure unblock
- Owner: Jason
- Start date: 2026-07-14
- Target end date: 2026-07-28
- Last updated: 2026-07-14
- Overall status: In progress

## Status legend

- [ ] Not started
- [-] In progress
- [x] Done
- [!] Blocked

## Weekly status rollup

| Week | Date range | Planned focus | Planned complete (%) | Actual complete (%) | Delta (pp) | Key blocker | Notes |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| Week 1 | 2026-07-14 to 2026-07-20 | Access, OIDC, platform or workload apply, initial AKS apply | 60 | 0 | -60 | B1 platform apply not started yet | A1 and A2 complete; infra-preview passed on run 29389080854 |
| Week 2 | 2026-07-21 to 2026-07-28 | App CD activation, Entra swap, entitlement revocation, sprint closeout | 100 | 0 | -100 | TBD | Fill at week close |

Formula: Actual complete (%) = round((number of checked boxes [x] in sprint checklist items / total sprint checklist boxes) x 100).

## Workstream A - Access and identities

### A1. Azure subscription execution access (P0)

- Owner: Jason
- Due: 2026-07-15
- Status: [x] Done
- Dependencies: none
- Checklist:
  - [x] Confirm subscription selected for workload resources.
  - [x] Confirm contributor-level access for workload deployment identity.
  - [x] Confirm platform-scope rights for one-time management group bootstrap.
  - [x] Record selected subscription ID and tenant ID in sprint notes.
- Done criteria:
  - [x] Workload and platform scopes can be queried successfully from CLI.

Execution notes (2026-07-14):
- Azure extensions auth context: signed in as jasonbrookecarney@outlook.com (tenant ddb3853e-a709-42c4-8841-8e69da7a1c45, Default Directory).
- Selected and default subscription: 6591cee6-ee26-4155-ae71-3777bf7e9c73 (Default, Enabled).
- Subscription-scope role assignments are readable at /subscriptions/6591cee6-ee26-4155-ae71-3777bf7e9c73.
- Azure CLI confirms current user object ID 9b14372c-a8ab-4d09-822d-578178fb0812 has Owner at subscription scope /subscriptions/6591cee6-ee26-4155-ae71-3777bf7e9c73 (Contributor-or-better satisfied).
- Microsoft Graph confirms this identity is in the Global Administrator directory role.
- Tenant-root management-group scope query at /providers/Microsoft.Management/managementGroups/ddb3853e-a709-42c4-8841-8e69da7a1c45 returned no explicit role assignments.
- az account management-group list currently fails with AuthorizationFailed for this identity, so platform bootstrap permissions are not yet in place.
- Root-scope role query (scope /) also returns no assignments, indicating elevated Azure-resource access is not active for this session.
- Follow-up needed: complete the one-time elevated-access bootstrap path for management-group creation, then re-run management-group visibility checks.
- Re-check result: as of 2026-07-14, `az account management-group list` still fails with AuthorizationFailed.
- Final verification (2026-07-14): `az account management-group list` succeeds and returns Tenant Root Group.
- Final verification (2026-07-14): current user has User Access Administrator at root scope `/`.

### A2. GitHub OIDC federation for infra/app workflows (P0)

- Owner: Jason
- Due: 2026-07-16
- Status: [x] Done
- Dependencies: A1
- Checklist:
  - [x] Create platform and workload federated identities.
  - [x] Add repo or environment secrets used by workflows:
    - [x] AZURE_CLIENT_ID_PLATFORM
    - [x] AZURE_CLIENT_ID_WORKLOAD
    - [x] AZURE_TENANT_ID
    - [x] AZURE_SUBSCRIPTION_ID
    - [x] PULUMI_ACCESS_TOKEN
  - [x] Validate auth with a pull request touching infra files.
- Done criteria:
  - [x] infra-preview workflow authenticates and reaches pulumi preview.

Execution notes (2026-07-14):
- Created or verified Entra app registrations and service principals:
  - platform: cani-platform-github-oidc (appId c6f6de9b-5bac-44de-8275-0bc0d7ba15dc, servicePrincipalObjectId 70683e31-95a8-46bc-8b43-b9be9bfded6f)
  - workload: cani-workload-github-oidc (appId 8ad51b43-0e1a-4a3f-9f92-07e455bda855, servicePrincipalObjectId 3e72ef11-bfce-4aae-8332-9c3f9a764d84)
- Added federated credentials for both apps:
  - cani-main (repo:jasoncarney1864/CanI:ref:refs/heads/main)
  - cani-pr (repo:jasoncarney1864/CanI:pull_request)
- GitHub repository secrets set:
  - AZURE_CLIENT_ID_PLATFORM
  - AZURE_CLIENT_ID_WORKLOAD
  - AZURE_TENANT_ID
  - AZURE_SUBSCRIPTION_ID
- Role assignments verified:
  - workload identity: Contributor at subscription scope
  - platform identity: Contributor at subscription scope, User Access Administrator at root scope, Management Group Contributor at root scope
- Workflow updates applied to split identities:
  - infra-preview and infra-apply-dev now use AZURE_CLIENT_ID_PLATFORM
  - app-cd-dev now uses AZURE_CLIENT_ID_WORKLOAD
- Validation check: GitHub repo secret `PULUMI_ACCESS_TOKEN` is present.
- Validation evidence: infra-preview run 29386602963 reached `Run pulumi/actions@v5` for both matrix jobs after azure/login succeeded.
- Follow-up evidence: Pulumi Cloud stack and config prerequisites were added and committed via `infra/platform/Pulumi.dev.yaml` and `infra/workload/Pulumi.dev.yaml`.
- Final auth validation: infra-preview run 29389080854 succeeded for both `preview (platform)` and `preview (workload)`.

## Workstream B - Platform and workload infrastructure

### B1. One-time platform bootstrap apply (P0)

- Owner: Jason
- Due: 2026-07-17
- Status: [ ] Not started
- Dependencies: A1, A2
- Checklist:
  - [ ] Complete elevated access step for management group bootstrap.
  - [ ] Initialize Pulumi dev stack for platform.
  - [ ] Set required platform config values.
  - [ ] Run pulumi up in infra/platform.
  - [ ] Capture stack outputs for downstream contract.
- Done criteria:
  - [ ] Management groups, hub VNet, central Log Analytics, shared ACR, and platform Key Vault exist.

### B2. Workload apply to dev with StackReference contract (P0)

- Owner: Jason
- Due: 2026-07-18
- Status: [ ] Not started
- Dependencies: B1
- Checklist:
  - [ ] Initialize Pulumi dev stack for workload.
  - [ ] Set workload config values:
    - [ ] platformStackRef
    - [ ] aadAdminGroupObjectIds
  - [ ] Run pulumi up in infra/workload.
  - [ ] Validate AKS, Postgres, Storage, and diagnostics resources are present.
- Done criteria:
  - [ ] All required workload outputs resolve without errors.

## Workstream C - AKS and deployment activation

### C1. Align names and image endpoints in CI and manifests (P1)

- Owner: Jason
- Due: 2026-07-19
- Status: [ ] Not started
- Dependencies: B2
- Checklist:
  - [ ] Confirm ACR login server used by app-cd-dev and kustomize images.
  - [ ] Confirm AKS resource group and cluster names in app-cd-dev.
  - [ ] Patch workflow or manifests if generated names differ from assumptions.
- Done criteria:
  - [ ] app-cd-dev references only real deployed resource names.

### C2. Apply k8s overlays to dev AKS (P1)

- Owner: Jason
- Due: 2026-07-20
- Status: [ ] Not started
- Dependencies: C1
- Checklist:
  - [ ] Set AKS context.
  - [ ] Apply k8s/overlays/dev.
  - [ ] Validate rollouts for hub-api, docs-api, retrieval-worker.
  - [ ] Validate qdrant statefulset and core namespaces.
- Done criteria:
  - [ ] All target deployments are available and healthy.

### C3. Activate app-cd-dev workflow path (P1)

- Owner: Jason
- Due: 2026-07-21
- Status: [ ] Not started
- Dependencies: C2
- Checklist:
  - [ ] Trigger apps change to run app-cd-dev.
  - [ ] Verify image build and push for each service.
  - [ ] Verify kustomize image updates and apply step.
  - [ ] Verify post-deploy smoke check.
- Done criteria:
  - [ ] One full successful app deployment to dev AKS from GitHub Actions.

## Workstream D - Auth hardening gap closure

### D1. Replace dev login with real Entra External ID flow (P1)

- Owner: Jason
- Due: 2026-07-24
- Status: [ ] Not started
- Dependencies: A1, A2
- Checklist:
  - [ ] Create Entra External ID tenant and app registration.
  - [ ] Implement OIDC callback flow in hub-api auth entrypoint.
  - [ ] Validate whoami and token issuance behavior remains compatible.
- Done criteria:
  - [ ] Non-dev environment auth no longer depends on the dev login route.

### D2. Entitlement revocation session invalidation (P1)

- Owner: Jason
- Due: 2026-07-25
- Status: [ ] Not started
- Dependencies: D1
- Checklist:
  - [ ] Implement revocation path that invalidates active session and token usage.
  - [ ] Add tests covering revoked user behavior on existing session.
  - [ ] Update incident runbook guidance if behavior changes.
- Done criteria:
  - [ ] Revoked entitlement cannot continue using previously issued credentials.

## Sprint closeout gate

- Owner: Jason
- Due: 2026-07-28
- Status: [ ] Not started
- Checklist:
  - [ ] CI remains green for lint, format check, unit, and integration.
  - [ ] infra-preview and infra-apply-dev both succeed with OIDC.
  - [ ] app-cd-dev succeeds end to end on dev AKS.
  - [ ] implementation-status updated to reflect scaffolded versus live deltas.
- Done criteria:
  - [ ] Sprint 1 marked complete with blockers reduced to operational readiness items.

## Daily standup log

Use one line per day.

- 2026-07-14: Board created. A1 completed after management-group access unblocked and root-scope User Access Administrator confirmed. A2 completed after OIDC identities, repo secrets, federated credentials, and workflow auth validation were verified in infra-preview. Latest infra-preview run 29389080854 is green; next step is B1 platform apply.
