SITREP — CanI Platform
Date: 2026-07-18 | Branch: main | Sprint: Sprint 3 (Reachability), A1 + B1/B2 done

1. LAST COMPLETED
The design-complete web UI is now running in the cluster, wired to the live backend. Two pieces landed. First, A1 (PR #36): the Document Viewer shows the real cited document with the design's in-context spotlight highlight, not mock data. That required a new backend capability — an owner-scoped endpoint that returns a document's source text as its ordered chunks — because the metadata table does not store chunk text and only the retrieval service is allowed to reach the vector store; so the endpoint lives on the retrieval service and the docs API proxies to it, exactly like the existing query path, confirming ownership first. Second, B1 and B2 (PR #37): the web app was containerized as a minimal non-root Next.js standalone image and deployed via the existing CD pipeline (build, roll out, health smoke check), reachable in the cluster. It was verified end to end in-cluster: the health endpoint returns 200, the app serves the Spotlight UI, and a query through the app's server-side proxy returns a valid answer across the full chain (web to hub API for auth, to docs API, to the retrieval service). Only the web pod is on the surface; the backend APIs stay private behind network policy.

2. WHERE WE ARE NOW
- Sprint 3 is 33 percent (12 of 36 board items), day one. A1 (frontend wired to live) and B1+B2 (deploy + CD) are done; the UI is live in the cluster.
- The web app talks to docs API (same namespace) and hub API (cross-namespace) only, via its server-side proxy; the browser never touches the backend directly. Network policies were extended so the two APIs admit the web pod and nothing else new.
- vCPU headroom was freed earlier by dropping the system node pool from two nodes to one (single-user dev needs no system-component HA): the cluster went from ten of ten cores used to eight, which unblocks the ingress controller for the next step. A full app-pool scale to three still needs a quota increase, noted on the board.
- Everything merged to main; the deploy pipeline is green including the new web image build and rollout. No known regressions.
- Still the dev-login auth flow (real Entra sign-in is a later item, coupled to the public redirect). One document shown per answer, all its cited chunks highlighted, matching the single-document blueprint.

3. NEXT STEPS
1. C1 — ingress controller plus TLS plus a public HTTPS endpoint, so the UI is reachable from a browser outside the cluster. This is now unblocked. It needs two decisions up front: the ingress technology (in-cluster NGINX vs a managed Application Gateway or Front Door with a built-in WAF) and a public DNS hostname plus a certificate approach.
2. C2 plus A2 together — once there is a public callback URL, wire the real Entra OIDC login into the web app and switch hub API's redirect to the public endpoint (closes the long-standing localhost-redirect production blocker).
3. C3 — move rate limiting to the ingress edge and add security headers, once the edge exists.
4. Optional A3 — upload and ingestion status in the UI, so a user can add a document from the browser and watch it become queryable.
