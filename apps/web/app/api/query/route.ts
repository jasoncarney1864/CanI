import { NextResponse } from "next/server";
import type { RetrievalAnswer } from "@/lib/types";
import { BackendError, DOCS_API_URL, UNREACHABLE_BODY, mintAccessToken } from "@/lib/backendAuth";

// Server-side proxy for the live docs-api /query endpoint (dev auth flow in
// lib/backendAuth). The browser never sees the access token.

export async function POST(request: Request) {
  let question: unknown;
  try {
    ({ question } = await request.json());
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }
  if (typeof question !== "string" || !question.trim()) {
    return NextResponse.json({ error: "A non-empty question is required." }, { status: 400 });
  }

  try {
    const accessToken = await mintAccessToken();
    const queryRes = await fetch(`${DOCS_API_URL}/query`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ question }),
      cache: "no-store",
    });
    if (!queryRes.ok) {
      return NextResponse.json({ error: `Upstream query failed (${queryRes.status}).` }, { status: 502 });
    }
    const answer = (await queryRes.json()) as RetrievalAnswer;
    return NextResponse.json(answer);
  } catch (e) {
    if (e instanceof BackendError) {
      return NextResponse.json({ error: e.message }, { status: e.status });
    }
    // Network-level failure (backend stack not running, DNS, etc.).
    return NextResponse.json(UNREACHABLE_BODY, { status: 503 });
  }
}
