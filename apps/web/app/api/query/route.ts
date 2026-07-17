import { NextResponse } from "next/server";
import type { RetrievalAnswer } from "@/lib/types";

// Server-side proxy for the live docs-api /query endpoint.
//
// The browser never talks to the backend directly: this route runs on the Next
// server, so it (a) avoids CORS entirely and (b) keeps the access token and
// session/CSRF cookies off the client. It reproduces the dev auth flow the
// integration tests use (tests/integration/conftest.py::login):
//   1. POST hub-api /auth/dev-login  -> sets cani_session + cani_csrf cookies
//   2. POST hub-api /auth/token      -> mints a bearer access token (CSRF-guarded)
//   3. POST docs-api /query          -> returns the RetrievalAnswer
//
// This is a dev convenience: /auth/dev-login only exists when the backend runs
// with ENV=dev. Point HUB_API_URL / DOCS_API_URL at the compose stack.

const HUB_API_URL = process.env.HUB_API_URL ?? "http://localhost:8001";
const DOCS_API_URL = process.env.DOCS_API_URL ?? "http://localhost:8002";
const DEV_IDP_SUBJECT = process.env.CANI_DEV_IDP_SUBJECT ?? "web-prototype-user";

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
    if (eq > -1) {
      jar.set(pair.slice(0, eq).trim(), pair.slice(eq + 1).trim());
    }
  }
  return jar;
}

function upstreamError(stage: string, status: number) {
  return NextResponse.json(
    { error: `Upstream ${stage} failed (${status}).` },
    { status: 502 },
  );
}

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
    // 1. dev-login -> session + csrf cookies
    const loginRes = await fetch(`${HUB_API_URL}/auth/dev-login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ idp_subject: DEV_IDP_SUBJECT }),
      cache: "no-store",
    });
    if (!loginRes.ok) return upstreamError("login", loginRes.status);

    const jar = parseSetCookies(loginRes.headers);
    const csrf = jar.get("cani_csrf");
    if (!csrf) return upstreamError("login (missing csrf)", loginRes.status);
    const cookieHeader = [...jar.entries()].map(([k, v]) => `${k}=${v}`).join("; ");

    // 2. token -> bearer access token (double-submit CSRF: cookie + header)
    const tokenRes = await fetch(`${HUB_API_URL}/auth/token`, {
      method: "POST",
      headers: { "x-cani-csrf-token": csrf, cookie: cookieHeader },
      cache: "no-store",
    });
    if (!tokenRes.ok) return upstreamError("token", tokenRes.status);
    const { access_token: accessToken } = (await tokenRes.json()) as { access_token: string };

    // 3. query -> RetrievalAnswer
    const queryRes = await fetch(`${DOCS_API_URL}/query`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ question }),
      cache: "no-store",
    });
    if (!queryRes.ok) return upstreamError("query", queryRes.status);

    const answer = (await queryRes.json()) as RetrievalAnswer;
    return NextResponse.json(answer);
  } catch {
    // Network-level failure (backend stack not running, DNS, etc.).
    return NextResponse.json(
      {
        error:
          "Could not reach the CanI backend. Start the dev stack (docker compose up) " +
          "or set HUB_API_URL / DOCS_API_URL.",
      },
      { status: 503 },
    );
  }
}
