import { NextResponse } from "next/server";
import { parseJsonBody, proxyLegal } from "@/lib/legalProxy";

// POST /api/legal/drafts/[id]/converse -> docs-api POST /legal/drafts/{id}/converse
// ({ message, field_key? }). Nothing here is persisted — only .../fields/confirm writes.
export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  const body = await parseJsonBody(request);
  if (body instanceof NextResponse) return body;
  return proxyLegal(request, `/drafts/${encodeURIComponent(id)}/converse`, { method: "POST", body });
}
