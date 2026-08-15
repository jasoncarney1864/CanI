import { describe, expect, it } from "vitest";
import { formatAsOfDate } from "./lawCitation";

describe("formatAsOfDate", () => {
  it("formats an ISO timestamp as a short, quiet date", () => {
    expect(formatAsOfDate("2026-08-14T08:17:15.221033Z")).toBe("Aug 14, 2026");
  });

  it("falls back to the raw string on an unparseable date instead of throwing", () => {
    expect(formatAsOfDate("not-a-date")).toBe("not-a-date");
  });
});
