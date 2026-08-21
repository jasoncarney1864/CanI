import { NextResponse } from "next/server";
import { BackendError, DOCS_API_URL, UNREACHABLE_BODY, mintAccessToken } from "@/lib/backendAuth";

// Server-side proxy for docs-api DELETE /documents/{id} (docs/21 §1.8). Tombstones the
// document synchronously and enqueues async cleanup upstream — the 202 here just means
// "delete accepted", not "fully removed".
export async function DELETE(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  try {
    const accessToken = await mintAccessToken(request.headers.get("cookie") ?? "");
    const res = await fetch(`${DOCS_API_URL}/documents/${encodeURIComponent(id)}`, {
      method: "DELETE",
      headers: { authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
    const body = await res.json().catch(() => ({}));
    if (res.status === 404) return NextResponse.json({ error: "Document not found." }, { status: 404 });
    if (!res.ok) {
      const message = (body as { detail?: string })?.detail ?? `Upstream delete failed (${res.status}).`;
      return NextResponse.json({ error: message }, { status: 502 });
    }
    return NextResponse.json(body, { status: 202 });
  } catch (e) {
    if (e instanceof BackendError) return NextResponse.json({ error: e.message }, { status: e.status });
    return NextResponse.json(UNREACHABLE_BODY, { status: 503 });
  }
}
