import { proxyLegal } from "@/lib/legalProxy";

// GET /api/legal/drafts/[id]/preview -> docs-api GET /legal/drafts/{id}/preview.
export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  return proxyLegal(request, `/drafts/${encodeURIComponent(id)}/preview`);
}
