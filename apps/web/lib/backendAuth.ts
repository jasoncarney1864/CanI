// Shared server-side auth for the docs-api proxy routes.
//
// The browser never talks to the backend directly: these helpers run on the Next
// server, so the access token and session/CSRF cookies stay off the client. This
// reproduces the dev auth flow the integration tests use
// (tests/integration/conftest.py::login):
//   1. POST hub-api /auth/dev-login  -> sets cani_session + cani_csrf cookies
//   2. POST hub-api /auth/token      -> mints a bearer access token (CSRF-guarded)
// The caller then hits docs-api with that token.
//
// This is a dev convenience: /auth/dev-login only exists when the backend runs with
// ENV=dev. Sprint 3 A2 replaces this with the real Entra OIDC login. Point
// HUB_API_URL / DOCS_API_URL at the compose stack (or, once deployed, the in-cluster
// services).

export const HUB_API_URL = process.env.HUB_API_URL ?? "http://localhost:8001";
export const DOCS_API_URL = process.env.DOCS_API_URL ?? "http://localhost:8002";
const DEV_IDP_SUBJECT = process.env.CANI_DEV_IDP_SUBJECT ?? "web-prototype-user";

/** A named upstream failure, carrying the HTTP status the proxy route should return. */
export class BackendError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** Parse Set-Cookie headers from an upstream response into a name->value jar. */
function parseSetCookies(headers: Headers): Map<string, string> {
  const jar = new Map<string, string>();
  // Node 18+/undici exposes getSetCookie(); fall back to the single-header form.
  const raw =
    (headers as Headers & { getSetCookie?: () => string[] }).getSetCookie?.() ??
    (headers.get("set-cookie") ? [headers.get("set-cookie") as string] : []);
  for (const entry of raw) {
    const [pair] = entry.split(";");
    const eq = pair.indexOf("=");
    if (eq > -1) jar.set(pair.slice(0, eq).trim(), pair.slice(eq + 1).trim());
  }
  return jar;
}

/** dev-login -> token. Returns a bearer access token for docs-api, or throws BackendError. */
export async function mintAccessToken(): Promise<string> {
  const loginRes = await fetch(`${HUB_API_URL}/auth/dev-login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ idp_subject: DEV_IDP_SUBJECT }),
    cache: "no-store",
  });
  if (!loginRes.ok) throw new BackendError(`Upstream login failed (${loginRes.status}).`, 502);

  const jar = parseSetCookies(loginRes.headers);
  const csrf = jar.get("cani_csrf");
  if (!csrf) throw new BackendError("Upstream login did not return a CSRF token.", 502);
  const cookieHeader = [...jar.entries()].map(([k, v]) => `${k}=${v}`).join("; ");

  const tokenRes = await fetch(`${HUB_API_URL}/auth/token`, {
    method: "POST",
    headers: { "x-cani-csrf-token": csrf, cookie: cookieHeader },
    cache: "no-store",
  });
  if (!tokenRes.ok) throw new BackendError(`Upstream token mint failed (${tokenRes.status}).`, 502);
  const { access_token: accessToken } = (await tokenRes.json()) as { access_token: string };
  return accessToken;
}

/** Shared error body for when the backend stack is unreachable (compose not up, etc.). */
export const UNREACHABLE_BODY = {
  error:
    "Could not reach the CanI backend. Start the dev stack (docker compose up) " +
    "or set HUB_API_URL / DOCS_API_URL.",
};
