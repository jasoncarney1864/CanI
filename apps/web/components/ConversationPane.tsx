import type { RetrievalAnswer } from "@/lib/types";
import type { Spoke } from "@/lib/spokes";
import { VerdictBadge } from "./VerdictBadge";

interface ConversationPaneProps {
  answer: RetrievalAnswer | null;
  spoke: Spoke;
  loading: boolean;
  error: string | null;
  onAsk: (question: string) => void;
}

/**
 * Column A — Conversation (35%). The verdict badge and ask input use the UI
 * font (DM Sans); the AI verdict summary uses the content font (Source Serif),
 * per the dual-stack typography system (§4).
 */
export function ConversationPane({ answer, spoke, loading, error, onAsk }: ConversationPaneProps) {
  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem("question") as HTMLInputElement | null;
    const question = input?.value.trim();
    if (!question || loading) return;
    onAsk(question);
    if (input) input.value = "";
  }

  return (
    <section className="conversation" aria-label="Conversation">
      <p className="col-label">Conversation</p>

      {answer?.verdict && <VerdictBadge verdict={answer.verdict} />}

      <div className="conversation__body">
        <h2 className="conversation__heading">AI Verdict Summary</h2>
        {error ? (
          <p className="conversation__error" role="alert">
            {error}
          </p>
        ) : (
          <p className="conversation__summary" aria-busy={loading}>
            {loading
              ? "Searching your documents\u2026"
              : (answer?.answer ??
                "Ask a question about your documents to get a grounded, cited answer.")}
          </p>
        )}

        {!loading &&
          !error &&
          answer?.citations.map((c) => (
            <div className="citation-card" key={c.chunk_id}>
              <span className="citation-card__title">{c.document_title}</span>
              <span className="citation-card__loc">
                {c.section_label} &middot; p.{c.page_start}
              </span>
              {c.snippet && <span className="citation-card__snippet">&ldquo;{c.snippet}&rdquo;</span>}
            </div>
          ))}
      </div>

      <form className="ask" onSubmit={handleSubmit}>
        <input
          className="ask__input"
          type="text"
          name="question"
          placeholder={spoke.placeholder}
          aria-label="Ask another question"
          disabled={loading}
          autoComplete="off"
        />
      </form>
    </section>
  );
}
