/**
 * Formats an ISO timestamp as a short, quiet "as of" date stamp.
 *
 * Per docs/20-public-law-corpus-design.md Q3 (decided): staleness disclosure is this
 * plain per-citation date only — no escalating warning banner. Falls back to the raw
 * string on an unparseable date rather than throwing, since this renders inline in the
 * citation card.
 */
export function formatAsOfDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", { year: "numeric", month: "short", day: "numeric" }).format(
    date,
  );
}
