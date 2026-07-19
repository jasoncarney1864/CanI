import type { Verdict, VerdictKind } from "@/lib/types";

// The glyph must match the verdict, not always affirm it: a ✓ next to "Insufficient
// evidence" reads as a false "yes". Affirmative verdicts get a check, a "no" gets a cross,
// and "insufficient" gets a neutral mark (it neither affirms nor denies).
const GLYPH: Record<VerdictKind, string> = {
  yes: "✓", // ✓
  yes_with_conditions: "✓", // ✓
  no: "✗", // ✗
  insufficient: "?",
};

/**
 * The verdict pill (§5). Affirmative verdicts use the spoke's success colour; a
 * "no" or "insufficient" verdict is rendered neutral so the colour doesn't imply
 * a "yes".
 *
 * NOTE: a structured verdict is prototype-only; the live API currently returns
 * free-text `answer` + `insufficient_evidence` (surfaced as the `insufficient` kind).
 */
export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const affirmative = verdict.kind === "yes" || verdict.kind === "yes_with_conditions";
  return (
    <span
      className={`verdict-badge${affirmative ? "" : " verdict-badge--neutral"}`}
      data-kind={verdict.kind}
      role="status"
    >
      <span className="verdict-badge__check" aria-hidden>
        {GLYPH[verdict.kind]}
      </span>
      {verdict.label.toUpperCase()}
    </span>
  );
}
