// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { mintAccessToken } from "@/lib/backendAuth";
import { POST } from "./route";

vi.mock("@/lib/backendAuth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/backendAuth")>();
  return { ...actual, mintAccessToken: vi.fn().mockResolvedValue("fake-token") };
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(mintAccessToken).mockClear();
});

describe("POST /api/documents/generated (docs/21 §3.6)", () => {
  it("forwards the JSON body as-is and returns the upstream response", async () => {
    let capturedBody: unknown = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string | URL, init?: RequestInit) => {
        capturedBody = JSON.parse(init?.body as string);
        return new Response(
          JSON.stringify({ document_id: "doc-1", document_version_id: "v-1", status: "queued" }),
          { status: 200 },
        );
      }),
    );

    const payload = {
      title: null,
      spoke: "Legal",
      markdown: "# Can I sublet?\n\nYes.",
      provenance: { question: "Can I sublet?", model_id: null, citations: [] },
    };
    const request = new Request("http://localhost/api/documents/generated", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    const response = await POST(request);
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(capturedBody).toEqual(payload);
    expect(body).toEqual({ document_id: "doc-1", document_version_id: "v-1", status: "queued" });
  });

  it("surfaces a docs-api 400's detail verbatim", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "markdown must be between 1 byte and 1048576 bytes" }), { status: 400 })),
    );

    const request = new Request("http://localhost/api/documents/generated", {
      method: "POST",
      body: JSON.stringify({ markdown: "", provenance: { question: "q" } }),
    });

    const response = await POST(request);
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body.error).toBe("markdown must be between 1 byte and 1048576 bytes");
  });

  it("returns 400 for an invalid JSON body without calling the backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const request = new Request("http://localhost/api/documents/generated", {
      method: "POST",
      body: "not json",
    });

    const response = await POST(request);

    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("maps an unreachable backend to a 503", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      }),
    );

    const request = new Request("http://localhost/api/documents/generated", {
      method: "POST",
      body: JSON.stringify({ markdown: "x", provenance: { question: "q" } }),
    });

    const response = await POST(request);

    expect(response.status).toBe(503);
  });
});
