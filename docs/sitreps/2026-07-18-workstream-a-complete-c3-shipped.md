SITREP — CanI Platform
Date: 2026-07-18 | Branch: main | Sprint: 3 (Reachability), 89% (32/36)

1. LAST COMPLETED

C3 (edge rate limiting + security headers) shipped and deployed (PR #48, merge 110b081), with a follow-up accuracy correction to the board (PR #49). Security headers are applied at the app layer (next.config.js headers()) and verified present on live responses (curl -I https://app.canido.co returns all six: HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy with the microphone allowed for voice, and a Next-appropriate CSP). Edge rate limiting is applied via NGINX ingress annotations (limit-rps 20, burst x5, limit-connections 20 per client IP) and verified active in the running controller config (limit_req burst=100 nodelay + limit_conn 20 on the web server block). WAF decision recorded: no managed WAF for dev; Azure Front Door / App Gateway WAF is the documented production upgrade path.

2. WHERE WE ARE NOW

- CanI is live at https://app.canido.co and the full loop is proven end to end this session on real content: real Entra OIDC sign-in, in-UI upload with OCR ingestion (Document Intelligence), voice and typed query, grounded cited answers with the Document Viewer spotlight, and two-user owner-scoping confirmed live (a second Entra user saw none of the first user's documents).
- Sprint 3 is 89% (32/36). Workstream A is complete (A1, A2, A3); B1+B2, C1, C2, C3 all done. Remaining: D1 (Key Vault CSI) and the closeout gate.
- Verification honesty on C3: the rate limit is config-verified (limit_req/limit_conn present and active) but a 503 was NOT empirically triggered — a single curl client tops out ~17 rps, below the ~40 rps needed across the 2 ingress-controller replicas (per-pod local counters). The board reflects this accurately. Also noted: ingress-nginx overrides the app's HSTS value with its own 1-year default (HSTS is present and correct, just the ingress value wins).
- Four production-only bugs were caught and fixed this session, all merged, deployed, and verified: voice silent-failure (Edge Web Speech API has no speech backend — works in Chrome; PR #43), the verdict-badge glyph (a check next to "Insufficient evidence"; PR #43), the ingress 413 on uploads over 1 MB (proxy-body-size raised to 26m; PR #45), and the post-auth redirect landing on 0.0.0.0:3000 (relative redirects; PR #47).
- main is clean at 60e3786; PRs #42 through #49 all merged. Nothing is half-done — this is a clean stopping point.
- Watch item: Docker Desktop was started locally for the compose-stack verifications and can be closed when convenient.

3. NEXT STEPS

1. D1 — Key Vault CSI secret cutover (move cluster secrets to Azure Key Vault via the CSI driver + workload identity, then verify pods still read them). Meatier infra task; best started fresh, not at the tail of a session, since it touches the secret-handling path. (Owner: Jason)
2. Sprint 3 closeout gate — final acceptance walkthrough + update implementation-status.md with the Sprint 3 outcomes. (Depends on D1.)
3. Optional follow-ups (backlog): empirical rate-limit load test (hey/wrk/vegeta) to observe the 503 throttle; nonce-based CSP to drop script/style 'unsafe-inline'; raise ingress HSTS to 2y/preload; server-side Azure Speech STT so voice works beyond Chrome.
