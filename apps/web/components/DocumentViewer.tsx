import { useEffect, useRef } from "react";
import type { DocumentText } from "@/lib/types";

/**
 * Document Viewer — a slide-over panel opened by clicking a citation. Renders
 * the real source document (its ordered chunks from GET /documents/{id}/text)
 * in the content font (Source Serif) on the Viewer Gray canvas, with every
 * cited chunk wrapped in a Spotlight-Yellow <mark> (§2, §5). Highlights are
 * driven by the live citations' chunk_ids; the first spotlighted passage is
 * scrolled into view so the evidence is never off-screen. Dismissed via the
 * close button, the backdrop, or Escape.
 */
export function DocumentViewer({
  doc,
  highlightChunkIds,
  loading,
  onClose,
}: {
  doc: DocumentText | null;
  highlightChunkIds: Set<string>;
  loading: boolean;
  onClose: () => void;
}) {
  const pageRef = useRef<HTMLElement | null>(null);

  // When a document (or a new set of citations) lands, bring the first
  // spotlighted passage into view — centered, so surrounding context is visible.
  useEffect(() => {
    if (!doc || loading) return;
    const mark = pageRef.current?.querySelector("mark.spotlight");
    mark?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [doc, highlightChunkIds, loading]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="viewer-overlay">
      <button
        type="button"
        className="viewer-overlay__backdrop"
        onClick={onClose}
        aria-label="Close document viewer"
        tabIndex={-1}
      />
      <section className="viewer" role="dialog" aria-modal="true" aria-label="Document viewer">
        <header className="viewer__bar">
          <p className="col-label col-label--muted">Document Viewer</p>
          <button
            type="button"
            className="viewer__close"
            onClick={onClose}
            aria-label="Close document viewer"
          >
            &times;
          </button>
        </header>

        {loading ? (
          <p className="viewer__empty" aria-busy="true">
            Loading source document…
          </p>
        ) : !doc || doc.chunks.length === 0 ? (
          <p className="viewer__empty">
            The source document couldn&rsquo;t be loaded. Close this panel and try the
            citation again.
          </p>
        ) : (
          <article className="viewer__page" ref={pageRef}>
            <h3 className="viewer__section">{doc.title}</h3>
            {doc.chunks.map((chunk) => (
              <p className="viewer__para" key={chunk.chunk_id}>
                {highlightChunkIds.has(chunk.chunk_id) ? (
                  <mark className="spotlight">{chunk.text}</mark>
                ) : (
                  chunk.text
                )}
              </p>
            ))}
          </article>
        )}
      </section>
    </div>
  );
}
