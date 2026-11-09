# 22. Low-cost rebuild (November 2026)

**Status:** infrastructure code written and validated against Azure; not yet deployed.
**Supersedes for deployment purposes:** `06-azure-landing-zone-design.md`,
`10-aks-cluster-design.md`, `11-iac-strategy.md`, `container-apps-migration-guide.md`.
Those remain as history of how the platform got here.

## Why

The original subscription (Canido tenant) was disabled in September 2026 after a $435
August. Most of that month was not compute serving users: Log Analytics with no cap ($76),
a Premium container registry ($50), a VNet-integrated Container Apps environment with its
load balancer ($21), three private endpoints, nine private DNS zones, and an AKS cluster
that had already been migrated away from ($19). Budget alerts went to a mailbox nobody
read. Jason chose to rebuild from scratch in the Default Directory subscription (renamed
"CanI"), as cheaply as possible, with the guardrails in the deployment itself.

## What runs

| Component | Choice | Idle cost |
|---|---|---|
| Postgres (data + vectors, ADR-008) | Flexible Server B1ms, 32 GB auto-grow, 7-day backup, no HA, TLS only. In **centralus**, not eastus: see below | ~$17/mo, the only fixed cost |
| Container Apps | Consumption plan, no VNet. `web` warm at 1 replica; hub-api, docs-api, retrieval-worker scale 0–3 on HTTP; ingestion-worker 0–1 on a KEDA Postgres queue-depth query | a few dollars |
| Images | Azure Container Registry, Basic tier, built in Azure with `az acr build`, pulled with a user-assigned managed identity | ~$5/mo |
| AI | The existing Foundry AIServices resource `aif-jcarney-dev-eus-001` for embeddings, chat, Document Intelligence and Speech; deployments created by `infra/container-apps/deploy-models.ps1` | per use |
| Logs | One Log Analytics workspace, 30-day retention, 0.5 GB/day cap | $0–7 |
| Blob storage | Standard LRS, 7-day soft delete + versioning (docs/21 phase-2 gate) | pennies |
| Marketing site | Static Web App, Free tier | $0 |
| Budget + alerts | $30/month budget on the resource group (50/80/100 % actual, 100 % forecast), action group to Jason's Gmail, alerts on web 5xx, Postgres CPU, dead-lettered jobs | $0 |

Expected steady state: $30–35/month. Everything is tagged `project=cani environment=prod`.

Deliberately absent: VNet, private endpoints, Key Vault (secrets are Container Apps
secrets fed from GitHub environment secrets or a local secrets file), Qdrant, the Qdrant
snapshot job, Pulumi, and any dependency on GitHub at deploy time. The registry was GHCR in
the first draft; it became ACR Basic on 2026-11-09 because GitHub Actions is locked for
billing on the account and a registry that needs no GitHub token lets the whole deploy run
from `az` alone.

## Files

- `infra/container-apps/main.bicep` — the whole environment, resource-group scoped.
- `infra/container-apps/budget.bicep` — subscription-scoped budget module, filtered to the RG.
- `infra/container-apps/main.parameters.json` — non-secret values (endpoints, client ids, flags).
  The alert mailbox and the subscription id are deliberately not in the repo: the workflow
  takes them from the `ALERT_EMAIL` variable and the OIDC login, the scripts from
  `CANI_ALERT_EMAIL` / `CANI_SUBSCRIPTION_ID`.
- `infra/container-apps/deploy.ps1` — local deploy: phase 1 (registry, data, guardrails), `az acr
  build` of the six images, phase 2 (apps, jobs), migration job. Secrets from environment
  variables or `-SecretsFile` (e.g. `~/.cani/prod.env`, never in the repo).
- `infra/container-apps/deploy-models.ps1` — model deployments on the Foundry resource.
- `.github/workflows/deploy.yml` — the same sequence under Actions (OIDC login only, no
  registry tokens). Replaces `container-apps-cd-dev.yml` and the two Pulumi workflows.

## Security posture changes vs the old template

- `ENV=prod` on every Python service. The old template never set it, so hub-api ran in dev
  mode: the `/auth/dev-login` stub was reachable in production.
- Only `web` has external ingress. The APIs are internal to the environment.
- Postgres is public-endpoint with the "allow Azure services" firewall rule, because a
  Consumption environment without a VNet has no stable egress address. The tradeoff is
  stated in the template; the mitigation is a 48-character password that lives only in
  Container Apps secrets and GitHub environment secrets.
- Ingestion is capped at one replica on purpose: `deletion.process_deletion`'s
  single-worker invariant (docs/21 §1.7) is only race-free with one.
- Postgres lives in a different region from the apps (`postgresLocation`). On 2026-11-09 this
  subscription could not provision Flexible Server in eastus at all ("Version should be in:
  []") and was refused B1ms in eastus2 ("SkuNotAvailable") although `az postgres
  flexible-server list-skus` advertises it there — the catalog does not reflect
  per-subscription capacity holds, so only a real create tells you. centralus worked. The
  cost is tens of milliseconds per query across regions, acceptable for a RAG workload whose
  latency is dominated by the embedding and chat calls. Move it back by changing one
  parameter once the hold lifts; data would need a dump/restore.

## Bootstrap, in order

1. **Models.** `pwsh infra/container-apps/deploy-models.ps1`. Prints the two endpoints for
   `main.parameters.json` and the command for the key.
2. **Secrets.** Locally: `~/.cani/prod.env` with the keys listed in `deploy.ps1`'s header
   (generated 2026-11-09). For Actions, once billing is restored: environment `prod` with the
   secrets listed at the top of `.github/workflows/deploy.yml`, plus an Azure OIDC federated
   credential (Contributor on the subscription, since the budget is subscription-scoped) for
   `repo:jasoncarney1864/CanI:environment:prod`.
3. **Entra.** The External ID tenant and app registration are reused unchanged. The client
   secret from the local `.env` goes into `ENTRA_CLIENT_SECRET`. Redirect URI stays
   `https://app.canido.co/auth/callback`.
4. **First deploy** with domain phase 0: `pwsh infra/container-apps/deploy.ps1 -SecretsFile
   $HOME\.cani\prod.env` (or the workflow). It prints the web FQDN and the `asuid`
   verification id.
5. **GoDaddy.** Change the `app` CNAME to the new web FQDN. Add `TXT asuid.app` with the
   verification id. Leave the Microsoft 365 records alone.
6. **Domain phase 1** (`-CustomDomainPhase 1`): adds the domain to the app unbound so Azure
   can validate. **Phase 2** (`2`): issues the managed certificate and binds it. Each is a
   deploy run with `-SkipBuild`.
7. **Marketing site.** The Static Web App's deployment token
   (`az staticwebapp secrets list --name cani-prod-marketing`) goes into
   `AZURE_STATIC_WEB_APPS_API_TOKEN` for `marketing-static-web-app.yml`. Pointing the root
   domain at it is a separate GoDaddy change (the two A records currently park at GoDaddy).
8. **Old subscription.** Cancel it outright once the new one is serving, so it can never
   bill again.

## Known follow-ups

- Rate limiting in `cani_shared.middleware` keys on the direct client address. Behind
  Container Apps ingress every request arrives from the envoy, so all users share one
  bucket. Set `TRUSTED_PROXY_HOSTS` once the ingress source address is known, or key on
  the authenticated user instead.
- Scale-to-zero means a cold start of a few seconds on the first request to hub-api or
  docs-api after idle, and up to ~30 s before the ingestion worker wakes for a new upload
  (KEDA polling interval). Acceptable at this stage; raise `minReplicas` when it is not.
- The alert queries name `ContainerAppConsoleLogs_CL` / `Log_s`, the Log Analytics schema
  Container Apps writes by default. Verify the first dead-letter alert fires with a
  deliberately failing upload before trusting it.
