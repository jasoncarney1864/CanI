import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LegalDraftingView } from "./LegalDraftingView";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LegalDraftingView", () => {
  it("renders the intentionally dark state when no templates are active", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));

    render(<LegalDraftingView />);

    expect(await screen.findByText("No templates are available yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start drafting" })).not.toBeInTheDocument();
  });

  it("starts a draft, confirms a field, previews, and finalizes", async () => {
    const template = {
      slug: "reviewed-template",
      version: 1,
      title: "Reviewed test template",
      category: "Legal",
      jurisdiction_note: "Test jurisdiction only.",
      disclaimer_text: "Not legal advice.",
      field_schema: {
        principal_name: { type: "text", label: "Principal", required: true },
      },
    };
    let draft = {
      legal_draft_id: "draft-1",
      owner_user_id: "owner-1",
      legal_template_id: "template-1",
      template_version: 1,
      status: "draft",
      field_values_json: {},
      document_id: null,
      created_at: "2026-08-21T00:00:00Z",
      updated_at: "2026-08-21T00:00:00Z",
    };
    const fetchMock = vi.fn(async (url: string | URL, init?: RequestInit) => {
      const path = url.toString();
      if (path === "/api/legal/templates") return new Response(JSON.stringify([template]));
      if (path === "/api/legal/templates/reviewed-template") return new Response(JSON.stringify(template));
      if (path === "/api/legal/drafts" && init?.method === "POST") return new Response(JSON.stringify(draft));
      if (path.endsWith("/fields/confirm")) {
        draft = { ...draft, field_values_json: { principal_name: "Jane Doe" } };
        return new Response(JSON.stringify(draft));
      }
      if (path.endsWith("/preview")) {
        return new Response(
          JSON.stringify({ body: "Principal: Jane Doe", disclaimer_text: "Not legal advice.", missing_required_fields: [] }),
        );
      }
      if (path.endsWith("/finalize")) {
        return new Response(JSON.stringify({ document_id: "document-1", status: "finalized" }));
      }
      return new Response(JSON.stringify({ error: "unexpected request" }), { status: 500 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LegalDraftingView />);
    fireEvent.click(await screen.findByRole("button", { name: "Start drafting" }));
    const fieldButton = await screen.findByRole("button", { name: /Principal/ });
    fireEvent.click(fieldButton);

    fireEvent.change(screen.getAllByRole("textbox")[0], { target: { value: "Jane Doe" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByText("1 of 1 fields filled")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText("Principal: Jane Doe")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Finalize & generate PDF" }));
    expect(await screen.findByText(/saved to your Documents page/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download PDF" })).toHaveAttribute(
      "href",
      "/api/documents/document-1/original",
    );
  });
});
