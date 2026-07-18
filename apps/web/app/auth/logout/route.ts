import { NextResponse } from "next/server";
import { HUB_API_URL, readCookie } from "@/lib/backendAuth";

// Sign out: best-effort tell hub-api (for the audit event + its own cookie clear), then
// clear the session cookies on our domain and land back on the sign-in screen.
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const cookieHeader = request.headers.get("cookie") ?? "";
  const csrf = readCookie(cookieHeader, "cani_csrf");
  try {
    await fetch(`${HUB_API_URL}/auth/logout`, {
      method: "POST",
      headers: { cookie: cookieHeader, ...(csrf ? { "x-cani-csrf-token": csrf } : {}) },
      cache: "no-store",
    });
  } catch {
    // Best effort — clear our own cookies regardless.
  }
  const response = NextResponse.redirect(new URL("/", request.url), 302);
  response.cookies.set({ name: "cani_session", value: "", maxAge: 0, path: "/" });
  response.cookies.set({ name: "cani_csrf", value: "", maxAge: 0, path: "/" });
  return response;
}
