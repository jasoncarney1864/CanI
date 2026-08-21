import { NextResponse } from "next/server";
import type { DocumentListResponse } from "@/lib/types";
import { BackendError, DOCS_API_URL, UNREACHABLE_BODY, mintAccessToken } from "@/lib/backendAuth";

// Server-side proxy for docs-api document endpoints, owner-scoped to the signed-in user's
// session (the bearer token is minted here and never reaches client JS).
//   GET  /api/documents  -> list the caller's documents + ingestion status (envelope)
//   POST /api/documents  -> upload a file (multipart passthrough)

// Forwarded verbatim to docs-api's GET /documents (docs/21 §1.8) — the whitelist here is
// just which params we bother copying, not a security boundary (docs-api revalidates
// every value itself).
const LIST_PARAMS = ["spoke", "status", "origin", "q", "sort", "order", "limit", "offset"];

export async function GET(request: Request) {
  try {
    const accessToken = await mintAccessToken(request.headers.get("cookie") ?? "");
    const { searchParams } = new URL(request.url);
    const url = new URL(`${DOCS_API_URL}/documents`);
    for (const param of LIST_PARAMS) {
      const value = searchParams.get(param);
      if (value !== null) url.searchParams.set(param, value);
    }
    const res = await fetch(url, {
      headers: { authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const message = (body as { detail?: string })?.detail ?? `Upstream list failed (${res.status}).`;
      return NextResponse.json({ error: message }, { status: res.status === 400 ? 400 : 502 });
    }
    return NextResponse.json(body as DocumentListResponse);
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
    // BUG (docs/21 §1.8): this used to drop the `spoke` field UploadView.tsx sends,
    // silently landing every upload in General regardless of the picker.
    const upstreamForm = new FormData();
    upstreamForm.append("file", file, file.name);
    const spoke = form.get("spoke");
    if (typeof spoke === "string") upstreamForm.append("spoke", spoke);
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
