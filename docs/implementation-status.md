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
- **Real Entra External ID OIDC implemented and wired (2026-07-16, D1):** tenant
  `caniauth.onmicrosoft.com` + `cani-hub` app registration live; hub-api's
  `/auth/login` → `/auth/callback` does authorization code + PKCE with full ID-token
  validation (RS256/JWKS, audience, discovered issuer, expiry, nonce), 12 unit tests on
  the rejection paths. Outside dev, hub-api refuses to start without OIDC config.
  Verified end to end 2026-07-16: interactive browser sign-up through the live
  tenant created the first customer identity and returned the session JSON.
- dev-login stub remains for local/compose/tests only (404s outside `ENV=dev`)
- **Revocation live (2026-07-16, D2):** per-user revocation epoch (`users.auth_revoked_at`,
  migration 0002) enforced on every authenticated request — a session or access token
  with `iat <= auth_revoked_at` is rejected even while otherwise valid, so revoking a
  user kills their already-issued credentials immediately rather than waiting out the
  TTL (§7.7). Operator tool `scripts/revoke_user_access.py` (no admin HTTP endpoint until
  admin RBAC exists); verified by an integration test where a live token and session both
  die post-revocation. `suspected-cross-tenant-access.md` containment updated to use it.

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
- **NetworkPolicy now enforced (2026-07-16):** the cluster ran `networkPolicy: none`, so
  the deny-by-default objects were inert (proven: docs-api reached Qdrant freely). Enabled
  Calico in-place (`az aks update`, reconciled into IaC + Pulumi state). The policies were
  also rewritten to the real topology — they had modeled Postgres as a pod (it's external
  Azure Flexible Server) and gave the workers no egress, so enforcing them as-written would
  have caused an outage. Verified post-enablement: docs-api→Qdrant is now blocked while
  retrieval-worker→Qdrant and all auth/DNS/Postgres paths still work. Two incidental fixes
  came out of the node roll: the Qdrant PDB was `maxUnavailable: 0` (blocked all node
  drains) and the user node pools now roll in-place (`maxSurge: 0`) because regional vCPU
  quota (10) leaves no surge headroom.
- KEDA 2.14.0 live and wired (2026-07-15): a partial CRD install had left the operator
  crashlooping (`ScaledJob` informer could never sync); fixed by server-side applying the
  complete v2.14.0 CRD bundle. The ingestion-worker ScaledObject is now Ready, scaling on
  queue depth via the scoped `keda_scaler` Postgres role (SELECT on `ingestion_jobs`
  only) through the `cani-postgres-keda-auth` TriggerAuthentication
  (`k8s/base/ingestion-worker/scaling.yaml`)
- **Still open:** full overlay apply as the routine deploy path (C2);
  workload-identity client-id annotations still placeholders — the Key Vault CSI driver
  add-on is installed but SecretProviderClass values are unset, so secrets currently
  arrive via `scripts/apply_dev_secrets.sh`, not the CSI driver

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
- Public-endpoint drift reconciled (2026-07-15): live ACR and storage had been flipped
  to public access in the portal during C2 while the IaC still said Disabled — the next
  `pulumi up` would have reverted them and broken image pulls and blob access. Now an
  explicit per-stack flag (`publicDataEndpoints`, dev=true) with Disabled remaining the
  secure default; both stacks re-applied so state matches live. The flag is a documented
  dev stopgap that disappears when private endpoints + workload identity land.
- **Still open:** `prod` stacks untouched; drift detection (§11.9) not scheduled

### §12 CI/CD strategy — Live (app CI), Scaffolded (infra CI, prod, GitOps)
- `ci.yml`: secret scan (gitleaks) → lint (`ruff check`) → format check (`ruff format
  --check`) → unit tests → docker-compose integration tests as the "dev deployment" proxy.
  **This is real and runs on every PR.**
- `infra-preview.yml` / `infra-apply-dev.yml`: OIDC federated credentials configured
  (split platform/workload identities) and preview validated against live Azure (C1)
- `app-cd-dev.yml`: **live and activated** (C3, 2026-07-16). Reworked for the private
  cluster: applies the kustomize overlay via `az aks command invoke` (hosted runners
  can't reach the private API server), with a pre-deploy contract check and in-cluster
  smoke checks. Runs unattended on every `apps/**`/`db/**` push to main.
- Migrations now run in CD (2026-07-16): a gating Job built from `db/Dockerfile`
  executes `migrate.py` against the live DB **before** the app rollout, so a schema
  change can't ship behind the code that needs it. Added after D2's migration 0002 had
  to be applied by hand — the smoke check now also calls `whoami` (which queries the
  revocation column), so a missing migration fails the deploy instead of passing silently.
- **Not scaffolded at all (explicit MVP-fast deferral):** `infra-apply-prod.yml`,
  `app-cd-prod.yml`, `ops-drift-detection.yml`, GitOps controller (§12.9 Phase 2)

### §13 Observability — Live (app + cluster telemetry); alerts/dashboards pending
- Structured JSON logs with `trace_id` correlation propagated across service boundaries
  (`cani_shared.logging`, `cani_shared.middleware.TraceIdMiddleware`)
- Unhandled exceptions log a structured, trace_id-correlated `request_failed` event
  before Starlette returns its generic (non-leaking) 500
- Ingestion stage events (`stage_completed`, `job_retry_scheduled`, `job_dead_lettered`)
  with owner-id hashing (never raw `owner_user_id` in logs)
- **Application Insights — live and verified (Sprint 2 A1, 2026-07-17).** Workspace-based
  component (`infra/modules/observability.py`); all four services instrumented via the
  Azure Monitor OTel Distro (`cani_shared.telemetry`, opt-in on
  `APPLICATIONINSIGHTS_CONNECTION_STRING`, no-op locally/CI). Verified with real traffic
  against live dev: requests + dependencies from all four `cloud_RoleName`s, and a
  docs-api → retrieval-worker → Qdrant call confirmed as a **single 12-span distributed
  trace** (§13.5). Health probes excluded from tracing; `TELEMETRY_SAMPLING_RATIO` is the
  ingestion-cost lever (dev = 1.0).
- **Container Insights — live (fixed 2026-07-17 evening).** Correction: the original
  claim here was wrong — `omsagent` with AAD auth deploys agents but no Data Collection
  Rule, so nothing ever flowed (agents Running ≠ data flowing). Fixed with
  `ContainerInsightsCollection` (DCR + association named `ContainerInsightsExtension`)
  in the workload stack (PR #17).
- **Alert baseline — live and validated (Sprint 2 A2 done 2026-07-17, PR #17).** Four
  §13.8 alerts as IaC: P1 elevated 5xx (AppRequests), P2 retrieval-latency SLO (P95
  `POST /query` > 5s), P2 ingestion dead-letter (`ContainerLogV2` `job_dead_lettered` —
  container stdout is the only place that signal exists), P1 node not-ready (platform
  metric `kube_node_status_condition`, immune to log-pipeline failures and to the
  workspace daily cap). Email action group routing validated by test notification.
  Fire-in-test passed: a 47-second forced outage produced six 500s + a genuine
  dead-letter, and all three testable alerts completed the full Fired → Resolved cycle
  (`auto_mitigate` confirmed); node not-ready validated by signal + action-group test
  (cluster at the 10-core vCPU ceiling, so not tripped by breaking a node).
- **Ingestion cost controls (§15):** AKS diagnostics trimmed from `allLogs`
  (5.78 GB/day, 76% read-inclusive kube-audit, ~$400/month) to `kube-audit-admin` +
  `guard`; workspace hard cap 3 GB/day as a runaway-source circuit breaker (when hit,
  ALL workspace ingestion pauses until the daily reset — metric alerts unaffected);
  `logger_name="cani"` stops the azure.core exporter-log feedback loop that made
  AppTraces 100% self-noise.
- Known gap: psycopg is not instrumented, so Postgres calls emit no dependency spans
  (Qdrant is visible only because qdrant-client rides httpx). DB latency lives inside the
  enclosing server span only. Fix when needed: `opentelemetry-instrumentation-psycopg`.
- **Not implemented:** Azure Monitor alert rules (§13.8 — Sprint 2 A2, next) and
  dashboards (§13.9). No custom metrics endpoint/counters; metrics derive from traces
  and logs.

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
- **Not implemented:** malware scanning (§8.11/§14.9), rate limiting (§14.8),
  customer-managed keys, most of the documented policy set (only 2 of the "deny public
  network access" built-in policies are wired in `infra/modules/security.py` — explicitly
  noted as a representative-not-complete example in that file's docstring). (Real Entra
  External ID landed in D1; session/token revocation on entitlement change in D2.)

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

1. **Entra External ID tenant** — ~~closed 2026-07-16~~: `caniauth` tenant + `cani-hub`
   app registration live, OIDC flow implemented in hub-api and verified with a real
   browser sign-up (D1). Residual: a public redirect URI once ingress exists
   (localhost-only today).
2. **Secrets delivery is a manual stopgap** — `scripts/apply_dev_secrets.sh` from an
   operator-held env file, using a storage account key. Target state is workload identity
   + Key Vault CSI (`k8s/base/secret-provider-class.yaml`); the exposed pre-migration
   values must be rotated per `runbooks/rotate-dev-secrets.md` §"One-time migration note".
3. **Azure Monitor alerting** — mostly closed (Sprint 2 A2, 2026-07-17): §13.8 baseline
   of four alerts live as IaC with routing validated (see §13 above). Container
   Insights required a same-day fix (missing DCR — the A1 claim of "flowing" was wrong
   until PR #17). Residual gap: dashboards (§13.9).
4. **Cost budgets/alerts** — partially mitigated: workspace ingestion is now bounded
   (category trim + 3 GB/day hard cap after A2 recon found a 5.78 GB/day kube-audit
   leak), but subscription-level budget thresholds (§15.3) are still not configured —
   that is Sprint 2 B1.
5. **Dev OCR fallback is broken (found 2026-07-17 during A2 validation)** —
   `AZURE_DOCUMENTINTELLIGENCE_ENDPOINT` is empty in the cluster, so the extraction OCR
   fallback builds a relative URL ("No connection adapters were found") and any
   scanned/no-text-layer document dead-letters after retries. Fix: deliver the DI
   endpoint + key to cani-secrets (docs-platform namespace) via
   `scripts/apply_dev_secrets.sh`, or make an explicit skip-OCR-in-dev decision.
6. ~~CD not activated~~ — closed: `app-cd-dev.yml` activated 2026-07-16 and now gates on
   a migration Job before rollout (see §12 above).

## Sprint planning

Sprint-level planning and live status now live in the execution boards, which supersede
the sprint recommendations that used to be in this file:

- `17-sprint-1-execution-board.md` — live infrastructure unblock (in progress)
- `18-sprint-2-operational-readiness-board.md` — operational readiness
