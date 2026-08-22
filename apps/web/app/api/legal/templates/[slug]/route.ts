import { proxyLegal } from "@/lib/legalProxy";

// GET /api/legal/templates/[slug] -> docs-api GET /legal/templates/{slug}.
export async function GET(request: Request, context: { params: Promise<{ slug: string }> }) {
  const { slug } = await context.params;
  return proxyLegal(request, `/templates/${encodeURIComponent(slug)}`);
}
