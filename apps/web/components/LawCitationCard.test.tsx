import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { LawCitation } from "@/lib/types";
import { LawCitationCard } from "./LawCitationCard";

const baseCitation: LawCitation = {
  source_kind: "state_statute",
  chunk_id: "law-chunk-1",
  citation_ref: "NRS 116.31065",
  source_url: "https://www.leg.state.nv.us/NRS/NRS-116.html#NRS116Sec31065",
  snippet: "Must be reasonably related to the purpose for which they are adopted.",
  law_fetched_at: "2026-08-14T08:17:15.221033Z",
};

describe("LawCitationCard (docs/20 §20.8, §20.11 Phase 3)", () => {
  it("renders the citation ref, verbatim quote, source link, and quiet as-of date", () => {
    render(<LawCitationCard citation={baseCitation} />);
    expect(screen.getByText("NRS 116.31065")).toBeInTheDocument();
    expect(
      screen.getByText("“Must be reasonably related to the purpose for which they are adopted.”"),
    ).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "View source" });
    expect(link).toHaveAttribute("href", baseCitation.source_url);
    expect(link).toHaveAttribute("target", "_blank");
    expect(screen.getByText(/as of Aug 14, 2026/)).toBeInTheDocument();
  });

  it("is not rendered as a button — there is no document to open", () => {
    render(<LawCitationCard citation={baseCitation} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("omits the as-of stamp when law_fetched_at is absent", () => {
    render(<LawCitationCard citation={{ ...baseCitation, law_fetched_at: null }} />);
    expect(screen.queryByText(/as of/)).not.toBeInTheDocument();
    // The citation and quote must still render in full regardless.
    expect(screen.getByText("NRS 116.31065")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View source" })).toBeInTheDocument();
  });
});
