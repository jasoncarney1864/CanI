# CanI Web — "Illuminated Clarity" prototype

A Next.js (App Router + TypeScript) prototype of the CanI design language: the
**Spotlight** dual-pane layout and the **Spoke** token framework. The workspace
seeds with the Oakwood mock sample, and the **ask box is wired to the live
docs-api `/query` endpoint** via a server-side proxy (see below).

## Run

```bash
cd apps/web
npm install
npm run dev
```

Then open http://localhost:3000. The app opens on the **Legal** spoke to mirror
the design-language blueprint.

### Live queries against the dev stack

Asking a question calls `POST /api/query` (a Next server Route Handler), which
reproduces the dev auth flow and proxies to docs-api — so the browser never
handles tokens/cookies and there is no CORS. Start the backend first:

```bash
docker compose up -d   # from the repo root; brings up hub-api/docs-api/etc.
```

The proxy targets these defaults (override via env if your ports differ):

| Env var | Default | Purpose |
| --- | --- | --- |
| `HUB_API_URL` | `http://localhost:8001` | dev-login + token minting |
| `DOCS_API_URL` | `http://localhost:8002` | the `/query` gateway |
| `CANI_DEV_IDP_SUBJECT` | `web-prototype-user` | dev-login identity |

> The `/auth/dev-login` path only exists when the backend runs with `ENV=dev`.
> If the stack is down, the ask box shows a friendly "could not reach backend"
> message and the seeded sample stays visible.

## What it demonstrates

- **Global design tokens** (§2) and **dual-stack typography** (§4): DM Sans for
  UI chrome, Source Serif for the verdict summary and document body.
- **Spotlight layout** (§5): collapsible left rail (25% ↔ icon-only), header,
  and a 35% / 65% Conversation + Document Viewer split.
- **Extensibility framework** (§6): the spoke switcher in the left rail re-maps
  tokens (accent, badge colour, label, domain icon, input placeholder) across
  Hub / Legal / Health / Finance with **no structural change**.
- **Spotlight-Yellow citation highlight** on the cited passage in the viewer.

## Structure

| Path | Purpose |
| --- | --- |
| `app/layout.tsx` | Root layout; loads fonts; imports global tokens |
| `app/globals.css` | Design tokens (§2/§3) + all component styles |
| `app/page.tsx` | Renders `AppShell` on the Legal spoke |
| `app/api/query/route.ts` | Server proxy: dev-login → token → docs-api `/query` |
| `lib/spokes.ts` | Spoke token config (the token-mapping table, §6) |
| `lib/mockData.ts` | Oakwood HOA seed answer + source document |
| `lib/types.ts` | Types mirroring `cani_shared` for the API contract |
| `components/*` | `AppShell`, `LeftRail`, `SpokeSwitcher`, `ConversationPane`, `VerdictBadge`, `DocumentViewer` |

## Deliberately out of scope (deferred)

- Real Entra sign-in / session UI — the proxy uses dev-login for local wiring.
- Document **upload** and the ingestion status UI.
- Driving the **Document Viewer** from live data — it still renders the mock
  Oakwood document (the API returns citation snippets, not full paginated
  source text with highlight spans).
- Mobile/responsive polish beyond the left-rail collapse.
- A **Finance** backend entitlement (design shows it; code has DOCS/LEGAL/HEALTH).

Types are intentionally aligned with `apps/shared-lib/cani_shared/models.py`
(`RetrievalAnswer`, `Citation`, `Verdict`, `Document`) so wiring to the live
docs-api later is a small step. Both the cited-chunk **`snippet`**
(`Citation.snippet`) and the structured **`verdict`** field
(`RetrievalAnswer.verdict`, populated by the LLM grounder for yes/no questions)
are already returned by the backend, so the citation source text and the verdict
pill are real-data-ready.
