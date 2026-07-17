import type { Verdict } from "@/lib/types";

/**
 * The "YES, WITH CONDITIONS" verdict pill (§5). Colour is driven by the
 * --spoke-badge-success token so it re-themes per spoke.
 *
 * NOTE: a structured verdict is prototype-only; the live API currently returns
 * free-text `answer` + `insufficient_evidence` only.
 */
export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return (
    <span className="verdict-badge" role="status">
      <span className="verdict-badge__check" aria-hidden>
        &#10003;
      </span>
      {verdict.label.toUpperCase()}
    </span>
  );
}
