import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DocumentListResponse, DocumentMeta } from "@/lib/types";
import { DocumentsView } from "./DocumentsView";

function doc(overrides: Partial<DocumentMeta> = {}): DocumentMeta {
  return {
    document_id: "doc-1",
    owner_user_id: "owner-1",
    title: "hoa-rules.pdf",
    source_type: "application/pdf",
    current_status: "indexed",
    checksum: "abc123",
    created_at: "2026-08-14T00:00:00Z",
    updated_at: "2026-08-14T00:00:00Z",
    spoke: "General",
    origin: "uploaded",
    ...overrides,
  };
}

function mockFetchSequence(initialDocs: DocumentMeta[]) {
  let currentDocs = initialDocs;
  const calls: { url: string; method: string }[] = [];
  const fetchMock = vi.fn(async (url: string | URL, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url: url.toString(), method });
    if (method === "DELETE") {
      const id = url.toString().split("/").pop()!;
      currentDocs = currentDocs.filter((d) => d.document_id !== id);
      return new Response(JSON.stringify({ document_id: id, status: "delete_pending" }), { status: 202 });
    }
    const envelope: DocumentListResponse = { items: currentDocs, total: currentDocs.length, limit: 50, offset: 0 };
    return new Response(JSON.stringify(envelope), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DocumentsView delete flow (docs/21 §1.4/§1.9)", () => {
  it("shows an inline confirm, then deletes on confirm click", async () => {
    mockFetchSequence([doc()]);
    render(<DocumentsView spoke="General" />);

    await screen.findByText("hoa-rules.pdf");
    fireEvent.click(screen.getByRole("button", { name: "Delete hoa-rules.pdf" }));

    expect(
      screen.getByText(/Delete .hoa-rules\.pdf.\? This removes it from your library and from answers\./),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.queryByText("hoa-rules.pdf")).not.toBeInTheDocument());
  });

  it("warns about non-cascading deletion for an unpacked archive parent", async () => {
    mockFetchSequence([doc({ document_id: "doc-2", title: "paperwork.zip", current_status: "unpacked" })]);
    render(<DocumentsView spoke="General" />);

    await screen.findByText("paperwork.zip");
    fireEvent.click(screen.getByRole("button", { name: "Delete paperwork.zip" }));

    expect(
      screen.getByText(/will NOT be deleted/),
    ).toBeInTheDocument();
  });

  it("cancel dismisses the confirm without deleting", async () => {
    const { calls } = mockFetchSequence([doc()]);
    render(<DocumentsView spoke="General" />);

    await screen.findByText("hoa-rules.pdf");
    fireEvent.click(screen.getByRole("button", { name: "Delete hoa-rules.pdf" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByText("hoa-rules.pdf")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  });

  it("shows a row-level error and keeps the row when delete fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string | URL, init?: RequestInit) => {
        if (init?.method === "DELETE") {
          return new Response(JSON.stringify({ error: "Upstream delete failed (502)." }), { status: 502 });
        }
        const envelope: DocumentListResponse = { items: [doc()], total: 1, limit: 50, offset: 0 };
        return new Response(JSON.stringify(envelope), { status: 200 });
      }),
    );
    render(<DocumentsView spoke="General" />);

    await screen.findByText("hoa-rules.pdf");
    fireEvent.click(screen.getByRole("button", { name: "Delete hoa-rules.pdf" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    await screen.findByText("Upstream delete failed (502).");
    expect(screen.getByText("hoa-rules.pdf")).toBeInTheDocument();
  });
});
