# CanI Web — "Illuminated Clarity" prototype

A **static, mock-data** Next.js (App Router + TypeScript) prototype of the CanI
design language: the **Spotlight** dual-pane layout and the **Spoke** token
framework. No backend is called — all data is mocked in `lib/mockData.ts`.

## Run

```bash
cd apps/web
npm install
npm run dev
```

Then open http://localhost:3000. The app opens on the **Legal** spoke to mirror
the design-language blueprint.

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
| `lib/spokes.ts` | Spoke token config (the token-mapping table, §6) |
| `lib/mockData.ts` | Oakwood HOA mock verdict + source document |
| `lib/types.ts` | Types mirroring `cani_shared` for future API wiring |
| `components/*` | `AppShell`, `LeftRail`, `SpokeSwitcher`, `ConversationPane`, `VerdictBadge`, `DocumentViewer` |

## Deliberately out of scope (deferred)

- Live API calls, auth/login, token flow, CORS/ingress.
- Mobile/responsive polish beyond the left-rail collapse.
- A **Finance** backend entitlement (design shows it; code has DOCS/LEGAL/HEALTH).

Types are intentionally aligned with `apps/shared-lib/cani_shared/models.py`
(`RetrievalAnswer`, `Citation`, `Verdict`, `Document`) so wiring to the live
docs-api later is a small step. Both the cited-chunk **`snippet`**
(`Citation.snippet`) and the structured **`verdict`** field
(`RetrievalAnswer.verdict`, populated by the LLM grounder for yes/no questions)
are already returned by the backend, so the citation source text and the verdict
pill are real-data-ready.
