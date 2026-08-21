import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SPOKES } from "@/lib/spokes";
import type { LawCitation, RetrievalAnswer, UserDocumentCitation } from "@/lib/types";
import { ConversationPane } from "./ConversationPane";

const docCitation: UserDocumentCitation = {
  source_kind: "user_document",
  document_id: "doc-1",
  document_title: "Shadow Ridge CC&Rs",
  page_start: 3,
  page_end: 3,
  section_label: "7.2",
  chunk_id: "chunk-1",
  snippet: "No pets over 40 lbs.",
};

const lawCitation: LawCitation = {
  source_kind: "state_statute",
  chunk_id: "law-chunk-1",
  citation_ref: "NRS 116.31065",
  source_url: "https://www.leg.state.nv.us/NRS/NRS-116.html#NRS116Sec31065",
  snippet: "Must be reasonably related to the purpose for which they are adopted.",
  law_fetched_at: "2026-08-14T08:17:15.221033Z",
};

function renderPane(answer: RetrievalAnswer | null, overrides: Partial<Parameters<typeof ConversationPane>[0]> = {}) {
  return render(
    <ConversationPane
      answer={answer}
      spoke={SPOKES.legal}
      loading={false}
      error={null}
      onAsk={vi.fn().mockResolvedValue(null)}
      activeDocumentId={null}
      onSelectCitation={vi.fn()}
      onSaveAsDocument={vi.fn()}
      saveState="idle"
      saveError={null}
      onGoToDocuments={vi.fn()}
      {...overrides}
    />,
  );
}

describe("ConversationPane citation rendering (docs/20 §20.11 Phase 3)", () => {
  it("keeps rendering a user_document citation as a clickable card with title/page", () => {
    const onSelectCitation = vi.fn();
    renderPane(
      { answer: "Answer text.", citations: [docCitation], insufficient_evidence: false, verdict: null },
      { onSelectCitation },
    );

    const card = screen.getByRole("button", {
      name: "Open Shadow Ridge CC&Rs with the cited passage spotlighted",
    });
    expect(card).toBeInTheDocument();
    expect(screen.getByText("Shadow Ridge CC&Rs")).toBeInTheDocument();

    fireEvent.click(card);
    expect(onSelectCitation).toHaveBeenCalledWith("doc-1");
  });

  it("renders a law citation as the quote/citation card, not a document button", () => {
    renderPane({
      answer: "Answer text.",
      citations: [lawCitation],
      insufficient_evidence: false,
      verdict: null,
    });

    expect(screen.getByText("NRS 116.31065")).toBeInTheDocument();
    expect(
      screen.getByText("“Must be reasonably related to the purpose for which they are adopted.”"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View source" })).toHaveAttribute(
      "href",
      lawCitation.source_url,
    );
    // Only the document citation is a button — the law card has no "open document" action.
    expect(screen.queryByRole("button", { name: /Open .* with the cited passage/ })).not.toBeInTheDocument();
  });

  it("renders both source kinds together when an answer cites both corpora", () => {
    renderPane({
      answer: "Answer text.",
      citations: [docCitation, lawCitation],
      insufficient_evidence: false,
      verdict: null,
    });

    expect(screen.getByText("Shadow Ridge CC&Rs")).toBeInTheDocument();
    expect(screen.getByText("NRS 116.31065")).toBeInTheDocument();
  });

  it("suppresses the verdict badge when verdict is null, even though a law chunk is cited", () => {
    const { container } = renderPane({
      answer: "Answer text.",
      citations: [docCitation, lawCitation],
      insufficient_evidence: false,
      verdict: null,
    });

    // No verdict badge — but the citations/quote still render in full. (The voice presence
    // indicator also carries role="status", so scope this query to the badge's own class
    // rather than role alone.)
    expect(container.querySelector(".verdict-badge")).not.toBeInTheDocument();
    expect(screen.getByText("NRS 116.31065")).toBeInTheDocument();
    expect(
      screen.getByText("“Must be reasonably related to the purpose for which they are adopted.”"),
    ).toBeInTheDocument();
  });

  it("still renders the verdict badge for document-only answers, unchanged from before", () => {
    const { container } = renderPane({
      answer: "Answer text.",
      citations: [docCitation],
      insufficient_evidence: false,
      verdict: { kind: "yes_with_conditions", label: "Yes, with conditions" },
    });

    expect(container.querySelector(".verdict-badge")).toHaveTextContent("YES, WITH CONDITIONS");
  });
});

describe("ConversationPane 'Save as document' (docs/21 §3.6)", () => {
  const answer: RetrievalAnswer = {
    answer: "Yes, with board approval.",
    citations: [],
    insufficient_evidence: false,
    verdict: null,
  };

  it("does not render the save control when there is no answer yet", () => {
    renderPane(null);
    expect(screen.queryByRole("button", { name: "Save as document" })).not.toBeInTheDocument();
  });

  it("renders a 'Save as document' button once an answer is present, wired to onSaveAsDocument", () => {
    const onSaveAsDocument = vi.fn();
    renderPane(answer, { onSaveAsDocument });

    const button = screen.getByRole("button", { name: "Save as document" });
    fireEvent.click(button);
    expect(onSaveAsDocument).toHaveBeenCalledTimes(1);
  });

  it("disables the button and shows 'Saving…' while saveState is 'saving'", () => {
    renderPane(answer, { saveState: "saving" });

    const button = screen.getByRole("button", { name: "Saving…" });
    expect(button).toBeDisabled();
  });

  it("shows a 'Saved — view in Documents' link when saveState is 'saved', wired to onGoToDocuments", () => {
    const onGoToDocuments = vi.fn();
    renderPane(answer, { saveState: "saved", onGoToDocuments });

    expect(screen.queryByRole("button", { name: "Save as document" })).not.toBeInTheDocument();
    const link = screen.getByRole("button", { name: "view in Documents" });
    fireEvent.click(link);
    expect(onGoToDocuments).toHaveBeenCalledTimes(1);
  });

  it("shows the save error inline when saveState is 'error'", () => {
    renderPane(answer, { saveState: "error", saveError: "Couldn't save (500)." });

    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't save (500).");
    // The button is still present so the user can retry.
    expect(screen.getByRole("button", { name: "Save as document" })).toBeInTheDocument();
  });
});
