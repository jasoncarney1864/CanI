# CanI

A personal RAG platform — auth → upload → ingest → retrieve → cite over your own
documents. See [docs/](docs/) for the full architecture; this file only covers running
the code in this repo.

Current scope: v1 core loop (`docs/16-roadmap-and-phasing.md` Phase 1). What's real vs
scaffolded is tracked in [docs/implementation-status.md](docs/implementation-status.md).

## Prerequisites

- Python 3.13 (pinned baseline for reproducible local + CI runs)
- Docker Desktop (or another Docker Engine + Compose v2) — only required for the full
  dev stack and the integration tests, not for unit tests or lint

## Setup (clean machine)

```bash
git clone <this-repo>
cd CanI
python3.13 -m venv .venv-test
```

```powershell
# Windows (recommended)
py -3.13 -m venv .venv-test
```

```bash
# macOS/Linux
source .venv-test/bin/activate
```
```powershell
# Windows
.\.venv-test\Scripts\Activate.ps1
```

```bash
pip install --upgrade pip
pip install -r requirements-dev.txt
```

This installs `cani-shared` plus all four services in editable mode, along with
`pytest`, `ruff`, and `reportlab` (used to generate a real PDF fixture in the
integration tests).

## Configuration

```bash
cp .env.example .env
```

Generate the two required signing secrets (app startup fails fast — see
`cani_shared.config.Settings` — if these are missing, empty, or shorter than 32
characters):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"   # CANI_TOKEN_SIGNING_SECRET
python -c "import secrets; print(secrets.token_urlsafe(48))"   # CANI_SESSION_SECRET
```

Paste each into `.env`. Everything else in `.env.example` already has a working local
default (Postgres, Qdrant, Azurite) — you do **not** need real Azure credentials to run
the full core loop locally. If you leave `AZURE_OPENAI_*` / `AZURE_DOCUMENTINTELLIGENCE_*`
blank, ingestion and retrieval automatically use deterministic fake providers
(`cani_shared.providers.factory`) instead of calling out to Azure. Fill them in only if
you want to exercise the real embedding/OCR/chat path.

`.env` is gitignored — never commit it. `.gitleaks.toml` allowlists exactly one
non-secret string (the publicly documented Azurite emulator dev key); everything else in
`.env.example` is a placeholder, not a credential.

## Running tests

Reliable one-command local test run (unit first, then integration):

```bash
python scripts/run_local_tests.py
```

On Windows without an activated venv:

```powershell
.\.venv-test\Scripts\python.exe scripts\run_local_tests.py
```

Unit tests (fast, no Docker required):

```bash
pytest tests/unit -v
```

Integration tests (drives the real HTTP flow against a docker-compose stack — this
builds images and can take a few minutes on first run):

```bash
pytest tests/integration -v
```

This brings the full stack up and down automatically (see `tests/integration/conftest.py`).
If you already have the stack running via `docker compose up` and want the tests to use
it instead of managing their own lifecycle, set `CANI_SKIP_COMPOSE=1`.

Everything (what CI runs, in order):

```bash
ruff check apps tests db
ruff format --check apps tests db
python scripts/run_local_tests.py
```

## Running the dev stack manually

```bash
docker compose up -d --build
```

Services: hub-api `:8001`, docs-api `:8002`, retrieval-worker `:8003` (internal-only in
production, exposed here for local debugging), Postgres `:5432`, Qdrant `:6333`, Azurite
`:10000`. Tear down with `docker compose down -v` (the `-v` also drops the local
Postgres/Qdrant/Azurite volumes — omit it to keep data between restarts).

Walk the core loop by hand:

```bash
# 1. Dev-login (stub IdP — see docs/implementation-status.md for the real-Entra swap plan)
curl -c cookies.txt -X POST http://localhost:8001/auth/dev-login \
  -H "Content-Type: application/json" -d '{"idp_subject":"local-test-user"}'

# 2. Mint an access token (needs the CSRF cookie set above)
CSRF=$(grep cani_csrf cookies.txt | awk '{print $7}')
TOKEN=$(curl -s -b cookies.txt -X POST http://localhost:8001/auth/token \
  -H "x-cani-csrf-token: $CSRF" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 3. Upload a PDF
curl -X POST http://localhost:8002/documents \
  -H "Authorization: Bearer $TOKEN" -F "file=@/path/to/your.pdf;type=application/pdf"

# 4. Poll GET /documents/{document_id} until current_status == "indexed", then:
curl -X POST http://localhost:8002/query \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"your question here"}'
```

(Note: on native Windows Git Bash, `curl -F "file=@/path/..."` can mis-parse the path —
the integration tests use `httpx` for exactly this reason. `curl` from WSL/macOS/Linux is
fine.)

## Lint & format

```bash
ruff check apps tests db          # lint
ruff format apps tests db         # auto-format
ruff format --check apps tests db # verify formatting without changing files (CI mode)
```

## Project layout

```
apps/            hub-api, docs-api, ingestion-worker, retrieval-worker, shared-lib
db/               SQL migrations + migration runner
infra/            Pulumi IaC (platform + workload landing zones) — applied to dev; see docs/implementation-status.md
tests/unit/       no external dependencies
tests/integration/ drives docker-compose
runbooks/         operational runbooks for the scenarios already covered by this MVP
docs/             architecture, ADRs, implementation status, PR summary
scripts/          local developer automation helpers (including sequential test runner)
```
