// Shared server-side proxy helper for the /api/legal/** routes — every one of them mints
// a docs-api bearer token from the caller's hub-api session and forwards to docs-api's
// /legal/** router, so the eight route files below are each a couple of lines rather than
// repeating the same try/catch/error-shaping (see app/api/documents/route.ts for the
// pattern this was factored out of).

import { NextResponse } from "next/server";
import { BackendError, DOCS_API_URL, UNREACHABLE_BODY, mintAccessToken } from "@/lib/backendAuth";

export async function proxyLegal(
  request: Request,
  path: string,
  init?: { method?: string; body?: unknown },
): Promise<NextResponse> {
  try {
    const accessToken = await mintAccessToken(request.headers.get("cookie") ?? "");
    const res = await fetch(`${DOCS_API_URL}/legal${path}`, {
      method: init?.method ?? "GET",
      headers: {
        authorization: `Bearer ${accessToken}`,
        ...(init?.body !== undefined ? { "content-type": "application/json" } : {}),
      },
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
      cache: "no-store",
    });
    if (res.status === 204) return new NextResponse(null, { status: 204 });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const message = (data as { detail?: string })?.detail ?? `Upstream request failed (${res.status}).`;
      const status = [400, 404, 409].includes(res.status) ? res.status : 502;
      return NextResponse.json({ error: message }, { status });
    }
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    if (e instanceof BackendError) return NextResponse.json({ error: e.message }, { status: e.status });
    return NextResponse.json(UNREACHABLE_BODY, { status: 503 });
  }
}

/** Parses a JSON body, or returns a 400 NextResponse (never throws) — route handlers that
 * need a body do `const body = await parseJsonBody(request); if (body instanceof NextResponse) return body;`. */
export async function parseJsonBody(request: Request): Promise<unknown | NextResponse> {
  try {
    return await request.json();
  } catch {
    return NextResponse.json({ error: "Expected a JSON body." }, { status: 400 });
  }
}
