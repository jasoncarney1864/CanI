import { useEffect, useRef } from "react";
import type { DocumentText } from "@/lib/types";

/**
 * Column B — Document Viewer (65%). Renders the real source document (its ordered
 * chunks from GET /documents/{id}/text) in the content font (Source Serif) on the
 * Viewer Gray canvas, with every cited chunk wrapped in a Spotlight-Yellow <mark>
 * (§2, §5). Highlights are driven by the live citations' chunk_ids; the first
 * spotlighted passage is scrolled into view so the evidence is never off-screen.
 */
export function DocumentViewer({
  doc,
  highlightChunkIds,
  loading,
}: {
  doc: DocumentText | null;
  highlightChunkIds: Set<string>;
  loading: boolean;
}) {
  const pageRef = useRef<HTMLElement | null>(null);

  // When a document (or a new set of citations) lands, bring the first
  // spotlighted passage into view — centered, so surrounding context is visible.
  useEffect(() => {
    if (!doc || loading) return;
    const mark = pageRef.current?.querySelector("mark.spotlight");
    mark?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [doc, highlightChunkIds, loading]);

  return (
    <section className="viewer" aria-label="Document viewer">
      <p className="col-label col-label--muted">Document Viewer</p>

      {loading ? (
        <p className="viewer__empty" aria-busy="true">
          Loading source document…
        </p>
      ) : !doc || doc.chunks.length === 0 ? (
        <p className="viewer__empty">
          Ask a question and the cited source document will appear here, with the cited
          passage spotlighted.
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
  );
}
