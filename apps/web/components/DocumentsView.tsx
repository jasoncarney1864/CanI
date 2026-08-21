"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { buildDocumentsListQuery, DOCUMENTS_PAGE_SIZE } from "@/lib/documentsQuery";
import type { DocumentListResponse, DocumentMeta, DocumentStatus } from "@/lib/types";
import type { DocumentsSortField, DocumentsSortOrder } from "@/lib/documentsQuery";

// Non-terminal stages: while any document sits here, we keep polling for progress.
const IN_PROGRESS: ReadonlySet<DocumentStatus> = new Set([
  "queued",
  "unpacking",
  "extracting",
  "chunking",
  "embedding",
]);

const STATUS_LABEL: Record<DocumentStatus, string> = {
  queued: "Queued",
  unpacking: "Unpacking archive",
  extracting: "Extracting text",
  chunking: "Chunking",
  embedding: "Embedding",
  indexed: "Ready",
  unpacked: "Unpacked",
  failed: "Failed",
};

const STATUS_OPTIONS: DocumentStatus[] = [
  "queued",
  "unpacking",
  "extracting",
  "chunking",
  "embedding",
  "indexed",
  "unpacked",
  "failed",
];

// Tone drives the badge colour: in-progress (amber), ready (green), failed (red).
function tone(status: DocumentStatus): "progress" | "ready" | "failed" {
  if (status === "failed") return "failed";
  if (status === "indexed" || status === "unpacked") return "ready";
  return "progress";
}

// The sort <select> shows human labels; each maps to a sort+order pair the API expects.
const SORT_CHOICES: { value: string; label: string; sort: DocumentsSortField; order: DocumentsSortOrder }[] = [
  { value: "newest", label: "Newest", sort: "created_at", order: "desc" },
  { value: "oldest", label: "Oldest", sort: "created_at", order: "asc" },
  { value: "updated", label: "Recently updated", sort: "updated_at", order: "desc" },
  { value: "title", label: "Title A–Z", sort: "title", order: "asc" },
];

function sortChoiceValue(sort: DocumentsSortField, order: DocumentsSortOrder): string {
  return SORT_CHOICES.find((c) => c.sort === sort && c.order === order)?.value ?? "newest";
}

interface DocumentsViewProps {
  spoke: string;
}

/**
 * Documents view (A3). Lists the caller's documents (owner-scoped via the /api/documents
 * proxy) with honest ingestion status, polling while anything is still in flight so the
 * user watches queued -> extracting -> ... -> indexed without refreshing. A "failed" doc is
 * surfaced plainly (malware-blocked or OCR-unsupported), not hidden.
 *
 * Filtering, sorting, and pagination are server-side (docs/21 §1.9/§1.10) — this
 * component never holds more than one page of results.
 */
export function DocumentsView({ spoke }: DocumentsViewProps) {
  const [docs, setDocs] = useState<DocumentMeta[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [q, setQ] = useState("");
  const [effectiveQ, setEffectiveQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<DocumentStatus | "all">("all");
  const [sort, setSort] = useState<DocumentsSortField>("created_at");
  const [order, setOrder] = useState<DocumentsSortOrder>("desc");
  const [page, setPage] = useState(0);

  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Set<string>>(new Set());
  const [rowError, setRowError] = useState<{ id: string; message: string } | null>(null);
  // A poll's GET can be in flight when the user clicks delete; if it resolves after our
  // own optimistic removal + reload, it would otherwise re-add the just-deleted row until
  // the next 3s tick corrects it. Tracked in a ref (not state) so load() can read the
  // latest guard set without needing to be recreated every time it changes.
  const deletingRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    deletingRef.current = deleting;
  }, [deleting]);

  // Debounce the search box 300ms so every keystroke doesn't fire a request.
  useEffect(() => {
    const t = setTimeout(() => setEffectiveQ(q), 300);
    return () => clearTimeout(t);
  }, [q]);

  // Any change to a filter/sort (or spoke) starts back at page 0 — an old offset can
  // otherwise land past the end of a narrower result set and render an empty page.
  useEffect(() => {
    setPage(0);
  }, [spoke, effectiveQ, statusFilter, sort, order]);

  const load = useCallback(async () => {
    try {
      const qs = buildDocumentsListQuery({
        spoke,
        q: effectiveQ,
        statusFilter,
        sort,
        order,
        page,
        pageSize: DOCUMENTS_PAGE_SIZE,
      });
      const res = await fetch(`/api/documents?${qs}`, { cache: "no-store" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error ?? `Couldn't load documents (${res.status}).`);
      setError(null);
      const envelope = data as DocumentListResponse;
      setDocs(envelope.items.filter((d) => !deletingRef.current.has(d.document_id)));
      setTotal(envelope.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load documents.");
    }
  }, [spoke, effectiveQ, statusFilter, sort, order, page]);

  const handleDelete = useCallback(
    async (doc: DocumentMeta) => {
      setConfirmingId(null);
      setRowError(null);
      setDeleting((prev) => new Set(prev).add(doc.document_id));
      try {
        const res = await fetch(`/api/documents/${doc.document_id}`, { method: "DELETE" });
        if (res.status !== 202) {
          const body = await res.json().catch(() => ({}));
          throw new Error((body as { error?: string })?.error ?? `Couldn't delete '${doc.title}' (${res.status}).`);
        }
        // Remove immediately rather than waiting for the reload below to reflect it.
        setDocs((prev) => (prev ? prev.filter((d) => d.document_id !== doc.document_id) : prev));
        await load();
      } catch (e) {
        setRowError({ id: doc.document_id, message: e instanceof Error ? e.message : "Delete failed." });
      } finally {
        setDeleting((prev) => {
          const next = new Set(prev);
          next.delete(doc.document_id);
          return next;
        });
      }
    },
    [load],
  );

  // Load once, then poll every 3s while any document is still ingesting; stop when all
  // documents have reached a terminal state (indexed / unpacked / failed).
  useEffect(() => {
    let cancelled = false;
    async function tick() {
      await load();
      if (cancelled) return;
      timerRef.current = setTimeout(tick, 3000);
    }
    void tick();
    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [load]);

  // Once nothing is in progress, drop the polling loop until the next manual refresh.
  const anyInProgress = docs?.some((d) => IN_PROGRESS.has(d.current_status)) ?? false;
  useEffect(() => {
    if (!anyInProgress && timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, [anyInProgress]);

  const pageCount = Math.max(1, Math.ceil(total / DOCUMENTS_PAGE_SIZE));

  return (
    <div className="docsview">
      <div className="docsview__head">
        <p className="col-label">Documents</p>
        <button type="button" className="docsview__refresh" onClick={() => void load()}>
          Refresh
        </button>
      </div>

      <div className="docsview__toolbar">
        <input
          type="search"
          className="docsview__search"
          placeholder="Search titles…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search documents by title"
        />
        <select
          className="docsview__select"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as DocumentStatus | "all")}
          aria-label="Filter by status"
        >
          <option value="all">All statuses</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s]}
            </option>
          ))}
        </select>
        <select
          className="docsview__select"
          value={sortChoiceValue(sort, order)}
          onChange={(e) => {
            const choice = SORT_CHOICES.find((c) => c.value === e.target.value) ?? SORT_CHOICES[0];
            setSort(choice.sort);
            setOrder(choice.order);
          }}
          aria-label="Sort documents"
        >
          {SORT_CHOICES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <p className="docsview__error" role="alert">
          {error}
        </p>
      )}

      {docs === null && !error && <p className="docsview__muted">Loading&hellip;</p>}

      {docs !== null && docs.length === 0 && (
        <p className="docsview__muted">
          No documents yet. Upload one to start asking questions about it.
        </p>
      )}

      {docs !== null && docs.length > 0 && (
        <ul className="docsview__list">
          {docs.map((doc) => (
            <li className="doc-row" key={doc.document_id}>
              <div className="doc-row__info">
                <span className="doc-row__title">{doc.title}</span>
                {doc.origin === "generated" && <span className="doc-badge doc-badge--origin">AI</span>}
                <span className="doc-row__spoke">{doc.spoke}</span>
                {rowError?.id === doc.document_id && (
                  <span className="doc-row__error" role="alert">
                    {rowError.message}
                  </span>
                )}
              </div>
              <div className="doc-row__actions">
                <span className={`doc-badge doc-badge--${tone(doc.current_status)}`}>
                  {tone(doc.current_status) === "progress" && (
                    <span className="doc-badge__spinner" aria-hidden />
                  )}
                  {STATUS_LABEL[doc.current_status]}
                </span>
                {doc.current_status !== "failed" && (
                  // Same-origin cookie auth means a plain anchor is enough — no JS fetch
                  // needed. Hidden for `failed` docs (docs/21 §2.3): a scan-blocked
                  // malware upload's original is still in blob storage, and re-serving it
                  // one click away is the one case worth not making convenient.
                  <a
                    className="doc-row__download"
                    href={`/api/documents/${doc.document_id}/original`}
                    download
                    aria-label={`Download original of ${doc.title}`}
                  >
                    Download
                  </a>
                )}
                {confirmingId === doc.document_id ? (
                  <span className="doc-row__confirm">
                    <span className="doc-row__confirm-text">
                      Delete &lsquo;{doc.title}&rsquo;? This removes it from your library and from
                      answers.
                      {doc.current_status === "unpacked" &&
                        " The documents extracted from this archive (they appear separately in this list) will NOT be deleted."}
                    </span>
                    <button
                      type="button"
                      className="doc-row__confirm-btn doc-row__confirm-btn--danger"
                      disabled={deleting.has(doc.document_id)}
                      onClick={() => void handleDelete(doc)}
                    >
                      {deleting.has(doc.document_id) ? "Deleting…" : "Delete"}
                    </button>
                    <button
                      type="button"
                      className="doc-row__confirm-btn"
                      onClick={() => setConfirmingId(null)}
                    >
                      Cancel
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    className="doc-row__delete"
                    aria-label={`Delete ${doc.title}`}
                    onClick={() => setConfirmingId(doc.document_id)}
                  >
                    Delete
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {total > DOCUMENTS_PAGE_SIZE && (
        <div className="docsview__pager">
          <button
            type="button"
            className="docsview__pager-btn"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            &lsaquo; Prev
          </button>
          <span className="docsview__pager-label">
            page {page + 1} of {pageCount}
          </span>
          <button
            type="button"
            className="docsview__pager-btn"
            disabled={page >= pageCount - 1}
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
          >
            Next &rsaquo;
          </button>
        </div>
      )}
    </div>
  );
}
