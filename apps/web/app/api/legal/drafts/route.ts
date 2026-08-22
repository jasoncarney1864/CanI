import { NextResponse } from "next/server";
import { parseJsonBody, proxyLegal } from "@/lib/legalProxy";

// POST /api/legal/drafts -> docs-api POST /legal/drafts ({ template_slug }).
export async function POST(request: Request) {
  const body = await parseJsonBody(request);
  if (body instanceof NextResponse) return body;
  return proxyLegal(request, "/drafts", { method: "POST", body });
}
