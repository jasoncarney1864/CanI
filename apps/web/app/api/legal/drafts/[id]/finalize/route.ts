import { proxyLegal } from "@/lib/legalProxy";

// POST /api/legal/drafts/[id]/finalize -> docs-api POST /legal/drafts/{id}/finalize.
// No request body. Idempotent: a duplicate call returns the same document_id rather than
// creating a second document/blob; a concurrent in-flight finalize returns
// status: "finalize_pending" instead of racing.
export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  return proxyLegal(request, `/drafts/${encodeURIComponent(id)}/finalize`, { method: "POST" });
}
