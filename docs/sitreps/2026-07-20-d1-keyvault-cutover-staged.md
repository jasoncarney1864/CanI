SITREP — CanI Platform
Date: 2026-07-20 | Branch: feat/d1-cutover (pushed, not merged) | Sprint: 3, D1 in progress

1. LAST COMPLETED

D1 (Key Vault CSI secret cutover) Phase 1 is applied and live, and the full cutover is staged but deliberately NOT applied. Phase 1 (PR #52, merged to main) created a private endpoint to the platform Key Vault, a user-assigned managed identity, and one federated credential per app service account — CI-applied and verified (private endpoint Approved). The two elevated steps the Contributor-only CI can't do were done out-of-band by an Owner: the UAMI got Key Vault Secrets User, the operator got Key Vault Secrets Officer, and ARM management-plane secret writes to the private (public-access-Disabled) vault were validated with a throwaway secret. The k8s cutover manifests + the cutover runbook are committed on feat/d1-cutover.

2. WHERE WE ARE NOW

- Applied/live (safe, additive — the running app is untouched and healthy): Phase 1 infra (private endpoint cani-kv-pe59f3f147 Approved; UAMI cani-secrets-id9e0938f8, client 4a790202-610f-499c-bb0b-2c64b2d42898, principal 9d752c78-7b4b-4940-8936-0b8406d49a50; 5 federated creds); the two KV role assignments.
- Staged on feat/d1-cutover (committed, kustomize builds clean, NOT applied): cani-config split with real values (k8s/base/config.yaml); SecretProviderClass filled (k8s/base/secret-provider-class.yaml — KV cani-platform-kv6370c4cb, tenant ddb3853e-a709-42c4-8841-8e69da7a1c45, 8 secrets incl. a cani-keda-postgres secretObject); four deployments wired with the CSI volume + workload-identity label + SA client-id (docs-api, hub-api, retrieval-worker, ingestion-worker — web excluded, it uses no KV secrets); hub-api dropped its cani-hub-oidc ref; runbooks/keyvault-secret-cutover.md.
- Held: the live cutover itself (populate KV, delete the manual cani-secrets, apply, verify, rotate). Merging feat/d1-cutover IS the flip (the next app deploy applies the CSI wiring), so it must merge as part of the cutover, not before.
- Key facts to resume: KV cani-platform-kv6370c4cb in RG cani-platform-core-dev-eastus2-rg1227b5a0; app-cd-dev only triggers on apps/** so k8s-only changes need workflow_dispatch or kubectl via az aks command invoke; a leftover d1-connectivity-test secret sits in the KV (ARM delete unsupported — clean up in-cluster later); main is at 0e998a1.
- Sprint 3 board is unchanged (D1 still open); two untracked sitreps sit in docs/sitreps/ per the workflow.

3. NEXT STEPS (the live cutover — follow runbooks/keyvault-secret-cutover.md, done as a watched, reversible operation)

1. Populate the 8 KV secrets via the ARM management plane (values from ~/.cani/dev-secrets.env, never printed; rotate the token-signing + session secrets now). Recommended: populate current values first, cut over, verify, THEN rotate the backing services.
2. Delete the manually-applied cani-secrets in both namespaces so the CSI driver can own it.
3. Merge feat/d1-cutover and deploy (app-cd-dev workflow_dispatch, or kubectl apply the rendered overlay); watch all four rollouts.
4. Verify: CSI volume mounted + workload-identity label on each pod; cani-secrets + cani-keda-postgres driver-populated; full loop at https://app.canido.co (Entra sign-in -> upload -> query -> cited answer). Keep scripts/apply_dev_secrets.sh as the rollback until confirmed.
5. Rotate the backing services one at a time (Postgres admin password via Pulumi config, storage account key, Entra client secret), updating both the service and the KV secret, then restarting.
6. Cleanup: retire scripts/apply_dev_secrets.sh, repoint runbooks/rotate-dev-secrets.md at the KV flow, close D1 on docs/19-sprint-3-reachability-board.md.
