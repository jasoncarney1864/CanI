# PR summary: v1 core loop — hardening pass for merge readiness

**Branch:** `feat/v1-core-loop-checkpoint` → `main`
**Base commit:** `1bd5a70` (feat: add v1 core loop implementation and test harness)

## What changed

This is a hardening pass on top of the already-implemented core loop, not new features.
Everything below was found by actually running the checks this PR adds, not by
inspection.

**Security / correctness**
- `cani_shared/config.py`: `CANI_TOKEN_SIGNING_SECRET` and `CANI_SESSION_SECRET` now must
  be ≥32 characters or the app refuses to start. Previously, an env file with these keys
  present-but-empty — exactly what `cp .env.example .env` produces before you fill it
  in — passed validation and ran every service with an empty JWT signing key, making
  every access/session token trivially forgeable. `POSTGRES_PASSWORD` similarly can no
  longer be empty.
- `cani_shared/middleware.py`: unhandled exceptions now log a structured,
  `trace_id`-correlated `request_failed` event before the (unchanged) generic 500 goes
  back to the client. Previously this only reached the client-facing response and a raw,
  uncorrelated stdlib traceback dump — invisible to anything doing structured log
  ingestion later, and impossible to tie back to a specific request.
- `.gitleaks.toml` + a `secret-scan` job in `ci.yml`: real secret scanning on every PR
  (§14.10 requires this; it wasn't wired up). Verified locally against this repo's full
  git history — one false positive (the publicly-documented Azurite emulator dev key in
  `.env.example`) is allowlisted by exact string match; a real high-entropy secret with
  the same shape is still caught (tested both cases).

**CI**
- `ci.yml`: added `ruff format --check` as a gate (13 files were previously unformatted —
  formatting existed as a tool but wasn't enforced). Added pip caching. `compose-smoke-deploy`
  now depends on `secret-scan` passing too, not just lint/unit tests.
- Fixed dangling references across 12 files (`.github/workflows/*.yml`, `infra/**/*.py`,
  `k8s/**/*.yaml`, one runbook) that pointed at a "launch-readiness gap report" that was
  never actually committed — they now point at `docs/implementation-status.md`, which is.

**Documentation**
- `README.md`: rewritten for actual clean-machine reproducibility. The previous version
  gave a single Windows-only test command and didn't distinguish unit tests (no
  dependencies) from integration tests (require Docker) — running the literal documented
  command would silently try to build and run the full docker-compose stack. Verified the
  new instructions end-to-end in a throwaway venv.
- `docs/implementation-status.md` (new): delivered-vs-scaffolded mapped to docs sections
  7–16, a production-blockers list, and a prioritized 2-sprint plan.
- `docs/pr-summary-v1-core-loop.md` (this file).

**Tests** (+10 net new, all passing)
- `tests/unit/test_config.py`: 7 tests for the new fail-fast secret/password validation.
- `tests/unit/test_middleware.py`: 3 tests proving unhandled exceptions (a) never leak
  exception details to the client and (b) produce a structured, trace_id-tagged log line.

No changes to the ownership-scoping code paths themselves (`cani_shared/db/repositories.py`,
`cani_shared/vector/qdrant_client.py`) beyond formatting — those were already correct and
tested; this pass verified that, it didn't touch the guarantee.

## Why it matters

The two security-relevant fixes (weak-secret startup validation, structured failure
logging) are the kind of gap that's invisible in a demo — the app runs fine either way —
but turns into either a real vulnerability (forgeable tokens) or a real operability
problem (untraceable production failures) the first time someone other than the original
author sets this up or something breaks under load. Catching them now, before the first
real deployment, is cheap. Catching them after is not.

The CI/doc fixes exist because this branch is about to be reviewed by someone who wasn't
in the room while it was built — a PR that lints clean but can't actually be followed
step-by-step by a reviewer, or that references a document that doesn't exist, costs the
reviewer time figuring out what's real.

## How to run locally

Full instructions are in `README.md`; short version:

```bash
python -m venv .venv-test && source .venv-test/bin/activate   # or Activate.ps1 on Windows
pip install -r requirements-dev.txt
cp .env.example .env
# fill in CANI_TOKEN_SIGNING_SECRET and CANI_SESSION_SECRET:
python -c "import secrets; print(secrets.token_urlsafe(48))"

ruff check apps tests db
ruff format --check apps tests db
pytest tests/unit -v          # fast, no Docker
pytest tests/integration -v   # builds + runs the full docker-compose stack
```

No Azure credentials are required for any of the above — `AZURE_OPENAI_*` /
`AZURE_DOCUMENTINTELLIGENCE_*` left blank makes ingestion/retrieval use deterministic
fake providers automatically.

## Test evidence

Ran on this branch, this session, immediately before writing this summary:

```
$ ruff check apps tests db
All checks passed!

$ ruff format --check apps tests db
43 files already formatted

$ pytest tests/unit -v
...
29 passed in 2.32s

$ pytest tests/integration -v
tests/integration/test_e2e_flow.py::test_upload_ingest_retrieve_cite PASSED
tests/integration/test_isolation.py::test_cross_user_isolation PASSED
2 passed in 68.31s
```

31 tests total, 0 failures, 0 skips. The integration run builds all four service images
fresh and drives real HTTP calls through hub-api → docs-api → ingestion-worker →
retrieval-worker → Postgres/Qdrant/Azurite — nothing in that path is mocked.

Also verified: `gitleaks detect` against full git history returns zero findings with
`.gitleaks.toml`'s allowlist in place, and still catches a synthetic high-entropy secret
planted for the purpose of checking the allowlist isn't overbroad (not committed).

## Known limitations and follow-up

Full detail in `docs/implementation-status.md`. Highlights:

- **No live Azure access this session** — everything in `infra/` and `k8s/` is
  scaffolded (correct, reviewable) but has never been applied/deployed. `infra-preview.yml`,
  `infra-apply-dev.yml`, and `app-cd-dev.yml` will not run successfully until Azure OIDC
  federated credentials are configured as repo secrets and a subscription exists behind
  them.
- **Entitlement revocation doesn't invalidate existing sessions/tokens** (§7.7 gap) —
  tracked in `runbooks/suspected-cross-tenant-access.md`'s containment step as a required
  workaround (rotate the signing secret) until this is implemented.
- **No malware scanning on upload** (§8.11) — type/size/magic-byte validation only.
- **No rate limiting** on public endpoints (§14.8).
- Follow-up issues to file against this repo: entitlement-revocation session
  invalidation, upload malware scanning, rate limiting, Application Insights wiring
  (blocked on Azure access), budget alerts (blocked on Azure access).

## Non-negotiables — confirmed still true after this pass

- `owner_user_id` enforcement: unchanged, still structural (no unscoped repository/vector
  accessor exists), still covered by `tests/integration/test_isolation.py`.
- No plaintext secrets committed: confirmed via `git ls-files | grep .env` (only
  `.env.example` tracked) and a full-history `gitleaks` scan.
- Nothing in this PR or `docs/implementation-status.md` claims Azure resources were
  applied — every infra/K8s item is explicitly labeled scaffolded-not-live.
