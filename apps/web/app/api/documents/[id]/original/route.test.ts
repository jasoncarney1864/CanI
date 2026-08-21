// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { mintAccessToken } from "@/lib/backendAuth";
import { GET } from "./route";

vi.mock("@/lib/backendAuth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/backendAuth")>();
  return { ...actual, mintAccessToken: vi.fn().mockResolvedValue("fake-token") };
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(mintAccessToken).mockClear();
});

function makeContext(id: string) {
  return { params: Promise.resolve({ id }) };
}

describe("GET /api/documents/[id]/original (docs/21 §2.3)", () => {
  it("streams the upstream body through with its content-type and content-disposition", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(new Blob([new Uint8Array([1, 2, 3])]), {
          status: 200,
          headers: {
            "content-type": "application/pdf",
            "content-disposition": 'attachment; filename="lease.pdf"',
          },
        }),
      ),
    );

    const response = await GET(new Request("http://localhost/api/documents/doc-1/original"), makeContext("doc-1"));

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("application/pdf");
    expect(response.headers.get("content-disposition")).toBe('attachment; filename="lease.pdf"');
    const bytes = new Uint8Array(await response.arrayBuffer());
    expect(Array.from(bytes)).toEqual([1, 2, 3]);
  });

  it("maps a 404 to a JSON error body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "document not found" }), { status: 404 })),
    );

    const response = await GET(new Request("http://localhost/api/documents/doc-1/original"), makeContext("doc-1"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body.error).toBe("document not found");
  });

  it("maps an unreachable backend to a 503", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      }),
    );

    const response = await GET(new Request("http://localhost/api/documents/doc-1/original"), makeContext("doc-1"));

    expect(response.status).toBe(503);
  });
});
