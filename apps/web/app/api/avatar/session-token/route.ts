import { NextResponse } from "next/server";
import type { AvatarSessionToken } from "@/lib/types";
import { BackendError, DOCS_API_URL, UNREACHABLE_BODY, mintAccessToken } from "@/lib/backendAuth";

// Server-side proxy for docs-api /avatar/session-token. Mints a short-lived LiveAvatar
// (HeyGen) session token so the browser can open the WebRTC avatar session directly with
// LiveAvatar — LIVEAVATAR_API_KEY never reaches this app's client bundle, the same
// bearer-token pattern /api/query already uses for docs-api itself.
export async function POST(request: Request) {
  try {
    const accessToken = await mintAccessToken(request.headers.get("cookie") ?? "");
    const tokenRes = await fetch(`${DOCS_API_URL}/avatar/session-token`, {
      method: "POST",
      headers: { authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
    if (tokenRes.status === 503) {
      // Avatar voicing isn't configured on this deployment — the client falls back to
      // its normal TTS quietly, mirroring /api/speech's 501-for-unconfigured convention.
      return NextResponse.json({ error: "Avatar voicing is not configured." }, { status: 503 });
    }
    if (!tokenRes.ok) {
      return NextResponse.json(
        { error: `Upstream avatar session-token request failed (${tokenRes.status}).` },
        { status: 502 },
      );
    }
    return NextResponse.json((await tokenRes.json()) as AvatarSessionToken);
  } catch (e) {
    if (e instanceof BackendError) return NextResponse.json({ error: e.message }, { status: e.status });
    return NextResponse.json(UNREACHABLE_BODY, { status: 503 });
  }
}
