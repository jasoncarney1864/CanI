import { describe, expect, it } from "vitest";
import type { LawCitation, RetrievalAnswer, UserDocumentCitation } from "./types";
import { buildAnswerMarkdown } from "./exportAnswer";

const userCitation: UserDocumentCitation = {
  source_kind: "user_document",
  chunk_id: "chunk-1",
  document_id: "doc-1",
  document_title: "HOA Rules 2026",
  page_start: 4,
  page_end: 5,
  section_label: "Section 3",
};

const lawCitation: LawCitation = {
  source_kind: "state_statute",
  chunk_id: "chunk-2",
  citation_ref: "NRS 116.31065",
  source_url: "https://www.leg.state.nv.us/nrs/nrs-116.html",
};

describe("buildAnswerMarkdown", () => {
  it("renders question, answer, and no Sources section when there are no citations", () => {
    const answer: RetrievalAnswer = {
      answer: "Yes, subletting is allowed with board approval.",
      citations: [],
      insufficient_evidence: false,
    };

    const markdown = buildAnswerMarkdown("Can I sublet my unit?", answer);

    expect(markdown).toContain("# Can I sublet my unit?");
    expect(markdown).toContain("## Question");
    expect(markdown).toContain("## Answer");
    expect(markdown).toContain("Yes, subletting is allowed with board approval.");
    expect(markdown).not.toContain("## Sources");
  });

  it("prefixes the answer with the verdict label when a verdict is present", () => {
    const answer: RetrievalAnswer = {
      answer: "the HOA allows it.",
      citations: [],
      insufficient_evidence: false,
      verdict: { kind: "yes_with_conditions", label: "Yes, with conditions" },
    };

    const markdown = buildAnswerMarkdown("Can I sublet?", answer);

    expect(markdown).toContain("Yes, with conditions. the HOA allows it.");
  });

  it("strips inline [chunk:N] markers from the answer body", () => {
    const answer: RetrievalAnswer = {
      answer: "Yes[chunk:1], as long as you notify the board[chunk:2].",
      citations: [],
      insufficient_evidence: false,
    };

    const markdown = buildAnswerMarkdown("Can I sublet?", answer);

    expect(markdown).not.toContain("[chunk:");
    expect(markdown).toContain("Yes, as long as you notify the board.");
  });

  it("renders a Sources section with document citations formatted as title (pp. X–Y)", () => {
    const answer: RetrievalAnswer = {
      answer: "Yes.",
      citations: [userCitation],
      insufficient_evidence: false,
    };

    const markdown = buildAnswerMarkdown("Can I sublet?", answer);

    expect(markdown).toContain("## Sources");
    expect(markdown).toContain("- HOA Rules 2026 (pp. 4–5)");
  });

  it("renders law citations formatted as citation_ref — source_url", () => {
    const answer: RetrievalAnswer = {
      answer: "Yes.",
      citations: [lawCitation],
      insufficient_evidence: false,
    };

    const markdown = buildAnswerMarkdown("Can I sublet?", answer);

    expect(markdown).toContain("- NRS 116.31065 — https://www.leg.state.nv.us/nrs/nrs-116.html");
  });

  it("renders both citation kinds together in citation order", () => {
    const answer: RetrievalAnswer = {
      answer: "Yes.",
      citations: [userCitation, lawCitation],
      insufficient_evidence: false,
    };

    const markdown = buildAnswerMarkdown("Can I sublet?", answer);
    const sourcesIndex = markdown.indexOf("## Sources");
    const userIndex = markdown.indexOf("HOA Rules 2026");
    const lawIndex = markdown.indexOf("NRS 116.31065");

    expect(sourcesIndex).toBeGreaterThan(-1);
    expect(userIndex).toBeGreaterThan(sourcesIndex);
    expect(lawIndex).toBeGreaterThan(userIndex);
  });
});
