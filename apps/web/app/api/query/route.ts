import { NextResponse } from "next/server";
import type { RetrievalAnswer } from "@/lib/types";
import { BackendError, DOCS_API_URL, UNREACHABLE_BODY, mintAccessToken } from "@/lib/backendAuth";

// Server-side proxy for docs-api /query. Mints a bearer token from the caller's session
// (set by the Entra OIDC flow), so the answer is owner-scoped to the signed-in user.
export async function POST(request: Request) {
  let question: unknown;
  let spoke: unknown;
  try {
    ({ question, spoke } = await request.json());
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }
  if (typeof question !== "string" || !question.trim()) {
    return NextResponse.json({ error: "A non-empty question is required." }, { status: 400 });
  }
  // spoke is optional; defaults to "General" if not specified
  const spokeValue = typeof spoke === "string" ? spoke : "General";

  try {
    const accessToken = await mintAccessToken(request.headers.get("cookie") ?? "");
    const queryRes = await fetch(`${DOCS_API_URL}/query`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ question, spoke: spokeValue }),
      cache: "no-store",
    });
    if (!queryRes.ok) {
      return NextResponse.json({ error: `Upstream query failed (${queryRes.status}).` }, { status: 502 });
    }
    return NextResponse.json((await queryRes.json()) as RetrievalAnswer);
  } catch (e) {
    if (e instanceof BackendError) return NextResponse.json({ error: e.message }, { status: e.status });
    return NextResponse.json(UNREACHABLE_BODY, { status: 503 });
  }
}
