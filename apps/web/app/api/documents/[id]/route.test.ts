// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { mintAccessToken } from "@/lib/backendAuth";
import { DELETE, PATCH } from "./route";

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

describe("PATCH /api/documents/[id] (docs/21 follow-up: move to spoke)", () => {
  it("forwards the JSON body and returns the upstream document", async () => {
    let capturedBody: unknown = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string | URL, init?: RequestInit) => {
        capturedBody = JSON.parse(init?.body as string);
        return new Response(JSON.stringify({ document_id: "doc-1", spoke: "Legal" }), { status: 200 });
      }),
    );

    const request = new Request("http://localhost/api/documents/doc-1", {
      method: "PATCH",
      body: JSON.stringify({ spoke: "Legal" }),
    });
    const response = await PATCH(request, makeContext("doc-1"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(capturedBody).toEqual({ spoke: "Legal" });
    expect(body).toEqual({ document_id: "doc-1", spoke: "Legal" });
  });

  it("surfaces a docs-api 400's detail verbatim", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "Invalid spoke: NotASpoke" }), { status: 400 })),
    );

    const request = new Request("http://localhost/api/documents/doc-1", {
      method: "PATCH",
      body: JSON.stringify({ spoke: "NotASpoke" }),
    });
    const response = await PATCH(request, makeContext("doc-1"));
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body.error).toBe("Invalid spoke: NotASpoke");
  });

  it("maps a 404 to a JSON error body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "document not found" }), { status: 404 })),
    );

    const request = new Request("http://localhost/api/documents/doc-1", {
      method: "PATCH",
      body: JSON.stringify({ spoke: "Legal" }),
    });
    const response = await PATCH(request, makeContext("doc-1"));

    expect(response.status).toBe(404);
  });

  it("returns 400 for an invalid JSON body without calling the backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const request = new Request("http://localhost/api/documents/doc-1", { method: "PATCH", body: "not json" });
    const response = await PATCH(request, makeContext("doc-1"));

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

    const request = new Request("http://localhost/api/documents/doc-1", {
      method: "PATCH",
      body: JSON.stringify({ spoke: "Legal" }),
    });
    const response = await PATCH(request, makeContext("doc-1"));

    expect(response.status).toBe(503);
  });
});

describe("DELETE /api/documents/[id] (docs/21 §1.8)", () => {
  it("still works alongside the new PATCH handler", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ document_id: "doc-1", status: "delete_pending" }), { status: 202 })),
    );

    const response = await DELETE(new Request("http://localhost/api/documents/doc-1"), makeContext("doc-1"));

    expect(response.status).toBe(202);
  });
});
