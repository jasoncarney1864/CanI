# 21 — Documents page management, original download, and AI-generated documents

**Status:** Approved spec, ready for implementation
**Date:** 2026-08-18
**Author:** Architecture pass (Claude Fable 5); implementation target: Sonnet 5
**Scope confirmation:** Problem 3 confirmed with Jason as option (b) — the AI exports the
current grounded answer as a document artifact that appears on the Documents page
alongside uploads. In-app authoring (rich text editor) is explicitly out of scope.

This spec is grounded in the code as of this date, not in `docs/` prose. Where the two
disagree (e.g. docs mention Azure AI Search-style retrieval; the code uses Qdrant), the
code wins. Every file path and symbol named below was read during the architecture pass.

---

## 0. Ground truth — what the codebase actually does today

Read these before implementing; the design below assumes them.

| Concern | Where | Current behavior |
|---|---|---|
| Documents page | `apps/web/components/DocumentsView.tsx` | Read-only list: title + spoke + status badge, 3s polling while ingesting, manual Refresh. **No sort, filter, or delete UI exists at all** — nothing is "dead"; the affordances were never built. |
| List endpoint | `apps/docs-api/docs_api_app/main.py` `GET /documents` | Owner-scoped, optional `spoke` param only, hardcoded `ORDER BY created_at DESC`, returns a **bare JSON array**, no pagination. |
| List query | `cani_shared/db/repositories.py::list_documents` | Two static queries (with/without spoke). |
| Delete | — | **No DELETE endpoint anywhere** (docs-api, web proxy, UI). `OwnerScopedQdrant` has no delete method. `PublicLawQdrant.delete_points` exists as a pattern (`cani_shared/vector/public_law_client.py`). |
| Upload | docs-api `POST /documents` | Validates (`docs_api_app/uploads.py`, 25 MB cap, pdf/jpeg/png/zip magic bytes), sha256 dedupe per owner, **stores raw bytes to blob before ingestion**, creates document + version + ingestion job. |
| Spoke on upload | `apps/web/app/api/documents/route.ts` `POST` | **BUG:** `UploadView.tsx` sends a `spoke` form field, but the proxy rebuilds the multipart body with only `file` — the spoke is silently dropped and every upload lands in `General`. This is why spoke "filtering" appears broken: docs uploaded under Legal/Health/Finance never show up in those spokes. |
| Originals persisted? | docs-api upload path + `cani_shared/blob.py` | **Yes.** Originals go to container `raw-documents` at `{owner_user_id}/{document_id}/{document_version_id}/original.{ext}`; `document_versions.blob_uri` records the path (`NOT NULL` since migration 0001). Zip fan-out children get their own originals (`ingestion_worker_app/pipeline.py::_unpack_archive_job`). Blobs are immutable (no overwrite); ingestion only reads them. **No download endpoint or UI exists.** |
| Ingestion | `ingestion_worker_app/worker.py` + `pipeline.py` | Polls `ingestion_jobs` via `SELECT … FOR UPDATE SKIP LOCKED`; scan → extract → (LLM title gen) → chunk → embed → Qdrant upsert + `chunk_manifests` rows. |
| Extractor | `cani_shared/providers/extractor.py` | PDF native via pypdf, OCR fallback via Document Intelligence. **No text/markdown path.** |
| Conversation | `apps/web/components/AppShell.tsx` / `ConversationPane.tsx` | Single-turn: one `RetrievalAnswer` in state, no history, question text not retained after ask. |
| Auth pattern for new routes | `apps/web/lib/backendAuth.ts::mintAccessToken` | Every proxy route mints a docs-api bearer from the hub session; tokens never reach client JS. |
| Deletion design intent | `docs/09-data-model-and-storage.md` §9.9 | Tombstone job → async deleter removes vectors, blobs, metadata in controlled order → completion audit event. This spec implements exactly that. |
| Consumers of `GET /documents` | grep of repo | Only `apps/web` and `tests/integration/*`. No other consumer — the response-shape change in §1.2 is safe. |

**Problem 2 verdict:** originals ARE retained for every document ever ingested (the blob
write happens synchronously in the upload request, before any processing). No backfill or
migration is needed. The gap is purely the missing download endpoint + UI. Edge case to
handle: a blob manually deleted out-of-band must produce a clean 404, not a 500.

---

## 1. Problem 1 — Documents page: sort, filter, delete

### 1.1 Diagnosis

Root cause is absence, not breakage: no backend list parameters beyond `spoke`, no delete
endpoint, no frontend affordances. Compounding it, the spoke-forwarding bug (§0) makes
the one filter that does exist appear broken. Fix = one bug fix + new API surface + new
UI + an async deletion pipeline.

### 1.2 API contract — list (revised `GET /documents`, docs-api)

Query parameters (all optional):

| Param | Type | Semantics |
|---|---|---|
| `spoke` | `General\|Legal\|Health\|Finance` | Exact match (existing behavior, kept). Invalid value → 400. |
| `status` | comma-separated `IngestionStage` values | `current_status IN (…)`. Unknown value → 400. |
| `origin` | `uploaded\|generated` | Exact match (new column, §4). |
| `q` | string ≤ 200 chars | Case-insensitive substring on title: `lower(title) LIKE '%' \|\| lower(%s) \|\| '%'`. Escape `%`/`_` in the input. |
| `sort` | `created_at\|updated_at\|title` | Default `created_at`. Whitelist-mapped to a column expression server-side (`title` → `lower(title)`); **never interpolate user input into ORDER BY**. |
| `order` | `asc\|desc` | Default `desc`. |
| `limit` | int 1–200 | Default 50. |
| `offset` | int ≥ 0 | Default 0. |

Response — **envelope replaces the bare array** (breaking; consumers updated in §6/§8):

```json
{
  "items": [ { …Document, "origin": "uploaded" } ],
  "total": 123,
  "limit": 50,
  "offset": 0
}
```

New pydantic model in `cani_shared/models.py`:

```python
class DocumentListResponse(BaseModel):
    items: list[Document]
    total: int
    limit: int
    offset: int
```

Secondary sort is always `document_id` in the same direction, for a stable order under
ties. All predicates additionally require `deleted_at IS NULL` (§1.4).

### 1.3 Repository change

Replace `list_documents` in `cani_shared/db/repositories.py`:

```python
def list_documents(
    conn, owner_user_id, *,
    spoke: str | None = None,
    statuses: list[str] | None = None,
    origin: str | None = None,
    title_query: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Document], int]:  # (page items, total matching count)
```

Build the WHERE clause from parameterized predicates; run `SELECT *` with
ORDER BY/LIMIT/OFFSET and a second `SELECT count(*)` with the same predicates. Sort
whitelist: `{"created_at": "created_at", "updated_at": "updated_at", "title": "lower(title)"}`
— raise `ValueError` on anything else (docs-api maps to 400). Keep the mandatory
`owner_user_id` first-parameter convention documented at the top of the file.

### 1.4 API contract — delete (`DELETE /documents/{document_id}`, docs-api)

Per docs/09 §9.9: tombstone synchronously, clean up asynchronously.

Request: no body. Auth: same `get_principal` + `require_docs_entitlement` dependencies as
every other route.

Behavior:

1. `get_document(conn, principal.user_id, document_id)` — if absent (not owned, never
   existed, or already hard-deleted) → **404** `{"detail": "document not found"}`
   (uniform, no cross-owner existence leak, §9.8).
2. If `deleted_at` is already set → **202** (idempotent; do not enqueue a second job).
3. Otherwise, in one transaction:
   - `UPDATE documents SET deleted_at = now(), updated_at = now() WHERE owner_user_id = %s AND document_id = %s`
   - Cancel pending ingestion: `UPDATE ingestion_jobs SET status = 'cancelled' WHERE owner_user_id = %s AND status IN ('queued','retry_pending') AND document_version_id IN (SELECT document_version_id FROM document_versions WHERE owner_user_id = %s AND document_id = %s)` — the claim query already only claims `queued`/`retry_pending`, so `cancelled` is never picked up.
   - Insert a `deletion_jobs` row (schema in §4), status `queued`.
   - `record_audit_event(event_type="document_delete_requested", actor_user_id=principal.user_id, detail={"document_id": …})`
4. Response: **202** `{"document_id": "...", "status": "delete_pending"}`.

Once `deleted_at` is set, the document disappears from list/get/text/download/dedupe
(all those queries gain `AND deleted_at IS NULL` — see §4). A duplicate re-upload of the
same file therefore creates a fresh document while cleanup proceeds, which is correct.

### 1.5 Qdrant delete method

Add to `OwnerScopedQdrant` (`cani_shared/vector/qdrant_client.py`), matching the
fail-closed guard discipline of `search`/`chunks_for_document`:

```python
def delete_document_points(self, *, owner_user_id: str, document_id: str) -> None:
    if not owner_user_id: raise MissingOwnerFilterError(...)
    if not document_id: raise MissingOwnerFilterError(...)
    self._client.delete(
        collection_name=self._collection,
        points_selector=qmodels.FilterSelector(filter=qmodels.Filter(must=[
            qmodels.FieldCondition(key="owner_user_id", match=qmodels.MatchValue(value=owner_user_id)),
            qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=document_id)),
        ])),
    )
```

Delete-by-filter is idempotent (deleting zero points succeeds). Confirm the
`FilterSelector` name against the pinned qdrant-client 1.9.x before use;
`PublicLawQdrant.delete_points` is the in-repo reference for the delete call shape.

### 1.6 Blob deletion helper

Add to `BlobStore` (`cani_shared/blob.py`):

```python
def delete_prefix(self, *, container: str, prefix: str) -> int:
    """Delete every blob under prefix; returns count. Missing blobs are not errors."""
```

Implementation: `container_client.list_blobs(name_starts_with=prefix)` then
`delete_blob(name)` each, swallowing `ResourceNotFoundError`. The deletion worker calls
it for prefix `f"{owner_user_id}/{document_id}/"` in all three document containers
(`raw-documents`, `extracted-text`, `ingestion-artifacts`) — today only `raw-documents`
is populated for user docs, but prefix-deleting all three is future-proof and free.

### 1.7 Deletion worker

Extend the existing poller (`ingestion_worker_app/worker.py`) rather than adding a new
deployable — same rationale as §8.10 (the jobs table is the queue).

New repo functions (same SKIP LOCKED pattern as `claim_next_ingestion_job`):
`claim_next_deletion_job(conn) -> DeletionJob | None`,
`finish_deletion_job(conn, owner_user_id, deletion_job_id, *, status, error_detail=None)`.
New pydantic model `DeletionJob` mirroring the table.

Loop change in `run_forever`: each iteration, first try an ingestion job (unchanged); if
none, try a deletion job; if neither, sleep. New module
`ingestion_worker_app/deletion.py::process_deletion(conn, job, *, blob_store, qdrant)`:

1. **Guard:** if any `ingestion_jobs` row for this document is `status = 'processing'`,
   raise a retryable error (job goes back to `queued` with attempt_count bumped; retry
   with the existing backoff). This prevents racing a mid-flight ingestion that would
   re-insert chunks after we delete them.
2. `qdrant.delete_document_points(owner_user_id=…, document_id=…)`
3. `blob_store.delete_prefix(...)` for the three containers (§1.6).
4. One transaction, in FK-safe order:
   `DELETE FROM chunk_manifests WHERE owner_user_id=%s AND document_id=%s;`
   `DELETE FROM ingestion_jobs WHERE owner_user_id=%s AND document_version_id IN (SELECT document_version_id FROM document_versions WHERE owner_user_id=%s AND document_id=%s);`
   `DELETE FROM document_versions WHERE owner_user_id=%s AND document_id=%s;`
   `DELETE FROM documents WHERE owner_user_id=%s AND document_id=%s;`
5. Mark job `done`; `record_audit_event("document_deleted", …, detail={"document_id", "chunks_deleted", "blobs_deleted"})`.

Failure handling mirrors `handle_job_failure`: cap at 5 attempts, then status `failed` +
audit event `document_delete_failed`. The document stays tombstoned (invisible to the
user) — a failed cleanup is an ops concern, not a user-visible one. Add a short runbook
note (`runbooks/`) for re-queueing failed deletion jobs.

Steps 2–4 are each idempotent, so a crash mid-job and re-claim is safe (at-least-once).

**Single-worker invariant (must be stated in code, not just here):** the step-1 guard is
a check-then-act and is only race-free because one worker process drains both queues in
a single loop — an ingestion job cannot start while a deletion job for the same document
is being processed, and vice versa. If the worker is ever scaled to multiple replicas,
the guard has a TOCTOU gap: replica A can pass the "no processing ingestion job" check
while replica B claims one, and B's late chunk upserts land after A's Qdrant delete —
resurrected orphan vectors for a deleted document. Put this as a comment directly on the
guard in `deletion.py` (this codebase's comments cite the incident/risk that motivated
them — match that), so a future "add a second worker replica" change can't quietly
reintroduce the race. The multi-replica fix, when needed: take a per-document advisory
lock (`pg_advisory_xact_lock(hashtext(document_id::text))`) in both `process_job` and
`process_deletion`.

### 1.8 Web proxy changes (`apps/web/app/api/documents/…`)

- **`route.ts` GET:** forward all of `spoke,status,origin,q,sort,order,limit,offset`
  verbatim from `request.url` searchParams to the upstream URL; type the response as the
  new envelope.
- **`route.ts` POST (bug fix):** forward the `spoke` field —
  `const spoke = form.get("spoke"); if (typeof spoke === "string") upstreamForm.append("spoke", spoke);`
- **New `[id]/route.ts`:** `DELETE` handler — mint token, `fetch(`${DOCS_API_URL}/documents/${id}`, {method:"DELETE", …})`,
  map 404→404, other non-2xx→502, else pass the 202 JSON through. Same
  `BackendError`/`UNREACHABLE_BODY` handling as the existing routes.

### 1.9 Frontend — `DocumentsView.tsx` rework

State additions (stay with `useState`; no new state library):

```ts
const [q, setQ] = useState("");                       // debounced 300ms into effectiveQ
const [statusFilter, setStatusFilter] = useState<DocumentStatus | "all">("all");
const [sort, setSort] = useState<"created_at"|"updated_at"|"title">("created_at");
const [order, setOrder] = useState<"asc"|"desc">("desc");
const [page, setPage] = useState(0);                  // offset = page * PAGE_SIZE (50)
const [total, setTotal] = useState(0);
const [deleting, setDeleting] = useState<Set<string>>(new Set());
```

`load()` builds the query string from current state + the existing `spoke` prop and reads
the envelope (`data.items`, `data.total`). Changing any filter/sort resets `page` to 0.
The existing 3s poll loop is kept and simply re-invokes `load()` with current params, so
status transitions update in place; polling still stops when nothing on the current page
is in a non-terminal stage.

UI (toolbar above the list): search input, status `<select>` (All + the 8 stages), sort
`<select>` (Newest / Oldest / Recently updated / Title A–Z — these map to sort+order
pairs), and pager (`‹ Prev`, `page X of ⌈total/50⌉`, `Next ›`) shown only when
`total > 50`. Row additions: a Download action (§2.3) and a Delete action.

Delete flow: button → inline confirm state on the row ("Delete '<title>'? This removes
it from your library and from answers. [Delete] [Cancel]") → `fetch(`/api/documents/${id}`, {method:"DELETE"})`
→ on 202 remove the row optimistically, add to `deleting` guard set, then `load()`. On
error, restore and show the row-level error. For `unpacked` archive parents the confirm
copy must state the non-cascade behavior **in the confirmation body itself, not a
tooltip or fine print** — e.g. "Delete 'paperwork.zip'? The documents extracted from
this archive (they appear separately in this list) will NOT be deleted." This is a
genuine surprise-the-user risk; make it unmissable at the moment of confirmation.

Also render an "AI" origin badge on rows with `origin === "generated"` (§3).

`lib/types.ts`: add `origin: "uploaded" | "generated"` to `DocumentMeta`; add
`DocumentListResponse`.

### 1.10 Performance notes

- Filtering/sorting/pagination are **server-side** from day one — the client never holds
  more than one page, so a corpus of tens of thousands of rows changes nothing in the UI.
- Offset pagination is deliberate: per-owner corpora are small (personal RAG), the
  partial indexes in §4 make the scans cheap, and offset keeps the pager trivial. If an
  owner ever exceeds ~50k documents, swap to keyset pagination on
  `(sort column, document_id)` — the envelope shape already accommodates adding a
  `next_cursor` field without breaking clients.
- `q` uses un-indexed `LIKE`; fine at this scale. If it ever shows up in slow-query
  logs, add `pg_trgm` + a GIN index — do not pre-build it now.
- The 3s poll re-runs the filtered query; it already stops at terminal states, so
  steady-state load is one query per manual page view.

---

## 2. Problem 2 — Download of original documents

### 2.1 Findings (see §0)

Originals are already durably stored and referenced (`document_versions.blob_uri`,
`raw-documents` container, immutable). **No storage fix and no backfill/migration is
required.** Blob versioning + soft delete were enabled for the storage account in the
AKS era (docs/18, PR #25) — verify the same protections carry over in
`infra/container-apps/` during implementation (flagged in Open Questions).

### 2.2 API — `GET /documents/{document_id}/original` (docs-api)

1. Ownership + tombstone check via `get_document` → 404 if absent/deleted.
2. New repo fn `get_latest_document_version(conn, owner_user_id, document_id) -> DocumentVersion | None`
   — `ORDER BY created_at DESC LIMIT 1` (the `created_at` column is added in §4; every
   existing document has exactly one version, so backfilled `now()` ordering is harmless).
   No version row → 404.
3. `blob_store.download(version.blob_uri)` — catch blob-not-found (Azure
   `ResourceNotFoundError`) → 404 `{"detail": "original file is no longer available"}`.
   The existing `download` retry loop retries transient faults already; do not retry 404s
   (make `download` re-raise `ResourceNotFoundError` immediately — small change, keep the
   backoff for everything else).
4. Return `fastapi.Response(content=raw, media_type=document.source_type, headers={"Content-Disposition": …})`.
   In-memory bytes are fine: uploads are capped at 25 MB (`MAX_UPLOAD_BYTES`), the same
   bound the upload path already accepts into memory.

Filename: `{sanitize(document.title)}.{ext}` where `ext` is the suffix of the blob path
(`original.pdf` → `pdf`). Sanitizer (new helper next to `uploads.py`): strip control
chars, `\/ : * ? " < > |`, collapse whitespace, cap 120 chars, fallback `"document"`.
Emit both `filename="…"` (ASCII-fallback) and `filename*=UTF-8''…` (RFC 5987
percent-encoded) parameters.

### 2.3 Web proxy + UI

New `apps/web/app/api/documents/[id]/original/route.ts` `GET`: mint token, fetch
upstream, and stream through:

```ts
return new NextResponse(upstream.body, { status: 200, headers: {
  "content-type": upstream.headers.get("content-type") ?? "application/octet-stream",
  "content-disposition": upstream.headers.get("content-disposition") ?? "attachment",
  "cache-control": "no-store",
}});
```

(404/other errors map to JSON errors as in the `text` route.)

UI: in each `DocumentsView` row, a download action rendered as a plain anchor —
`<a href={`/api/documents/${doc.document_id}/original`} download>` — same-origin cookie
auth means no JS needed. Render it for every non-`failed` document (failed docs still
have their original stored — scan-blocked malware included — so **hide the affordance
for `failed` docs**: re-serving a malware-flagged file is the one case we should not
make one click away. See Open Questions.)

### 2.4 Retention policy

Originals are the product; retain indefinitely, deleted only by the §1 deletion
workflow (which permanently removes them, subject to the storage account's blob
soft-delete window as the accidental-deletion safety net). No lifecycle tiering now;
`docs/09` §9.12 Q1 (cool/archive tiering) remains open and is unaffected by this spec.

---

## 3. Problem 3 — AI-generated document artifacts (confirmed scope: option b)

### 3.1 Concept

A "Save as document" action on the current grounded answer. The client composes a
Markdown rendering of the Q&A; docs-api persists it as a first-class document
(`origin = 'generated'`, `source_type = 'text/markdown'`) whose *original* is a real
`.md` blob in `raw-documents` — so Problem 2's download endpoint works on it unchanged —
and which flows through the ordinary ingestion pipeline, so it is chunked, embedded, and
indexed exactly like an upload and appears on the Documents page with live status.

There is no conversation persistence today (single-answer state in `AppShell`), so the
export unit is the current answer, not a transcript. That is the confirmed scope.

### 3.2 Data model

Covered by migration 0006 (§4): `documents.origin` (`'uploaded' | 'generated'`),
`documents.generated_from JSONB` (provenance; null for uploads). `create_document` gains
keyword args `origin: str = "uploaded"` and `generated_from: dict | None = None`.
`Document` pydantic model and the TS `DocumentMeta` gain `origin`. `generated_from` is
intentionally **not** included in the list response (keeps pages lean); it is returned by
`GET /documents/{id}` (additive field on the existing response).

### 3.3 API — `POST /documents/generated` (docs-api)

```python
class ProvenanceCitation(BaseModel):
    chunk_id: str
    document_id: str | None = None
    document_title: str | None = None
    citation_ref: str | None = None       # law citations, e.g. "NRS 116.31065"

class GeneratedDocumentRequest(BaseModel):
    title: str | None = None              # ≤ 200 chars
    spoke: str = "General"                # validated against DocumentSpoke like upload
    markdown: str                         # 1 byte .. 1 MiB (UTF-8 encoded length)
    provenance: Provenance                # question ≤ 2000 chars, model_id | None,
                                          # citations: list[ProvenanceCitation] ≤ 50
```

Flow (mirrors `upload_document` deliberately — same route file, same dependencies):

1. Validate spoke, sizes; 400 with a human-readable `detail` on violation (the web proxy
   already surfaces `detail` verbatim for 400s).
2. Compose the stored file: YAML front matter (`title`, `generated_at` ISO-8601 UTC,
   `question`, `model_id`, `citations` as `chunk_id`/`citation_ref` pairs) + blank line +
   `markdown`. Encode UTF-8 → `raw`.
3. `checksum = sha256(raw)`; per-owner dedupe via `get_document_by_checksum` (which now
   excludes tombstoned rows) — on hit, return the existing document like upload does.
4. `create_document(…, title=title or derived, source_type="text/markdown",
   checksum=…, spoke=…, origin="generated", generated_from=provenance_dict)`.
   Derived title: first 80 chars of the question, else `"Generated document"`.
5. Blob to `raw-documents` at the standard artifact path, artifact name `original.md`.
6. `create_document_version` + `create_ingestion_job` (unchanged functions).
7. Audit event `document_generated`. Response: the existing `UploadResponse` shape —
   `{"document_id", "document_version_id", "status": "queued"}`.

Note: `docs_api_app/uploads.py::validate_upload` is **not** touched — browser uploads
still accept only pdf/jpeg/png/zip. Markdown enters only via this endpoint.

### 3.4 Ingestion pipeline changes

- **Extractor** (`cani_shared/providers/extractor.py`, `NativeThenOcrExtractor.extract`):
  new first branch — `if content_type in ("text/markdown", "text/plain"): return
  ExtractionResult(pages=[PageText(page_number=1, text=file_bytes.decode("utf-8",
  errors="replace"))], method="native-text")`. Strip the YAML front matter block (between
  leading `---` fences) before returning, so provenance metadata isn't embedded/searched.
  `FakeExtractor` already decodes bytes; no change.
- **Title generation guard** (`ingestion_worker_app/pipeline.py`): run `generate_title`
  only when `document.origin == "uploaded"` — generated docs arrive titled and the LLM
  pass would overwrite the user-facing title.
- **Qdrant payload:** add `"origin": document.origin` to the upsert payload in
  `pipeline.py` (alongside the existing `"spoke": document.spoke`), and add `"origin"`
  to the payload index field list in `ensure_collection`. Move the payload-index creation so it runs on
  the already-exists path too (each `create_payload_index` call is wrapped in the
  existing 409-tolerant handler, so re-running it against a live collection is safe) —
  otherwise the existing production collection never gets the new index.

### 3.5 Retrieval

No retrieval change in v1: generated documents are indexed and retrievable like uploads
(they are first-class documents; that's the point). The `origin` payload field + index
exist so a later change can exclude or down-weight generated docs with a one-line
`must_not` filter if the echo-chamber effect (answers citing prior answers) proves
annoying in practice. Flagged in Open Questions — do not build the filter now.

### 3.6 Web proxy + UI

- New `apps/web/app/api/documents/generated/route.ts` `POST`: JSON passthrough with
  `mintAccessToken`, mirroring the query route's error mapping.
- `AppShell.tsx`: retain the question — add `const [lastQuestion, setLastQuestion] =
  useState<string | null>(null)` set at the top of `handleAsk`. Add
  `saveAnswerAsDocument()` that posts `{title: null, spoke: spokeMap[spoke.key],
  markdown: buildAnswerMarkdown(lastQuestion, answer), provenance: {question:
  lastQuestion, model_id: null, citations: answer.citations.map(…)}}` and surfaces
  success ("Saved — view in Documents") with a button that calls `setView("documents")`,
  or the error inline.
- New `apps/web/lib/exportAnswer.ts::buildAnswerMarkdown(question, answer)`: renders
  `# <title-ish question>`, `## Question`, `## Answer` (verdict label prefixed when
  present, `[chunk:N]` markers stripped — reuse the regex from `ConversationPane`), and
  `## Sources` as a list (document citations: `<title> (pp. X–Y)`; law citations:
  `<citation_ref> — <source_url>`). Pure function; unit-test it with vitest.
- `ConversationPane.tsx`: "Save as document" button in the answer footer, rendered when
  `answer && !loading`, wired to a new `onSaveAsDocument` prop; disable + "Saving…" while
  in flight.
- `DocumentsView.tsx`: origin badge (§1.9).

---

## 4. Data model — migration `db/migrations/0006_documents_management.sql`

```sql
-- Documents page management (docs/21): origin/provenance for generated docs,
-- tombstone delete per docs/09 §9.9, deletion job queue, version ordering.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'uploaded',
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS generated_from JSONB;

-- Partial indexes: every live-document query filters deleted_at IS NULL.
CREATE INDEX IF NOT EXISTS idx_documents_owner_live_created
    ON documents (owner_user_id, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_documents_owner_live_updated
    ON documents (owner_user_id, updated_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_documents_owner_live_title
    ON documents (owner_user_id, lower(title)) WHERE deleted_at IS NULL;

-- Version ordering for "latest version" (download endpoint). Existing rows take now();
-- harmless because every existing document has exactly one version.
ALTER TABLE document_versions
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Async deletion queue (docs/09 §9.9 "tombstone job"). No FK to documents on purpose:
-- the job's final step deletes the documents row.
CREATE TABLE IF NOT EXISTS deletion_jobs (
    deletion_job_id UUID PRIMARY KEY,
    document_id     UUID NOT NULL,
    owner_user_id   UUID NOT NULL REFERENCES users(user_id),
    status          TEXT NOT NULL DEFAULT 'queued',   -- queued|processing|done|failed
    attempt_count   INT NOT NULL DEFAULT 0,
    error_detail    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_deletion_jobs_claim ON deletion_jobs (status, created_at);
```

**Repository predicate sweep (required, same commit as the migration):** add
`AND deleted_at IS NULL` to `get_document`, `list_documents`,
`get_document_by_checksum`, and `get_document_title`. (`mark_document_status` /
`update_document_title` are worker-internal and may keep updating tombstoned rows
harmlessly.) During the tombstone→cleanup window a still-indexed chunk can surface in
retrieval with title "Untitled document" (title lookup now misses); acceptable transient
measured in seconds — do not special-case it.

Backfill: none. `origin` defaults cover existing rows; originals already exist (§2.1).

---

## 5. API surface summary

| Method & path (docs-api) | New/changed | Notes |
|---|---|---|
| `GET /documents` | changed | filter/sort/pagination params; envelope response (breaking, consumers updated) |
| `DELETE /documents/{id}` | new | 202 tombstone + async cleanup |
| `GET /documents/{id}/original` | new | streams original blob, attachment disposition |
| `POST /documents/generated` | new | persist AI answer as a document |
| `GET /documents/{id}` | additive | gains `origin`, `generated_from` |
| Web proxy `/api/documents` GET/POST | changed | param passthrough; **spoke bug fix** |
| Web proxy `/api/documents/[id]` DELETE | new | passthrough |
| Web proxy `/api/documents/[id]/original` GET | new | stream passthrough |
| Web proxy `/api/documents/generated` POST | new | passthrough |

Unchanged: `/query`, `/documents/{id}/text`, retrieval-worker endpoints, hub-api.

## 6. Frontend change summary

`DocumentsView.tsx` (toolbar, pager, delete, download, origin badge — §1.9, §2.3),
`AppShell.tsx` (lastQuestion, saveAnswerAsDocument — §3.6), `ConversationPane.tsx`
(save button), new `lib/exportAnswer.ts`, `lib/types.ts` (origin, envelope type), four
proxy route files under `app/api/documents/`.

## 7. Migration considerations for existing data

- Existing documents: `origin='uploaded'` via column default; originals already in blob
  storage → download works retroactively with zero backfill.
- Existing Qdrant points lack the `origin` payload key: they are uploads by definition,
  and nothing filters on `origin` in v1, so no re-index. If the retrieval filter is ever
  built, treat missing key as `uploaded`.
- Existing collection gets the `origin` payload index via the §3.4 ensure_collection
  change (idempotent create on startup).
- The list-response envelope is the only breaking contract change; both in-repo
  consumers (web proxy, integration tests) are updated in this work. The "no other
  consumers" claim rests on a repo grep — it cannot see personal scripts, cron jobs, or
  anything outside this repo that hits docs-api directly. **Jason: personally confirm
  nothing out-of-repo calls `GET /documents` before Phase 1 ships.** (docs-api is
  private in prod — only the web app reaches it — so exposure is limited to anything
  running inside the environment or against local compose.)

## 8. Test plan

Existing tests touched:
- `tests/integration/test_e2e_flow.py` line ~104 (`documents = docs_client.get("/documents", …).json()`)
  now reads `.json()["items"]`. The other `/documents` references (upload POSTs, single
  GETs, status-code asserts in `test_revocation.py`, `test_isolation.py`,
  `test_public_law_retrieval.py`) are shape-compatible.

New tests (follow existing patterns; `httpx`, not curl — CLAUDE.md):
- **Unit:** sort/filter whitelist validation (400 paths); filename sanitizer; extractor
  markdown branch incl. front-matter stripping; `GeneratedDocumentRequest` size caps;
  vitest for `buildAnswerMarkdown` and the DocumentsView toolbar query-string builder.
- **Integration:** (1) list envelope + spoke/status/q/sort/pagination behavior, and
  spoke round-trip through the web-proxy bug fix; (2) delete: 202 → doc vanishes from
  list/get/text → deletion job completes → re-upload of same bytes succeeds (dedupe
  cleared); ownership: user B deleting user A's doc → 404; (3) download: bytes equal
  uploaded bytes, content-type + disposition headers, 404 for missing blob; (4)
  generated: POST → appears in list with `origin=generated` → reaches `indexed` → `/text`
  returns chunks without front matter → download returns the `.md`.

CI gate order to match locally: gitleaks → `ruff check` → `ruff format --check` →
`pytest tests/unit` → integration (compose). Line length 110; comments explain *why*.

## 9. Phased implementation plan (execute in order; each phase leaves CI green)

**Phase 0 — schema + fixes (no behavior change visible yet)**
1. Add `db/migrations/0006_documents_management.sql` (§4).
2. `cani_shared/models.py`: `Document.origin` (default `"uploaded"`), `DeletionJob`,
   `DocumentListResponse`; repositories predicate sweep (§4) and `create_document`
   origin/generated_from kwargs.
3. Web proxy POST spoke-forwarding fix (§1.8). Integration-test the spoke round trip.

**Phase 1 — list API + Documents page toolbar**
4. `list_documents` rewrite (§1.3); docs-api `GET /documents` params + envelope (§1.2);
   proxy GET passthrough; update `test_e2e_flow.py`.
5. `DocumentsView` toolbar/pager (§1.9); `lib/types.ts`. New integration + vitest tests.

**Phase 2 — delete**
6. **GATE (hard blocker, do first):** verify blob soft-delete + versioning are active on
   the *live* storage account before writing any deletion code — see Open Question #6
   for the audit findings and the exact `az` command. Do not proceed past this step
   until the command output confirms both policies enabled; a delete pipeline against
   an unprotected account turns any bug or mis-click into unrecoverable loss of a
   user's originals.
7. `OwnerScopedQdrant.delete_document_points` (§1.5); `BlobStore.delete_prefix` (§1.6).
8. Deletion job repo fns + `ingestion_worker_app/deletion.py` + worker loop (§1.7),
   including the single-worker-invariant comment on the race guard.
9. docs-api `DELETE /documents/{id}` (§1.4); proxy `[id]/route.ts`; UI delete + confirm.
10. Integration tests (delete suite); runbook note for failed deletion jobs.

**Phase 3 — download**
11. `get_latest_document_version`; `BlobStore.download` re-raises not-found immediately
    (§2.2); docs-api `GET /documents/{id}/original`; filename sanitizer + unit tests.
12. Proxy stream route; UI download anchor (hidden for `failed`). Integration tests.

**Phase 4 — generated documents**
13. Extractor markdown branch + front-matter strip; pipeline title-gen guard; payload
    `origin` + index-on-existing-collection change (§3.4). Unit tests.
14. docs-api `POST /documents/generated` (§3.3) + audit event; proxy route.
15. `lib/exportAnswer.ts` + vitest; `AppShell`/`ConversationPane` wiring; origin badge.
16. Integration test (generated suite).

**Phase 5 — closeout**
17. Full local gate (`python scripts/run_local_tests.py`), `.env.example` untouched (no
    new settings introduced), update `docs/implementation-status.md` with a dated entry
    referencing this doc.

## 10. Open questions & flagged trade-offs (decisions made, revisit if wrong)

1. **Generated-doc echo chamber** — generated docs are indexed and retrievable (v1
   decision: first-class means first-class). If answers start citing prior answers in a
   confusing loop, add a `must_not origin=generated` retrieval filter or a per-query
   toggle; the payload field + index are already in place. *Confidence: medium.*
2. **Archive parent deletion does not cascade to children** — children are independent
   documents (own checksums, own jobs); cascading would surprise a user who deleted "just
   the zip". UI copy states this. If users expect cascade, add an opt-in
   `?cascade=children` later (children are discoverable only by checksum today — a
   `parent_document_id` column would be the real fix, out of scope). *Confidence: medium.*
3. **Download hidden for `failed` docs** — deliberate, because `failed` includes
   malware-blocked uploads and one-click re-serving of flagged bytes is a bad default.
   Cost: OCR-unsupported failures also lose the affordance. Alternative: store a
   `failure_class` and only hide malware. Not built now. *Confidence: medium-low; cheap
   to revisit.*
4. **Hard delete (rows removed) vs. audit retention** — per docs/09 §9.9 the metadata
   rows are removed and the audit trail lives in `audit_events`
   (`document_delete_requested`/`document_deleted` with document_id). If compliance ever
   needs richer tombstones, keep the `documents` row instead of the final DELETE — the
   dedupe/list predicates already exclude tombstoned rows either way. *Confidence: high.*
5. **Offset vs. keyset pagination** — offset chosen for simplicity at personal-corpus
   scale; upgrade path documented (§1.10). *Confidence: high.*
6. **Verify blob soft-delete/versioning on the LIVE storage account — hard blocker on
   Phase 2 (see plan step 6).** Audit findings (2026-08-18): the protections ARE
   codified in IaC — `infra/modules/data_services.py` lines 154–165 set
   `is_versioning_enabled=True`, blob `delete_retention_policy` 7 days, and container
   delete retention 7 days (window deliberately matched to Postgres PITR). **But** the
   current deploy target `infra/container-apps/main.bicep` does not define the storage
   account at all — it only references an existing one by name
   (`storageAccountName = 'cani6ada34dffd'`, line 124), while the Pulumi naming comment
   in `data_services.py` references a differently-hashed account
   (`cani9820b2c229`) and a subscription migration is a known loose end
   (`docs/implementation-status.md` follow-ups). So it is **not proven** that the
   account production actually uses is the one Pulumi hardened. Live verification (an
   Azure MCP check from the architecture session found no logged-in subscription, so
   this must be run with real credentials):

   ```
   az storage account blob-service-properties show --account-name cani6ada34dffd
   az storage account show --account-name cani6ada34dffd \
       --query "{tls:minimumTlsVersion, blobPublicAccess:allowBlobPublicAccess, publicNetworkAccess:publicNetworkAccess, networkRules:networkRuleSet, encryption:encryption.keySource, sku:sku.name}"
   ```

   Pull the **full** output, not just the soft-delete fields: if the name mismatch is
   real, every protection Pulumi configured on the account is in question, not just
   soft-delete — `data_services.py` also sets TLS 1.2 minimum,
   `allow_blob_public_access=False`, and `public_network_access` disabled, so compare
   the second command's output against those lines too and reconcile any drift while
   you're in there, rather than rediscovering it one property at a time later.

   For the Phase 2 gate specifically: versioning and both delete-retention policies
   must show `enabled: true` (7-day window expected). If they don't,
   enable them (`az storage account blob-service-properties update --account-name
   cani6ada34dffd --enable-versioning true --enable-delete-retention true
   --delete-retention-days 7 --enable-container-delete-retention true
   --container-delete-retention-days 7`) and codify the setting in
   `infra/container-apps/main.bicep` before any deletion code ships.
7. **qdrant-client 1.9.x delete API name** — §1.5 assumes `FilterSelector` exists in the
   pinned 1.9.x client (delete-by-filter has been stable since well before 1.9, but the
   exact model name should be confirmed against the installed package before coding).
