import { NextResponse } from "next/server";
import { HUB_API_URL, forwardSetCookie } from "@/lib/backendAuth";

// Start the Entra OIDC login. hub-api mints the PKCE/state flow and returns a 302 to Entra
// plus the cani_oidc_flow cookie; we relay both to the browser (on our own domain) so the
// backend stays private. All the OIDC security (PKCE, state, nonce) lives in hub-api.
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const res = await fetch(`${HUB_API_URL}/auth/login`, { redirect: "manual", cache: "no-store" });
    const location = res.headers.get("location");
    if (!location) {
      return NextResponse.json({ error: "Login is not available right now." }, { status: 502 });
    }
    const response = NextResponse.redirect(location, 302);
    for (const cookie of res.headers.getSetCookie()) forwardSetCookie(response, cookie);
    return response;
  } catch {
    return NextResponse.json({ error: "Could not reach the sign-in service." }, { status: 503 });
  }
}
