# 17. Sprint 1 execution board

Execution board for Sprint 1 from the current v1 checkpoint. This turns the plan in
implementation-status into a trackable run sheet with owners, dates, status, and
explicit acceptance checks.

## Board metadata

- Sprint: Sprint 1 - Live infrastructure unblock
- Owner: Jason
- Start date: 2026-07-14
- Target end date: 2026-07-28
- Last updated: 2026-07-15
- Overall status: In progress

## Status legend

- [ ] Not started
- [-] In progress
- [x] Done
- [!] Blocked

## Weekly status rollup

| Week | Date range | Planned focus | Planned complete (%) | Actual complete (%) | Delta (pp) | Key blocker | Notes |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| Week 1 | 2026-07-14 to 2026-07-20 | Access, OIDC, platform or workload apply, initial AKS apply | 60 | 75 | +15 | None - D1 (Entra tenant) is the next gating item | A1, A2, B1, B2, C1, C2, C3 complete (C3 ahead of Week 2 plan); CD pipeline verified end to end on 2026-07-15; 42 of 56 boxes checked |
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
- Status: [x] Done
- Dependencies: A1, A2
- Checklist:
  - [x] Complete elevated access step for management group bootstrap.
  - [x] Initialize Pulumi dev stack for platform.
  - [x] Set required platform config values.
  - [x] Run pulumi up in infra/platform.
  - [x] Capture stack outputs for downstream contract.
- Done criteria:
  - [x] Management groups, hub VNet, central Log Analytics, shared ACR, and platform Key Vault exist.

Execution notes (2026-07-14):
- Local preflight `pulumi preview --stack dev` succeeded for `infra/platform`.
- Initial `pulumi up` surfaced and resolved real IaC defects:
  - ACR Standard SKU + public network disabled incompatibility.
  - Policy assignment name length limit (24 chars).
  - Outdated built-in Storage public network policy definition ID.
- Final `pulumi up --stack dev` succeeded and exported contract outputs:
  - `hub_vnet_id`
  - `log_analytics_workspace_id`
  - `acr_login_server`
  - `acr_id`
  - `platform_key_vault_id`
  - `workload_management_group_id`

### B2. Workload apply to dev with StackReference contract (P0)

- Owner: Jason
- Due: 2026-07-18
- Status: [x] Done
- Dependencies: B1
- Checklist:
  - [x] Initialize Pulumi dev stack for workload.
  - [x] Set workload config values:
    - [x] platformStackRef
    - [x] aadAdminGroupObjectIds
  - [x] Run pulumi up in infra/workload.
  - [x] Validate AKS, Postgres, Storage, and diagnostics resources are present.
- Done criteria:
  - [x] All required workload outputs resolve without errors.

Execution notes (2026-07-15):
- Initial workload apply surfaced IaC and platform constraints that were fixed in code:
  - Added required Postgres admin password configuration (`postgresAdminPassword`).
  - Added deterministic AKS `dnsPrefix` generation.
  - Added delegated Postgres subnet and private DNS zone wiring (`privatelink.postgres.database.azure.com`).
  - Switched AKS nodepool VM sizes from DSv5 to DSv4 to match eastus2 quota.
- During convergence, Azure reported a stale in-progress AKS operation tied to an already-created managed cluster name (`cani-aks64bdb7d1`) while Pulumi logical name remained `cani-aks`.
- Recovery: aborted the latest AKS operation using the actual Azure cluster name, then re-ran `pulumi up`.
- Final result: Pulumi update version 6 succeeded (1 created, 1 updated), and outputs resolved:
  - `aks_cluster_id`
  - `aks_oidc_issuer_url`
  - `postgres_fqdn`
  - `storage_account_id`
  - `acr_id_reference`

## Workstream C - AKS and deployment activation

### C1. Align names and image endpoints in CI and manifests (P1)

- Owner: Jason
- Due: 2026-07-19
- Status: [x] Done
- Dependencies: B2
- Checklist:
  - [x] Confirm ACR login server used by app-cd-dev and kustomize images.
  - [x] Confirm AKS resource group and cluster names in app-cd-dev.
  - [x] Patch workflow or manifests if generated names differ from assumptions.
- Done criteria:
  - [x] app-cd-dev references only real deployed resource names.

Execution notes (2026-07-15):
- app-cd-dev now references live dev workload names/IDs from successful workload apply:
  - AKS resource group: `cani-workload-core-dev-eastus2-rg9c8e66d0`
  - AKS cluster: `cani-aks64bdb7d1`
  - ACR name/login server: `canishareded20367db8` / `canishareded20367db8.azurecr.io`
  - Storage account ID: `/subscriptions/6591cee6-ee26-4155-ae71-3777bf7e9c73/resourceGroups/cani-workload-core-dev-eastus2-rg9c8e66d0/providers/Microsoft.Storage/storageAccounts/cani9820b2c229`
- Added deploy-time preflight checks for AKS, ACR, and storage account contract IDs.
- Updated k8s base and overlay image references from `cani.azurecr.io/*` to `canishareded20367db8.azurecr.io/*`.

### C2. Apply k8s overlays to dev AKS (P1)

- Owner: Jason
- Due: 2026-07-20
- Status: [x] Done
- Dependencies: C1
- Checklist:
  - [x] Set AKS context. (Adapted: cluster API server is private, so all kubectl runs
        via `az aks command invoke` instead of a local context — from operator machines
        and from CI alike.)
  - [x] Apply k8s/overlays/dev.
  - [x] Validate rollouts for hub-api, docs-api, retrieval-worker.
  - [x] Validate qdrant statefulset and core namespaces.
- Done criteria:
  - [x] All target deployments are available and healthy.

Execution notes (2026-07-15):
- Overlay applied twice: manually during runtime stabilization, then by the first
  app-cd-dev run (31 rendered objects; all pre-existing objects `unchanged`, image
  tags updated to the merge SHA).
- All four rollouts (incl. ingestion-worker) reported "successfully rolled out";
  qdrant StatefulSet Running; KEDA ScaledObject Ready=True on live queue depth.
- Secrets arrive out-of-band via scripts/apply_dev_secrets.sh (see
  runbooks/rotate-dev-secrets.md); Key Vault CSI remains the target state.

### C3. Activate app-cd-dev workflow path (P1)

- Owner: Jason
- Due: 2026-07-21
- Status: [x] Done
- Dependencies: C2
- Checklist:
  - [x] Trigger apps change to run app-cd-dev.
  - [x] Verify image build and push for each service.
  - [x] Verify kustomize image updates and apply step.
  - [x] Verify post-deploy smoke check.
- Done criteria:
  - [x] One full successful app deployment to dev AKS from GitHub Actions.

Execution notes (2026-07-15):
- Activated by the PR #2 merge (d18a855). First run failed at azure/login for jobs
  using the GitHub `dev` environment: OIDC subject becomes
  `repo:...:environment:dev`, and only `pull_request` / `ref:refs/heads/main`
  federated credentials existed. Fixed by adding `cani-env-dev` federated
  credentials to both app registrations; also pre-granted the workload identity
  "Azure Kubernetes Service RBAC Cluster Admin" scoped to the dev cluster only
  (Contributor covers the ARM runcommand action but no Kubernetes data actions).
- Rerun succeeded end to end (run 29459516493): 4/4 images built and pushed with the
  merge SHA, contract preflight passed, overlay applied via command invoke, all four
  rollout gates green, in-cluster smoke checks passed (hub/docs/retrieval healthz +
  dev-login POST proving a live Postgres write).
- infra-apply-dev on the same merge: pure no-ops (platform 23 unchanged, workload 17
  unchanged) — the public-endpoint drift reconciliation held.

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

- 2026-07-14: Board created. A1 completed after management-group access unblocked and root-scope User Access Administrator confirmed. A2 completed after OIDC identities, repo secrets, federated credentials, and workflow auth validation were verified in infra-preview. B1 completed with successful `pulumi up` on platform dev and outputs captured.
- 2026-07-15: B2 completed after fixing workload IaC gaps (Postgres password, AKS dnsPrefix, Postgres private DNS/delegated subnet, DSv4 nodepools), resolving a stuck AKS long-running operation, and successfully finishing `pulumi up` update 6.
- 2026-07-15: C1 completed by aligning app-cd and k8s manifests to live AKS/ACR/storage names and IDs from workload outputs.
- 2026-07-15: C2 and C3 completed. PR #2 (secret handling, KEDA repair, private-cluster CD rework, public-endpoint drift fix) merged as d18a855; first app-cd-dev activation failed on missing `environment:dev` federated credentials, fixed and rerun green end to end — 4 SHA-tagged images deployed, all rollouts and in-cluster smoke checks passed, infra applies no-op. Week 1 actual now 75% vs 60% planned.
