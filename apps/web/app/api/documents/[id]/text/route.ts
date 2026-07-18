import { NextResponse } from "next/server";
import type { DocumentText } from "@/lib/types";
import { BackendError, DOCS_API_URL, UNREACHABLE_BODY, mintAccessToken } from "@/lib/backendAuth";

// Server-side proxy for docs-api GET /documents/{id}/text — the source text (ordered
// chunks) that powers the Document Viewer's in-context spotlight. Owner-scoping is
// enforced end to end in the backend; this route only forwards the authed request.

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;

  try {
    const accessToken = await mintAccessToken();
    const res = await fetch(`${DOCS_API_URL}/documents/${encodeURIComponent(id)}/text`, {
      method: "GET",
      headers: { authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
    if (res.status === 404) {
      return NextResponse.json({ error: "Document not found." }, { status: 404 });
    }
    if (!res.ok) {
      return NextResponse.json({ error: `Upstream document fetch failed (${res.status}).` }, { status: 502 });
    }
    const doc = (await res.json()) as DocumentText;
    return NextResponse.json(doc);
  } catch (e) {
    if (e instanceof BackendError) {
      return NextResponse.json({ error: e.message }, { status: e.status });
    }
    return NextResponse.json(UNREACHABLE_BODY, { status: 503 });
  }
}
