SITREP — CanI Platform
Date: 2026-07-20 | Branch: main (d89364d) | Sprint: 3, D1 — core cutover COMPLETE

1. LAST COMPLETED

D1's core objective is done and independently verified: every CanI service now reads its secrets from Azure Key Vault via the Secrets Store CSI driver + workload identity, and the manual cani-secrets script is no longer the source of truth. The cutover was executed live with zero downtime (validated the CSI read path with a throwaway test pod first, populated the vault with current values, then flipped namespace-by-namespace). A clean end-to-end incognito sign-in (CanI sign-in screen -> Entra prompt -> callback -> workspace) confirmed the whole auth chain works on the vaulted secrets, including the Entra client secret (code exchange), the session secret, and the token-signing secret. The token-signing and session secrets were also rotated.

2. WHERE WE ARE NOW

- Core cutover live and healthy: cani-secrets (docs-platform + hub-system) and cani-keda-postgres are all driver-managed from Key Vault (cani-platform-kv6370c4cb). Orphaned cani-hub-oidc + manual cani-secrets deleted. App verified: public health, sign-in gate, fresh incognito Entra login, hub dev-login+whoami, all service health checks green.
- Rotated: CANI_TOKEN_SIGNING_SECRET + CANI_SESSION_SECRET (new random values in KV, propagated to all services; old sessions invalidated).
- NOT rotated: storage account key (rotation attempted and FAILED — the freshly-renewed key2 connection string would not authenticate against blob and briefly crashlooped docs-api; reverted to the working key1 connection and recovered. Storage is on the original key1, working). Entra client secret + Postgres admin password: not attempted.
- CRITICAL LEARNING (the rotate-dev-secrets / keyvault-secret-cutover runbooks are WRONG on this and must be corrected): the CSI driver does NOT auto-propagate Key Vault changes to the k8s cani-secrets Secret (secret rotation is off by default). "Update KV + restart" does nothing — pods keep reading the stale k8s Secret. To rotate, you MUST delete cani-secrets in BOTH namespaces and restart ALL services together (so shared secrets like the signing key never diverge between hub-api and docs-api). During this session that divergence briefly happened and was fixed by refreshing both namespaces.
- Incident note: docs-api was briefly down during the failed storage rotation (crashloop on the bad key2 connection, then a force-delete of all pods); fully recovered by deleting cani-secrets so the driver re-synced key1, then making all services consistent.
- Repo: main at d89364d (PRs #52 infra, #53 k8s cutover both merged). scripts/apply_dev_secrets.sh still present (kept as rollback). A leftover d1-connectivity-test secret + an unused renewed storage key2 exist in Azure. Three untracked sitreps in docs/sitreps/.

3. NEXT STEPS (rotation + cleanup — fresh window; use the CORRECTED procedure below)

Corrected rotation procedure for every secret: set the new value in KV (ARM management-plane PUT; values from ~/.cani/dev-secrets.env, never printed) -> delete cani-secrets in BOTH namespaces -> rollout restart ALL services (hub-api, docs-api, retrieval-worker, ingestion-worker) together -> verify.

1. Storage key: renew a key, build the connection string in Python from az storage account keys list (the --key secondary / show-connection-string CLI forms returned empty here), TEST it authenticates with `az storage container list --connection-string` BEFORE writing to KV, then rotate per the corrected procedure.
2. Entra client secret: `az ad app credential reset` on app 1f0927a0-... in the caniauth CIAM tenant — this is CROSS-TENANT (your az session is in Default Directory), so likely needs you in the caniauth portal or an az login --tenant caniauth. Then KV + refresh.
3. Postgres admin password (highest risk): bump postgresAdminPassword in infra/workload Pulumi config -> CI apply on main -> KV postgres-password + rebuild keda-postgres-connection -> refresh. Watch the DB carefully.
4. Cleanup: correct runbooks/keyvault-secret-cutover.md + rotate-dev-secrets.md with the delete-secret procedure; retire scripts/apply_dev_secrets.sh; close D1 on docs/19-sprint-3-reachability-board.md; delete the d1-connectivity-test KV secret.
