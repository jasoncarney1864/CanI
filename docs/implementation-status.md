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

## 2026-07-15 update (live dev apply — B1/B2/C1)

Sprint 1 execution (tracked in `17-sprint-1-execution-board.md`) has materially changed
what is Live vs Scaffolded since this doc was written:

- **Platform stack applied to dev** (B1): management groups, hub VNet, central Log
  Analytics, shared ACR (Premium — required once public network access is disabled),
  platform Key Vault.
- **Workload stack applied to dev** (B2): AKS cluster, Postgres Flexible Server
  (delegated subnet + private DNS + public access disabled, admin password held as
  encrypted Pulumi config), Storage account, workload VNet peered to hub.
- **CI/manifests aligned to live resource IDs** (C1): `app-cd-dev.yml` and `k8s/`
  reference the real ACR/AKS names; OIDC federated credentials are configured as repo
  secrets (split platform/workload identities) and `infra-preview.yml` has been
  validated against them.
- **C2 (overlay apply / runtime stabilization) in progress:** images now run as non-root
  (UID 10001) with `emptyDir` tmp mounts to satisfy the strict pod security context;
  dev secrets are applied out-of-band via `scripts/apply_dev_secrets.sh` from an env
  file kept outside the repo (see `runbooks/rotate-dev-secrets.md`); schema is applied
  via `scripts/aks_apply_core_schema.sh`, which runs the repo's real `db/migrate.py`
  inside a pod. C3 (app-cd activation) not started.
- Sections §10–§12 below have been updated to match; the per-section labels are the
  source of truth for what remains scaffolded.

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

### §10 AKS cluster design — Live cluster (dev), workload rollout in progress
- Dev AKS cluster provisioned via `infra/workload` (B2 apply, 2026-07-15)
- `k8s/base` + `k8s/overlays/dev`: namespaces matching §10.2 exactly, NetworkPolicy
  deny-by-default with explicit allows, Qdrant StatefulSet with PodDisruptionBudget,
  HPA on docs-api, KEDA ScaledObject stub on ingestion-worker, Key Vault CSI
  SecretProviderClass, workload-identity service account annotations
- Runtime hardening landed for the strict pod security context: images run as non-root
  (UID 10001), `readOnlyRootFilesystem` kept with `emptyDir` tmp mounts
- **Still open:** full overlay apply as the routine deploy path (C2), KEDA and Key Vault
  CSI add-ons not yet installed (ScaledObject/SecretProviderClass will fail to apply
  until they are), workload-identity client-id annotations still placeholders — secrets
  currently arrive via `scripts/apply_dev_secrets.sh`, not the CSI driver

### §11 IaC strategy — Applied to dev
- `infra/platform` and `infra/workload` Pulumi Python projects following the exact
  project/stack split in §11.2–§11.4, with `infra/modules` component resources
  (networking, security, observability, compute-aks, data-services) per §11.7's
  recommended module families
- `infra/workload/__main__.py` consumes `infra/platform` outputs via `StackReference` —
  §11.6 contract, exercised for real by the B2 apply
- Management-group bootstrap (§6.6 elevated-access path) completed 2026-07-14; both dev
  stacks applied 2026-07-14/15 (see `17-sprint-1-execution-board.md` B1/B2 notes)
- Deterministic Azure-name generation (stable hash suffixes) added for ACR/Storage
  global-uniqueness; secret config (Postgres admin password) held encrypted in stack config
- **Still open:** `prod` stacks untouched; drift detection (§11.9) not scheduled; watch
  for portal-side drift against IaC (e.g. the storage account's public-network-access
  posture vs. the account-key connection string currently used by the app)

### §12 CI/CD strategy — Live (app CI), Scaffolded (infra CI, prod, GitOps)
- `ci.yml`: secret scan (gitleaks) → lint (`ruff check`) → format check (`ruff format
  --check`) → unit tests → docker-compose integration tests as the "dev deployment" proxy.
  **This is real and runs on every PR.**
- `infra-preview.yml` / `infra-apply-dev.yml`: OIDC federated credentials configured
  (split platform/workload identities) and preview validated against live Azure (C1)
- `app-cd-dev.yml`: aligned to live AKS/ACR IDs with a pre-deploy contract check, but
  **not yet activated** (C3) — and its post-deploy smoke check curls
  `https://dev.cani.internal/healthz`, which cannot succeed (no Ingress exists and the
  hostname doesn't resolve from a GitHub runner); replace before first activation
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

## Production blockers (updated 2026-07-15)

Original blockers 1 (subscription access), 2 (no AKS cluster), and 4 (OIDC/state backend)
are **closed** by the B1/B2/C1 applies. Still blocking anything beyond dev:

1. **Entra External ID tenant** — no tenant/app registration exists; auth runs on the
   dev-mode stub IdP only.
2. **Secrets delivery is a manual stopgap** — `scripts/apply_dev_secrets.sh` from an
   operator-held env file, using a storage account key. Target state is workload identity
   + Key Vault CSI (`k8s/base/secret-provider-class.yaml`); the exposed pre-migration
   values must be rotated per `runbooks/rotate-dev-secrets.md` §"One-time migration note".
3. **Azure Monitor / Application Insights / Container Insights** — central Log Analytics
   workspace exists (B1), but no app/container telemetry flows to it and no alert rules
   exist; only local structured logs.
4. **Cost budgets/alerts** — subscription is live and billable (private AKS, Premium ACR,
   three node pools) but no budget thresholds (§15.3) are configured yet.
5. **CD not activated** — `app-cd-dev.yml` (C3) unproven end-to-end; smoke-check step
   must be replaced first (see §12 above).

## Sprint planning

Sprint-level planning and live status now live in the execution boards, which supersede
the sprint recommendations that used to be in this file:

- `17-sprint-1-execution-board.md` — live infrastructure unblock (in progress)
- `18-sprint-2-operational-readiness-board.md` — operational readiness
