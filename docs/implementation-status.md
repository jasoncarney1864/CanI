# Implementation status — v1 core loop

**Branch:** `main`
**Checkpoint tag:** `checkpoint-2026-07-14-py313`
**Scope:** Phase 1 of `16-roadmap-and-phasing.md` — auth → upload → ingest → retrieve →
cite, plus baseline CI/observability/security and infra/K8s scaffolding.
**Environment constraint:** no live Azure subscription access during implementation. Every
item below is labeled **Live** (real, running, verified) or **Scaffolded** (code is
written and structurally correct, but has never been applied/deployed against real Azure
resources). Nothing in this document claims Azure resources were provisioned — where a
section says "scaffolded," that means Pulumi/K8s/workflow YAML exists and is reviewable,
not that it has run.

## 2026-07-14 update (post-merge checkpoint)

- `feat/v1-core-loop-checkpoint` has been merged into `main`; feature branch cleanup is complete.
- Checkpoint tag created and pushed: `checkpoint-2026-07-14-py313`.
- Reproducibility baseline is now Python 3.13 for local + CI:
  - `.python-version` pins `3.13`
  - CI workflow now uses `actions/setup-python` with `python-version: "3.13"`
  - Ruff target version is `py313`
- Reliable local test command added:
  - `python scripts/run_local_tests.py` (runs unit tests first, then integration tests)
- Current verification snapshot:
  - `ruff check .` passes
  - `ruff format --check .` passes
  - `pytest tests/unit -q` passes (29)
  - `pytest tests/integration -q` passes (2)

## Delivered now, mapped to docs/07–16

### §7 Identity & access — Live (dev-mode), Scaffolded (real Entra)
- Session cookie + CSRF, short-lived signed access tokens with the claims shape §7.5
  specifies (`sub`, `entitlements`, `auth_time`, `exp`, `jti`) — `apps/hub-api`
- Every spoke re-validates the token and entitlement independently
  (`cani_shared.auth.entitlements`), never trusting network placement alone — matches
  §7.4's "spokes must re-check on every call"
- Audit events for login, token issuance, logout (`record_audit_event`) — §7.8
- **Live via dev-login stub** (`hub-api-app POST /auth/dev-login`, 404s outside `ENV=dev`).
  **Not live:** real Entra External ID OIDC — no tenant/app registration exists. Swapping
  it in is scoped to `hub_api_app/main.py`'s login route only; token issuance/validation
  downstream is unchanged.
- **Gap:** entitlement revocation does not force session/token invalidation (§7.7 requires
  it). Documented as a known limitation in `runbooks/suspected-cross-tenant-access.md`.

### §8 RAG pipeline — Live
- Full pipeline running end to end: upload → extract (native PDF; OCR-ready via Document
  Intelligence when keys are configured) → chunk (hybrid structural+token, §8.6 targets)
  → embed → index → owner-filtered retrieve → rerank → grounded answer → citations
- Postgres-table-backed queue (`ingestion_jobs`, `SELECT ... FOR UPDATE SKIP LOCKED`)
  instead of a separate broker — §8.10's retry/idempotency requirements, with exponential
  backoff between job-level retry attempts and per-download retry with backoff
  (`cani_shared.blob.BlobStore.download`)
- Prompt-injection guardrail and "answer only from context" instruction in the grounding
  system prompt (`cani_shared/providers/grounder.py`) — §8.9, §14.8
- Verified live via `tests/integration/test_e2e_flow.py` against a real docker-compose
  stack (not mocked)
- **Gap:** malware/AV scanning on upload (§8.11) is not implemented — file type/size/magic-byte
  validation only

### §9 Data model & storage — Live (schema + isolation), Scaffolded (backup/restore, tiering)
- Postgres schema matches §9.4 exactly, plus `users`/`entitlements`/`audit_events` for hub
  identity (`db/migrations/0001_core_schema.sql`)
- Ownership-scoped repository layer: every function that touches user data requires
  `owner_user_id` as its first parameter — no unscoped accessor exists to call by mistake
  (`cani_shared/db/repositories.py`)
- Qdrant wrapper fails closed (`MissingOwnerFilterError`) if a caller ever omits the owner
  filter, and independently re-verifies `payload["owner_user_id"]` on every result before
  it leaves the wrapper — §9.6, §9.8 defense in depth
- Verified live via `tests/integration/test_isolation.py` — user B gets zero citations
  into user A's document even asking about identical content
- **Not implemented:** backup/restore automation (§9.10), archive-tier lifecycle policies
  (§9.12), deletion orchestrator (§9.9) — all require either real Azure Storage/Postgres
  Flexible Server or are out of MVP-fast scope

### §10 AKS cluster design — Scaffolded only
- `k8s/base` + `k8s/overlays/dev`: namespaces matching §10.2 exactly, NetworkPolicy
  deny-by-default with explicit allows, Qdrant StatefulSet with PodDisruptionBudget,
  HPA on docs-api, KEDA ScaledObject stub on ingestion-worker, Key Vault CSI
  SecretProviderClass, workload-identity service account annotations
- **Not live:** no AKS cluster exists. Manifests have not been `kubectl apply`'d anywhere.
  KEDA/Key Vault CSI add-ons referenced are not installed on any cluster because no
  cluster exists.

### §11 IaC strategy — Scaffolded only
- `infra/platform` and `infra/workload` Pulumi Python projects following the exact
  project/stack split in §11.2–§11.4, with `infra/modules` component resources
  (networking, security, observability, compute-aks, data-services) per §11.7's
  recommended module families
- `infra/workload/__main__.py` consumes `infra/platform` outputs via `StackReference` —
  §11.6 contract
- **Not live:** `pulumi preview`/`pulumi up` has never been run. No Pulumi state backend,
  no Azure OIDC federated identity, no management group bootstrap (§6.6) has happened.

### §12 CI/CD strategy — Live (app CI), Scaffolded (infra CI, prod, GitOps)
- `ci.yml`: secret scan (gitleaks) → lint (`ruff check`) → format check (`ruff format
  --check`) → unit tests → docker-compose integration tests as the "dev deployment" proxy.
  **This is real and runs on every PR.**
- `infra-preview.yml`, `infra-apply-dev.yml`, `app-cd-dev.yml`: written correctly, will
  not run successfully today — they require `AZURE_CLIENT_ID`/`AZURE_TENANT_ID`/
  `AZURE_SUBSCRIPTION_ID`/`PULUMI_ACCESS_TOKEN` repo secrets that don't exist, an AKS
  cluster to deploy to, and (for `app-cd-dev.yml`) a real ACR
- **Not scaffolded at all (explicit MVP-fast deferral):** `infra-apply-prod.yml`,
  `app-cd-prod.yml`, `ops-drift-detection.yml`, GitOps controller (§12.9 Phase 2)

### §13 Observability — Live (app-level), Scaffolded/absent (cloud-level)
- Structured JSON logs with `trace_id` correlation propagated across service boundaries
  (`cani_shared.logging`, `cani_shared.middleware.TraceIdMiddleware`)
- Unhandled exceptions now log a structured, trace_id-correlated `request_failed` event
  before Starlette returns its generic (non-leaking) 500 — added this pass, see below
- Ingestion stage events (`stage_completed`, `job_retry_scheduled`, `job_dead_lettered`)
  with owner-id hashing (never raw `owner_user_id` in logs)
- **Not implemented:** Application Insights, Container Insights, Azure Monitor alert
  rules, dashboards (§13.6–§13.9) — all require a live subscription. No metrics
  endpoint/counters exist yet, only structured log events.

### §14 Security & compliance — Live (app-level), partial
- Fail-closed ownership enforcement (structural, not convention) — see §9 above
- CSRF (double-submit cookie) on session-authenticated state-changing hub-api endpoints
- Upload validation: content-type allowlist, size cap, magic-byte verification
  (`docs_api_app/uploads.py`)
- **Fail-fast config validation added this pass:** `CANI_TOKEN_SIGNING_SECRET` and
  `CANI_SESSION_SECRET` must be ≥32 characters or the app refuses to start
  (`cani_shared/config.py`) — closes a real "insecure default" gap where an env file with
  the secret keys present-but-empty (exactly what a naive `cp .env.example .env` produces)
  previously passed validation and ran with a forgeable JWT signing key
- Secret scanning now runs in CI (`gitleaks-action`, `.gitleaks.toml`)
- **Not implemented:** malware scanning (§8.11/§14.9), rate limiting (§14.8), real Entra
  External ID, session/token revocation on entitlement change, customer-managed keys,
  most of the documented policy set (only 2 of the "deny public network access" built-in
  policies are wired in `infra/modules/security.py` — explicitly noted as a
  representative-not-complete example in that file's docstring)

### §15 Cost management — Not implemented (needs live subscription)
- Budgets, alerts, cost dashboards, tag compliance checks all require a real Azure
  subscription and billing data. `k8s/overlays/dev` does reduce stateless-service replica
  counts vs. `k8s/base` as a cost-conscious default (§15.7), but that's the only cost
  control that exists without live infra.

### §16 Roadmap & phasing — On track for Phase 1 exit criteria
- Milestone A ("upload-to-answer path works end-to-end... no known cross-user access path
  in validation tests") is met and covered by automated tests
- Milestone B/C (operational readiness, production launch readiness) are blocked on the
  items in "Production blockers" below

## Production blockers (require live Azure access)

These cannot be closed from this environment — they are hard blockers for anything beyond
local dev, not implementation gaps:

1. **Azure subscription access** — nothing in `infra/` has been applied. No resource
   groups, networking, Key Vault, Postgres Flexible Server, Storage account, or ACR exist.
2. **AKS cluster** — `k8s/` manifests have never been applied anywhere. KEDA and the Key
   Vault CSI driver add-ons are referenced but not installed anywhere.
3. **Entra External ID tenant** — no tenant/app registration exists; auth runs on the
   dev-mode stub IdP only.
4. **Pulumi state backend + OIDC federated credentials** — `infra-preview.yml` and
   `infra-apply-dev.yml` cannot authenticate to Azure without these being configured as
   repo/environment secrets.
5. **Azure Monitor / Log Analytics / Application Insights** — no cloud observability
   exists; only local structured logs.
6. **Cost budgets/alerts** — need a live subscription and billing data to configure.

## Recommended next 2 sprints

**Sprint 1 — unblock live infrastructure (priority: highest)**
1. Get Azure subscription access into an environment that can run `pulumi up` (P0 — every
   other blocker is downstream of this)
2. Run the one-time management-group bootstrap (§6.6: elevate access, interactive
   `pulumi up` for `infra/platform`) — P0
3. Apply `infra/platform` then `infra/workload` to `dev`; wire the OIDC federated
   credentials `infra-preview.yml`/`infra-apply-dev.yml` already expect — P0
4. Stand up an Entra External ID tenant + app registration; replace `hub-api`'s dev-login
   route with the real OIDC callback (isolated change, downstream token
   validation/entitlement code does not change) — P1
5. Apply `k8s/` manifests to the new AKS cluster; get `app-cd-dev.yml` actually deploying
   — P1
6. Implement entitlement-revocation session invalidation (§7.7 gap noted above) — P1

**Sprint 2 — operational readiness (priority: high, unblocked once Sprint 1 lands)**
1. Application Insights + Container Insights wiring; at minimum the P1/P2 alert set from
   §13.8 (elevated 5xx rate, retrieval latency SLO breach, ingestion dead-letter growth,
   node not-ready) — P1
2. Budget alerts at the 50/75/90/100% thresholds from §15.3 — P1
3. Backup/restore validation: Postgres PITR, Qdrant snapshot-to-blob, one real restore
   drill (§9.10, §14.13) — P1
4. Malware scanning on upload before it reaches extraction (§8.11) — P2
5. Rate limiting on public endpoints (§14.8) — P2
6. Complete the deferred baseline policy set in `infra/modules/security.py` (required
   tags, allowed locations, TLS enforcement, diagnostic-settings deploy-if-not-exists)
   — P2
