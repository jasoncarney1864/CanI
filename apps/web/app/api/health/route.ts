import { NextResponse } from "next/server";

// Liveness/readiness for the web pod: confirms the Next server is up, independent of the
// backend (the UI should start and degrade gracefully even if hub-api/docs-api are down).
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ status: "ok" });
}
