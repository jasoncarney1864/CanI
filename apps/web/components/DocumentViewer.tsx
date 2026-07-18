import type { DocumentText } from "@/lib/types";

/**
 * Column B — Document Viewer (65%). Renders the real source document (its ordered
 * chunks from GET /documents/{id}/text) in the content font (Source Serif) on the
 * Viewer Gray canvas, with every cited chunk wrapped in a Spotlight-Yellow <mark>
 * (§2, §5). Highlights are driven by the live citations' chunk_ids.
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
        <article className="viewer__page">
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
