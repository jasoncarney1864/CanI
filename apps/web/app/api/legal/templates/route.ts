import { proxyLegal } from "@/lib/legalProxy";

// GET /api/legal/templates -> docs-api GET /legal/templates (active templates only).
export async function GET(request: Request) {
  return proxyLegal(request, "/templates");
}
