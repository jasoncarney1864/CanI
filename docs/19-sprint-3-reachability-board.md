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
- Last updated: 2026-08-04
- Overall status: [-] In progress (97%, 35/36) — **Workstreams A, B, C complete** (A1–A3,
  B1+B2, C1, C2, C3) **plus D1 (Key Vault CSI cutover)**. **CanI is live on the public internet
  at https://app.canido.co**: real Entra OIDC sign-in, in-UI upload with OCR ingestion, voice +
  typed query, grounded cited answers, two-user owner-scoping, edge rate limiting + security
  headers, and secrets now sourced from Azure Key Vault via the CSI driver + workload identity
  (manual secret script retired). Real Azure OpenAI providers were finally wired in on
  2026-08-04 — until then the deployed environment ran the fake embedder/grounder, so treat
  pre-2026-08-04 "grounded answer" claims as proving plumbing only (see the changelog).
  Remaining: closeout gate — plus the deferred storage/Entra/
  Postgres secret rotations tracked under D1.

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
- Status: [x] Done (2026-07-18, PR #42; two-user owner-scoping confirmed live 2026-07-18)
- Dependencies: A1
- Checklist:
  - [x] Web app has a real sign-in via hub-api's Entra OIDC flow (not the mock profile);
    signed-in user shown in the rail footer (and top bar). Verified live at
    `https://app.canido.co`: `/auth/login` -> caniauth -> `/auth/callback` -> session.
  - [x] The session is carried to docs-api calls so responses are owner-scoped to the
    logged-in user (server-side token mint from `cani_session`; query returned the correct
    fail-closed "insufficient evidence" for the signed-in user's empty corpus).
  - [x] Unauthenticated users cannot reach the workspace (server-side whoami gate renders the
    sign-in screen); logout works.
- Done criteria:
  - [x] Two different users see only their own documents/answers through the web app.
    Confirmed live 2026-07-18: user A (`3de34a00...`) uploaded + queried a document; user B
    (`1c8664cb...`, separate Entra sign-in, incognito) saw an empty Documents list and no
    access to A's content. This is the browser-level proof of the owner-scoping that is
    enforced at every data boundary and covered by the cross-user isolation integration test.

### A3. Upload + ingestion status in the web app (P2)

- Owner: Jason
- Status: [x] Done (2026-07-18, PR #44) — server path verified end-to-end locally; browser
  visual pass pending.
- Dependencies: A1, A2
- Checklist:
  - [x] A user can upload a PDF from the UI (type/size validated client-side in
    `lib/uploads.ts` and server-side in docs-api). Upload/Documents nav items are now real
    views (were inert placeholders); the file posts through a new owner-scoped
    `/api/documents` proxy.
  - [x] The UI shows ingestion progress (queued -> extracting -> chunking -> embedding ->
    indexed) via the Documents view, which polls while anything is in flight and surfaces a
    plain "Failed" badge for a blocked (malware) or OCR-unsupported document.
  - [x] After indexing, the document is queryable from the UI (the existing query loop).
- Done criteria:
  - [x] Upload-to-queryable works from the browser, with honest status and failure states.
    Verified end-to-end against the local stack through the actual proxy routes (the same
    requests the browser issues): PDF upload -> queued -> indexed -> query returned a
    grounded answer citing the uploaded doc; unsupported type -> honest 400; no session ->
    401. Web tsc/build/lint clean. Final browser click-through is the remaining confirmation.

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
- Status: [x] Done (2026-07-18, PR #42)
- Dependencies: C1 (met)
- Checklist:
  - [x] Add the public callback URL (`https://app.canido.co/auth/callback`) to the
    `cani-hub` Entra app registration redirect URIs (caniauth CIAM tenant, Web platform).
  - [x] hub-api `ENTRA_OIDC_REDIRECT_URI` set to the public callback (via the
    `cani-hub-oidc` cluster secret); the callback path is reachable through the ingress.
  - [x] The full authorization-code + PKCE flow completes over the public endpoint; the
    localhost redirect remains only as a dev entry.
- Done criteria:
  - [x] A real browser sign-in through the public URL creates a session and reaches the
    workspace. (Verified live 2026-07-18 — closes the long-standing "public redirect URI"
    production blocker.)

### C3. Edge rate limiting + security headers (P2)

- Owner: Jason
- Status: [x] Done (2026-07-18, PR #48)
- Dependencies: C1
- Checklist:
  - [x] Rate limiting enforced at the ingress edge (NGINX annotations on the web Ingress:
    `limit-rps: 20`, `limit-burst-multiplier: 5` (burst bucket 100), `limit-connections: 20`
    per client IP) — a global edge throttle complementing the Sprint 2 per-pod limit.
  - [x] Standard security headers present, applied at the app layer via `next.config.js`
    `headers()` (portable; survives ingress changes): HSTS, X-Content-Type-Options: nosniff,
    X-Frame-Options: DENY, Referrer-Policy: strict-origin-when-cross-origin, Permissions-Policy
    (mic allowed for voice; camera/geo denied), and a Next-appropriate CSP (`default-src
    'self'`; `connect-src 'self'`; `frame-ancestors 'none'`; `script/style-src 'self'
    'unsafe-inline'` — inline is required for Next's un-nonced hydration/styles; nonce-based
    CSP is a tracked follow-up). Note: the app sets HSTS `max-age=63072000; preload`, but the
    ingress-nginx controller overrides it with its own default (`max-age=31536000;
    includeSubDomains`) — HSTS is present and correct on live responses, just the ingress
    value wins; raising it to 2y/preload would be an ingress-level config, a minor follow-up.
  - [x] WAF posture decided and recorded (see decision below).
- Done criteria:
  - [x] Security headers verified present on live responses (`curl -I https://app.canido.co/`
    returns all six). Edge rate limiting verified **active in the running NGINX config**:
    the annotations translate into `limit_req zone=... burst=100 nodelay` and `limit_conn ...
    20` on the web server block (confirmed by inspecting the live controller's nginx.conf). A
    503 was **not** empirically triggered — a single curl client (full TLS handshake per
    request) tops out ~17 rps, below the ~40 rps (2 controller replicas x 20 rps, per-pod
    local counters) needed to drain the burst bucket. Empirical burst-throttle confirmation
    needs a load tool (hey/wrk/vegeta); the mechanism itself is present and active.
- WAF decision: **No managed WAF for dev.** An Azure Front Door / App Gateway WAF adds
  recurring cost, another hop, and operational surface that isn't justified for a
  single-user dev deployment. The current posture — only the web app publicly exposed
  (backend private), edge rate limiting, security headers, and TLS — is the accepted dev
  baseline. A managed WAF (Front Door or App Gateway + AGIC) is the documented production
  upgrade path if/when the app takes real multi-tenant traffic.

## Workstream D - Hardening elevated by public exposure

### D1. Key Vault CSI secret cutover (P2)

- Owner: Jason
- Status: [x] Done (2026-07-20, PRs #52 infra + #53 k8s) — cutover complete and verified live;
  full secret rotation partially done (signing/session rotated; storage/Entra/Postgres deferred,
  tracked below).
- Dependencies: none (independent; higher priority now the surface is public)
- Checklist:
  - [x] Workloads read secrets from Key Vault via the CSI driver + workload identity. All four
    services (docs-api, hub-api, retrieval-worker, ingestion-worker) mount the
    `cani-keyvault-secrets` SPC; the driver syncs `cani-secrets` (both namespaces) +
    `cani-keda-postgres` from the private vault `cani-platform-kv6370c4cb` over a private
    endpoint, authenticated by the `cani-secrets` workload identity. Config split out to the
    `cani-config` ConfigMap; orphaned `cani-hub-oidc` removed.
  - [x] Retire the manual `scripts/apply_dev_secrets.sh` path. Script removed; Key Vault is now
    the source of truth; runbooks rewritten to the KV rotation flow. (Storage-account-key auth
    itself remains a dev stopgap — the KV secret still holds a connection string; RBAC-only
    storage is a later hardening.)
  - [-] Rotate the exposed pre-migration secret values per `runbooks/rotate-dev-secrets.md`.
    `CANI_TOKEN_SIGNING_SECRET` + `CANI_SESSION_SECRET` rotated and propagated. Storage key,
    Entra client secret, and Postgres admin password rotation **deferred** to a focused
    follow-up (a storage-key rotation attempt during the cutover wrote an unverified key and
    briefly crashlooped docs-api — reverted; the runbook now mandates a test-first, CSI-aware
    delete-secret procedure).
- Done criteria:
  - [x] Services boot with secrets sourced from Key Vault; the manual stopgap is removed.
    Verified live: healthy pods on KV-sourced secrets and a clean end-to-end incognito Entra
    sign-in (proves the vaulted Entra/session/signing secrets all work). The remaining
    pre-migration value rotations (storage/Entra/Postgres) are tracked, not a blocker for the
    cutover objective — the closeout gate accepts "Key Vault CSI (or an explicit, documented
    deferral)".

## Sprint closeout gate

- Owner: Jason
- Status: [ ] Not started
- Checklist:
  - [x] End-to-end from the public URL: Entra login -> upload -> query -> cited answer in
    the Spotlight UI, owner-scoped. (Verified 2026-08-04, but only after fixing the
    fake-provider defect below — the first attempt failed semantically.)
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
8. **Cross-browser voice input (backlog).** The voice-first UI uses the browser Web Speech
   API (`webkitSpeechRecognition`), which only transcribes in Chrome — Edge exposes the API
   but ships no speech backend, so it silently fails (fix in PR #43 now surfaces the error).
   For voice to work everywhere, replace the browser API with server-side STT (Azure Speech)
   fed by `getUserMedia`. Decide whether cross-browser voice is worth that build, or whether
   "voice in Chrome, type elsewhere" is acceptable for a solo-user product. See memory
   `voice-web-speech-edge-limitation`.

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
- 2026-07-18 (cont.): **C2 DONE, A2 in final verification (64%) — real Entra OIDC sign-in is
  live.** Delivered the `cani-hub-oidc` secret to the cluster; registered
  `https://app.canido.co/auth/callback` on the `cani-hub` app registration (caniauth CIAM
  tenant, Web platform). Built the web OIDC layer (PR #42, bundled with parallel voice-UI +
  marketing-site + zip-ingestion work): session-based token mint from `cani_session`, the
  three `/auth/*` proxy routes, a server-side whoami gate, and the signed-in user + sign-out
  in the rail/top bar. Verified live: a real browser sign-in round-trips through Entra into
  the workspace, and an authenticated query fails closed ("insufficient evidence") for an
  empty corpus. Remaining for A2: the manual two-user owner-scoping pass. Also diagnosed the
  voice mic (works in Chrome; Edge's Web Speech API has no speech backend) and fixed the
  silent-failure UX + a mis-affirming verdict glyph (PR #43). Next: upload-in-UI test +
  two-user owner-scoping, then A3/C3/D1/closeout.
- 2026-07-18 (cont.): **A3 DONE (75%) — upload + ingestion status in the UI.** The rail's
  Upload/Documents items were inert prototype placeholders; wired them to real views. Added
  an owner-scoped `/api/documents` proxy (POST multipart upload + GET list, session-token
  minted server-side), an UploadView (file picker + drag-drop, client-side type/size
  validation mirroring docs-api), and a DocumentsView (status badges, polls queued ->
  extracting -> ... -> indexed while in flight, plain "Failed" badge for blocked/OCR-
  unsupported). Verified end-to-end against the local compose stack through the actual proxy
  routes: PDF upload -> queued -> indexed -> query returned a grounded answer citing the
  uploaded doc; unsupported type -> 400; no session -> 401. This unblocks A2's two-user
  owner-scoping pass (there is finally a browser path to add documents). Next: A2 two-user
  check, then C3/D1/closeout.
- 2026-07-18 (cont.): **Workstream A COMPLETE (78%) — full loop proven live on real content.**
  Caught + fixed a production-only bug the local A3 test missed: uploads >1 MB 413'd at the
  managed-NGINX ingress (1 MB default client-body limit). Raised
  `nginx.ingress.kubernetes.io/proxy-body-size` to 26m — applied live via `kubectl annotate`
  and persisted to the manifest (PR #45; verified it renders through the dev kustomize
  overlay so future deploys don't revert it). Then walked the whole loop in the browser: a
  JPEG uploaded -> **OCR via Document Intelligence** -> chunked/embedded (real Azure OpenAI)
  -> indexed -> a **voice** question returned a grounded answer with a citation and the
  Document Viewer spotlight. Finally confirmed **A2's two-user owner-scoping** live: user B
  (separate Entra sign-in, incognito) saw none of user A's documents. A1+A2+A3 all Done.
  Next: C3 (edge rate limit/headers), D1 (Key Vault CSI), closeout.
- 2026-07-18 (cont.): Fixed a post-auth redirect bug (PR #47): sign-in/out landed on
  `https://0.0.0.0:3000/` (ERR_ADDRESS_INVALID) because the redirect was built from the Next
  server's internal `request.url`. Now uses a relative Location so the browser resolves it
  against the public host; verified live.
- 2026-07-18 (cont.): **C3 DONE (89%) — edge rate limiting + security headers.** Rate limiting
  via NGINX annotations on the web Ingress (`limit-rps: 20`, burst x5, `limit-connections: 20`
  per client IP). Security headers applied at the app layer in `next.config.js` `headers()`
  (HSTS, nosniff, X-Frame-Options: DENY, Referrer-Policy, Permissions-Policy with mic allowed
  for voice, and a Next-appropriate CSP) — all six verified present on live responses
  (`curl -I`). Edge rate limiting verified active in the live controller's nginx.conf
  (`limit_req burst=100 nodelay` + `limit_conn 20` on the web block); a 503 was not
  empirically triggered (a single curl client tops out ~17 rps, below the ~40 rps needed
  across 2 controller replicas — needs a proper load tool). Also noted: ingress-nginx
  overrides the app HSTS value with its own 1y default. WAF: no managed WAF for dev
  (recorded in C3); Front Door / App Gateway WAF is the production upgrade path. Next:
  D1 (Key Vault CSI), closeout.
- 2026-07-20: **D1 DONE (97%) — Key Vault CSI secret cutover.** All four services now source
  secrets from the private platform Key Vault via the Secrets Store CSI driver + a
  workload-identity-federated UAMI (infra PR #52: KV private endpoint + DNS + UAMI + per-SA
  federated creds; k8s PR #53: SPC filled, `cani-config` ConfigMap split out, four deployments
  wired with the CSI volume + SA client-id + workload-identity label). Cut over live with zero
  downtime (validated the CSI read path with a throwaway pod, populated the vault via ARM PUT,
  flipped namespace-by-namespace), retired `scripts/apply_dev_secrets.sh`, and deleted the
  orphaned `cani-hub-oidc`. Rotated the signing + session secrets and
  verified end-to-end with a clean incognito Entra sign-in. **Key learning:** the CSI driver
  does NOT auto-propagate KV changes — rotation requires deleting the synced `cani-secrets` in
  both namespaces and restarting all services (a restart-only attempt read the stale secret as
  a false "verified"); a storage-key rotation that wrote an unverified key briefly crashlooped
  docs-api (reverted). Storage/Entra/Postgres rotations deferred to a focused follow-up with
  the corrected, test-first procedure now in `runbooks/rotate-dev-secrets.md`. Next: closeout
  gate.
- 2026-08-04: **Closeout gate run — and it caught a latent defect that invalidates every
  earlier "grounded answer" claim on this board.** Driving the gate end-to-end from
  `https://app.canido.co` (Entra sign-in -> in-UI PDF upload -> ingestion to Ready -> typed
  query) passed *mechanically* but failed *semantically*: the answer to "What is the closeout
  verification code for Sprint 3?" was an unrelated Washoe County tax coupon, rendered in
  `FakeGrounder.ground()`'s exact format. Root cause: **no Azure OpenAI resource had ever
  existed in any subscription**, so `AZURE_OPENAI_ENDPOINT`/`_API_KEY` were unset,
  `Settings.azure_ai_providers_configured` was False, and `providers/factory.py` had been
  silently returning `FakeEmbedder` (32-dim hash vectors) and `FakeGrounder` in production the
  whole time. Not a migration regression —
  `git log -S AZURE_OPENAI_ENDPOINT -- k8s/ infra/` returns nothing. Auth, upload, OCR
  ingestion, storage, citation plumbing and the spotlight were all genuinely working; only the
  intelligence layer was stubbed. **Read the earlier A1/A2/A3 "grounded, cited answer" entries
  as proving the plumbing, not the retrieval quality.**
  Resolution (PR #55 + this PR): provisioned `cani-openai` (S0, eastus2) with
  `text-embedding-3-small` and `gpt-5-1` deployments, both on regional **Standard** SKU to
  honour the single-region data-residency constraint in
  `06-azure-landing-zone-design.md:29`; wired endpoint + deployment names into `cani-config`
  and the API key through Key Vault -> the CSI SecretProviderClass; changed the grounder's
  `max_tokens` to `max_completion_tokens` (gpt-5.x rejects the former); and cut
  `QDRANT_COLLECTION` over to `cani_docs_dev_v2` because `ensure_collection` never validated
  dimensionality and would have silently kept the 32-dim collection. Re-ingested the whole
  corpus: 105 chunks across 72 documents now carry
  `embedding_version = azure-openai:text-embedding-3-small`, and `cani_docs_dev_v2` holds 105
  points at 1536 dims. Re-ran the gate: the same question now returns
  **CLOSEOUT-ZEPHYR-7734** citing `sprint3-closeout-verification.pdf` with the correct
  spotlight, and an out-of-corpus question ("average annual rainfall in Reykjavik") correctly
  returns **INSUFFICIENT EVIDENCE** rather than a guess — fail-closed confirmed.
  Hardening added here: `ensure_collection` now raises `VectorDimensionMismatchError` instead
  of reusing a collection built for a different embedder, so this class of silent corruption
  fails loudly at startup.
  Known follow-ups: `cani-openai` was created with public network access (unlike KV/Postgres);
  neither `cani-openai` nor `cani-docintel` is codified in Pulumi; no sitrep exists for the
  Aug 1-2 subscription migration and several runbooks still name old-subscription resources;
  `test-upload.png` shows "Queued" in the UI although its job is terminally `failed`
  ("no extractable text content" — a blank image), which is a status-display bug.
