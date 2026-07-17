import type { RetrievalAnswer } from "@/lib/types";
import type { Spoke } from "@/lib/spokes";
import { VerdictBadge } from "./VerdictBadge";

interface ConversationPaneProps {
  answer: RetrievalAnswer;
  spoke: Spoke;
}

/**
 * Column A — Conversation (35%). The verdict badge and ask input use the UI
 * font (DM Sans); the AI verdict summary uses the content font (Source Serif),
 * per the dual-stack typography system (§4).
 */
export function ConversationPane({ answer, spoke }: ConversationPaneProps) {
  return (
    <section className="conversation" aria-label="Conversation">
      <p className="col-label">Conversation</p>

      {answer.verdict && <VerdictBadge verdict={answer.verdict} />}

      <div className="conversation__body">
        <h2 className="conversation__heading">AI Verdict Summary</h2>
        <p className="conversation__summary">{answer.answer}</p>

        {answer.citations.map((c) => (
          <div className="citation-card" key={c.chunk_id}>
            <span className="citation-card__title">{c.document_title}</span>
            <span className="citation-card__loc">
              {c.section_label} &middot; p.{c.page_start}
            </span>
            {c.snippet && <span className="citation-card__snippet">&ldquo;{c.snippet}&rdquo;</span>}
          </div>
        ))}
      </div>

      <form className="ask" onSubmit={(e) => e.preventDefault()}>
        <input
          className="ask__input"
          type="text"
          placeholder={spoke.placeholder}
          aria-label="Ask another question"
        />
      </form>
    </section>
  );
}
