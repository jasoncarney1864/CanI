import type { LawCitation } from "@/lib/types";
import { formatAsOfDate } from "@/lib/lawCitation";

/**
 * Law/statute citation card (docs/20-public-law-corpus-design.md §20.8, §20.11 Phase 3).
 * Unlike the user-document citation card this isn't a button — there's no document to
 * open in the Viewer — so it surfaces the citation, verbatim quote, source link, and a
 * quiet "as of" date stamp directly. Per Q3 (decided), that quiet stamp is the *whole*
 * staleness story: no escalating warning banner.
 */
export function LawCitationCard({ citation }: { citation: LawCitation }) {
  return (
    <div className="citation-card citation-card--law">
      <span className="citation-card__title">{citation.citation_ref}</span>
      {citation.snippet && (
        <blockquote className="citation-card__quote">&ldquo;{citation.snippet}&rdquo;</blockquote>
      )}
      <span className="citation-card__loc">
        {citation.source_url && (
          <a
            href={citation.source_url}
            target="_blank"
            rel="noreferrer"
            className="citation-card__link"
          >
            View source
          </a>
        )}
        {citation.law_fetched_at && (
          <span className="citation-card__asof">
            {citation.source_url ? " · " : ""}
            as of {formatAsOfDate(citation.law_fetched_at)}
          </span>
        )}
      </span>
    </div>
  );
}
