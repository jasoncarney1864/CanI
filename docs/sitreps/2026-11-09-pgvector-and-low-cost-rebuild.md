# Sitrep 2026-11-09 — vectors into Postgres, low-cost rebuild designed, production still down

**Status:** active work, no live deployment. The original subscription (Canido tenant) is
disabled; app.canido.co does not answer. The replacement deployment is written, validated
against Azure, and not yet deployed.
**Impact:** no users can reach the product until the bootstrap in
`docs/22-low-cost-rebuild.md` is completed. There were no active users at the time.

## What happened since the last confirmed state (2026-09-04)

The last commit before this week was `8b82b13` on 2026-09-04. Between then and now:

- **The production subscription went dark.** The ARM subscription record reports
  `Disabled`; Postgres is disabled, every Container App shows provisioning `Failed`, and
  cost data stops mid-September. August 2026 cost $435 against a $200 budget. The largest
  lines were Log Analytics with no daily cap ($76), Container Apps ($66), Postgres ($53), a
  Premium container registry ($50), the VNet load balancer ($21), and the already-migrated
  AKS cluster ($19). Budget alerts routed to ops@canido.co, a mailbox nobody read. The AKS
  cluster itself no longer exists. The portal's default directory is a different tenant, so
  the spend was invisible from where it was usually looked at.
- **Decision (Jason, 2026-11-07):** rebuild from scratch in the Default Directory
  subscription, renamed "CanI", as cheaply as possible; leave the old subscription
  disabled and cancel it once the new one serves traffic.

## What shipped this session (2026-11-07 to 2026-11-09)

Two commits on `main`, both pushed:

1. **`8e91368` — vectors move into Postgres (pgvector), Qdrant retired.** ADR-008.
   Migration `0009_pgvector.sql`, `OwnerScopedVectorStore` and `PublicLawVectorStore` with
   the Qdrant wrappers' exact surface and fail-closed rules, every service rewired, the
   snapshot backup module and all `QDRANT_*` settings removed, compose on
   `pgvector/pgvector:pg16`. A chunk's vector and its manifest row now commit in one
   transaction, which closes the 2026-08-09 incident's open reconciliation item by
   construction. Verified: ruff clean, 243/243 unit, 25/25 integration against the pgvector
   image with fake providers.
2. **`4dbcf44` — low-cost Container Apps rebuild.** One resource-group-scoped Bicep template
   plus a subscription-scoped budget module: no VNet, ACR, Key Vault or Qdrant; images from
   GitHub Container Registry; B1ms Postgres with `azure.extensions=VECTOR`; `web` warm at
   one replica, APIs 0–3, ingestion 0–1 on a KEDA queue-depth query; capped Log Analytics;
   Free Static Web App; and the guardrails in-template (a $30 budget filtered to the
   resource group, action group to a read mailbox, alerts on web 5xx, Postgres CPU and
   dead-lettered jobs). `ENV=prod` is set on every service — the previous template never
   set it, so `/auth/dev-login` was reachable in production. `.github/workflows/deploy.yml`
   builds, deploys, migrates, asserts the guardrails exist, and smoke-checks. The Pulumi
   landing zones and their workflows are deleted. Verified: `az bicep build` clean,
   `az deployment group validate` Succeeded, what-if lists 21 creates in `rg-cani-prod-eus`
   (created, empty).

Also this session, not in the repo: the subscription rename to "CanI" was submitted via
the Subscription API and is propagating.

## Where we are now

| Area | State |
|---|---|
| Code on `main` | pgvector swap + rebuild template, pushed; CI and `deploy` workflows triggered on `4dbcf44` |
| Old deployment | Subscription disabled; nothing recoverable worth carrying over except the Entra app registration (independent CIAM tenant) and the Foundry resource in the new subscription |
| New deployment | Resource group exists, empty. Template validated. Not deployed. |
| GitHub Actions | **Locked for a billing issue on the account.** Every workflow run since 2026-08-21, including today's CI and `deploy` runs on `4dbcf44`, failed before executing a single step ("The job was not started because your account is locked due to a billing issue"). All verification in this sitrep is from local runs. |
| `deploy` workflow | Once Actions runs again it will fail at its secrets check until the GitHub `prod` environment is configured; that is the intended behaviour |
| Repository history | Scanned 2026-11-09 for public release: 219 commits, gitleaks finds only two "Dummy…" validation placeholders in a superseded script; no `.env` ever committed; no real keys. Azure subscription and tenant GUIDs appear in docs, runbooks and old IaC; the alert mailbox and subscription id were moved out of tracked infra files in this session. |
| DNS (GoDaddy) | `app` CNAME still points at the dead environment's hostname; root A records park at GoDaddy; MX/TXT not yet reviewed |
| Cost | $0/month for CanI right now. Target after deploy: $25–30/month |

## What needs doing next

Owner for every item below is Jason unless noted; the order matters.

0. **Unblock GitHub Actions** (billing page on github.com). Nothing below can run in CI until
   this is cleared; CI has been silently red for eleven weeks.
1. Run `infra/container-apps/deploy-models.ps1` to create the embedding and chat
   deployments on the Foundry resource, and confirm the model versions it picks.
2. Create the GitHub `prod` environment with the secrets listed at the top of
   `.github/workflows/deploy.yml`, including a new Azure OIDC federated credential with
   Contributor on the CanI subscription and a classic PAT with `read:packages`.
3. Re-run the `deploy` workflow. Take the printed web FQDN and verification id to GoDaddy:
   repoint the `app` CNAME, add `TXT asuid.app`. Then bump `CUSTOM_DOMAIN_PHASE` through 1
   and 2.
4. Verify the first dead-letter alert fires with a deliberately failing upload before
   trusting it, and that a budget email arrives at the configured address.
5. Cancel the old Canido-tenant subscription outright.
6. **Decision needed:** Postgres sits on a public endpoint with the "allow Azure services"
   firewall rule because a Consumption environment without a VNet has no fixed egress
   address. A VNet would add roughly $20/month. The template states the tradeoff; confirm
   it is acceptable or ask for the VNet variant.
7. Follow-ups recorded in docs/22: rate limiting keys on the ingress address behind
   Container Apps (all users share one bucket), and cold-start latency on scale-to-zero
   services.

## Evidence

- Subscription state, cost, and resource inventory: read via `az` on 2026-11-07 against
  subscription `833d780f…` (old) and `d2a378be…` (new).
- Test results: local runs on 2026-11-07, recorded in `docs/implementation-status.md`.
- Template validation: `az deployment group validate` and `what-if` against
  `rg-cani-prod-eus` on 2026-11-07.
