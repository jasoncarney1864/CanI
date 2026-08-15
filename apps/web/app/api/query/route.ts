import { NextResponse } from "next/server";
import type { RetrievalAnswer } from "@/lib/types";
import { BackendError, DOCS_API_URL, UNREACHABLE_BODY, mintAccessToken } from "@/lib/backendAuth";

// Server-side proxy for docs-api /query. Mints a bearer token from the caller's session
// (set by the Entra OIDC flow), so the answer is owner-scoped to the signed-in user.
export async function POST(request: Request) {
  let question: unknown;
  let spoke: unknown;
  let includePublicLaw: unknown;
  let jurisdictions: unknown;
  try {
    ({
      question,
      spoke,
      include_public_law: includePublicLaw,
      jurisdictions,
    } = await request.json());
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }
  if (typeof question !== "string" || !question.trim()) {
    return NextResponse.json({ error: "A non-empty question is required." }, { status: 400 });
  }
  // spoke is optional; defaults to "General" if not specified
  const spokeValue = typeof spoke === "string" ? spoke : "General";
  // Public-law fields (docs/20 §20.8) are both optional pass-throughs — retrieval-worker
  // applies its own spoke-based/config-based defaults when either is absent.
  const includePublicLawValue = typeof includePublicLaw === "boolean" ? includePublicLaw : undefined;
  const jurisdictionsValue =
    Array.isArray(jurisdictions) && jurisdictions.every((j) => typeof j === "string")
      ? jurisdictions
      : undefined;

  try {
    const accessToken = await mintAccessToken(request.headers.get("cookie") ?? "");
    const queryRes = await fetch(`${DOCS_API_URL}/query`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({
        question,
        spoke: spokeValue,
        include_public_law: includePublicLawValue,
        jurisdictions: jurisdictionsValue,
      }),
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
