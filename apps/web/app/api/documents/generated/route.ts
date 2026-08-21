import { NextResponse } from "next/server";
import { BackendError, DOCS_API_URL, UNREACHABLE_BODY, mintAccessToken } from "@/lib/backendAuth";

// Server-side proxy for docs-api POST /documents/generated (docs/21 §3.6). Straight JSON
// passthrough — title/spoke/markdown/provenance size validation lives in docs-api, the
// single source of truth for those limits (§3.3), so this route doesn't duplicate them.
export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  try {
    const accessToken = await mintAccessToken(request.headers.get("cookie") ?? "");
    const upstream = await fetch(`${DOCS_API_URL}/documents/generated`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${accessToken}` },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const responseBody = await upstream.json().catch(() => ({}));
    if (upstream.status === 400) {
      return NextResponse.json(
        { error: (responseBody as { detail?: string })?.detail ?? "Invalid request." },
        { status: 400 },
      );
    }
    if (!upstream.ok) {
      return NextResponse.json({ error: `Upstream save failed (${upstream.status}).` }, { status: 502 });
    }
    return NextResponse.json(responseBody);
  } catch (e) {
    if (e instanceof BackendError) return NextResponse.json({ error: e.message }, { status: e.status });
    return NextResponse.json(UNREACHABLE_BODY, { status: 503 });
  }
}
