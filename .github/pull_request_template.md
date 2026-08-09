## What and why

<!-- What changes, and what problem it solves. Link the docs/ section, ADR, or sprint
     board item if there is one. -->

## Gate

- [ ] `ruff check apps tests db`
- [ ] `ruff format --check apps tests db`
- [ ] `pytest tests/unit`
- [ ] `pytest tests/integration` (or: not applicable, because …)

## Risk

<!-- Blast radius, and how to back it out. -->

- [ ] Includes a schema migration (`db/migrations/`) — backfill needed? _yes / no_
- [ ] Changes config (`Settings`) — `.env.example` updated to match
- [ ] Touches auth, owner-scoping, or the vector access boundary
- [ ] Changes provider selection — **confirm real providers are still in play, not the
      fakes** (see the August 2026 fallback incident in `docs/implementation-status.md`)

## Docs

- [ ] `docs/implementation-status.md` updated if this moves something from scaffolded to live
