# CanI — working notes for Claude

Personal RAG platform: auth → upload → ingest → retrieve → cite over the user's own
documents. Live at https://app.canido.co.

`docs/` holds the authoritative architecture. This file is the operating manual: how to
run things, what the conventions are, and what will bite you.

## Repo map

Python monorepo, 5 installable packages under `apps/`, plus two JS frontends.

| Path | What it is |
|---|---|
| `apps/shared-lib` (`cani_shared`) | Everything shared: config, auth/tokens, db pool + repositories, blob, chunking, vector client, providers, middleware, telemetry. **Most changes start here.** |
| `apps/hub-api` (`:8001`) | Auth. OIDC (Entra External ID), dev-login stub, session→token mint, CSRF. |
| `apps/docs-api` (`:8002`) | Public API. Upload, document status, `/query`. |
| `apps/retrieval-worker` (`:8003`) | Vector search + grounded answer. Internal-only in prod. |
| `apps/ingestion-worker` | No HTTP server. Polls jobs → extract → chunk → embed → upsert. |
| `apps/web` | Next.js app (standalone output). The deployed UI. |
| `apps/marketing` | Separate Vite marketing site → Azure Static Web Apps. |
| `db/` | Numbered SQL migrations + runner image. |
| `infra/container-apps/` | **Current** deploy target: Bicep + PowerShell. |
| `infra/platform`, `infra/workload` | Pulumi landing zones (the older AKS-era IaC). |
| `tests/unit` | Fast, no Docker, no credentials. |
| `tests/integration` | Drives real HTTP against docker-compose. Slow. |
| `runbooks/` | Operational procedures. |
| `scripts/` | Local dev helpers. |

Python 3.13, pinned in `.python-version`. Services are installed editable via
`requirements-dev.txt` — importing `cani_shared` from a test just works, no path hacks.

## Commands

Use the `.venv-test` virtualenv. (`.venv` also exists but `.venv-test` is what the README
and `scripts/run_local_tests.py` assume.)

```bash
pip install -r requirements-dev.txt   # installs all 5 packages editable + pytest/ruff/reportlab

pytest tests/unit -v                  # fast, no Docker
pytest tests/integration -v           # builds images, minutes on first run
python scripts/run_local_tests.py     # unit then integration, sequential — the reliable one

ruff check apps tests db              # lint
ruff format apps tests db             # format
ruff format --check apps tests db     # CI mode

docker compose up -d --build          # full dev stack
docker compose down -v                # tear down (-v also drops volumes)
```

CI (`.github/workflows/ci.yml`) runs, in order: gitleaks → `ruff check` → `ruff format
--check` → `pytest tests/unit` → integration against compose. Match that order locally
before pushing and CI won't surprise you.

On Windows without an activated venv: `.\.venv-test\Scripts\python.exe scripts\run_local_tests.py`.

**Three Python versions are currently in play, and they disagree:**

| Where | Version | Set in |
|---|---|---|
| Service containers (what actually ships) | **3.12** | `apps/*/Dockerfile`, `db/Dockerfile` |
| CI + the documented local baseline | **3.13** | `.github/workflows/ci.yml`, `.python-version`, ruff `target-version` |
| Package floor | 3.11 | `requires-python` in every `pyproject.toml` |

So CI unit tests run on an interpreter that production never uses. Unresolved — do not
"fix" it by bumping one number in isolation; changing the container base image needs the
integration suite to pass against it, and dropping CI to 3.12 needs the ruff target moved
too. Flag it rather than papering over it.

## Conventions

- **ruff** with `E, F, I, UP, B`. Line length 110, but `E501` is ignored — so long lines
  don't error; ruff format still wraps at 110. `fastapi.Depends/File/Query` are
  allowlisted for B008 (`pyproject.toml`).
- Config is environment-only, via `cani_shared.config.Settings` (pydantic-settings).
  Add new config there with an explicit `alias=` and document it in `.env.example`.
- Migrations are numbered SQL in `db/migrations/` (`000N_description.sql`). That file is
  the source of truth — do not write ad-hoc migration scripts at repo root.
- Comments in this codebase explain *why*, often citing the incident that motivated the
  code. Match that when adding non-obvious logic.

## Gotchas

**Fake providers fail open, silently.** `cani_shared/providers/factory.py` returns
`FakeEmbedder`/`FakeGrounder` whenever the Azure AI settings are unset. That is
deliberate — CI and local dev need no credentials — but in August 2026 production ran
fakes for an entire sprint before anyone noticed, because nothing errored. If you are
verifying that real AI is in play, check the deployed config, not the fact that a
grounded answer came back. `ensure_collection` now hard-fails on vector-dimension
mismatch, which is the tripwire for that class of bug.

**`.env` secrets must be ≥32 chars.** `CANI_TOKEN_SIGNING_SECRET` and
`CANI_SESSION_SECRET` fail startup if missing, empty, or short. An unedited copy of
`.env.example` leaves them empty, which is exactly the case the validators exist to
catch. Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

**Never commit `.env`.** `.gitleaks.toml` allowlists exactly one string — the publicly
documented Azurite emulator dev key. Everything else it flags is real.

**Docs lag the infrastructure.** Much of `docs/` (and `docs/10-aks-cluster-design.md`
especially) describes the AKS deployment. Commit `25a8899` consolidated onto Azure
Container Apps. When docs and `infra/container-apps/` disagree, the latter is current;
say so rather than following stale docs.

**Don't search `node_modules`.** `apps/web`, `apps/marketing`, and
`cani-approval-broker` all have populated `node_modules/` in the working tree. Scope
greps and globs to source directories or they'll drown.

**Integration tests own the compose lifecycle.** `tests/integration/conftest.py` brings
the stack up and down itself. If you already have it running, set `CANI_SKIP_COMPOSE=1`
so the tests use yours instead of fighting over it.

**Windows `curl -F "file=@path"`** mis-parses paths under Git Bash. The integration tests
use `httpx` for exactly this reason — reach for httpx, not curl, in anything scripted.

**Repo root stays clean.** Scratch files, captured command output, and one-off scripts do
not belong at root; 16 of them were removed in `184df3a`. Throwaway work goes in `/tmp`,
keepers go in `scripts/`.

**The dev machine is Windows on ARM, but the venv must be x64 Python.** `grpcio` and
`grpcio-tools` (pulled in by `qdrant-client`) publish no `win_arm64` wheels at all, and
`cryptography` has none past 46.0.3. On a native ARM64 interpreter pip falls back to
source builds requiring Rust + MSVC; `cryptography` fails metadata generation and the
whole install aborts, leaving a venv with *nothing* in it — including no `pytest` or
`ruff`, which makes it look like a PATH problem rather than a failed install. If
`pip install -r requirements-dev.txt` dies on a `.tar.gz` dependency, check
`python -c "import platform; print(platform.machine())"` first; it must say `AMD64`.

## Where to look first

- What's actually built vs. scaffolded → `docs/implementation-status.md`
- Architecture decisions → `docs/adr/`, `docs/04-key-architectural-decisions.md`
- Current sprint state → `docs/19-sprint-3-reachability-board.md`
- Recent sitreps → `docs/sitreps/`
- Operational procedures → `runbooks/`
