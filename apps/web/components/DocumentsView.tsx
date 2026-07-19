"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { DocumentMeta, DocumentStatus } from "@/lib/types";

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

// Tone drives the badge colour: in-progress (amber), ready (green), failed (red).
function tone(status: DocumentStatus): "progress" | "ready" | "failed" {
  if (status === "failed") return "failed";
  if (status === "indexed" || status === "unpacked") return "ready";
  return "progress";
}

/**
 * Documents view (A3). Lists the caller's documents (owner-scoped via the /api/documents
 * proxy) with honest ingestion status, polling while anything is still in flight so the
 * user watches queued -> extracting -> ... -> indexed without refreshing. A "failed" doc is
 * surfaced plainly (malware-blocked or OCR-unsupported), not hidden.
 */
export function DocumentsView() {
  const [docs, setDocs] = useState<DocumentMeta[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/documents", { cache: "no-store" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error ?? `Couldn't load documents (${res.status}).`);
      setError(null);
      setDocs(data as DocumentMeta[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load documents.");
    }
  }, []);

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

  return (
    <div className="docsview">
      <div className="docsview__head">
        <p className="col-label">Documents</p>
        <button type="button" className="docsview__refresh" onClick={() => void load()}>
          Refresh
        </button>
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
              <span className="doc-row__title">{doc.title}</span>
              <span className={`doc-badge doc-badge--${tone(doc.current_status)}`}>
                {tone(doc.current_status) === "progress" && (
                  <span className="doc-badge__spinner" aria-hidden />
                )}
                {STATUS_LABEL[doc.current_status]}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
