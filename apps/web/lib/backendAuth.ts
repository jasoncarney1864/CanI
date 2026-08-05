// Server-side backend access for the web app's API + auth proxy routes.
//
// The browser holds a real hub-api session (cani_session + cani_csrf cookies), established
// by the Entra OIDC flow (see app/auth/*). These helpers run on the Next server and use
// that session to mint short-lived docs-api access tokens and to check identity — the
// access token and the CSRF value never reach client JS. hub-api/docs-api stay private;
// only this app is public.

import { NextResponse } from "next/server";

export const HUB_API_URL = process.env.HUB_API_URL ?? "http://localhost:8001";
export const DOCS_API_URL = process.env.DOCS_API_URL ?? "http://localhost:8002";

/** A named upstream failure, carrying the HTTP status the proxy route should return. */
export class BackendError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** Read one cookie value out of a raw Cookie header. */
export function readCookie(cookieHeader: string, name: string): string | undefined {
  for (const part of cookieHeader.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (k === name) return rest.join("=");
  }
  return undefined;
}

/** Mint a docs-api bearer token from the caller's hub-api session (cani_session +
 * cani_csrf, double-submit CSRF). Throws BackendError(401) if not signed in. */
export async function mintAccessToken(cookieHeader: string): Promise<string> {
  if (!readCookie(cookieHeader, "cani_session")) {
    throw new BackendError("Not signed in.", 401);
  }
  const csrf = readCookie(cookieHeader, "cani_csrf");
  if (!csrf) throw new BackendError("Missing CSRF token — sign in again.", 401);

  const res = await fetch(`${HUB_API_URL}/auth/token`, {
    method: "POST",
    headers: { "x-cani-csrf-token": csrf, cookie: cookieHeader },
    cache: "no-store",
  });
  if (res.status === 401) throw new BackendError("Session expired — sign in again.", 401);
  if (!res.ok) throw new BackendError(`Token mint failed (${res.status}).`, 502);
  const { access_token: accessToken } = (await res.json()) as { access_token: string };
  return accessToken;
}

export interface Principal {
  user_id: string;
  idp_subject: string;
  entitlements: string[];
}

/** The signed-in user, or null if there's no valid session. */
export async function whoami(cookieHeader: string): Promise<Principal | null> {
  if (!readCookie(cookieHeader, "cani_session")) return null;
  try {
    const res = await fetch(`${HUB_API_URL}/auth/whoami`, {
      headers: { cookie: cookieHeader },
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as Principal;
  } catch {
    return null;
  }
}

/** Redirect to a path on THIS app's own origin, using a *relative* Location header.
 *
 * The Next server sits behind the ingress and binds 0.0.0.0:3000, so `request.url` reflects
 * that internal address — a redirect built from it (`new URL("/", request.url)`) sends the
 * browser to https://0.0.0.0:3000/ (ERR_ADDRESS_INVALID). A relative Location is instead
 * resolved by the browser against its own address bar (e.g. https://app.canido.co), which is
 * always correct and needs no host config. `path` must start with "/".
 */
export function appRedirect(path: string): NextResponse {
  return new NextResponse(null, { status: 302, headers: { location: path } });
}

/** Re-set an upstream Set-Cookie on our own response for the app's own domain. hub-api sets
 * these without a domain (so they bind to the request host) and, in dev, without Secure;
 * we always mark them Secure (the app is HTTPS) and keep hub-api's httponly intent
 * (cani_csrf must stay readable by client JS; the rest are httponly). */
export function forwardSetCookie(response: NextResponse, upstream: string): void {
  const [pair, ...attrs] = upstream.split(";");
  const eq = pair.indexOf("=");
  if (eq < 0) return;
  const name = pair.slice(0, eq).trim();
  const value = pair.slice(eq + 1).trim();

  let maxAge: number | undefined;
  for (const attr of attrs) {
    const [k, v] = attr.trim().split("=");
    if (k.toLowerCase() === "max-age") maxAge = Number(v);
  }
  response.cookies.set({
    name,
    value,
    httpOnly: name !== "cani_csrf",
    secure: true,
    sameSite: "lax",
    path: "/",
    ...(maxAge !== undefined ? { maxAge } : {}),
  });
}

/** Shared error body for when the backend stack is unreachable. */
export const UNREACHABLE_BODY = {
  error: "Could not reach the CanI backend. Please try again.",
};
