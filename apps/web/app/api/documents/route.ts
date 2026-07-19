import { NextResponse } from "next/server";
import type { DocumentMeta } from "@/lib/types";
import { BackendError, DOCS_API_URL, UNREACHABLE_BODY, mintAccessToken } from "@/lib/backendAuth";

// Server-side proxy for docs-api document endpoints, owner-scoped to the signed-in user's
// session (the bearer token is minted here and never reaches client JS).
//   GET  /api/documents  -> list the caller's documents + ingestion status
//   POST /api/documents  -> upload a file (multipart passthrough)

export async function GET(request: Request) {
  try {
    const accessToken = await mintAccessToken(request.headers.get("cookie") ?? "");
    const res = await fetch(`${DOCS_API_URL}/documents`, {
      headers: { authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json({ error: `Upstream list failed (${res.status}).` }, { status: 502 });
    }
    return NextResponse.json((await res.json()) as DocumentMeta[]);
  } catch (e) {
    if (e instanceof BackendError) return NextResponse.json({ error: e.message }, { status: e.status });
    return NextResponse.json(UNREACHABLE_BODY, { status: 503 });
  }
}

export async function POST(request: Request) {
  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return NextResponse.json({ error: "Expected a multipart file upload." }, { status: 400 });
  }
  const file = form.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json({ error: "No file provided." }, { status: 400 });
  }

  try {
    const accessToken = await mintAccessToken(request.headers.get("cookie") ?? "");
    // Rebuild the multipart body so docs-api sees a clean `file` field with its filename.
    const upstreamForm = new FormData();
    upstreamForm.append("file", file, file.name);
    const res = await fetch(`${DOCS_API_URL}/documents`, {
      method: "POST",
      headers: { authorization: `Bearer ${accessToken}` },
      body: upstreamForm,
      cache: "no-store",
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      // docs-api returns a 400 with a human-readable reason for rejected uploads
      // (unsupported type, too large) — surface it verbatim.
      const message = (body as { detail?: string })?.detail ?? `Upload failed (${res.status}).`;
      return NextResponse.json({ error: message }, { status: res.status === 400 ? 400 : 502 });
    }
    return NextResponse.json(body);
  } catch (e) {
    if (e instanceof BackendError) return NextResponse.json({ error: e.message }, { status: e.status });
    return NextResponse.json(UNREACHABLE_BODY, { status: 503 });
  }
}
