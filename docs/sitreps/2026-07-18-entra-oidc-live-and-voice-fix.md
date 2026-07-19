SITREP — CanI Platform
Date: 2026-07-18 | Branch: feat/voice-ux-and-a2c2-closeout | Sprint: 3 (Reachability), 2026-07-18

1. LAST COMPLETED

Real Entra OIDC sign-in is live at https://app.canido.co. The web app's authentication layer (A2) and the Entra configuration (C2) were built and merged in PR #42 (merge 3d682e2) — bundled with parallel voice-UI, marketing-site, and zip-ingestion work — then deployed by the app-cd-dev pipeline (all six images built and pushed, rollout plus health smoke passed). Verified live in the browser: a real sign-in round-trips through the caniauth CIAM tenant into the workspace, the unauthenticated sign-in gate renders instead of the workspace, and an authenticated query correctly fails closed ("insufficient evidence") for an empty corpus. The zip-ingestion path was also proven end-to-end against the full docker-compose stack (archive reaches "unpacked", entries reach "indexed", retrieval returns citations) before merge.

2. WHERE WE ARE NOW

- CanI is live on the public internet at https://app.canido.co with a valid Let's Encrypt cert and real Entra OIDC sign-in; health endpoint returns 200 and /auth/login redirects to caniauth.
- C2 is DONE and verified (public callback URL registered, full auth-code + PKCE flow completes over the public endpoint).
- A2 is implementation-complete and single-user sign-in is verified live; its final done-criterion — two different users seeing only their own documents through the web UI — is NOT yet manually verified. Owner-scoping is enforced at every data boundary and covered by the cross-user isolation integration test, but the browser-level two-user pass is still outstanding.
- Voice input works in Google Chrome but not Microsoft Edge: Edge exposes the Web Speech API but ships no speech backend, so it silently failed. Root cause diagnosed and confirmed (Chrome transcribes, Edge does not).
- Current branch (feat/voice-ux-and-a2c2-closeout, uncommitted) adds the voice-failure fix (surface a clear error instead of a silent "Listening..." loop) and a verdict-badge glyph fix (no more affirmative check next to "Insufficient evidence"), plus the A2/C2 board closeout. Web app tsc, lint, and production build are clean. This branch is not yet committed, pushed, or deployed (PR #43 pending).
- Backend unit tests: 96 passed. All checks green on the merged PR #42.
- Watch item: Docker Desktop was started locally for the e2e run and left running; close when convenient.

3. NEXT STEPS

1. Commit the current branch and open PR #43 (voice UX fix + verdict glyph + board closeout); merge to deploy the fixes (Owner: Jason to approve merge).
2. Run the manual two-user owner-scoping pass through the web UI — this closes A2's last done-criterion (Owner: Jason, needs a second account).
3. Upload-in-UI test: upload a document, confirm ingestion to "indexed", then a real clickable citation opens the viewer (groundwork for A3).
4. Decide cross-browser voice: accept "voice in Chrome, type elsewhere", or build server-side Azure Speech STT so voice works in all browsers (backlog).
5. Proceed to remaining Sprint 3 items: A3 (upload in UI), C3 (edge rate limit + headers), D1 (Key Vault CSI), then sprint closeout.
