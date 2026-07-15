---
description: Situation report — persisted to docs/sitreps/ and printed Word paste-ready
---

Produce a situation report ("sitrep") for the CanI project.

Gather facts before writing — never from memory alone:
1. This conversation's recent work (primary source).
2. `git log --oneline -8` and `git status --short` for what's committed vs in flight.
3. `docs/17-sprint-1-execution-board.md` (and 18) for sprint item status.
4. `docs/implementation-status.md` for live-vs-scaffolded state.

Deliver it twice:
1. **Persist** to `docs/sitreps/YYYY-MM-DD-<slug>.md` — ISO date prefix (files sort
   into a timeline), then a 2-5 word kebab slug naming the headline work (e.g.
   `2026-07-15-keda-fix-and-secret-rotation.md`). If that day already has a sitrep,
   pick a distinct slug; never overwrite an existing sitrep. Do not commit it unless
   asked — leave it in the working tree.
2. **Print the full report in chat** so it can be copy/pasted into Word immediately.

Content rules — the body will be pasted into Microsoft Word, so use ONLY plain text
that pastes cleanly: no markdown headers (#), no backticks, no tables/pipes, no bold
markers. Use CAPS section headings, simple dashes, and numbered lists. Keep it under
one page. Never include secret values, connection strings, or key material. Structure
exactly:

SITREP — CanI Platform
Date: <today> | Branch: <current branch> | Sprint: <sprint + day if known>

1. LAST COMPLETED
<Short prose paragraph: the most recent finished piece of work, what it fixed or
delivered, and how it was verified. Reference commit short-hashes in parentheses.>

2. WHERE WE ARE NOW
<4-8 dash lines covering: what is live and healthy (cluster/services/tests),
what is in flight, and any known risks or watch items. State test/verification
status explicitly — never imply something is verified if it is not.>

3. NEXT STEPS
<Numbered list in priority order, 3-5 items max. Each item one line plus, where
relevant, its blocker or owner in parentheses.>

Accuracy rules: distinguish committed vs uncommitted, applied vs scaffolded,
verified vs assumed — same discipline as docs/implementation-status.md. If the last
session's end state is unknown (fresh session), say so and report from git/docs
evidence only.
