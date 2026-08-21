import { describe, expect, it } from "vitest";
import { buildDocumentsListQuery, DOCUMENTS_PAGE_SIZE } from "./documentsQuery";

describe("buildDocumentsListQuery (docs/21 §1.9)", () => {
  it("builds the default first-page query for a spoke with no filters", () => {
    const qs = buildDocumentsListQuery({
      spoke: "General",
      q: "",
      statusFilter: "all",
      sort: "created_at",
      order: "desc",
      page: 0,
    });
    const params = new URLSearchParams(qs);
    expect(params.get("spoke")).toBe("General");
    expect(params.has("q")).toBe(false);
    expect(params.has("status")).toBe(false);
    expect(params.get("sort")).toBe("created_at");
    expect(params.get("order")).toBe("desc");
    expect(params.get("limit")).toBe(String(DOCUMENTS_PAGE_SIZE));
    expect(params.get("offset")).toBe("0");
  });

  it("trims the search box value and omits q entirely when it's blank", () => {
    const qs = buildDocumentsListQuery({
      spoke: "Legal",
      q: "   ",
      statusFilter: "all",
      sort: "created_at",
      order: "desc",
      page: 0,
    });
    expect(new URLSearchParams(qs).has("q")).toBe(false);

    const qs2 = buildDocumentsListQuery({
      spoke: "Legal",
      q: "  lease agreement  ",
      statusFilter: "all",
      sort: "created_at",
      order: "desc",
      page: 0,
    });
    expect(new URLSearchParams(qs2).get("q")).toBe("lease agreement");
  });

  it("includes status only when a specific stage is selected", () => {
    const qs = buildDocumentsListQuery({
      spoke: "Health",
      q: "",
      statusFilter: "failed",
      sort: "created_at",
      order: "desc",
      page: 0,
    });
    expect(new URLSearchParams(qs).get("status")).toBe("failed");
  });

  it("computes offset from page * pageSize", () => {
    const qs = buildDocumentsListQuery({
      spoke: "General",
      q: "",
      statusFilter: "all",
      sort: "title",
      order: "asc",
      page: 3,
      pageSize: 50,
    });
    const params = new URLSearchParams(qs);
    expect(params.get("offset")).toBe("150");
    expect(params.get("sort")).toBe("title");
    expect(params.get("order")).toBe("asc");
  });
});
