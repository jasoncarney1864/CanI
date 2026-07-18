import { NextResponse } from "next/server";
import type { DocumentText } from "@/lib/types";
import { BackendError, DOCS_API_URL, UNREACHABLE_BODY, mintAccessToken } from "@/lib/backendAuth";

// Server-side proxy for docs-api GET /documents/{id}/text — the source text (ordered
// chunks) that powers the Document Viewer. Owner-scoped to the signed-in user's session.
export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  try {
    const accessToken = await mintAccessToken(request.headers.get("cookie") ?? "");
    const res = await fetch(`${DOCS_API_URL}/documents/${encodeURIComponent(id)}/text`, {
      method: "GET",
      headers: { authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
    if (res.status === 404) return NextResponse.json({ error: "Document not found." }, { status: 404 });
    if (!res.ok) {
      return NextResponse.json({ error: `Upstream document fetch failed (${res.status}).` }, { status: 502 });
    }
    return NextResponse.json((await res.json()) as DocumentText);
  } catch (e) {
    if (e instanceof BackendError) return NextResponse.json({ error: e.message }, { status: e.status });
    return NextResponse.json(UNREACHABLE_BODY, { status: 503 });
  }
}
