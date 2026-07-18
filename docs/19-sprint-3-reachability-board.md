# 19. Sprint 3 reachability board

Execution board for Sprint 3. Sprint 2 established the operational-readiness baseline;
Sprint 3 makes CanI **reachable** — the design-complete `apps/web` prototype becomes a
real, deployed, publicly accessible product wired to the live backend.

## Sprint goal

A real user can open CanI at a public HTTPS URL, sign in with Entra External ID, upload a
document, ask a question, and get a grounded, cited answer rendered in the "Spotlight" UI —
under the same owner-scoping, security, observability, and cost guarantees the API already
has. Only the web app is publicly exposed; the backend services stay private.

## Board metadata

- Sprint: Sprint 3 - Reachability & real-user access
- Owner: Jason
- Start date: 2026-07-18 (pulled forward — Sprint 2 closed ~4 weeks early)
- Target end date: 2026-08-22
- Last updated: 2026-07-18
- Overall status: [-] In progress (44%, 16/36) — A1, B1+B2, and C1 done. **CanI is live on
  the public internet at https://app.canido.co** (custom domain -> managed-NGINX ingress)
  with a valid Let's Encrypt cert. Next: A2 + C2 (real Entra OIDC — now unblocked by the
  public callback URL).

## Status legend

- [ ] Not started
- [-] In progress
- [x] Done
- [!] Blocked

## Weekly status rollup

| Week | Date range | Planned focus | Planned complete (%) | Actual complete (%) | Delta (pp) | Key blocker | Notes |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| Week 1 | 2026-07-18 to 2026-08-01 | Wire the web app to the live backend (A); containerize it (B1) | 45 | 44 | -1 | None | On plan (day 1). A1 (live Document Viewer), B1+B2 (web deployed), and C1 (public HTTPS ingress) all done — CanI is publicly reachable. A week-2 item (C1) pulled forward. |
| Week 2 | 2026-08-02 to 2026-08-15 | Web in CD (B2); ingress controller + TLS + public endpoint (C1) | 80 | 0 | -80 | vCPU ceiling | Fill at week close |
| Week 3 | 2026-08-16 to 2026-08-22 | Public OIDC (C2); edge rate limit + headers (C3); Key Vault CSI (D1); closeout | 100 | 0 | -100 | TBD | Fill at week close |

Formula: Actual complete (%) = round((number of checked boxes [x] in sprint checklist items / total sprint checklist boxes) x 100).

## Entry criteria

- [x] Sprint 2 closeout gate complete. (Observability, alerts, budget, backup/restore,
  malware scan, rate limiting, policy baseline all live — closed 2026-07-17.)
- [x] Web prototype is design-complete. (`apps/web` implements the design language to the
  hex: global tokens, spoke token-mapping, DM Sans + Source Serif Pro, the 35/65 Spotlight
  layout, verdict badge, citation spotlight — PR #19.)
- [x] Backend core loop live and owner-scoped. (auth -> upload -> ingest -> retrieve ->
  cite, verified end to end.)
- [x] vCPU headroom for an ingress controller + web pod. Freed by dropping systempool
  2 -> 1 node (single-user dev needs no system-component HA): 10 -> 8 of the 10-core quota,
  ~2 cores free — enough for the web pod (deployed, B1) + an ingress controller (C1). Note:
  a full appspool scale-to-3 still needs a quota increase (systempool 1 + datapool 1 +
  appspool 3 = 12 > 10), tracked in risks.

## Workstream A - Frontend wired to the live backend

Replace the prototype's mock data (`apps/web/lib/mockData.ts`) with the real docs-api /
hub-api flow. The Spotlight UI stays exactly as designed — only the data source changes.

### A1. Live query -> verdict + citations + document viewer (P1)

- Owner: Jason
- Status: [x] Done (2026-07-18, PR #36)
- Dependencies: entry criteria
- Checklist:
  - [x] Asking a question in the web UI calls the live docs-api `/query` (proxied in
    `app/api/query/route.ts`) and renders the real verdict in the badge + summary.
  - [x] Citations from the response render as citation-cards (title / location / snippet).
  - [x] The cited source text appears in the Document Viewer pane with the `.spotlight`
    highlight on the cited chunk (the §5 blueprint behaviour), driven by the real document
    text — not `mockData`. Required new backend (folded in as "B"): owner-scoped
    `GET /documents/{id}/text` (retrieval-worker chunk scroll, docs-api proxy) since
    `chunk_manifests` doesn't store chunk text and only retrieval-worker can reach Qdrant.
  - [x] Empty/again states and query errors degrade gracefully (no raw error leakage).
- Done criteria:
  - [x] The query path shows real docs-api data end to end; `mockData` removed. Verified in
    CI compose-smoke (cited chunk present in the document text; cross-owner 404) and live
    against the cluster.

### A2. Real authentication in the web app (P1)

- Owner: Jason
- Status: [ ] Not started
- Dependencies: A1
- Checklist:
  - [ ] Web app has a real sign-in via hub-api's Entra OIDC flow (not the mock profile);
    signed-in user shown in the rail footer.
  - [ ] The session is carried to docs-api calls so responses are owner-scoped to the
    logged-in user.
  - [ ] Unauthenticated users cannot reach the workspace (redirect to login); logout works.
- Done criteria:
  - [ ] Two different users see only their own documents/answers through the web app.

### A3. Upload + ingestion status in the web app (P2)

- Owner: Jason
- Status: [ ] Not started
- Dependencies: A1, A2
- Checklist:
  - [ ] A user can upload a PDF from the UI (type/size validated client- and server-side).
  - [ ] The UI shows ingestion progress (uploaded -> scanning -> extracting -> indexed) and
    surfaces a clear failure for a blocked (malware) or OCR-unsupported document.
  - [ ] After indexing, the document is queryable from the UI.
- Done criteria:
  - [ ] Upload-to-queryable works from the browser, with honest status and failure states.

## Workstream B - Deploy the frontend

### B1. Containerize and deploy apps/web (P1)

- Owner: Jason
- Status: [x] Done (2026-07-18, PR #37 — folds in B2)
- Dependencies: A1 (something worth deploying)
- Checklist:
  - [x] Dockerfile for `apps/web` (Next.js standalone build), non-root, minimal
    `node:20-alpine` runtime. Root `.dockerignore` re-includes `apps/web` minus
    node_modules/.next (root-context build, clean `npm ci`).
  - [x] `k8s/base` Deployment + Service (docs-platform): non-root, read-only rootfs with
    tmp + .next/cache emptyDirs, `/api/health` probes, resource limits, and a NetworkPolicy
    (egress to docs-api + hub-api + DNS only).
  - [x] Server-side proxy env points at the in-cluster `hub-api.hub-system:8001` +
    `docs-api:8002`; the browser only reaches the web pod. docs-api/hub-api ingress admit
    the web pod (hub-api cross-namespace via namespaceSelector).
- Done criteria:
  - [x] The web app runs in the cluster and serves the Spotlight UI wired to live data.
    Verified in-cluster: `/api/health` 200, `/` serves the UI, and `/api/query` returns a
    valid answer through the full proxy chain (web -> hub-api auth -> docs-api ->
    retrieval-worker).

### B2. Web app in CD (P2)

- Owner: Jason
- Status: [x] Done (2026-07-18, folded into B1/PR #37)
- Dependencies: B1
- Checklist:
  - [x] `app-cd-dev` builds + pushes the web image (added to the matrix) and rolls it out
    alongside the services (kustomize image entry + rollout wait).
  - [x] Post-deploy smoke check hits the web app's `/api/health`.
- Done criteria:
  - [x] A push to main builds, deploys, and smoke-checks the web app automatically
    (proven by this PR's own `app-cd-dev` run).

## Workstream C - Public reachability and edge security

### C1. Ingress controller + TLS + public endpoint (P1)

- Owner: Jason
- Status: [x] Done (2026-07-18, PR #39 addon + #40 TLS)
- Dependencies: B1 (met); vCPU headroom (met — systempool 2->1)
- Checklist:
  - [x] Ingress as IaC: AKS **managed NGINX** (web-app-routing addon), enabled via Pulumi
    (`compute_aks.py` ingress_profile). Public LB IP 172.175.33.251; class
    `webapprouting.kubernetes.azure.com`.
  - [x] TLS with a real certificate: **cert-manager + Let's Encrypt prod** (HTTP-01), host
    `172.175.33.251.sslip.io` (no domain needed). HTTP -> HTTPS 308 redirect. Debugged the
    HTTP-01 flow on LE staging first, then flipped to prod. Issuers/Ingress/policies as IaC
    (`k8s/base/ingress`, `k8s/base/web/ingress.yaml`, `network-policies.yaml`); cert-manager
    install + IP tracking documented in `runbooks/ingress-tls-setup.md`.
  - [x] Only the web app is published; hub-api/docs-api stay private (reached only via the
    web app's server-side proxy). NetworkPolicies added for controller -> web and the ACME
    solver (both blocked by the docs-platform deny-all otherwise).
- Done criteria:
  - [x] The Spotlight UI is reachable at a public HTTPS URL with a valid certificate; the
    backend APIs are not directly reachable from the internet. Verified from outside the
    cluster: `https://172.175.33.251.sslip.io/api/health` -> 200, ssl_verify=0 (valid cert);
    root serves the UI; a `POST /api/query` returns a valid answer through the full public
    chain; `http://` -> 308 to https.

### C2. Non-localhost OIDC redirect (P1)

- Owner: Jason
- Status: [ ] Not started — unblocked (C1 done; public callback URL exists at
  `https://app.canido.co`)
- Dependencies: C1 (met)
- Checklist:
  - [ ] Add the public callback URL to the `cani-hub` Entra app registration redirect URIs.
  - [ ] hub-api `ENTRA_OIDC_REDIRECT_URI` set to the public callback; the callback path is
    reachable through the ingress.
  - [ ] The full authorization-code + PKCE flow completes over the public endpoint; the
    localhost-only redirect is retired for non-dev.
- Done criteria:
  - [ ] A real browser sign-in through the public URL creates a session and reaches the
    workspace. (Closes the long-standing "public redirect URI" production blocker.)

### C3. Edge rate limiting + security headers (P2)

- Owner: Jason
- Status: [ ] Not started
- Dependencies: C1
- Checklist:
  - [ ] Rate limiting enforced at the ingress edge (a real global limit, complementing /
    superseding the Sprint 2 C3 per-pod service-layer limit).
  - [ ] Standard security headers present (HSTS, X-Content-Type-Options, Referrer-Policy,
    a CSP appropriate to the Next.js app), verified.
  - [ ] Decide WAF posture (managed ruleset vs none for dev) and record it.
- Done criteria:
  - [ ] A burst against the public URL is throttled at the edge; security headers verified
    on responses.

## Workstream D - Hardening elevated by public exposure

### D1. Key Vault CSI secret cutover (P2)

- Owner: Jason
- Status: [ ] Not started
- Dependencies: none (independent; higher priority now the surface is public)
- Checklist:
  - [ ] Workloads read secrets from Key Vault via the CSI driver + workload identity
    (`k8s/base/secret-provider-class.yaml` is already scaffolded).
  - [ ] Retire the manual `scripts/apply_dev_secrets.sh` + storage-account-key path.
  - [ ] Rotate the exposed pre-migration secret values per
    `runbooks/rotate-dev-secrets.md`.
- Done criteria:
  - [ ] Services boot with secrets sourced from Key Vault; the manual stopgap is removed
    and pre-migration values rotated.

## Sprint closeout gate

- Owner: Jason
- Status: [ ] Not started
- Checklist:
  - [ ] End-to-end from the public URL: Entra login -> upload -> query -> cited answer in
    the Spotlight UI, owner-scoped.
  - [ ] Only the web app is publicly exposed; backend APIs are private.
  - [ ] Edge TLS + rate limiting + security headers active.
  - [ ] Secrets sourced from Key Vault CSI (or an explicit, documented deferral).
  - [ ] Observability/alerts cover the public web tier (5xx + latency include the web app);
    the budget still holds (public ingress cost checked against B1's $200 cap).
  - [ ] `implementation-status.md` and docs updated with Sprint 3 outcomes.
- Done criteria:
  - [ ] Sprint 3 marked complete: CanI is a reachable, real-user product.

## Open questions and key decisions

1. **Ingress technology.** NGINX ingress controller (cheap, in-cluster, needs cert-manager)
   vs Application Gateway + AGIC (managed WAF, higher cost/complexity) vs Azure Front Door
   (global, WAF, but another hop). Trade-off: cost + vCPU footprint vs built-in WAF.
2. **TLS certificates.** cert-manager + Let's Encrypt (free, automated, needs public DNS +
   HTTP-01/DNS-01) vs an Azure-managed certificate vs a Key Vault cert. Needs a DNS name.
3. **Public DNS name.** What hostname does CanI live at? (A custom domain, or an
   Azure-provided one for dev.)
4. **Backend exposure.** Confirm the pattern: browser -> web app (public) -> server-side
   proxy -> hub-api/docs-api (private). The OIDC callback is the one backend path that must
   be publicly reachable — decide whether it is proxied through the web app or exposed as a
   dedicated ingress path.
5. **vCPU ceiling (blocker for C1).** The cluster is at the 10-core regional quota; an
   ingress controller + web pod need headroom. Request a quota increase, or rebalance
   pools. This gates the public-endpoint work.
6. **Cost.** A public ingress (and any WAF/Front Door) adds recurring spend; verify it
   against the $200/mo budget (Sprint 2 B1) and its 50% alert.
7. **Full AV vs EICAR dev backend (C2 of Sprint 2).** Public exposure raises the value of a
   real clamd deployment over the EICAR-only dev scanner — but that also needs vCPU
   headroom. Decide alongside the quota outcome.

## Daily standup log

Use one line per day.

- 2026-07-17: Board drafted from the design language (Gemini's "Illuminated Clarity" /
  Spotlight system) and the design-complete `apps/web` prototype. Framing: the design is
  settled and already built to the hex; Sprint 3 is "make it real and reachable" — wire the
  UI to live data, deploy it, and put a public TLS endpoint + real OIDC in front. Key risk
  flagged up front: the 10-core vCPU ceiling gates the ingress work.
- 2026-07-18: A1 + B1 + B2 done (33%). A1 (PR #36): the Document Viewer now shows the real
  cited document with the §5 in-context spotlight — required a new owner-scoped
  `GET /documents/{id}/text` (retrieval-worker scroll + docs-api proxy, since only
  retrieval-worker can reach Qdrant and chunk_manifests lacks the text). vCPU headroom
  freed by systempool 2->1 (10->8 cores). B1+B2 (PR #37): web app containerized (Next.js
  standalone) + deployed to docs-platform via CD; verified in-cluster — health 200, UI
  serves, and `/api/query` works through the full web->hub-api->docs-api->retrieval-worker
  proxy chain with only the web pod exposed. Next: C1 (ingress + TLS + public endpoint) —
  now unblocked (headroom freed).
- 2026-07-18 (cont.): C1 DONE (44%) — **CanI is live on the public internet.** Enabled the
  AKS managed-NGINX ingress addon via Pulumi (PR #39, in-place cluster update), installed
  cert-manager, and stood up a Let's Encrypt prod cert on `172.175.33.251.sslip.io`
  (HTTP-01, debugged on staging first). The docs-platform deny-all blocked both the ingress
  controller and the ACME solver — added targeted NetworkPolicies for each. Verified from
  outside the cluster: valid cert (ssl_verify=0), UI serves, public query works through
  NGINX -> web -> hub-api -> docs-api -> retrieval, HTTP->HTTPS 308. Codified to IaC
  (PR #40) + `runbooks/ingress-tls-setup.md`. Next: A2 + C2 (real Entra OIDC — the public
  callback URL that unblocks it now exists).
- 2026-07-18 (cont.): **Custom domain live — https://app.canido.co.** The interim
  `<ip>.sslip.io` was swapped for the real domain: added a GoDaddy A record
  `app -> 172.175.33.251` (the ingress static LB IP), switched the web Ingress host to
  app.canido.co, and cert-manager re-issued a Let's Encrypt cert for it. Verified valid
  (ssl_verify=0) + query works. This is the hostname A2/C2's OIDC redirect will register.
