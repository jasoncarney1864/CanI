import { NextResponse } from "next/server";
import { BackendError, DOCS_API_URL, UNREACHABLE_BODY, mintAccessToken } from "@/lib/backendAuth";

// Server-side proxy for docs-api GET /documents/{id}/original (docs/21 §2.3). Streams the
// upstream body through rather than buffering — the docs-api response is already capped
// at MAX_UPLOAD_BYTES, but there's no reason to hold it in this process's memory twice.
export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  try {
    const accessToken = await mintAccessToken(request.headers.get("cookie") ?? "");
    const upstream = await fetch(`${DOCS_API_URL}/documents/${encodeURIComponent(id)}/original`, {
      method: "GET",
      headers: { authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
    if (upstream.status === 404) {
      const body = await upstream.json().catch(() => ({}));
      return NextResponse.json(
        { error: (body as { detail?: string })?.detail ?? "Document not found." },
        { status: 404 },
      );
    }
    if (!upstream.ok || !upstream.body) {
      return NextResponse.json(
        { error: `Upstream download failed (${upstream.status}).` },
        { status: 502 },
      );
    }
    return new NextResponse(upstream.body, {
      status: 200,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/octet-stream",
        "content-disposition": upstream.headers.get("content-disposition") ?? "attachment",
        "cache-control": "no-store",
      },
    });
  } catch (e) {
    if (e instanceof BackendError) return NextResponse.json({ error: e.message }, { status: e.status });
    return NextResponse.json(UNREACHABLE_BODY, { status: 503 });
  }
}
