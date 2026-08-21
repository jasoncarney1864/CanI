import { NextResponse } from "next/server";
import type { DocumentMeta } from "@/lib/types";
import { BackendError, DOCS_API_URL, UNREACHABLE_BODY, mintAccessToken } from "@/lib/backendAuth";

// Server-side proxy for docs-api PATCH /documents/{id} (docs/21 follow-up: moving a
// mis-filed document to a different spoke). Body passthrough — docs-api validates the
// spoke value and 400s on anything not in DocumentSpoke.
export async function PATCH(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Expected a JSON body." }, { status: 400 });
  }
  try {
    const accessToken = await mintAccessToken(request.headers.get("cookie") ?? "");
    const res = await fetch(`${DOCS_API_URL}/documents/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { authorization: `Bearer ${accessToken}`, "content-type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const message = (data as { detail?: string })?.detail ?? `Upstream update failed (${res.status}).`;
      return NextResponse.json({ error: message }, { status: res.status === 400 || res.status === 404 ? res.status : 502 });
    }
    return NextResponse.json(data as DocumentMeta);
  } catch (e) {
    if (e instanceof BackendError) return NextResponse.json({ error: e.message }, { status: e.status });
    return NextResponse.json(UNREACHABLE_BODY, { status: 503 });
  }
}

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
