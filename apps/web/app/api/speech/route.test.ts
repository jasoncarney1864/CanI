// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { BackendError, mintAccessToken } from "@/lib/backendAuth";
import { POST } from "./route";

vi.mock("@/lib/backendAuth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/backendAuth")>();
  return { ...actual, mintAccessToken: vi.fn() };
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(mintAccessToken).mockReset();
});

describe("POST /api/speech", () => {
  it("rejects an unauthenticated request before invoking Azure Speech", async () => {
    vi.mocked(mintAccessToken).mockRejectedValueOnce(new BackendError("Not signed in.", 401));
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      new Request("http://localhost/api/speech", {
        method: "POST",
        body: JSON.stringify({ text: "confidential text" }),
      }),
    );

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "Not signed in." });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
