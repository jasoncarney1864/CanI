// Renders the current grounded answer as Markdown for "Save as document" (docs/21 §3.6).
// Pure function — no fetch, no state — so it's unit-testable in isolation and reused
// as-is for both the POST body and (indirectly, via the stored document) what a user sees
// when they later download or view the saved document.

import type { RetrievalAnswer } from "./types";

// Same marker the spoken-answer path strips in ConversationPane — inline citation
// pointers like "[chunk:3]" are meaningful to the model's answer but meaningless once the
// answer is exported as a standalone document.
const CHUNK_MARKER_RE = /\[chunk:\d+\]/g;

export function buildAnswerMarkdown(question: string, answer: RetrievalAnswer): string {
  const lines: string[] = [];

  lines.push(`# ${question}`, "");
  lines.push("## Question", "", question, "");

  lines.push("## Answer", "");
  const body = answer.verdict ? `${answer.verdict.label}. ${answer.answer}` : answer.answer;
  lines.push(body.replace(CHUNK_MARKER_RE, "").trim(), "");

  if (answer.citations.length > 0) {
    lines.push("## Sources", "");
    for (const citation of answer.citations) {
      if (citation.source_kind === "user_document") {
        lines.push(`- ${citation.document_title} (pp. ${citation.page_start}–${citation.page_end})`);
      } else {
        lines.push(`- ${citation.citation_ref} — ${citation.source_url}`);
      }
    }
    lines.push("");
  }

  return lines.join("\n").trimEnd() + "\n";
}
