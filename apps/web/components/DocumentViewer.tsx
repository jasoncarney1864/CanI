import type { SourceDocument } from "@/lib/types";

/**
 * Column B — Document Viewer (65%). Renders the source document in the content
 * font (Source Serif) on the Viewer Gray canvas, with the cited passage wrapped
 * in a Spotlight-Yellow <mark> (§2, §5).
 *
 * NOTE: the highlighted span is derived from mock data here. Serving real
 * source text + highlight offsets is deferred backend work.
 */
export function DocumentViewer({ doc }: { doc: SourceDocument }) {
  return (
    <section className="viewer" aria-label="Document viewer">
      <p className="col-label col-label--muted">Document Viewer</p>

      <article className="viewer__page">
        <h3 className="viewer__section">{doc.section_label}</h3>
        {doc.paragraphs.map((p) => (
          <p className="viewer__para" key={p.id}>
            {p.id === doc.highlightChunkId ? (
              <mark className="spotlight">{p.text}</mark>
            ) : (
              p.text
            )}
          </p>
        ))}
      </article>
    </section>
  );
}
