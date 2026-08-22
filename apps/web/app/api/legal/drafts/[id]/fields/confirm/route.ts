import { NextResponse } from "next/server";
import { parseJsonBody, proxyLegal } from "@/lib/legalProxy";

// POST /api/legal/drafts/[id]/fields/confirm -> docs-api POST
// /legal/drafts/{id}/fields/confirm ({ fields }). The only call that writes to the
// draft's field_values_json.
export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  const body = await parseJsonBody(request);
  if (body instanceof NextResponse) return body;
  return proxyLegal(request, `/drafts/${encodeURIComponent(id)}/fields/confirm`, { method: "POST", body });
}
