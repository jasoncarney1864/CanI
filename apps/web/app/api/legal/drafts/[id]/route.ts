import { proxyLegal } from "@/lib/legalProxy";

// GET /api/legal/drafts/[id] -> docs-api GET /legal/drafts/{id}.
export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  return proxyLegal(request, `/drafts/${encodeURIComponent(id)}`);
}

// DELETE /api/legal/drafts/[id] -> docs-api DELETE /legal/drafts/{id}. 409 if the draft is
// already finalized — its document lives on the ordinary Documents page instead.
export async function DELETE(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  return proxyLegal(request, `/drafts/${encodeURIComponent(id)}`, { method: "DELETE" });
}
