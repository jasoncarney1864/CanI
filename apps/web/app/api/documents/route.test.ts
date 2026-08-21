// @vitest-environment node
//
// These are server-side route handlers, not DOM code — jsdom's own File/FormData/Request
// implementations (the default environment for this project's other tests) don't
// correctly round-trip a multipart body through Request.formData(), so run this file
// under Node's native fetch primitives instead.
import { afterEach, describe, expect, it, vi } from "vitest";
import { mintAccessToken } from "@/lib/backendAuth";
import { GET, POST } from "./route";

// The hub-api session round trip is exercised by the integration suite; here we only need
// a token to exist so the proxy handlers proceed to the docs-api fetch under test.
vi.mock("@/lib/backendAuth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/backendAuth")>();
  return { ...actual, mintAccessToken: vi.fn().mockResolvedValue("fake-token") };
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(mintAccessToken).mockClear();
});

describe("POST /api/documents (docs/21 §1.8 spoke-forwarding bug fix)", () => {
  it("forwards the spoke field the client sent through to the upstream multipart body", async () => {
    let capturedForm: FormData | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string | URL, init?: RequestInit) => {
        capturedForm = init?.body as FormData;
        return new Response(
          JSON.stringify({ document_id: "doc-1", document_version_id: "v-1", status: "queued" }),
          { status: 200 },
        );
      }),
    );

    const form = new FormData();
    form.append("file", new File(["hello"], "hoa-rules.pdf", { type: "application/pdf" }));
    form.append("spoke", "Legal");
    const request = new Request("http://localhost/api/documents", { method: "POST", body: form });

    const response = await POST(request);

    expect(response.status).toBe(200);
    expect(capturedForm).not.toBeNull();
    expect(capturedForm!.get("spoke")).toBe("Legal");
    expect((capturedForm!.get("file") as File).name).toBe("hoa-rules.pdf");
  });

  it("omits spoke when the client didn't send one, rather than sending an empty value", async () => {
    let capturedForm: FormData | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string | URL, init?: RequestInit) => {
        capturedForm = init?.body as FormData;
        return new Response(
          JSON.stringify({ document_id: "doc-1", document_version_id: "v-1", status: "queued" }),
          { status: 200 },
        );
      }),
    );

    const form = new FormData();
    form.append("file", new File(["hello"], "notes.pdf", { type: "application/pdf" }));
    const request = new Request("http://localhost/api/documents", { method: "POST", body: form });

    await POST(request);

    expect(capturedForm!.get("spoke")).toBeNull();
  });
});

describe("GET /api/documents (docs/21 §1.8 param passthrough)", () => {
  it("forwards every list param verbatim to docs-api and returns the envelope", async () => {
    let capturedUrl: string | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string | URL) => {
        capturedUrl = url.toString();
        return new Response(JSON.stringify({ items: [], total: 0, limit: 25, offset: 25 }), { status: 200 });
      }),
    );

    const request = new Request(
      "http://localhost/api/documents?spoke=Legal&status=queued%2Cindexed&origin=uploaded&q=lease&sort=title&order=asc&limit=25&offset=25",
    );
    const response = await GET(request);
    const body = await response.json();

    const upstream = new URL(capturedUrl!);
    expect(upstream.searchParams.get("spoke")).toBe("Legal");
    expect(upstream.searchParams.get("status")).toBe("queued,indexed");
    expect(upstream.searchParams.get("origin")).toBe("uploaded");
    expect(upstream.searchParams.get("q")).toBe("lease");
    expect(upstream.searchParams.get("sort")).toBe("title");
    expect(upstream.searchParams.get("order")).toBe("asc");
    expect(upstream.searchParams.get("limit")).toBe("25");
    expect(upstream.searchParams.get("offset")).toBe("25");
    expect(body).toEqual({ items: [], total: 0, limit: 25, offset: 25 });
  });
});
