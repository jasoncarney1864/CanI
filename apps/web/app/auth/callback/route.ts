import { HUB_API_URL, appRedirect, forwardSetCookie } from "@/lib/backendAuth";

// Entra redirects the browser here after sign-in. We hand the code + the flow cookie to
// hub-api, which validates (state/nonce/PKCE/ID-token), maps the identity to a CanI user,
// and returns the session cookies. We relay those to the browser and land them on the
// workspace. This is the redirect URI registered in the Entra app (must be the public URL).
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code") ?? "";
  const state = url.searchParams.get("state") ?? "";
  const cookieHeader = request.headers.get("cookie") ?? ""; // carries cani_oidc_flow

  if (!code) {
    return appRedirect("/?auth_error=1");
  }

  try {
    const res = await fetch(
      `${HUB_API_URL}/auth/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`,
      { headers: { cookie: cookieHeader }, redirect: "manual", cache: "no-store" },
    );
    if (!res.ok) {
      // hub-api rejected the login (bad state/nonce, expired flow, etc.).
      return appRedirect("/?auth_error=1");
    }
    const response = appRedirect("/");
    // Relay hub-api's session cookies (+ its deletion of the flow cookie) to our domain.
    for (const cookie of res.headers.getSetCookie()) forwardSetCookie(response, cookie);
    return response;
  } catch {
    return appRedirect("/?auth_error=1");
  }
}
